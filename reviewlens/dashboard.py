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

# 색·간격·모서리를 전부 변수로 뽑는다. 다크 모드가 **변수 한 벌만 덮어쓰면** 끝나기
# 때문이다 — 규칙마다 색을 적어 두면 다크 대응이 규칙 수만큼 늘어난다.
STYLE = """
  :root {
    --bg:#f4f5f7; --surface:#fff; --surface-2:#fafbfc;
    --text:#1a1d23; --muted:#6b7280; --line:#e3e6ea;
    --accent:#3d5a80;
    --pos:#4C956C; --neu:#8D99AE; --neg:#C1585A;
    --pos-bg:#e9f3ed; --neu-bg:#eef0f4; --neg-bg:#f9ecec;
    --warn-bg:#fdf0ed; --warn-line:#f2c4bb; --warn-text:#9a3d33;
    --shadow:0 1px 2px rgba(16,24,40,.05), 0 1px 3px rgba(16,24,40,.06);
    --r:14px; --r-sm:8px;
    --s1:6px; --s2:12px; --s3:18px; --s4:28px; --s5:40px;
  }
  @media (prefers-color-scheme: dark) {
    :root {
      --bg:#101318; --surface:#181c23; --surface-2:#1e232b;
      --text:#e7e9ed; --muted:#98a0ac; --line:#2a2f39;
      --accent:#8ab0d8;
      --pos-bg:#16281f; --neu-bg:#1f2430; --neg-bg:#2c1b1c;
      --warn-bg:#2c1b18; --warn-line:#5c332c; --warn-text:#e8a89c;
      --shadow:0 1px 2px rgba(0,0,0,.4);
    }
  }

  * { box-sizing:border-box; }
  body {
    margin:0; padding:var(--s4) var(--s3); background:var(--bg); color:var(--text);
    font-family:system-ui,-apple-system,"Apple SD Gothic Neo","Malgun Gothic",sans-serif;
    line-height:1.65; -webkit-font-smoothing:antialiased;
  }
  .wrap { max-width:1060px; margin:0 auto; }

  /* 헤더 — 제목과 "언제·무엇을 본 것인가"를 한 덩어리로 */
  .head { margin-bottom:var(--s4); }
  .eyebrow { color:var(--accent); font-size:12px; font-weight:700;
             letter-spacing:.09em; text-transform:uppercase; margin:0 0 var(--s1); }
  h1 { margin:0; font-size:30px; font-weight:750; letter-spacing:-.02em; line-height:1.25; }
  .meta { display:flex; flex-wrap:wrap; gap:var(--s1); margin-top:var(--s2); }
  .chip { background:var(--surface); border:1px solid var(--line); border-radius:999px;
          padding:3px 11px; font-size:12.5px; color:var(--muted); }

  /* KPI — 가장 먼저 읽히는 숫자. 값이 라벨보다 커야 눈이 값에 먼저 간다 */
  .kpis { display:grid; grid-template-columns:repeat(auto-fit,minmax(158px,1fr));
          gap:var(--s2); margin-bottom:var(--s3); }
  /* 위쪽 색 띠가 지표의 성격을 말해 준다 — 부정 비율만 빨강이면 나쁜 숫자가 어디인지
     라벨을 읽기 전에 보인다 */
  .kpi { background:var(--surface); border:1px solid var(--line); border-radius:var(--r);
         border-top:3px solid var(--accent); padding:var(--s3) var(--s2);
         box-shadow:var(--shadow); }
  .kpi.t-pos { border-top-color:var(--pos); }
  .kpi.t-neu { border-top-color:var(--neu); }
  .kpi.t-neg { border-top-color:var(--neg); }
  .kpi .label { color:var(--muted); font-size:12.5px; font-weight:600; }
  .kpi .value { font-size:27px; font-weight:750; margin-top:var(--s1);
                letter-spacing:-.02em; font-variant-numeric:tabular-nums; }
  .kpi .value .unit { font-size:15px; font-weight:600; color:var(--muted); margin-left:2px; }

  /* 섹션 — 카드만 스무 개 늘어놓으면 어디까지가 한 덩어리인지 알 수 없다.
     "요약 / 시각화 / 세부 데이터 / 해석" 처럼 읽는 순서를 이름으로 끊어 준다 */
  .sec { display:flex; align-items:baseline; justify-content:space-between;
         gap:var(--s2); margin:var(--s5) 0 var(--s2); }
  .sec:first-of-type { margin-top:var(--s3); }
  .sec h2 { margin:0; font-size:20px; font-weight:750; letter-spacing:-.02em; }
  .sec .eyebrow { margin:0 0 2px; }
  .sec .note { color:var(--muted); font-size:12.5px; text-align:right; }

  .card { background:var(--surface); border:1px solid var(--line); border-radius:var(--r);
          padding:var(--s3); margin-bottom:var(--s3); box-shadow:var(--shadow); }
  .card > h3 { margin:0 0 var(--s3); font-size:15px; font-weight:700; letter-spacing:-.01em; }
  .card > h3 .count { color:var(--muted); font-weight:500; font-size:13px; margin-left:6px; }

  /* 두 카드를 나란히. 좁아지면 자동으로 한 줄씩 내려간다 */
  .pair { display:grid; grid-template-columns:repeat(auto-fit,minmax(330px,1fr));
          gap:var(--s3); align-items:start; }
  .pair > .card { margin-bottom:0; }

  /* 감정 비율 막대 — 도넛 차트와 같은 사실을 글자 없이 한 줄로 보여 준다 */
  .meter { display:flex; height:10px; border-radius:999px; overflow:hidden;
           background:var(--neu-bg); margin-bottom:var(--s2); }
  .meter span { display:block; }
  .legend { display:flex; flex-wrap:wrap; gap:var(--s3); font-size:13px; color:var(--muted); }
  .legend b { color:var(--text); font-variant-numeric:tabular-nums; }
  .dot { display:inline-block; width:9px; height:9px; border-radius:50%; margin-right:6px; }

  /* 표는 카드보다 넓어질 수 있다. 페이지가 아니라 **표가** 가로로 스크롤해야 한다 */
  .scroll { overflow-x:auto; }
  table { width:100%; border-collapse:collapse; font-size:14px; }
  th, td { text-align:left; padding:9px 12px; border-bottom:1px solid var(--line);
           white-space:nowrap; }
  th { color:var(--muted); font-weight:600; font-size:12.5px;
       letter-spacing:.03em; background:var(--surface-2); }
  th:first-child { border-top-left-radius:var(--r-sm); }
  th:last-child  { border-top-right-radius:var(--r-sm); }
  tr:last-child td { border-bottom:none; }
  td.num { font-variant-numeric:tabular-nums; }
  td.wrap-text { white-space:normal; min-width:200px; }

  .charts { display:grid; grid-template-columns:repeat(auto-fit,minmax(300px,1fr));
            gap:var(--s3); }
  figure { margin:0; }
  figcaption { color:var(--muted); font-size:12.5px; margin-bottom:var(--s1); font-weight:600; }
  img { max-width:100%; display:block; border:1px solid var(--line);
        border-radius:var(--r-sm); background:#fff; }

  .alert { background:var(--warn-bg); border:1px solid var(--warn-line); color:var(--warn-text);
           border-radius:var(--r); padding:var(--s2) var(--s3); margin-bottom:var(--s3); }

  /* 감정 태그는 채도 높은 배경 대신 옅은 바탕 + 진한 글자.
     표 안에서 색 덩어리 세 개가 나란히 있으면 정작 숫자가 안 읽힌다 */
  .tag { display:inline-block; padding:2px 9px; border-radius:999px; font-size:12px;
         font-weight:650; margin-right:4px; font-variant-numeric:tabular-nums; }
  .pos { background:var(--pos-bg); color:var(--pos); }
  .neu { background:var(--neu-bg); color:var(--neu); }
  .neg { background:var(--neg-bg); color:var(--neg); }

  .cols { display:grid; grid-template-columns:repeat(auto-fit,minmax(260px,1fr)); gap:var(--s3); }
  .block { background:var(--surface-2); border:1px solid var(--line);
           border-radius:var(--r-sm); padding:var(--s2) var(--s3); }
  .block h3 { margin:0 0 var(--s1); font-size:13px; font-weight:700; color:var(--muted); }
  .block p { margin:0; }
  .block ul { margin:0; padding-left:18px; }
  .block li { margin:3px 0; }
  .block.accent { border-left:3px solid var(--accent); }
  .kw { display:inline-block; background:var(--surface); border:1px solid var(--line);
        border-radius:999px; padding:3px 10px; margin:0 5px 5px 0; font-size:13px; }
  .muted { color:var(--muted); font-size:13px; }
  footer { color:var(--muted); font-size:12.5px; text-align:center; padding:var(--s3) 0; }
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


_TONE = {"긍정": "pos", "중립": "neu", "부정": "neg"}


def _kpi(label: str, value, unit: str = "", tone: str = "") -> str:
    """KPI 타일 하나. 단위를 값과 분리해 두면 숫자만 크게 키울 수 있다."""
    tail = f"<span class='unit'>{_esc(unit)}</span>" if unit else ""
    cls = f"kpi t-{tone}" if tone else "kpi"
    return (
        f"<div class='{cls}'><div class='label'>{_esc(label)}</div>"
        f"<div class='value'>{_esc(value)}{tail}</div></div>"
    )


def _section(eyebrow: str, title: str, note: str = "") -> str:
    """섹션 머리. 카드 묶음이 어디서 시작하는지 알려 준다."""
    right = f"<div class='note'>{_esc(note)}</div>" if note else ""
    return (
        f"<div class='sec'><div><p class='eyebrow'>{_esc(eyebrow)}</p>"
        f"<h2>{_esc(title)}</h2></div>{right}</div>"
    )


def _meter(sentiment_rows) -> str:
    """감정 분포를 막대 한 줄 + 범례로. 비율이 0 인 칸은 넣지 않는다(1px 줄이 남는다)."""
    bars, legend = [], []
    for name, count, pct in sentiment_rows:
        tone = _TONE.get(name, "neu")
        if pct > 0:
            bars.append(f"<span class='{tone}' style='width:{pct:.2f}%;background:var(--{tone})'></span>")
        legend.append(
            f"<span><i class='dot' style='background:var(--{tone})'></i>"
            f"{_esc(name)} <b>{count}건 · {pct:.1f}%</b></span>"
        )
    return f"<div class='meter'>{''.join(bars)}</div><div class='legend'>{''.join(legend)}</div>"


def build_html(db_path: str, charts: dict[str, str | None], alert: str | None = None) -> str:
    """대시보드 HTML 문자열을 만든다."""
    data = summary(db_path)
    counts = data["counts"]
    with storage.connect(db_path) as conn:
        extraction_row = storage.latest_extraction(conn)

    parts = [
        "<div class='wrap'>",
        "<header class='head'>",
        "<p class='eyebrow'>reviewlens</p>",
        "<h1>고객 리뷰 감정 분석 대시보드</h1>",
        "<div class='meta'>",
        f"<span class='chip'>생성 {_esc(now_iso())}</span>",
        f"<span class='chip'>정제 리뷰 {counts['clean']}건</span>",
        f"<span class='chip'>분석 완료 {counts['analyzed']}건</span>",
        "</div></header>",
    ]

    if alert:
        parts.append(f"<div class='alert'><strong>⚠ 경고</strong><br>{_esc(alert)}</div>")

    # 요약 — 숫자 다섯 개와, 그 숫자가 어디서 나왔는지를 한 화면에
    parts.append(_section("요약", "한눈에 보기", f"정제 리뷰 {counts['clean']}건 기준"))

    sentiment_map = {name: (count, pct) for name, count, pct in data["sentiment"]}
    negative_pct = sentiment_map.get("부정", (0, 0.0))[1]
    parts.append("<div class='kpis'>")
    parts.append(_kpi("총 리뷰", counts["clean"], "건"))
    parts.append(_kpi("분석 완료", counts["analyzed"], "건"))
    parts.append(_kpi("평균 별점",
                      counts["avg_rating"] if counts["avg_rating"] is not None else "-",
                      tone="neu"))
    parts.append(_kpi("부정 비율", f"{negative_pct:.1f}", "%", tone="neg"))
    parts.append(_kpi("평균 신뢰도", data["avg_confidence"] if data["avg_confidence"] else "-",
                      tone="pos"))
    parts.append("</div>")

    # 감정 분포는 막대 한 줄이라 전체 폭에서 가장 잘 읽힌다. 표와 짝지으면 한쪽만
    # 비어 높이가 어긋나므로, 표는 아래에서 표끼리 묶는다.
    if data["sentiment"]:
        parts.append("<div class='card'><h3>감정 분포</h3>")
        parts.append(_meter(data["sentiment"]))
        parts.append("</div>")

    # 차트 — base64 로 심어 파일 하나로 완결시킨다
    parts.append(_section("시각화", "분석 차트", "리뷰 데이터에서 발견한 패턴"))
    parts.append("<div class='card'><div class='charts'>")
    for label, path in charts.items():
        uri = embed_image(path)
        if uri:
            parts.append(f"<figure><figcaption>{_esc(label)}</figcaption>"
                         f"<img alt='{_esc(label)}' src='{uri}'></figure>")
        else:
            parts.append(f"<p class='muted'>{_esc(label)}: 생성되지 않음</p>")
    parts.append("</div></div>")

    # 세부 데이터 — 제품별 비교와 키워드도 성격이 같아 나란히 둔다
    parts.append(_section("세부 데이터", "품질과 제품", "이 데이터를 믿어도 되나"))
    parts.append("<div class='pair'>")
    parts.append("<div class='card'><h3>품질 지표</h3><div class='scroll'><table>"
                 "<tr><th>지표</th><th>값</th></tr>")
    for name, value in quality_metrics(counts):
        parts.append(f"<tr><td>{_esc(name)}</td>"
                     f"<td class='num wrap-text'>{_esc(value)}</td></tr>")
    parts.append("</table></div></div>")
    if data["products"]:
        parts.append(
            "<div class='card'><h3>제품별 비교"
            f"<span class='count'>{len(data['products'])}종</span></h3>"
            "<div class='scroll'><table>"
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
                f"<tr><td>{_esc(product['product'])}</td>"
                f"<td class='num'>{product['total']}</td>"
                f"<td class='num'>{_esc(avg)}</td><td>{mix}</td></tr>"
            )
        parts.append("</table></div></div>")
    parts.append("</div>")

    # 순위표보다 칩 나열이 눈으로 훑기 쉽다 — 순위는 등장 순서가 말해 준다
    if data["keywords"]:
        parts.append("<div class='card'><h3>핵심 키워드"
                     f"<span class='count'>상위 {len(data['keywords'])}개</span></h3><div>")
        for word, count in data["keywords"]:
            parts.append(f"<span class='kw'>{_esc(word)} <b>{count}</b></span>")
        parts.append("</div></div>")

    # AI 추출
    parts.append(_section("해석", "AI 추출 인사이트"))
    parts.append("<div class='card'>")
    if extraction_row:
        result = json.loads(extraction_row["result"])
        parts.append(f"<p class='muted' style='margin-top:0'>범위: "
                     f"{_esc(extraction_row['scope'])} · {extraction_row['item_count']}건</p>")
        if result.get("summary"):
            parts.append(f"<div class='block accent' style='margin-bottom:var(--s3)'>"
                         f"<h3>전체 요약</h3><p>{_esc(result['summary'])}</p></div>")
        parts.append("<div class='cols'>")
        for label, key in [("긍정 키워드", "positive_keywords"),
                           ("부정 키워드", "negative_keywords")]:
            values = result.get(key) or []
            if values:
                tone = "pos" if key.startswith("positive") else "neg"
                tags = "".join(f"<span class='tag {tone}'>{_esc(v)}</span>" for v in values)
                parts.append(f"<div class='block'><h3>{_esc(label)}</h3><p>{tags}</p></div>")
        parts.append("</div>")
        improvements = result.get("improvements") or []
        if improvements:
            items = "".join(f"<li>{_esc(v)}</li>" for v in improvements)
            parts.append(f"<div class='block' style='margin-top:var(--s3)'>"
                         f"<h3>개선 제안</h3><ul>{items}</ul></div>")
        if result.get("priority"):
            parts.append(f"<div class='block accent' style='margin-top:var(--s3)'>"
                         f"<h3>우선순위</h3><p>{_esc(result['priority'])}</p></div>")
    else:
        parts.append("<p class='muted'>아직 추출을 실행하지 않았습니다 (extract 서브커맨드).</p>")
    parts.append("</div>")

    # 신뢰도 낮은 건 — 사람이 확인할 목록
    if data["low_confidence"]:
        parts.append(_section("검토 대기", "확인 필요", "판정 신뢰도 0.7 미만"))
        parts.append(f"<div class='card'><h3>사람이 다시 볼 리뷰"
                     f"<span class='count'>{len(data['low_confidence'])}건</span></h3>"
                     "<div class='scroll'><table>"
                     "<tr><th>리뷰 ID</th><th>판정</th><th>신뢰도</th></tr>")
        for rid, sentiment, confidence in data["low_confidence"]:
            tone = _TONE.get(sentiment, "neu")
            parts.append(f"<tr><td>{_esc(rid)}</td>"
                         f"<td><span class='tag {tone}'>{_esc(sentiment)}</span></td>"
                         f"<td class='num'>{confidence:.2f}</td></tr>")
        parts.append("</table></div></div>")

    parts.append("<footer>reviewlens · 단일 HTML 대시보드 (외부 파일 없음)</footer>")
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
