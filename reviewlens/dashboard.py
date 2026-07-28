"""보너스 — 단일 HTML 대시보드. 차트 이미지와 통계를 한 파일에 담는다.

**단일 파일**로 만드는 이유: 대시보드는 남에게 보내는 물건이다. HTML·CSS·이미지가 따로
있으면 받는 사람이 폴더째 받아야 하고, 한 파일만 열면 이미지가 깨진다. 이미지를 base64 로
심어 **파일 하나로 완결**시킨다.

미션 제약대로 **실시간 웹 서버는 만들지 않는다** — 정적 HTML 하나다.
"""

from __future__ import annotations

import base64
import html
import json
import logging
import os

from . import storage
from .ingest import now_iso
from .stats import quality_metrics, summary

logger = logging.getLogger(__name__)

STYLE = """
  :root { --bg:#f7f7f9; --card:#fff; --text:#22242a; --muted:#6b7280; --line:#e5e7eb;
          --pos:#4C956C; --neu:#8D99AE; --neg:#C1585A; }
  * { box-sizing:border-box; }
  body { margin:0; padding:24px; background:var(--bg); color:var(--text);
         font-family:system-ui,"Apple SD Gothic Neo","Malgun Gothic",sans-serif; line-height:1.6; }
  .wrap { max-width:1000px; margin:0 auto; }
  h1 { margin:0 0 4px; font-size:26px; }
  .sub { color:var(--muted); margin:0 0 20px; }
  .card { background:var(--card); border:1px solid var(--line); border-radius:12px;
          padding:18px; margin-bottom:16px; }
  .card h2 { margin:0 0 12px; font-size:18px; }
  .kpis { display:grid; grid-template-columns:repeat(auto-fit,minmax(150px,1fr)); gap:12px; }
  .kpi { background:var(--card); border:1px solid var(--line); border-radius:12px; padding:14px; }
  .kpi .label { color:var(--muted); font-size:13px; }
  .kpi .value { font-size:24px; font-weight:700; margin-top:4px; }
  table { width:100%; border-collapse:collapse; font-size:14px; }
  th,td { text-align:left; padding:8px 10px; border-bottom:1px solid var(--line); }
  th { color:var(--muted); font-weight:600; }
  img { max-width:100%; border:1px solid var(--line); border-radius:8px; }
  .charts { display:grid; grid-template-columns:repeat(auto-fit,minmax(320px,1fr)); gap:16px; }
  .alert { background:#fdecea; border:1px solid #f5c2c0; color:#8f2f2c;
           border-radius:12px; padding:14px; margin-bottom:16px; }
  .tag { display:inline-block; padding:2px 8px; border-radius:999px; font-size:12px;
         color:#fff; margin-right:4px; }
  .pos{background:var(--pos)} .neu{background:var(--neu)} .neg{background:var(--neg)}
  .muted { color:var(--muted); font-size:13px; }
  @media (prefers-color-scheme: dark) {
    :root { --bg:#16181d; --card:#1f2229; --text:#e8e9ec; --muted:#9aa1ad; --line:#2e323b; }
  }
"""


def embed_image(path: str | None) -> str | None:
    """PNG → data URI. 실패하면 None(그 자리는 안내 문구로 대체된다).

    base64 는 원본보다 약 33% 커진다. 차트 3장 정도면 수백 KB 수준이라 감당되지만,
    수십 장이 되면 이미지를 따로 두고 링크하는 편이 낫다.
    """
    if not path or not os.path.exists(path):
        return None
    try:
        with open(path, "rb") as f:
            encoded = base64.b64encode(f.read()).decode("ascii")
    except OSError as exc:
        logger.warning("이미지를 읽지 못했습니다(%s): %s", path, exc)
        return None
    return f"data:image/png;base64,{encoded}"


def _esc(value) -> str:
    """HTML 이스케이프. 리뷰 본문에 `<` 가 들어 있으면 태그로 해석된다."""
    return html.escape(str(value if value is not None else "-"))


