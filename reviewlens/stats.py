"""통계·리포트 — 품질 지표, TOP N, 제품 비교, 리포트 조립.

`stats` 명령이 쓰는 요약과 `dashboard`·리포트가 쓰는 집계를 한 곳에 모았다. 같은 숫자를
두 곳에서 따로 계산하면 언젠가 어긋난다.
"""

from __future__ import annotations

import json
import logging
import os
import re
from collections import Counter

from . import storage
from .ingest import now_iso

logger = logging.getLogger(__name__)

TOP_N = 10
# 빈도는 높지만 의미가 없어 집계에서 빼는 말들.
STOPWORDS = {
    "그리고", "하지만", "그런데", "정말", "너무", "조금", "약간", "그냥", "다시", "아주",
    "제품", "구매", "사용", "생각", "느낌", "경우", "때문", "정도", "부분", "가격",
    "the", "and", "for", "with", "this", "that", "was", "are", "but", "very", "not",
}
WORD = re.compile(r"[가-힣A-Za-z][가-힣A-Za-z0-9]{1,}")


def top_keywords(rows, limit: int = TOP_N) -> list[tuple[str, int]]:
    """리뷰 본문에서 단어를 세어 TOP N.

    뉴스(A2-2)에서는 제목만 셌지만 리뷰에는 제목이 없다. 본문 전체를 세되 불용어를
    넉넉히 둔다 — "제품"·"구매" 같은 말은 어느 리뷰에나 나와 순위를 채우기만 한다.
    """
    counter: Counter[str] = Counter()
    for row in rows:
        for word in WORD.findall(row["text"] or ""):
            lowered = word.lower()
            if len(word) >= 2 and lowered not in STOPWORDS:
                counter[word] += 1
    return counter.most_common(limit)


def quality_metrics(counts: dict) -> list[tuple[str, str]]:
    """품질 지표 — 비율로 낸다. 절대 수만으로는 좋아졌는지 알 수 없다.

    ⚠ **중복률을 함께 내는 이유**: raw 대비 clean 비율만 보면 "정제에서 절반이 버려졌다"로
    읽힌다. 그런데 같은 CSV 를 두 번 넣으면 중복이 생기는 것이 정상이다. 중복률을 옆에
    두어야 낮은 통과율이 문제인지 정상인지 구분된다.
    """
    clean = counts["clean"] or 1
    raw = counts["raw"] or 1
    duplicates = max(counts["raw"] - counts["clean"], 0)
    return [
        ("고유 리뷰 비율", f"{counts['clean']}/{counts['raw']} ({counts['clean'] / raw * 100:.1f}%)"),
        ("적재 중복률", f"{duplicates}/{counts['raw']} ({duplicates / raw * 100:.1f}%) "
                     f"— 같은 리뷰를 다시 넣은 비율(재실행에서는 정상)"),
        ("감정 분석 완료율", f"{counts['analyzed']}/{counts['clean']} "
                          f"({counts['analyzed'] / clean * 100:.1f}%)"),
        ("별점 확보율", f"{counts['with_rating']}/{counts['clean']} "
                     f"({counts['with_rating'] / clean * 100:.1f}%)"),
        ("작성일 확보율", f"{counts['with_date']}/{counts['clean']} "
                       f"({counts['with_date'] / clean * 100:.1f}%)"),
    ]


def summary(db_path: str) -> dict:
    """`stats` 명령이 쓰는 요약 — 총 리뷰 수, 감정별 비율, 평균 별점."""
    with storage.connect(db_path) as conn:
        counts = storage.counts(conn)
        by_sentiment = storage.group_by_sentiment(conn)
        by_language = storage.group_by_language(conn)
        by_product = [dict(row) for row in storage.group_by_product(conn)]
        rows = storage.select_clean(conn)
        confidences = [r["confidence"] for r in rows if r["confidence"] is not None]

    analyzed = sum(n for _, n in by_sentiment) or 1
    return {
        "counts": counts,
        "sentiment": [(s, n, n / analyzed * 100) for s, n in by_sentiment],
        "language": by_language,
        "products": by_product,
        "keywords": top_keywords(rows),
        "avg_confidence": round(sum(confidences) / len(confidences), 3) if confidences else None,
        # 신뢰도가 낮은 건은 사람이 확인할 목록이다 — 자동 판정을 그대로 믿지 않는다.
        "low_confidence": [
            (r["review_id"], r["sentiment"], r["confidence"])
            for r in rows
            if r["confidence"] is not None and r["confidence"] < 0.7
        ][:10],
    }


