# reviewlens — AI 기반 고객 리뷰 감정 분석 대시보드 (A2-3)

리뷰 CSV 를 넣으면 **적재 → 정제 → 감정 분석 → 인사이트 추출 → 차트·리포트·HTML 대시보드**
까지 만들어 주는 CLI 도구입니다. 데이터는 SQLite 에 남고, 단계마다 따로 실행할 수 있습니다.

| 항목 | 값 |
|---|---|
| 실행 | `python -m reviewlens <서브커맨드>` |
| 서브커맨드 | `import` `add` `clean` `analyze` `extract` `list` `show` `stats` `dashboard` `export` |
| 저장소 | SQLite — `raw_reviews` · `clean_reviews` · `extractions` |
| 차트 | 감정 분포 · 시간별 추이 · 별점별 감정 분포 (matplotlib) |
| 외부 의존 | `requests` · `matplotlib` |
| 환경 변수 | `GEMINI_API_KEY` — [AI Studio](https://aistudio.google.com/apikey) 무료 등급으로 발급 |
| 샘플 데이터 | `data/sample_reviews.csv` — 35건 · 제품 3종 · 한/영 혼합 |

---

## 이 미션의 위치 — 앞뒤 미션과의 연결

| | 미션 | 무엇을 주고받나 |
|---|---|---|
| 이어받음 | **A2-1** (브랜드 아이덴티티) | matplotlib 한글 폰트 탐색 · Agg 백엔드 · 도넛 차트 라벨 배치 |
| 이어받음 | **A2-2** (뉴스 트렌드) | raw/clean 분리 · 서브커맨드 파이프라인 · 품질 지표에 중복률 병기 |
| 넘겨줌 | **M2-1** (AI 카운슬러) | **감정 추이 차트** — 시간에 따른 감정 변화를 누적 영역으로 보는 방식 |

A2-2 는 **뉴스**, A2-3 은 **리뷰**입니다. 파이프라인 골격은 같지만 도메인이 달라 판단이
갈리는 지점이 있습니다.

| | A2-2 (뉴스) | A2-3 (리뷰) |
|---|---|---|
| 멱등키 | 원문 링크 | `review_id` — 본문이 같아도 다른 사람의 리뷰일 수 있다 |
| 짧은 항목 | 그대로 둔다 | **거른다** — "좋아요" 는 감정은 있어도 근거가 없다 |
| AI 출력 | 요약 + 감성 | 감정 + **신뢰도** — 낮으면 사람이 확인할 목록이 된다 |
| 교차 검증 | 없음 | **별점 vs 본문 감정** — 어긋나면 오입력이거나 반어법 |

---

## 실행 방법

```bash
git clone https://github.com/dicia-jhoh/codyssey-a2-3.git
cd codyssey-a2-3

python3 --version                 # 3.10 이상
pip install -r requirements.txt

cp .env.example .env              # 값을 실제 키로 채웁니다 (AI 단계에만 필요)
```

### 전체 흐름

```bash
python -m reviewlens import --file data/sample_reviews.csv   # 1) 적재
python -m reviewlens clean                                   # 2) 정제
python -m reviewlens analyze --unanalyzed                    # 3) 감정 분석 (키 필요)
python -m reviewlens extract --sentiment 부정                # 4) 인사이트 추출 (키 필요)
python -m reviewlens stats                                   # 5) 통계 + 알림
python -m reviewlens dashboard                               # 6) 차트 + 리포트 + HTML
python -m reviewlens export --format both                    # 7) CSV + JSONL
```

### 키 없이 확인하기

적재·정제·조회·내보내기는 AI 없이 돕니다. 차트·대시보드는 감정 값이 있어야 그려집니다.

```bash
python -m reviewlens import --file data/sample_reviews.csv
python -m reviewlens clean
python -m reviewlens list --rating-min 4
python -m reviewlens export --format csv
```

---

## 서브커맨드 10개

| 명령 | 하는 일 | 주요 옵션 |
|---|---|---|
| `import` | CSV 적재 → `raw_reviews` | `--file` |
| `add` | 리뷰 1건 직접 입력 | `--text` · `--id` · `--product` · `--rating` · `--date` |
| `clean` | 정제 규칙 5종 + 중복 처리 | `--policy {skip,upsert}` · `--all` |
| `analyze` | 감정 + 신뢰도 | `--all` · `--unanalyzed` · `--id` · `--limit` |
| `extract` | 키워드·요약·개선 제안 | `--sentiment` · `--product` · `--date-from/to` |
| `list` | 목록 조회 | `--sentiment` · `--rating` · `--rating-min` · `--product` · `--date-from/to` · `--status` · `--sort` · `--asc` · `--page` · `--size` |
| `show` | 상세 조회 | `review_id` |
| `stats` | 통계 요약 + 감정 변화 알림 | `--as-of` |
| `dashboard` | 차트 3종 + 리포트 + HTML | `--format {md,txt}` · `--no-charts` · `--no-html` · `--as-of` |
| `export` | CSV / JSONL | `--format {csv,jsonl,both}` · `--sentiment` · `--rating-min` · `--product` |

**단계를 나눈 이유**는 비용과 실패 성격이 다르기 때문입니다. 적재는 파일 I/O, 정제는 계산,
분석은 **돈**이 듭니다. 한 명령으로 묶으면 분석이 실패했을 때 적재부터 다시 해야 합니다.
나눠 두면 실패한 단계만 다시 돌리면 되고, **SQLite 가 그 사이를 잇습니다.**

### argparse 구성

서브커맨드는 `add_subparsers()` 로 만들고 각각 `set_defaults(func=...)` 로 처리 함수를
붙입니다. `main()` 에 `if/elif` 사슬이 생기지 않습니다.

```python
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="reviewlens",
        description="고객 리뷰 감정 분석 — 적재·정제·분석·추출·조회·대시보드",
        epilog="예) python -m reviewlens import --file data/sample_reviews.csv && "
               "python -m reviewlens clean",
    )
    parser.add_argument("--config", default=config_module.CONFIG_FILE, help="설정 파일 경로")
    parser.add_argument("-v", "--verbose", action="store_true", help="DEBUG 로그까지 출력")
    sub = parser.add_subparsers(dest="command", required=True)

    p_import = sub.add_parser("import", help="CSV 리뷰 파일 적재")
    p_import.add_argument("--file", required=True, help="CSV 경로")
    p_import.set_defaults(func=_cmd_import)
```

`--all` 과 `--id` 처럼 **동시에 줄 수 없는 옵션**은 배타 그룹으로 묶어 argparse 가 먼저
막게 합니다.

```python
    p_an = sub.add_parser("analyze", help="AI 감정 분석 + 신뢰도")
    group = p_an.add_mutually_exclusive_group()
    group.add_argument("--all", action="store_true", help="전부 다시 분석")
    group.add_argument("--unanalyzed", action="store_true", help="아직 분석 안 한 것만(기본)")
    group.add_argument("--id", dest="review_id", help="리뷰 1건만")
```

`main()` 은 파싱하고 함수를 부르기만 합니다. exit code 는 **return** 합니다 — 테스트가
`main([...])` 를 직접 부를 수 있어야 하기 때문입니다.

```python
def main(argv: Sequence[str] | None = None) -> int:
    """진입점. exit code 를 **return** 한다."""
    args = build_parser().parse_args(argv)
    setup_logging(args.verbose)

    try:
        cfg = config_module.load_config(args.config)
    except ValueError as exc:
        print(f"[중단] {exc}", file=sys.stderr)
        return 1

    config_module.load_dotenv()
    storage.init_db(cfg["storage"]["db_path"])
    return int(args.func(args, cfg))
```

---

## 모듈 구성 (4개 이상 분리)

```text
codyssey-a2-3/
├── reviewlens/
│   ├── __main__.py    python -m reviewlens 진입점
│   ├── cli.py         서브커맨드 10개 · 로깅 설정
│   ├── config.py      config.json + 환경변수
│   ├── storage.py     SQLite — 스키마·CRUD·집계·조회 필터
│   ├── ingest.py      CSV 적재 · 수동 입력
│   ├── clean.py       정제 규칙 5종 · 언어 판정
│   ├── ai.py          감정 분석 · 인사이트 추출
│   ├── charts.py      matplotlib 차트 3종
│   ├── stats.py       품질 지표 · TOP N · 리포트 조립
│   ├── alert.py       감정 급증 알림(보너스)
│   ├── dashboard.py   단일 HTML 대시보드(보너스)
│   └── export.py      CSV · JSONL
├── config.json        임계값 · 색 · 중복 정책 · 경로
├── data/sample_reviews.csv   샘플 리뷰 35건
├── docs/dashboard-sample.html  대시보드 결과물 샘플
└── images/            문서용 차트 샘플
```

나눈 기준은 **바뀌는 이유**입니다. `ingest.py` 는 입력 형식이 바뀔 때, `clean.py` 는 정제
규칙이 바뀔 때, `ai.py` 는 프롬프트·모델이 바뀔 때 바뀝니다. `cli.py` 에는 SQL 도 HTTP 도
없고 **순서와 옵션만** 있습니다.

---

## 데이터 입력

### CSV 헤더를 고정하지 않는다

쇼핑몰마다 열 이름이 다릅니다. 사용자에게 "열 이름을 `text` 로 바꾸세요"라고 요구하는 대신
**우리가 맞춥니다.**

```python
TEXT_COLUMNS = ("text", "review", "review_text", "content", "리뷰", "내용")
ID_COLUMNS = ("review_id", "id", "리뷰번호")
RATING_COLUMNS = ("rating", "score", "star", "별점", "평점")
DATE_COLUMNS = ("created_at", "date", "written_at", "작성일")
PRODUCT_COLUMNS = ("product", "item", "product_name", "제품", "상품명")
```

```python
def _pick(row: dict, candidates: tuple[str, ...]) -> str | None:
    for name in candidates:
        if name in row and str(row[name]).strip():
            return str(row[name]).strip()
    return None
```

### BOM 처리

```python
        with open(path, encoding="utf-8-sig", newline="") as f:
            rows = list(csv.DictReader(f))
```

`utf-8-sig` 로 여는 이유: 엑셀이 저장한 CSV 는 맨 앞에 BOM 이 붙습니다. 그냥 `utf-8` 로
읽으면 **첫 열 이름이 `﻿review_id`** 가 되어 헤더 매칭이 **조용히** 실패합니다.
오류도 안 나고 그 열만 비어 나오기 때문에 원인을 찾기 어렵습니다.

### 샘플 데이터 (35건)

`data/sample_reviews.csv` 는 검증 목적을 담아 구성했습니다.

| 축 | 구성 | 무엇을 확인하나 |
|---|---|---|
| 제품 | 3종(이어폰·스피커·워치) | 제품별 비교 분석(보너스) |
| 언어 | 한국어 31 · 영어 4 | 다국어 감정 분석(보너스) |
| 별점 | 1~5 고르게(6/6/4/9/10) | 별점별 감정 분포 차트 |
| 날짜 | 2026-07-01 ~ 07-16 | 시간별 추이 차트 |
| **부정 집중** | 7/12~14 에 몰아 둠 | **감정 급증 알림**(보너스) |

---

## raw / clean 분리

| | `raw_reviews` | `clean_reviews` |
|---|---|---|
| 무엇 | 받은 **그대로** | 규칙을 통과한 것 |
| 함께 남기는 것 | 적재 시각·출처·방법 | 정제 시각·raw_id(추적) |
| 손대나 | **절대 안 댄다** | 규칙이 바뀌면 다시 만든다 |
| 중복 | 그대로 쌓인다 | `review_id` UNIQUE |

```sql
CREATE TABLE IF NOT EXISTS raw_reviews (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    ingested_at  TEXT NOT NULL,   -- 적재 시각 (ISO8601)
    source       TEXT NOT NULL,   -- 파일 경로 또는 'manual'(add 명령)
    method       TEXT NOT NULL,   -- 'csv' | 'manual'
    payload      TEXT NOT NULL    -- 원본 행 전체(JSON)
);
```

**리뷰는 한 번 놓치면 다시 받기 어렵습니다** — 고객이 지우거나 쇼핑몰이 페이지를 내립니다.
정제 규칙(짧은 리뷰 기준·별점 범위)은 나중에 바뀔 수 있는데, 원본을 덮어쓰면 되돌릴 수
없습니다. **수집은 되돌릴 수 없고 정제는 되돌릴 수 있다** — 그 경계를 테이블 경계로 만든
것입니다.

`payload` 에 원본 행을 통째로 넣는 이유도 같습니다. 지금 안 쓰는 열이라도 나중에 필요해질
수 있는데, 적재 시점에 버리면 되찾을 방법이 없습니다.

### 메모리를 쓰지 않는 이유

서브커맨드는 **각각 별도 프로세스**로 실행됩니다(`import` 다음에 `clean`, 그다음 `analyze`).
프로세스가 끝나면 메모리는 사라지므로 **디스크가 아니면 단계 사이를 이을 수 없습니다.**
영구 저장소가 "있으면 좋은 것"이 아니라 이 구조의 **전제**입니다.

---

## 정제 규칙 5종

### ① 필수 필드 검증

```python
    text = normalize_text(fields.get("text"))
    if not text:
        return None, "리뷰 텍스트 없음"
```

### ② 텍스트 정규화

```python
def normalize_text(value: str | None) -> str:
    if not value:
        return ""
    text = html.unescape(str(value))
    return WHITESPACE.sub(" ", text).strip()
```

`&amp;` 를 먼저 되돌리는 이유: 쇼핑몰 CSV 에는 HTML 엔티티가 그대로 들어 있는 일이 흔합니다.
그대로 두면 AI 가 `&amp;` 를 글자로 읽습니다.

### ③ 별점 범위 검증 — 리뷰는 살린다

```python
def parse_rating(value, low: int, high: int) -> int | None:
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
```

별점이 틀렸다고 **리뷰를 버리지 않습니다** — 본문은 여전히 감정 분석에 쓸 수 있습니다.
별점만 비워 두고 "별점 확보율" 지표로 드러냅니다.

### ④ 날짜 형식 통일

```python
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y.%m.%d", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S"):
        try:
            from datetime import datetime

            return datetime.strptime(text[: len(fmt) + 6], fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    logger.warning("날짜 형식을 인식하지 못했습니다: %r", text[:30])
    return None
```

**시각을 버리고 날짜만 남기는 이유**: 리뷰 분석의 시간 단위는 '일' 입니다. 시분초까지 남기면
일자별 집계 때마다 잘라내야 하고, 그 과정에서 시간대 문제가 끼어듭니다.

### ⑤ 짧은 리뷰 필터링

```python
    min_length = cfg["clean"]["min_text_length"]
    if len(text) < min_length:
        # 짧은 리뷰를 거르는 이유: "좋아요"·"굿" 은 감정은 있어도 **왜 그런지**가 없다.
        # 키워드 추출·개선 제안에 아무 기여를 못 하면서 AI 호출 비용만 든다.
        return None, f"너무 짧음({len(text)}자 < {min_length}자)"
```

임계값은 `config.json` 에 둡니다 — 도메인마다 적정선이 다르고, 바꿔 가며 결과를 비교해야
합니다.

### 제외 사유를 나눠 세는 이유

```python
    stats = {"total": 0, "inserted": 0, "skipped": 0, "updated": 0, "invalid": 0}
    reasons: dict[str, int] = {}
```

`invalid` 만 세면 "왜 5건이 빠졌지?"를 답할 수 없습니다. **짧아서 빠진 것**과 **필수 필드가
없어 빠진 것**은 대응이 다릅니다(임계값 조정 vs 데이터 문제).

---

## 중복 처리 — 무엇을 키로 삼나

`review_id` 를 멱등키로 씁니다.

| 후보 | 왜 안 쓰나 |
|---|---|
| 본문 | 다른 사람이 쓴 같은 문장일 수 있다("배송 빨라요" 는 흔하다) |
| 본문+작성일 | 같은 날 같은 말을 한 두 사람이 하나로 합쳐진다 |
| **review_id** | **고객이 리뷰를 수정해도 유지된다** ✅ |

```python
    existing = conn.execute(
        "SELECT id FROM clean_reviews WHERE review_id = ?", (item["review_id"],)
    ).fetchone()
    if existing:
        if policy == "skip":
            return "skipped"
```

| 정책 | 언제 | 왜 |
|---|---|---|
| `skip` (기본) | 같은 파일을 다시 넣을 때 | **이미 분석한 감정 결과를 지우지 않는다.** 다시 분석하면 돈이 또 든다 |
| `upsert` | 고객이 리뷰를 수정했을 때 | 본문·별점을 갱신한다 |

---

## AI 단계

### 감정 + 신뢰도

```python
def build_sentiment_prompt(text: str, language: str) -> str:
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
```

**별점을 프롬프트에 넣지 않는 것**이 중요합니다. 넣으면 모델이 별점을 그대로 따라가고,
그러면 "별점과 본문이 어긋나는 리뷰"를 영영 못 찾습니다. 별점은 **검증용으로 남겨 둡니다.**

**신뢰도를 함께 받는 이유**: "부정"이라는 판정만으로는 얼마나 확신하는지 알 수 없습니다.
0.55 로 부정 판정한 리뷰와 0.95 는 다르게 다뤄야 합니다 — 낮은 신뢰도는 **사람이 확인할
목록**이 됩니다.

```python
    # 신뢰도가 낮은 건은 사람이 확인할 목록이다 — 자동 판정을 그대로 믿지 않는다.
    "low_confidence": [
        (r["review_id"], r["sentiment"], r["confidence"])
        for r in rows
        if r["confidence"] is not None and r["confidence"] < 0.7
    ][:10],
```

### 호출 본체

```python
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
```

값을 검증한 뒤에만 저장합니다.

```python
    sentiment = str(data.get("sentiment") or "").strip()
    if sentiment not in SENTIMENTS:
        # 허용 목록 밖 값은 버린다 — "다소 긍정적" 같은 값이 섞이면 집계가 갈린다
        logger.error("[분석 %s] 알 수 없는 감정 값: %r", row["review_id"], sentiment)
        return None
    ...
    # 범위를 벗어난 값을 그대로 저장하면 평균 신뢰도가 1.0 을 넘는 일이 생긴다
    confidence = min(max(confidence, 0.0), 1.0)
```

### 실패는 그 건만 건너뛴다

```python
    except requests.HTTPError as exc:
        code = exc.response.status_code if exc.response is not None else "?"
        logger.error("[분석 %s] HTTP %s — %s", row["review_id"], code, http_hint(code))
        return None
```

100건을 도는 중 3건이 실패했다고 나머지를 포기할 수 없습니다. **로그에 남기고 스킵**,
통계에 `failed` 로 셉니다. 이미 분석한 리뷰는 기본적으로 다시 부르지 않습니다(돈이 듭니다).

### 인사이트 추출

```python
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
```

감정 라벨을 함께 넣는 이유: "부정 리뷰에서 무엇이 반복되는가"를 물으려면 모델이 어느 리뷰가
부정인지 알아야 합니다. 라벨 없이 넣으면 긍·부정 키워드가 섞여 나옵니다.

**"실행 가능한 행동으로 써라"** 는 개선 제안이 쓸모 있으려면 필수입니다. "품질을 높인다"는
아무것도 알려 주지 않습니다.

---

## 차트 3종

세 차트가 **서로 다른 질문**에 답합니다.

| 차트 | 질문 | 형태 |
|---|---|---|
| 감정 분포 | "전체적으로 어떤가?" | 도넛(비율) |
| 시간별 추이 | "나빠지고 있나?" | 누적 영역(변화) |
| 별점별 감정 분포 | "별점과 본문이 맞는가?" | 누적 막대(교차 검증) |

| 감정 분포 | 시간별 추이 |
|---|---|
| ![감정 분포](images/sentiment_share.png) | ![시간별 추이](images/sentiment_trend.png) |

![별점별 감정 분포](images/rating_sentiment.png)

### 한글 폰트 — A2-1 에서 확립한 처리

```python
matplotlib.use("Agg")   # pyplot import 전에. 화면 없는 환경에서 창을 띄우려다 죽는 것을 막는다

KOREAN_FONTS = [
    "Malgun Gothic",     # Windows
    "AppleGothic",       # macOS
    "NanumGothic",       # Linux (fonts-nanum)
    "NanumSquareRound",
    "Noto Sans CJK KR",  # Linux (fonts-noto-cjk)
    "Noto Sans KR",
]
```

matplotlib 기본 폰트에는 한글 글리프가 없어 축 라벨이 전부 네모(□)로 나옵니다.
**그림은 정상적으로 만들어지므로 파일만 보면 놓칩니다.**

### 시간별 추이를 누적으로 그리는 이유

```python
    ax.stackplot(
        dates,
        [series[s] for s in SENTIMENT_ORDER],
        labels=SENTIMENT_ORDER,
        colors=[palette.get(s, FALLBACK_COLOR) for s in SENTIMENT_ORDER],
        alpha=0.9,
    )
```

날짜마다 리뷰 수가 다르므로 선을 따로 그리면 "부정이 늘었다"가 **전체가 늘어서인지 부정
비중이 커져서인지** 구분되지 않습니다. 누적하면 총량과 구성이 한 그림에 함께 보입니다.

### 별점별 분포가 이 미션에서 특히 중요한 이유

**별점 5점인데 본문이 부정**이면 별점을 잘못 눌렀거나 비꼬는 리뷰입니다. 둘을 함께 봐야
데이터를 믿을 수 있고, 어긋난 칸이 바로 **사람이 확인할 목록**이 됩니다.

```python
    # barh 는 목록 첫 항목을 맨 아래에 그린다. ratings 가 오름차순(1→5)이므로
    # 뒤집지 않아야 ★5 가 위로 온다 — 별점이 높은 것부터 읽는 순서다.
    ax.set_xlabel("리뷰 수")
    ax.set_title("별점별 감정 분포")
    # 범례를 그림 밖으로 뺀다 — 안에 두면 가장 긴 막대(★5)를 가린다.
    ax.legend(loc="upper left", bbox_to_anchor=(1.01, 1), borderaxespad=0)
```

두 줄 다 **실제로 겪고 고친 것**입니다. 처음에는 `invert_yaxis()` 를 넣어 ★1 이 위로 갔고,
범례를 그림 안에 두어 ★5 막대를 가렸습니다.

### 표시 순서와 색을 고정한다

```python
# 감정 표시 순서 — 긍정→중립→부정 고정. 데이터에 따라 순서가 바뀌면 여러 차트를
# 나란히 놓고 볼 때 색 위치가 달라져 읽기 어렵다.
SENTIMENT_ORDER = ["긍정", "중립", "부정"]
```

색은 `config.json` 에 둡니다 — 브랜드마다 다를 수 있고, 색맹 대응 팔레트로 바꾸는 것이
**설정 변경만으로** 되어야 합니다.

---

## 조회 — list · show

### list: 필터 · 정렬 · 페이지네이션

```text
$ python -m reviewlens list --sentiment 부정 --sort rating --asc --size 4
총 12건 · 1/3 페이지 · 정렬 rating 오름차순
리뷰ID    작성일         별점   감정   신뢰    본문
------------------------------------------------------------------------------------
R008    2026-07-04  ★1   부정   0.65  이틀 만에 전원이 안 켜집니다. 교환 요청했어요.
R023    2026-07-12  ★1   부정   0.74  한 달도 안 돼서 오른쪽 소리가 안 납니다. 실망입니다.
R024    2026-07-12  ★1   부정   0.67  배송 상자가 찌그러져 왔고 제품에도 흠집이 있었습니다.
R026    2026-07-13  ★1   부정   0.74  고객센터 연결이 안 됩니다. 환불 절차도 복잡해요.

다음 페이지: --page 2
```

**목록과 건수가 같은 조건을 쓰게** 하는 것이 페이지네이션의 핵심입니다.

```python
def _where_clause(sentiment, rating, rating_min, product, date_from, date_to, status):
    """조건 → (WHERE 절, 파라미터).

    목록 조회와 건수 세기가 **같은 조건**을 쓰도록 뽑아냈다. 둘이 어긋나면 "3페이지 중
    2페이지"인데 3페이지가 비는 일이 생긴다.
    """
```

정렬 컬럼은 **허용 목록**으로 받습니다. 사용자 입력을 SQL 에 그대로 넣으면 주입이 됩니다.

```python
SORT_COLUMNS = {
    "date": "created_at",
    "rating": "rating",
    "confidence": "confidence",
    "id": "id",
}
```

### show: 상세 + 신뢰도 경고

```text
$ python -m reviewlens show R023
======================================================================
리뷰 R023
======================================================================
제품     : 무선 이어폰 A
별점     : ★
작성일   : 2026-07-12
언어     : ko

[본문]
한 달도 안 돼서 오른쪽 소리가 안 납니다. 실망입니다.

[감정 분석]
  판정   : 부정
  신뢰도 : 0.74
```

신뢰도가 0.7 미만이면 확인하라는 문구가 함께 나옵니다.

```python
        if row["confidence"] is not None and row["confidence"] < 0.7:
            print("  ⚠ 신뢰도가 낮습니다 — 사람이 확인하는 것이 좋습니다")
```

---

## 통계 (`stats`)

```text
==============================================================
 리뷰 통계 요약
==============================================================
  총 리뷰(정제 후) : 35건 (원본 35건)
  감정 분석 완료   : 35건
  평균 별점        : 3.31
  평균 신뢰도      : 0.782

  [감정별 분포]
    긍정    19건  54.3%  ███████████
    부정    12건  34.3%  ███████
    중립     4건  11.4%  ██

  [언어별]
    ko   31건
    en   4건

  [제품별]
    제품                 건수     평균별점       긍/중/부
    무선 이어폰 A           16     3.06       7/3/6
    블루투스 스피커 B         11     3.45       7/0/4
    스마트 워치 C            8     3.62       5/1/2

  [신뢰도 0.7 미만 — 사람이 확인할 목록]
    R028  부정(0.65)
    R020  부정(0.62)
```

막대(`█`)를 함께 그리는 이유: 숫자만 있으면 비율 차이가 눈에 안 들어옵니다. 5% 당 한 칸이라
**숫자와 길이를 함께** 읽습니다.

### 품질 지표 — 중복률을 함께 낸다

```python
    duplicates = max(counts["raw"] - counts["clean"], 0)
    return [
        ("고유 리뷰 비율", f"{counts['clean']}/{counts['raw']} ({counts['clean'] / raw * 100:.1f}%)"),
        ("적재 중복률", f"{duplicates}/{counts['raw']} ({duplicates / raw * 100:.1f}%) "
                     f"— 같은 리뷰를 다시 넣은 비율(재실행에서는 정상)"),
```

raw 대비 clean 비율만 보면 "정제에서 절반이 버려졌다"로 읽힙니다. 같은 CSV 를 두 번 넣으면
중복이 생기는 것이 정상인데도요. **중복률을 옆에 두어야** 낮은 통과율이 문제인지 정상인지
구분됩니다(A2-2 에서 겪고 여기서도 그대로 적용했습니다).

---

## 보너스 (수행)

### 1. 다국어 감정 분석

언어를 먼저 판정하고, 그 정보를 프롬프트에 넣습니다.

```python
def detect_language(text: str) -> str:
    """언어 판정 — 한글이 있으면 'ko', 아니면 'en'(보너스: 다국어).

    라이브러리를 쓰지 않은 이유: 이 미션의 리뷰는 한국어·영어 두 가지뿐이고, 한글 음절
    존재 여부만으로 정확히 갈린다. 언어가 늘어나면 `langdetect` 같은 도구가 필요하지만
    **지금 필요 없는 의존성을 미리 넣지 않는다.**
    """
    return "ko" if HANGUL.search(text) else "en"
```

**원문 언어 그대로 판단시키는 것**이 핵심입니다. 모델이 영어 리뷰를 한국어로 옮겨 판단하면
뉘앙스가 바뀝니다. 결과 라벨만 한국어로 통일합니다.

```python
        "en": "The review is in English. Judge it in English, but answer with Korean labels.",
```

`stats` 의 `[언어별]` 항목이 실제로 갈렸는지 보여 줍니다(ko 31 · en 4).

### 2. 감정 변화 알림

최근 N일 부정 비율이 급증하면 경고합니다.

```text
$ python -m reviewlens stats --as-of 2026-07-14
  [감정 변화 알림]
  창 크기: 3일 · 기준선 50% · 최소 표본 5건
  최근 2026-07-12~2026-07-14  리뷰   8건 · 부정   8건 · 100.0%
  직전 2026-07-09~2026-07-11  리뷰   6건 · 부정   1건 · 16.7%
  ⚠ 최근 3일(2026-07-12~2026-07-14) 부정 비율이 100.0% (8/8건)로 기준선 50% 를
    넘었습니다. 직전 같은 기간(2026-07-09~2026-07-11) 대비 부정 비율이
    16.7% → 100.0% (+83.3%p) 로 급증했습니다.
```

판정 축이 **두 개**입니다.

```python
    if recent_ratio >= threshold:
        messages.append(...)           # ① 절대 기준선
    if prev_ratio is not None and prev_total >= min_reviews:
        delta = recent_ratio - prev_ratio
        if delta >= 0.2:
            messages.append(...)       # ② 직전 기간 대비 변화
```

**절대 임계값만 쓰면** 원래 부정이 많은 제품에서는 늘 경고가 뜨고, 원래 좋던 제품이 나빠지는
것은 놓칩니다. 둘 다 봐야 합니다.

**건수가 아니라 비율로** 보는 이유: 부정 건수만 보면 전체 리뷰가 늘어난 날에 항상 경고가
뜹니다.

표본이 적으면 판정을 보류합니다.

```python
    # 표본이 너무 적으면 판정하지 않는다 — 리뷰 2건 중 1건이 부정이어도 50% 다.
    if recent_total < min_reviews:
```

기준일은 `--as-of` 로 바꿀 수 있습니다. **오늘로 고정하지 않은 이유**: 과거 데이터를 분석할
때 창이 통째로 비어 버리고, "어느 시점에 경고가 떴을지"를 되짚어 볼 수도 있어야 합니다.

```python
        if reference is None:
            # 기준일을 '오늘'로 고정하지 않는다 — 과거 데이터를 분석할 때 창이 비어 버린다.
            row = conn.execute(
                "SELECT MAX(created_at) AS d FROM clean_reviews WHERE created_at IS NOT NULL"
            ).fetchone()
```

경고가 없을 때도 **무엇을 봤는지** 표로 보여 줍니다 — "이상 없음"만 뜨면 정말 검사한 건지
알 수 없습니다.

### 3. 단일 HTML 대시보드

```bash
python -m reviewlens dashboard
# → output/dashboard/dashboard.html (약 214KB, 차트 3장 포함)
```

`output/` 은 `.gitignore` 에 있어 저장소에 올라가지 않습니다 — 생성물이라 코드에서 언제든
다시 만들 수 있기 때문입니다. 대신 **결과가 어떻게 생겼는지 보라고 샘플 한 장**을
[`docs/dashboard-sample.html`](docs/dashboard-sample.html) 에 넣어 두었습니다.

GitHub 은 HTML 을 렌더하지 않고 소스로 보여 줍니다. 실제 화면으로 보려면 둘 중 하나입니다.

| 방법 | 어떻게 |
|---|---|
| 샘플을 본다 | 파일을 내려받아(Raw → 저장) 브라우저로 엽니다 |
| 직접 만든다 | 아래 3줄을 돌리면 같은 것이 `output/` 에 생깁니다 |

```bash
python -m reviewlens analyze     # 감정 분석 (GEMINI_API_KEY 필요)
python -m reviewlens extract     # 인사이트 추출
python -m reviewlens dashboard   # → output/dashboard/dashboard.html
```

샘플은 `data/sample_reviews.csv` 35건을 기준으로 만든 것이라, 위 3줄을 따라 하면 같은 형태의
화면이 나옵니다. 다만 **숫자까지 같지는 않습니다** — 감정 판정은 모델의 답이라 칭찬과 불만이
비슷하게 섞인 리뷰는 실행마다, 모델마다 긍정·중립·부정 사이에서 갈립니다.

**파일 하나로 완결**시킵니다. 대시보드는 남에게 보내는 물건인데, HTML·이미지가 따로 있으면
폴더째 보내야 하고 한 파일만 열면 이미지가 깨집니다.

```python
def embed_image(path: str | None) -> str | None:
    """PNG → data URI. 실패하면 None(그 자리는 안내 문구로 대체된다).

    base64 는 원본보다 약 33% 커진다. 차트 3장 정도면 수백 KB 수준이라 감당되지만,
    수십 장이 되면 이미지를 따로 두고 링크하는 편이 낫다.
    """
```

담기는 것: KPI 5개 · 차트 3종 · 품질 지표 · 제품별 비교 · 키워드 · AI 추출 · 확인 필요 목록.
경고가 있으면 **맨 위**에 띄웁니다 — 끝까지 읽지 않는 사람도 봐야 합니다.

리뷰 본문은 반드시 이스케이프합니다.

```python
def _esc(value) -> str:
    """HTML 이스케이프. 리뷰 본문에 `<` 가 들어 있으면 태그로 해석된다."""
    return html.escape(str(value if value is not None else "-"))
```

미션 제약대로 **실시간 웹 서버는 만들지 않습니다** — 정적 HTML 하나입니다.

### 4. 제품별 비교 분석

```sql
SELECT product,
       COUNT(*) AS total,
       AVG(rating) AS avg_rating,
       SUM(CASE WHEN sentiment = '긍정' THEN 1 ELSE 0 END) AS positive,
       SUM(CASE WHEN sentiment = '중립' THEN 1 ELSE 0 END) AS neutral,
       SUM(CASE WHEN sentiment = '부정' THEN 1 ELSE 0 END) AS negative
FROM clean_reviews
WHERE product IS NOT NULL
GROUP BY product ORDER BY total DESC
```

`SUM(CASE WHEN ...)` 로 **한 번의 조회에서** 감정별 개수를 함께 냅니다. 감정마다 따로 세면
제품 수 × 감정 수만큼 쿼리가 나갑니다.

`stats`·리포트·HTML 대시보드가 모두 이 집계를 씁니다 — 같은 숫자를 세 곳에서 따로 계산하면
언젠가 어긋납니다.

---

## 내보내기 — CSV vs JSONL

| | CSV | JSONL |
|---|---|---|
| 소비자 | 사람 · 엑셀 | 프로그램 |
| 줄바꿈이 든 값 | 약하다(엑셀에서 행이 밀린다) | 강하다 |

```python
            # 표 한 칸에 줄바꿈이 들어가면 엑셀에서 행이 밀려 보인다 — 공백으로 편다.
            if item.get("text"):
                item["text"] = str(item["text"]).replace("\n", " ")
```

인코딩도 포맷마다 다르게 정합니다.

```python
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
```

`utf-8-sig`(BOM 포함)를 쓰는 이유: 엑셀(Windows)이 BOM 없는 UTF-8 CSV 를 열면 한글이
깨집니다. **읽을 때와 쓸 때 같은 이유로 BOM 을 다룹니다.**

---

## 로깅

```python
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
        stream=sys.stderr,
    )
    # 라이브러리 내부 로그는 WARNING 부터만. matplotlib 은 축 라벨 하나에도 INFO 를 찍어
    # 우리 진행 메시지를 덮어 버린다.
    for noisy in ("matplotlib", "PIL", "urllib3"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
```

| 레벨 | 무엇에 | 예 |
|---|---|---|
| INFO | 정상 진행 | `CSV 읽기: data/sample_reviews.csv 35행` |
| WARNING | 계속 돌지만 확인 필요 | `별점이 범위(1~5) 밖입니다: 7` |
| ERROR | 그 단위는 실패 | `[분석 R023] HTTP 429 — 요청 한도 초과` |

로그는 **stderr**, 산출물(리포트·목록)은 **stdout** 입니다. `reviewlens stats | less` 를
했을 때 진행 메시지가 섞이면 안 됩니다.

---

## 실행 결과 (실측 로그)

```text
$ python -m reviewlens import --file data/sample_reviews.csv
19:32:54 [INFO] reviewlens.ingest: CSV 읽기: data/sample_reviews.csv 35행
적재 35건 (원본 저장소)

$ python -m reviewlens clean
19:32:55 [INFO] reviewlens.clean: 정제 완료: 대상 35 · 신규 35 · 중복 0 · 갱신 0 · 제외 0
정제 대상 35 · 신규 35 · 중복 0 · 갱신 0 · 제외 0

$ python -m reviewlens dashboard --as-of 2026-07-14
19:33:28 [INFO] reviewlens.charts: 차트 저장: output/charts/sentiment_share.png
19:33:28 [INFO] reviewlens.charts: 차트 저장: output/charts/sentiment_trend.png
19:33:28 [INFO] reviewlens.charts: 차트 저장: output/charts/rating_sentiment.png
19:33:28 [WARNING] reviewlens.alert: 감정 변화 경고 — 최근 3일(2026-07-12~2026-07-14)
  부정 비율이 100.0% (8/8건)로 기준선 50% 를 넘었습니다. …
19:33:28 [INFO] reviewlens.stats: 리포트 저장: output/reports/report_2026-07-28.md
19:33:28 [INFO] reviewlens.dashboard: 대시보드 저장: output/dashboard/dashboard.html

$ python -m reviewlens export --format both
19:33:40 [INFO] reviewlens.export: CSV 저장: output/exports/reviews_2026-07-28.csv (35건)
19:33:40 [INFO] reviewlens.export: JSONL 저장: output/exports/reviews_2026-07-28.jsonl (35건)
```

키가 없을 때:

```text
$ python -m reviewlens analyze
[안내] 환경변수 GEMINI_API_KEY 가 설정되어 있지 않습니다 — AI 단계를 실행할 수 없습니다.
  macOS/Linux : export GEMINI_API_KEY="YOUR_KEY"
  PowerShell  : $env:GEMINI_API_KEY="YOUR_KEY"
  또는 .env 파일에 GEMINI_API_KEY=YOUR_KEY (.gitignore 에 있어 커밋되지 않습니다)
```

---

## API 키 관리

| 층 | 무엇을 | 어디에 |
|---|---|---|
| 1 | 코드는 **이름만** 안다 | `LLM_KEY_NAME = "GEMINI_API_KEY"` |
| 2 | `.env` 를 커밋에서 제외 | `.gitignore` |
| 3 | 형식만 공유 | `.env.example` 의 값은 `YOUR_KEY` |

```python
def get_key(name: str = LLM_KEY_NAME) -> str | None:
    """환경변수에서 키를 읽는다. 없으면 None — 호출한 쪽이 안내 후 결정한다."""
    value = os.environ.get(name, "").strip()
    return value or None
```

`.env` 로더의 우선순위가 한 줄에 들어 있습니다.

```python
            if key and key not in os.environ:
                os.environ[key] = value.strip().strip('"').strip("'")
```

`if key not in os.environ` 이 **터미널에서 준 값이 `.env` 를 이기게** 합니다.

### 어떤 키를 넣나 — Gemini 무료 티어

기본 제공자는 **Google Gemini** 입니다. [Google AI Studio](https://aistudio.google.com/apikey)
에서 구글 계정으로 로그인하면 키가 바로 나오고, **결제 수단 등록 없이 무료 등급으로 시작**할
수 있습니다. 무료 등급에는 분당·하루 요청 수 한도가 있습니다(모델마다 다르고 정책이 바뀌므로
정확한 수치는 [공식 요금 문서](https://ai.google.dev/gemini-api/docs/pricing)를 보세요).

한도에 걸리면 HTTP 429 가 오고, 이 도구는 그 건만 건너뛰고 계속 돕니다.

```text
[분석 R014] HTTP 429 — 요청 한도 초과 — 잠시 후 재시도하세요
```

`analyze` 는 기본이 `unanalyzed` 대상이라, 한도가 풀린 뒤 같은 명령을 다시 치면 **실패한 건만**
이어서 처리합니다. 처음부터 다시 돌 필요가 없습니다.

한도는 **분당** 기준이라, 리뷰가 많으면 `--limit` 으로 끊어 도는 편이 빠릅니다. 한 번에 다
쏘면 한도를 넘긴 나머지가 전부 429 로 떨어집니다.

```bash
python -m reviewlens analyze --limit 15   # 1분 기다렸다 다시
```

모델은 `config.json` 의 `ai.model` 에서 고릅니다.

| 값 | 성격 |
|---|---|
| `gemini-flash-latest` (기본) | 최신 flash 로 자동 이동하는 별칭. 모델 ID 가 낡아 죽지 않습니다 |
| `gemini-3.7-flash` 등 고정 ID | 결과 재현이 필요할 때. 같은 코드가 언제 돌아도 같은 모델을 씁니다 |

### 다른 제공자로 바꾸기 — OpenAI 호환 endpoint

Gemini 는 **OpenAI 호환 endpoint** 를 제공합니다. 요청과 응답의 생김새가 OpenAI Chat
Completions 와 같다는 뜻이라, 호출 코드는 한 벌이면 됩니다.

| | 값 |
|---|---|
| 인증 헤더 | `Authorization: Bearer <키>` |
| 요청 본문 | `{"model": ..., "messages": [...], "temperature": ...}` |
| 응답 경로 | `choices[0].message.content` |

세 가지가 같으므로 `call_llm` 은 **URL 상수 하나**만 알면 됩니다.

```python
LLM_URL = "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"
```

OpenAI 로 되돌리려면 세 곳만 바꿉니다.

| 무엇을 | 어디 | 값 |
|---|---|---|
| URL | `reviewlens/ai.py` 의 `LLM_URL` | `https://api.openai.com/v1/chat/completions` |
| 모델 | `config.json` 의 `ai.model` | `gpt-4o-mini` 등 |
| 키 이름 | `reviewlens/config.py` 의 `LLM_KEY_NAME` | `OPENAI_API_KEY` |

같은 방식으로 OpenAI 호환 endpoint 를 내놓는 다른 서비스(로컬 모델 서버 포함)에도 붙습니다.

**주의**: 호환 레이어라 OpenAI 전용 옵션(`response_format`·`logprobs` 등)은 무시되거나 오류가
납니다. 이 도구는 `model`·`messages`·`temperature` 만 쓰므로 해당되지 않습니다.

한 가지 실제 차이는 있습니다 — 모델에 따라 JSON 응답에 ```` ```json ```` 코드펜스를 붙여 오는
경우가 있습니다. `parse_json` 이 펜스를 먼저 벗기므로 어느 쪽이든 똑같이 읽힙니다.

```python
FENCE = re.compile(r"^\s*```(?:json)?\s*|\s*```\s*$")
```

---

## 제약 조건 준수

| 제약 | 어떻게 지켰나 |
|---|---|
| Python 3.10 이상 | `str \| None` 등 3.10+ 문법 |
| argparse 서브커맨드 10개 | `import`·`add`·`clean`·`analyze`·`extract`·`list`·`show`·`stats`·`dashboard`·`export` |
| CSV 리뷰 읽기 | `csv.DictReader` + 헤더 후보 매칭 |
| raw / clean 분리 | 테이블 2개 + `raw_id` 추적 |
| 정제 규칙 5종 | 필수 필드·정규화·별점 범위·날짜 통일·짧은 리뷰 |
| 중복 정책 | `review_id` UNIQUE + skip/upsert |
| 감정 + 신뢰도 | `analyze` — 0.0~1.0 범위 강제 |
| 추출 항목 2개 이상 | 긍정·부정 키워드, 요약, 개선 제안, 우선순위 (**5개**) |
| 차트 3종 · 한글 폰트 | 감정 분포·시간별 추이·별점별 분포 |
| 내보내기 2포맷 | CSV · JSONL |
| 설정 파일 | `config.json` |
| logging | INFO/WARNING/ERROR |
| 영구 저장소 필수 | SQLite (메모리 사용 안 함) |
| 4모듈 이상 | `reviewlens/` 아래 **12개** |
| 샘플 데이터 30건 이상 | `data/sample_reviews.csv` **35건** |
| 웹 대시보드 없음 | 정적 HTML 파일 하나 |
| 크롤링 없음 | 파일 입력만 |
| 키를 코드에 쓰지 않음 | 환경변수 이름만 |
| (보너스) 다국어 | 한/영 판정 + 원문 언어 판단 |
| (보너스) 급증 알림 | 절대 기준선 + 직전 대비 변화 |
| (보너스) HTML 대시보드 | base64 내장 단일 파일 |
| (보너스) 제품 비교 | `stats`·리포트·대시보드 3곳 |

---

## What-if — 조건이 바뀌면

### Q1. 리뷰가 10만 건이면

지금 구조에서 먼저 아픈 곳은 **AI 호출 비용**입니다(건당 1회). 세 가지 순서로 대응합니다.

| 순위 | 대응 | 어디를 |
|---|---|---|
| 1 | 표본 추출 — 전수 대신 날짜·제품별 층화 표본 | `run_analyze` 의 대상 선정 |
| 2 | 배치 호출 — 한 요청에 리뷰 여러 건 | `build_sentiment_prompt` 를 배열 입력으로 |
| 3 | 사전 필터 — 별점 3점만 AI 로(1·5점은 명확) | `select_clean` 조건 |

3번이 가장 값싸지만 **별점과 본문이 어긋나는 리뷰를 놓칩니다.** 이 도구의 존재 이유 중
하나가 그 검출이므로, 비용을 줄이더라도 1·5점 일부는 표본으로 남겨야 합니다.

조회 쪽은 인덱스가 이미 걸려 있어(`created_at`·`product`·`sentiment`) 10만 건까지는
버팁니다. 그 이상은 `LIMIT` 없는 `select_clean` 호출(키워드 집계·추출)이 먼저 문제가 됩니다.

### Q2. 감정을 3종이 아니라 5단계로 나눈다면

바꿀 곳이 **네 군데**입니다.

| 위치 | 무엇을 |
|---|---|
| `ai.SENTIMENTS` | 허용 목록 확장 |
| `charts.SENTIMENT_ORDER` | 표시 순서 |
| `config.json` 의 `colors` | 색 5개 |
| `alert.check` | "부정" 판정 기준(매우부정 + 부정) |

**네 번째가 놓치기 쉽습니다.** 알림이 `sentiment == "부정"` 만 세고 있어서, 5단계로 바꾸면
"매우 부정"이 집계에서 빠집니다. 값이 늘어날 때는 **그 값을 소비하는 곳**을 전부 훑어야
합니다.

### Q3. 실시간으로 보고 싶다면

미션 제약상 정적 파일이지만, 확장 경로는 정해져 있습니다. `dashboard.build_html()` 이
문자열을 돌려주므로 그대로 HTTP 응답 본문으로 쓸 수 있습니다 — 서버 프레임워크를 붙이고
이 함수를 호출하면 됩니다. 다만 **차트 생성이 매 요청마다 돌면 느리므로**, 차트는 주기적으로
만들어 두고 HTML 만 실시간으로 조립하는 편이 맞습니다.

---

## 준비물 (전제 지식 0)

| 확인 항목 | 없으면 |
|---|---|
| Python 3.10 이상 | [python.org](https://www.python.org/downloads/) |
| Git | [git-scm.com](https://git-scm.com/) |
| 패키지 2개 | `pip install -r requirements.txt` |
| 한글 폰트 | Windows·macOS 기본 제공. Linux 는 `sudo apt install fonts-nanum` |
| Gemini API 키 | 없어도 적재·정제·조회·내보내기는 동작합니다. 발급 = [Google AI Studio](https://aistudio.google.com/apikey) |

---

## 용어 사전

| 용어 | 뜻 |
|---|---|
| **raw / clean** | 수집 원본 / 정제를 통과한 데이터. 저장소를 나눠 둔다 |
| **멱등키** | 같은 것을 두 번 넣어도 하나만 남게 하는 기준 값. 여기서는 `review_id` |
| **upsert** | 있으면 갱신(update), 없으면 삽입(insert) |
| **신뢰도(confidence)** | AI 가 자기 판정을 얼마나 확신하는지. 0.0~1.0 |
| **누적 영역 그래프** | 여러 값을 쌓아 그려 총량과 구성을 함께 보는 차트 |
| **BOM** | 파일 맨 앞의 표식. 엑셀이 UTF-8 임을 알아채게 한다 |
| **data URI** | 파일 내용을 주소 문자열에 직접 담는 방식. 이미지 내장에 쓴다 |
| **불용어(stopword)** | 빈도는 높지만 의미가 없어 집계에서 빼는 단어 |
| **층화 표본** | 집단을 나눠 각각에서 고르게 뽑는 표본 추출 방식 |

---

## 따라 하기

1. **내려받고 설치합니다.**
   ```bash
   git clone https://github.com/dicia-jhoh/codyssey-a2-3.git
   cd codyssey-a2-3
   pip install -r requirements.txt
   ```
2. **샘플을 적재하고 정제합니다.**
   ```bash
   python -m reviewlens import --file data/sample_reviews.csv
   python -m reviewlens clean
   ```
3. **키 없이 조회해 봅니다.**
   ```bash
   python -m reviewlens list --rating-min 4 --size 5
   python -m reviewlens show R001
   ```
4. **같은 파일을 한 번 더 넣어 봅니다.** 전부 중복으로 잡힙니다 — 멱등키가 동작하는 증거입니다.
   ```bash
   python -m reviewlens import --file data/sample_reviews.csv
   python -m reviewlens clean
   ```
5. **키를 넣고 감정을 분석합니다.**
   ```bash
   cp .env.example .env      # 값을 실제 키로 채웁니다
   python -m reviewlens analyze --unanalyzed --limit 10
   python -m reviewlens stats
   ```
6. **알림을 발동시켜 봅니다.** 샘플은 7/12~14 에 부정이 몰려 있습니다.
   ```bash
   python -m reviewlens stats --as-of 2026-07-14
   ```
7. **대시보드를 만듭니다.** `output/dashboard/dashboard.html` 을 브라우저로 엽니다.
   ```bash
   python -m reviewlens extract --sentiment 부정
   python -m reviewlens dashboard --as-of 2026-07-14
   ```
8. **직접 리뷰를 넣어 봅니다.**
   ```bash
   python -m reviewlens add --text "배터리가 하루를 못 갑니다. 교환하고 싶어요." \
     --product "스마트 워치 C" --rating 2 --date 2026-07-17
   python -m reviewlens clean
   python -m reviewlens analyze --unanalyzed
   ```