def build_html(db_path: str, charts: dict[str, str | None], alert: str | None = None) -> str:
    """대시보드 HTML 문자열을 만든다."""
    data = summary(db_path)
    counts = data["counts"]
    with storage.connect(db_path) as conn:
        extraction_row = storage.latest_extraction(conn)

    parts = [
        "<div class='wrap'>",
        "<h1>고객 리뷰 감정 분석 대시보드</h1>",
        f"<p class='sub'>생성 {_esc(now_iso())} · 정제 리뷰 {counts['clean']}건</p>",
    ]

    if alert:
        parts.append(f"<div class='alert'><strong>⚠ 경고</strong><br>{_esc(alert)}</div>")

    # KPI — 가장 먼저 보이는 숫자들
    sentiment_map = {name: (count, pct) for name, count, pct in data["sentiment"]}
    negative_pct = sentiment_map.get("부정", (0, 0.0))[1]
    parts.append("<div class='kpis'>")
    for label, value in [
        ("총 리뷰", f"{counts['clean']}건"),
        ("분석 완료", f"{counts['analyzed']}건"),
        ("평균 별점", counts["avg_rating"] if counts["avg_rating"] is not None else "-"),
        ("부정 비율", f"{negative_pct:.1f}%"),
        ("평균 신뢰도", data["avg_confidence"] if data["avg_confidence"] else "-"),
    ]:
        parts.append(
            f"<div class='kpi'><div class='label'>{_esc(label)}</div>"
            f"<div class='value'>{_esc(value)}</div></div>"
        )
    parts.append("</div>")

    # 차트 — base64 로 심어 파일 하나로 완결시킨다
    parts.append("<div class='card'><h2>차트</h2><div class='charts'>")
    for label, path in charts.items():
        uri = embed_image(path)
        if uri:
            parts.append(f"<figure style='margin:0'><img alt='{_esc(label)}' src='{uri}'>"
                         f"<figcaption class='muted'>{_esc(label)}</figcaption></figure>")
        else:
            parts.append(f"<p class='muted'>{_esc(label)}: 생성되지 않음</p>")
    parts.append("</div></div>")

    # 품질 지표
    parts.append("<div class='card'><h2>품질 지표</h2><table><tr><th>지표</th><th>값</th></tr>")
    for name, value in quality_metrics(counts):
        parts.append(f"<tr><td>{_esc(name)}</td><td>{_esc(value)}</td></tr>")
    parts.append("</table></div>")

    # 제품별 비교(보너스)
    if data["products"]:
        parts.append(
            "<div class='card'><h2>제품별 비교</h2><table>"
            "<tr><th>제품</th><th>리뷰</th><th>평균 별점</th><th>감정 분포</th></tr>"
        )
        for product in data["products"]:
            avg = f"{product['avg_rating']:.2f}" if product["avg_rating"] else "-"
            mix = (
                f"<span class='tag pos'>긍 {product['positive']}</span>"
                f"<span class='tag neu'>중 {product['neutral']}</span>"
                f"<span class='tag neg'>부 {product['negative']}</span>"
            )
            parts.append(
                f"<tr><td>{_esc(product['product'])}</td><td>{product['total']}</td>"
                f"<td>{_esc(avg)}</td><td>{mix}</td></tr>"
            )
        parts.append("</table></div>")

    # 키워드
    if data["keywords"]:
        parts.append("<div class='card'><h2>핵심 키워드</h2><table>"
                     "<tr><th>순위</th><th>키워드</th><th>빈도</th></tr>")
        for index, (word, count) in enumerate(data["keywords"], 1):
            parts.append(f"<tr><td>{index}</td><td>{_esc(word)}</td><td>{count}</td></tr>")
        parts.append("</table></div>")

    # AI 추출
    parts.append("<div class='card'><h2>AI 추출 인사이트</h2>")
    if extraction_row:
        result = json.loads(extraction_row["result"])
        parts.append(f"<p class='muted'>범위: {_esc(extraction_row['scope'])} · "
                     f"{extraction_row['item_count']}건</p>")
        for label, key in [("긍정 키워드", "positive_keywords"),
                           ("부정 키워드", "negative_keywords"),
                           ("개선 제안", "improvements")]:
            values = result.get(key) or []
            if values:
                items = "".join(f"<li>{_esc(v)}</li>" for v in values)
                parts.append(f"<p><strong>{_esc(label)}</strong></p><ul>{items}</ul>")
        for label, key in [("전체 요약", "summary"), ("우선순위", "priority")]:
            if result.get(key):
                parts.append(f"<p><strong>{_esc(label)}</strong><br>{_esc(result[key])}</p>")
    else:
        parts.append("<p class='muted'>아직 추출을 실행하지 않았습니다 (extract 서브커맨드).</p>")
    parts.append("</div>")

    # 신뢰도 낮은 건 — 사람이 확인할 목록
    if data["low_confidence"]:
        parts.append("<div class='card'><h2>확인 필요 (신뢰도 0.7 미만)</h2><table>"
                     "<tr><th>리뷰 ID</th><th>판정</th><th>신뢰도</th></tr>")
        for rid, sentiment, confidence in data["low_confidence"]:
            parts.append(f"<tr><td>{_esc(rid)}</td><td>{_esc(sentiment)}</td>"
                         f"<td>{confidence:.2f}</td></tr>")
        parts.append("</table></div>")

    parts.append("</div>")
    body = "\n".join(parts)
    return (
        "<!DOCTYPE html>\n<html lang='ko'>\n<head>\n<meta charset='utf-8'>\n"
        "<meta name='viewport' content='width=device-width, initial-scale=1'>\n"
        "<title>리뷰 감정 분석 대시보드</title>\n"
        f"<style>{STYLE}</style>\n</head>\n<body>\n{body}\n</body>\n</html>\n"
    )


def save_dashboard(html_text: str, out_dir: str) -> str:
    """HTML 을 파일로 저장 → 경로."""
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, "dashboard.html")
    with open(path, "w", encoding="utf-8") as f:
        f.write(html_text)
    logger.info("대시보드 저장: %s", path)
    return path
