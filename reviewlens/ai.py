"""AI 단계 — 리뷰별 감정 분석과 조건별 종합 추출.

두 호출의 성격이 다르다:
  분석(analyze) = 리뷰 **하나씩**. 감정 + 신뢰도. 실패해도 그 건만 건너뛴다.
  추출(extract) = 리뷰 **여러 개를 한 번에**. 키워드·요약·개선 제안.

**신뢰도(confidence)를 함께 받는 이유**: "부정"이라는 판정만으로는 얼마나 확신하는지 알 수
없다. 0.55 로 부정 판정한 리뷰와 0.95 로 부정 판정한 리뷰는 다르게 다뤄야 한다 —
낮은 신뢰도는 사람이 확인할 목록이 된다.
"""

from __future__ import annotations

import json
import logging
import re

import requests

from . import storage
from .ingest import now_iso

logger = logging.getLogger(__name__)

# Gemini 의 OpenAI 호환 endpoint. 요청·응답 형태가 Chat Completions 와 같아서
# 헤더(Bearer)·본문(messages/temperature)·응답 경로(choices[0].message.content)를
# 그대로 두고 URL 과 모델 이름만 바꿔 붙일 수 있다.
LLM_URL = "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"
FENCE = re.compile(r"^\s*```(?:json)?\s*|\s*```\s*$")
SENTIMENTS = {"긍정", "중립", "부정"}

# 추출에 넣을 리뷰 수 상한. 많이 넣는다고 통찰이 깊어지지 않고 토큰만 는다.
EXTRACT_CAP = 60
# 리뷰 본문이 아주 길면 잘라 넣는다 — 감정 판정에는 앞부분이면 충분하다.
TEXT_CAP = 1000


def call_llm(api_key: str, prompt: str, config: dict) -> str:
    """Chat Completions 호출 → 응답 텍스트. 실패는 예외로 올린다."""
    response = requests.post(
        LLM_URL,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json={
            "model": config["ai"]["model"],
            "messages": [{"role": "user", "content": prompt}],
            # 감정 판정은 사실 판단이다 — 같은 리뷰를 두 번 분석했는데 결과가 갈리면
            # 둘 중 하나가 틀린 것이다. 창작(A2-1 네이밍 0.8)과 반대 방향으로 낮춘다.
            "temperature": 0.1,
        },
        timeout=config["ai"]["timeout"],
    )
    response.raise_for_status()
    return response.json()["choices"][0]["message"]["content"]


def parse_json(text: str):
    """응답에서 코드펜스를 벗기고 JSON 으로 읽는다."""
    return json.loads(FENCE.sub("", text.strip()))


def build_sentiment_prompt(text: str, language: str) -> str:
    """리뷰 1건의 감정 + 신뢰도 프롬프트.

    **언어를 알려 주는 이유**(보너스: 다국어): 모델이 영어 리뷰를 한국어로 옮겨 판단하면
    뉘앙스가 바뀐다. 원문 언어 그대로 읽으라고 명시하고, 결과 라벨만 한국어로 통일한다.
    """
    language_note = {
        "ko": "리뷰는 한국어다.",
        "en": "The review is in English. Judge it in English, but answer with Korean labels.",
    }.get(language, "")
    return f"""너는 고객 리뷰 감정 분석기다. 아래 리뷰의 감정을 판정하라.
{language_note}

[리뷰]
{text[:TEXT_CAP]}

[출력 — JSON 객체 하나만]
- "sentiment": "긍정" | "중립" | "부정" 중 하나
- "confidence": 0.0~1.0 사이 숫자. 판정이 얼마나 확실한지
- "reason": 그렇게 본 근거 한 문장

[판정 기준]
- 제품·서비스에 대한 **작성자의 태도**로 판단한다(사실 나열이면 중립).
- 칭찬과 불만이 섞여 있으면 더 무게가 실린 쪽으로, 비등하면 중립.
- 별점은 주어지지 않았다. **본문만으로** 판단하라.

[규칙]
- JSON 외의 설명·코드펜스를 붙이지 마라.
"""


def analyze_one(api_key: str, row, config: dict) -> tuple[str, float] | None:
    """리뷰 1건 감정 분석 → (감정, 신뢰도) 또는 None(실패).

    실패를 예외로 올리지 않는 이유: 100건을 도는 중 3건이 실패했다고 나머지를 포기할 수 없다.
    """
    prompt = build_sentiment_prompt(row["text"], row["language"] or "ko")
    try:
        data = parse_json(call_llm(api_key, prompt, config))
    except requests.Timeout:
        logger.error("[분석 %s] 타임아웃", row["review_id"])
        return None
    except requests.HTTPError as exc:
        code = exc.response.status_code if exc.response is not None else "?"
        logger.error("[분석 %s] HTTP %s — %s", row["review_id"], code, http_hint(code))
        return None
    except requests.RequestException as exc:
        logger.error("[분석 %s] 네트워크 오류: %s", row["review_id"], exc)
        return None
    except (json.JSONDecodeError, KeyError, IndexError) as exc:
        logger.error("[분석 %s] 응답 형식 오류: %s", row["review_id"], exc)
        return None

    sentiment = str(data.get("sentiment") or "").strip()
    if sentiment not in SENTIMENTS:
        # 허용 목록 밖 값은 버린다 — "다소 긍정적" 같은 값이 섞이면 집계가 갈린다
        logger.error("[분석 %s] 알 수 없는 감정 값: %r", row["review_id"], sentiment)
        return None

    try:
        confidence = float(data.get("confidence", 0))
    except (TypeError, ValueError):
        confidence = 0.0
    # 범위를 벗어난 값을 그대로 저장하면 평균 신뢰도가 1.0 을 넘는 일이 생긴다
    confidence = min(max(confidence, 0.0), 1.0)
    return sentiment, confidence


