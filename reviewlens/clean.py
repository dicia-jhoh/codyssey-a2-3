"""정제 — raw 를 규칙에 통과시켜 clean 으로 옮긴다.

규칙 다섯 가지(미션 요구):
  ① 필수 필드 검증   — 리뷰 텍스트가 없으면 리뷰가 아니다
  ② 텍스트 정규화     — 공백·제어문자 정리, HTML 엔티티 복원
  ③ 별점 범위 검증    — 1~5 밖이면 버린다(별점만, 리뷰는 살린다)
  ④ 날짜 형식 통일    — 전부 YYYY-MM-DD, 못 읽으면 NULL
  ⑤ 짧은 리뷰 필터링  — "좋아요" 한 마디는 감정 분석에 쓸 정보가 없다

**정제는 되돌릴 수 있어야 한다.** raw 를 그대로 두고 여기서만 바꾸므로, 임계값을 고치면
clean 을 비우고 다시 돌리면 된다. 그래서 이 파일에는 네트워크 호출이 없다.
"""

from __future__ import annotations

import html
import json
import logging
import re
import sqlite3

from . import storage
from .ingest import extract_fields, now_iso

logger = logging.getLogger(__name__)

WHITESPACE = re.compile(r"\s+")
# 한글 음절이 하나라도 있으면 한국어로 본다(보너스: 다국어 처리의 1차 판정).
HANGUL = re.compile(r"[가-힣]")


def normalize_text(value: str | None) -> str:
    """텍스트 정규화 — HTML 엔티티 복원 → 공백 정리.

    `&amp;` 를 먼저 되돌리는 이유: 쇼핑몰에서 내려받은 CSV 에는 엔티티가 그대로 들어 있는
    일이 흔하다. 그대로 두면 AI 가 "&amp;" 를 글자로 읽는다.
    """
    if not value:
        return ""
    text = html.unescape(str(value))
    return WHITESPACE.sub(" ", text).strip()


def detect_language(text: str) -> str:
    """언어 판정 — 한글이 있으면 'ko', 아니면 'en'(보너스: 다국어).

    라이브러리를 쓰지 않은 이유: 이 미션의 리뷰는 한국어·영어 두 가지뿐이고, 한글 음절
    존재 여부만으로 정확히 갈린다. 언어가 늘어나면 `langdetect` 같은 도구가 필요하지만
    **지금 필요 없는 의존성을 미리 넣지 않는다.**
    """
    return "ko" if HANGUL.search(text) else "en"


def parse_rating(value, low: int, high: int) -> int | None:
    """별점 → 정수. 범위 밖이거나 숫자가 아니면 None.

    별점이 틀렸다고 **리뷰를 버리지 않는다** — 본문은 여전히 감정 분석에 쓸 수 있다.
    별점만 비워 두고 "별점 확보율" 지표로 드러낸다.
    """
    if value is None or str(value).strip() == "":
        return None
    try:
        number = int(float(str(value).strip()))
    except ValueError:
        logger.warning("별점을 숫자로 읽지 못했습니다: %r", value)
        return None
    if not low <= number <= high:
        logger.warning("별점이 범위(%d~%d) 밖입니다: %s", low, high, number)
        return None
    return number


def parse_date(value: str | None) -> str | None:
    """다양한 날짜 표기 → YYYY-MM-DD. 못 읽으면 None.

    **시각을 버리고 날짜만 남기는 이유**: 리뷰 분석의 시간 단위는 '일' 이다. 시분초까지
    남기면 일자별 집계 때마다 잘라내야 하고, 그 과정에서 시간대 문제가 끼어든다.
    """
    if not value:
        return None
    text = str(value).strip()
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y.%m.%d", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S"):
        try:
            from datetime import datetime

            return datetime.strptime(text[: len(fmt) + 6], fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    logger.warning("날짜 형식을 인식하지 못했습니다: %r", text[:30])
    return None


def to_clean_item(row: sqlite3.Row, cfg: dict) -> tuple[dict | None, str]:
    """raw 1행 → (clean 항목, 사유). 항목이 None 이면 제외된 것이고 사유가 이유다."""
    payload = json.loads(row["payload"])
    fields = extract_fields(payload)

    text = normalize_text(fields.get("text"))
    if not text:
        return None, "리뷰 텍스트 없음"

    min_length = cfg["clean"]["min_text_length"]
    if len(text) < min_length:
        # 짧은 리뷰를 거르는 이유: "좋아요"·"굿" 은 감정은 있어도 **왜 그런지**가 없다.
        # 키워드 추출·개선 제안에 아무 기여를 못 하면서 AI 호출 비용만 든다.
        return None, f"너무 짧음({len(text)}자 < {min_length}자)"

    review_id = fields.get("review_id")
    if not review_id:
        return None, "review_id 없음(중복 판정 불가)"

    low, high = cfg["clean"]["rating_range"]
    return {
        "raw_id": row["id"],
        "review_id": review_id,
        "product": normalize_text(fields.get("product")) or None,
        "rating": parse_rating(fields.get("rating"), low, high),
        "created_at": parse_date(fields.get("created_at")),
        "text": text,
        "language": detect_language(text),
        "cleaned_at": now_iso(),
    }, "ok"


def run_clean(db_path: str, cfg: dict, policy: str = "skip",
              only_uncleaned: bool = True) -> dict:
    """정제 단계 전체 → 통계 dict.

    제외 사유를 종류별로 세는 이유: `invalid` 만 세면 "왜 5건이 빠졌지?"를 답할 수 없다.
    짧아서 빠진 것과 필수 필드가 없어 빠진 것은 대응이 다르다(임계값 조정 vs 데이터 문제).
    """
    stats = {"total": 0, "inserted": 0, "skipped": 0, "updated": 0, "invalid": 0}
    reasons: dict[str, int] = {}

    with storage.connect(db_path) as conn:
        rows = storage.fetch_raw(conn, only_uncleaned=only_uncleaned)
        stats["total"] = len(rows)
        for row in rows:
            item, reason = to_clean_item(row, cfg)
            if item is None:
                stats["invalid"] += 1
                reasons[reason] = reasons.get(reason, 0) + 1
                continue
            result = storage.upsert_clean(conn, item, policy=policy)
            stats[result] = stats.get(result, 0) + 1

    stats["reasons"] = reasons
    logger.info(
        "정제 완료: 대상 %d · 신규 %d · 중복 %d · 갱신 %d · 제외 %d",
        stats["total"], stats["inserted"], stats["skipped"], stats["updated"], stats["invalid"],
    )
    for reason, count in reasons.items():
        logger.warning("제외 사유 — %s: %d건", reason, count)
    return stats