def format_summary(data: dict) -> str:
    """요약을 사람이 읽는 텍스트로. `stats` 명령의 화면 출력."""
    counts = data["counts"]
    lines = [
        "=" * 62,
        " 리뷰 통계 요약",
        "=" * 62,
        f"  총 리뷰(정제 후) : {counts['clean']}건 (원본 {counts['raw']}건)",
        f"  감정 분석 완료   : {counts['analyzed']}건",
        f"  평균 별점        : {counts['avg_rating'] if counts['avg_rating'] is not None else '-'}",
        f"  평균 신뢰도      : {data['avg_confidence'] if data['avg_confidence'] else '-'}",
        "",
        "  [감정별 분포]",
    ]
    if data["sentiment"]:
        for name, count, pct in data["sentiment"]:
            bar = "█" * max(1, round(pct / 5))  # 5% 당 한 칸 — 숫자와 길이를 함께 본다
            lines.append(f"    {name:<3} {count:>4}건 {pct:>5.1f}%  {bar}")
    else:
        lines.append("    (아직 분석하지 않았습니다 — `analyze` 를 실행하세요)")

    lines += ["", "  [언어별]"]
    lines += [f"    {lang:<4} {count}건" for lang, count in data["language"]]

    if data["products"]:
        lines += ["", "  [제품별]", f"    {'제품':<16}{'건수':>5}{'평균별점':>9}{'긍/중/부':>12}"]
        for product in data["products"]:
            avg = f"{product['avg_rating']:.2f}" if product["avg_rating"] else "-"
            mix = f"{product['positive']}/{product['neutral']}/{product['negative']}"
            lines.append(f"    {product['product'][:15]:<16}{product['total']:>5}{avg:>9}{mix:>12}")

    if data["low_confidence"]:
        lines += ["", "  [신뢰도 0.7 미만 — 사람이 확인할 목록]"]
        lines += [
            f"    {rid}  {sentiment}({conf:.2f})"
            for rid, sentiment, conf in data["low_confidence"]
        ]
    lines.append("")
    return "\n".join(lines)


def build_report(db_path: str, charts: dict[str, str | None], alert: str | None = None) -> str:
    """리포트 Markdown 문자열을 만든다(순수 조립 — 파일을 쓰지 않는다)."""
    data = summary(db_path)
    with storage.connect(db_path) as conn:
        extraction_row = storage.latest_extraction(conn)

    lines = [
        "# 고객 리뷰 감정 분석 리포트",
        "",
        f"생성 시각: {now_iso()}",
        "",
    ]

    if alert:
        # 경고는 맨 위에 둔다 — 리포트를 끝까지 읽지 않는 사람도 봐야 한다.
        lines += ["> ⚠ **경고**", ">", f"> {alert}", ""]

    lines += ["## 1. 품질 지표", "", "| 지표 | 값 |", "|---|---|"]
    lines += [f"| {name} | {value} |" for name, value in quality_metrics(data["counts"])]

    lines += ["", "## 2. 감정 분포", "", "| 감정 | 건수 | 비율 |", "|---|---|---|"]
    if data["sentiment"]:
        lines += [f"| {n} | {c} | {p:.1f}% |" for n, c, p in data["sentiment"]]
    else:
        lines.append("| (분석 전) | 0 | 0% |")

    lines += ["", "## 3. 제품별 비교", "",
              "| 제품 | 리뷰 수 | 평균 별점 | 긍정 | 중립 | 부정 |", "|---|---|---|---|---|---|"]
    for product in data["products"]:
        avg = f"{product['avg_rating']:.2f}" if product["avg_rating"] else "-"
        lines.append(
            f"| {product['product']} | {product['total']} | {avg} | "
            f"{product['positive']} | {product['neutral']} | {product['negative']} |"
        )

    lines += ["", f"## 4. 핵심 키워드 TOP {TOP_N}", "", "| 순위 | 키워드 | 빈도 |", "|---|---|---|"]
    keywords = data["keywords"]
    lines += [f"| {i} | {word} | {count} |" for i, (word, count) in enumerate(keywords, 1)]
    if not keywords:
        lines.append("| - | (데이터 없음) | 0 |")

    lines += ["", "## 5. AI 추출 인사이트", ""]
    if extraction_row:
        result = json.loads(extraction_row["result"])
        lines += [f"분석 범위: {extraction_row['scope']} · {extraction_row['item_count']}건", ""]
        for label, key in [("긍정 키워드", "positive_keywords"),
                           ("부정 키워드", "negative_keywords"),
                           ("개선 제안", "improvements")]:
            values = result.get(key) or []
            if values:
                lines += [f"**{label}**", ""]
                lines += [f"- {v}" for v in values]
                lines.append("")
        for label, key in [("전체 요약", "summary"), ("우선순위", "priority")]:
            if result.get(key):
                lines += [f"**{label}**", "", str(result[key]), ""]
    else:
        lines += ["아직 추출을 실행하지 않았습니다 (`extract` 서브커맨드).", ""]

    lines += ["## 6. 차트", ""]
    for label, path in charts.items():
        lines.append(f"- {label}: `{path}`" if path else f"- {label}: (생성되지 않음)")
    lines.append("")
    return "\n".join(lines)


def save_report(text: str, out_dir: str, fmt: str = "md") -> str:
    """리포트를 파일로 저장 → 경로. fmt 는 md 또는 txt."""
    os.makedirs(out_dir, exist_ok=True)
    name = f"report_{now_iso()[:10]}.{'md' if fmt == 'md' else 'txt'}"
    path = os.path.join(out_dir, name)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    logger.info("리포트 저장: %s", path)
    return path