def run_analyze(db_path: str, api_key: str, config: dict, *, target: str = "unanalyzed",
                review_id: str | None = None, limit: int | None = None) -> dict:
    """감정 분석 단계 → 통계.

    target:
      unanalyzed — 아직 분석 안 한 것만 (기본. 이미 분석한 건에 돈을 두 번 쓰지 않는다)
      all        — 전부 다시 분석 (프롬프트를 고쳤을 때)
      id         — review_id 하나만
    """
    stats = {"target": 0, "done": 0, "failed": 0}
    with storage.connect(db_path) as conn:
        if target == "id" and review_id:
            row = storage.get_clean(conn, review_id)
            rows = [row] if row else []
        elif target == "all":
            rows = storage.select_clean(conn, limit=limit)
        else:
            rows = storage.select_clean(conn, status="unanalyzed", limit=limit)

        stats["target"] = len(rows)
        for row in rows:
            result = analyze_one(api_key, row, config)
            if result is None:
                stats["failed"] += 1
                continue
            sentiment, confidence = result
            storage.save_sentiment(conn, row["id"], sentiment, confidence, now_iso())
            stats["done"] += 1
            logger.info("분석 완료 %s → %s(%.2f)", row["review_id"], sentiment, confidence)
    return stats


def build_extract_prompt(rows, scope: str) -> str:
    """여러 리뷰를 묶어 키워드·요약·개선 제안을 뽑는 프롬프트.

    감정 라벨을 함께 넣는 이유: "부정 리뷰에서 무엇이 반복되는가"를 물으려면 모델이 어느
    리뷰가 부정인지 알아야 한다. 라벨 없이 넣으면 긍·부정 키워드가 섞여 나온다.
    """
    lines = []
    for index, row in enumerate(rows, start=1):
        label = row["sentiment"] or "미분석"
        rating = f"★{row['rating']}" if row["rating"] else "★-"
        body = row["text"].replace("\n", " ")[:200]
        lines.append(f"{index}. [{label}][{rating}][{row['product'] or '-'}] {body}")

    return f"""너는 고객 리뷰 분석가다. 아래 리뷰 묶음에서 인사이트를 뽑아라.

[분석 범위]
{scope} · 총 {len(rows)}건

[리뷰 목록]
{chr(10).join(lines)}

[출력 — JSON 객체 하나만]
- "positive_keywords": 긍정 리뷰에서 반복되는 키워드 3~6개의 문자열 배열
- "negative_keywords": 부정 리뷰에서 반복되는 키워드 3~6개의 문자열 배열
- "summary": 전체 요약 (3~4문장). 무엇이 좋고 무엇이 문제인지
- "improvements": 개선 제안 2~4개의 문자열 배열. **리뷰에 근거가 있는 것만**
- "priority": 가장 먼저 손봐야 할 것 한 문장과 그 이유

[규칙]
- 목록에 없는 문제를 지어내지 마라.
- 확인되지 않은 수치(불량률·점유율)를 만들지 마라.
- 개선 제안은 실행 가능한 행동으로 써라("품질을 높인다" 같은 말은 쓰지 마라).
- JSON 외의 설명·코드펜스를 붙이지 마라.
"""


def run_extract(db_path: str, api_key: str, config: dict, *, sentiment: str | None = None,
                product: str | None = None, date_from: str | None = None,
                date_to: str | None = None) -> dict | None:
    """추출 단계 → 결과 dict(실패 시 None). 결과는 extractions 테이블에 저장된다."""
    scope_parts = [product or "전체 제품"]
    if sentiment:
        scope_parts.append(f"{sentiment} 리뷰")
    if date_from or date_to:
        scope_parts.append(f"{date_from or '처음'} ~ {date_to or '지금'}")
    scope = " · ".join(scope_parts)

    with storage.connect(db_path) as conn:
        rows = storage.select_clean(
            conn, sentiment=sentiment, product=product, date_from=date_from, date_to=date_to,
            limit=EXTRACT_CAP,
        )
        if not rows:
            logger.warning("추출 대상이 없습니다 (%s)", scope)
            return None

        try:
            data = parse_json(call_llm(api_key, build_extract_prompt(rows, scope), config))
        except requests.Timeout:
            logger.error("[추출] 타임아웃")
            return None
        except requests.HTTPError as exc:
            code = exc.response.status_code if exc.response is not None else "?"
            logger.error("[추출] HTTP %s — %s", code, http_hint(code))
            return None
        except requests.RequestException as exc:
            logger.error("[추출] 네트워크 오류: %s", exc)
            return None
        except (json.JSONDecodeError, KeyError, IndexError) as exc:
            logger.error("[추출] 응답 형식 오류: %s", exc)
            return None

        storage.save_extraction(conn, scope, len(rows), data, now_iso())
        logger.info("추출 저장: %s (%d건)", scope, len(rows))
        return data


def http_hint(code) -> str:
    """상태코드별 점검 안내. 401 은 인증, 403 은 인가, 429 는 쿼터."""
    hints = {
        401: "API 키 값·헤더 이름을 확인하세요",
        403: "키의 사용 권한·결제 상태를 확인하세요",
        429: "요청 한도 초과 — 잠시 후 재시도하세요",
        500: "서버 오류 — 잠시 후 재시도하세요",
    }
    return hints.get(code, "응답 코드를 확인하세요")
