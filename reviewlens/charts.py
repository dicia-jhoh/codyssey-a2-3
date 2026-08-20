"""차트 3종 — 감정 분포(도넛), 시간별 추이(누적 영역), 별점별 감정 분포(누적 막대).

**한글 폰트·Agg 백엔드 처리는 A2-1 에서 확립하고 A2-2 가 이어받은 방식을 그대로 쓴다.**
matplotlib 기본 폰트에 한글 글리프가 없어 축 라벨이 네모(□)로 나오는 문제인데, 그림은
정상적으로 만들어지므로 파일만 보면 놓친다.

세 차트가 답하는 질문이 다르다:
  감정 분포   — "전체적으로 어떤가?"      (비율)
  시간별 추이 — "나빠지고 있나?"          (변화)
  별점별 분포 — "별점과 본문이 맞는가?"   (교차 검증)

세 번째가 이 미션에서 특히 중요하다. 별점 5점인데 본문이 부정이면 **별점을 잘못 눌렀거나
비꼬는 리뷰**다. 둘을 함께 봐야 데이터를 믿을 수 있다.
"""

from __future__ import annotations

import logging
import os

import matplotlib

# ⚠ pyplot import **전에** 백엔드를 지정한다. "Agg" = 화면 없이 파일로만 그린다.
matplotlib.use("Agg")

import matplotlib.font_manager as fm  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402

logger = logging.getLogger(__name__)

KOREAN_FONTS = [
    "Malgun Gothic",  # Windows
    "AppleGothic",  # macOS
    "NanumGothic",  # Linux (fonts-nanum)
    "NanumSquareRound",
    "Noto Sans CJK KR",  # Linux (fonts-noto-cjk)
    "Noto Sans KR",
]

# 감정 표시 순서 — 긍정→중립→부정 고정. 데이터에 따라 순서가 바뀌면 여러 차트를
# 나란히 놓고 볼 때 색 위치가 달라져 읽기 어렵다.
SENTIMENT_ORDER = ["긍정", "중립", "부정"]
FALLBACK_COLOR = "#B0B0B0"
RING_WIDTH = 0.42  # 도넛 링 두께. 퍼센트 라벨 위치를 이 값으로 계산한다


def setup_korean_font() -> str | None:
    """설치된 한글 폰트를 matplotlib 기본으로 지정 → 폰트 이름(없으면 None).

    `axes.unicode_minus = False` 도 함께 끈다 — 한글 폰트 상당수에 유니코드 음수 기호(−)가
    없어서, 음수 눈금이 있는 그래프에서 마이너스만 네모가 된다.
    """
    installed = {f.name for f in fm.fontManager.ttflist}
    for name in KOREAN_FONTS:
        if name in installed:
            plt.rcParams["font.family"] = name
            plt.rcParams["axes.unicode_minus"] = False
            return name
    logger.warning(
        "한글 폰트를 찾지 못했습니다 — 차트의 한글이 네모(□)로 나옵니다. "
        "Linux: sudo apt install fonts-nanum"
    )
    return None


def _colors(cfg: dict) -> dict:
    """설정에서 감정별 색을 읽는다. 색을 코드가 아니라 config 에 둔 이유는 브랜드마다
    다를 수 있고, 색맹 대응 팔레트로 바꾸는 것이 설정 변경만으로 되어야 하기 때문이다."""
    return cfg.get("visualization", {}).get("colors", {})


def chart_sentiment_share(data: list[tuple[str, int]], out_dir: str, cfg: dict) -> str | None:
    """① 감정 분포 — 도넛. 저장 경로(데이터가 없으면 None)."""
    if not data:
        logger.warning("감정 분포 차트: 분석된 리뷰가 없습니다 (analyze 를 먼저 실행하세요)")
        return None
    setup_korean_font()
    palette = _colors(cfg)

    # 표시 순서를 고정한다 — 건수 순으로 두면 실행할 때마다 색 위치가 바뀐다.
    ordered = [(s, n) for s in SENTIMENT_ORDER for label, n in data if label == s]
    labels = [s for s, _ in ordered]
    values = [n for _, n in ordered]
    total = sum(values)

    # 대시보드가 차트 3장을 한 줄에 놓는다. 정사각형 하나만 섞이면 그 칸만 높이가
    # 두 배가 되어 줄이 어긋난다 — 세 장의 가로세로비를 비슷하게 맞춘다.
    fig, ax = plt.subplots(figsize=(8, 4.5))
    _, _, autotexts = ax.pie(
        values,
        labels=[f"{s} ({n}건)" for s, n in ordered],
        colors=[palette.get(s, FALLBACK_COLOR) for s in labels],
        autopct=lambda pct: f"{pct:.1f}%",
        startangle=90,
        counterclock=False,  # 시계 방향 — 사람이 읽는 순서와 맞춘다
        wedgeprops={"width": RING_WIDTH, "edgecolor": "white", "linewidth": 2},
        # 퍼센트를 링 두께 한가운데에 놓는다. 기본값(0.6)은 도넛 구멍에 걸쳐 글자가 잘린다.
        pctdistance=1 - RING_WIDTH / 2,
    )
    for text in autotexts:
        text.set_color("white")
        text.set_fontweight("bold")

    ax.text(0, 0, f"총 {total}건", ha="center", va="center", fontsize=15, fontweight="bold")
    ax.set_title("감정 분포")
    fig.tight_layout()
    path = os.path.join(out_dir, "sentiment_share.png")
    fig.savefig(path, dpi=cfg["visualization"]["dpi"], facecolor="white")
    plt.close(fig)  # figure 를 닫는다 — 반복 호출하면 메모리에 쌓인다
    logger.info("차트 저장: %s", path)
    return path


def chart_sentiment_trend(data: list[tuple[str, str, int]], out_dir: str,
                          cfg: dict) -> str | None:
    """② 시간별 감정 추이 — 누적 영역. 저장 경로(데이터가 없으면 None).

    누적으로 그리는 이유: 날짜마다 리뷰 수가 다르므로 선을 따로 그리면 "부정이 늘었다"가
    **전체가 늘어서인지 부정 비중이 커져서인지** 구분되지 않는다. 누적하면 총량과 구성이
    한 그림에 함께 보인다.
    """
    if not data:
        logger.warning("추이 차트: 날짜·감정이 모두 있는 리뷰가 없습니다")
        return None
    setup_korean_font()
    palette = _colors(cfg)

    dates = sorted({d for d, _, _ in data})
    series = {s: [0] * len(dates) for s in SENTIMENT_ORDER}
    index_of = {d: i for i, d in enumerate(dates)}
    for date, sentiment, count in data:
        if sentiment in series:
            series[sentiment][index_of[date]] = count

    fig, ax = plt.subplots(figsize=(10, 4.5))
    ax.stackplot(
        dates,
        [series[s] for s in SENTIMENT_ORDER],
        labels=SENTIMENT_ORDER,
        colors=[palette.get(s, FALLBACK_COLOR) for s in SENTIMENT_ORDER],
        alpha=0.9,
    )
    ax.set_ylabel("리뷰 수")
    ax.set_title("시간별 감정 추이")
    ax.legend(loc="upper left")
    ax.grid(axis="y", linestyle=":", alpha=0.4)

    # 날짜가 많으면 라벨이 겹친다 — 기울이고, 너무 많으면 솎아 낸다.
    step = max(1, len(dates) // 12)
    ax.set_xticks(dates[::step])
    plt.setp(ax.get_xticklabels(), rotation=45, ha="right")
    # 리뷰 수는 정수다. 눈금에 0.5 가 찍히면 "0.5건" 이라는 없는 값을 읽게 된다.
    peak = max((sum(series[s][i] for s in SENTIMENT_ORDER) for i in range(len(dates))), default=1)
    ax.set_yticks(range(0, peak + 2))

    ax.spines[["top", "right"]].set_visible(False)
    fig.tight_layout()
    path = os.path.join(out_dir, "sentiment_trend.png")
    fig.savefig(path, dpi=cfg["visualization"]["dpi"], facecolor="white")
    plt.close(fig)
    logger.info("차트 저장: %s", path)
    return path


def chart_rating_sentiment(data: list[tuple[int, str, int]], out_dir: str,
                           cfg: dict) -> str | None:
    """③ 별점별 감정 분포 — 누적 가로 막대. 저장 경로(데이터가 없으면 None).

    **별점과 본문 감정의 교차 검증**이 목적이다. 5점인데 부정, 1점인데 긍정이 보이면
    별점 오입력이거나 반어법이다 — 그 칸이 바로 사람이 확인할 목록이 된다.
    """
    if not data:
        logger.warning("별점별 차트: 별점·감정이 모두 있는 리뷰가 없습니다")
        return None
    setup_korean_font()
    palette = _colors(cfg)

    ratings = sorted({r for r, _, _ in data})
    series = {s: [0] * len(ratings) for s in SENTIMENT_ORDER}
    index_of = {r: i for i, r in enumerate(ratings)}
    for rating, sentiment, count in data:
        if sentiment in series:
            series[sentiment][index_of[rating]] = count

    fig, ax = plt.subplots(figsize=(9, max(3.5, len(ratings) * 0.8)))
    labels = [f"★{r}" for r in ratings]
    left = [0] * len(ratings)
    for sentiment in SENTIMENT_ORDER:
        values = series[sentiment]
        ax.barh(labels, values, left=left, label=sentiment,
                color=palette.get(sentiment, FALLBACK_COLOR))
        # 조각 안에 건수를 적는다 — 누적 막대는 눈금만으로 각 조각 길이를 읽기 어렵다.
        for i, value in enumerate(values):
            if value:
                ax.text(left[i] + value / 2, i, str(value), ha="center", va="center",
                        color="white", fontweight="bold", fontsize=9)
        left = [left[i] + values[i] for i in range(len(ratings))]

    # barh 는 목록 첫 항목을 맨 아래에 그린다. ratings 가 오름차순(1→5)이므로
    # 뒤집지 않아야 ★5 가 위로 온다 — 별점이 높은 것부터 읽는 순서다.
    ax.set_xlabel("리뷰 수")
    ax.set_title("별점별 감정 분포")
    # 범례를 그림 밖으로 뺀다 — 안에 두면 가장 긴 막대(★5)를 가린다.
    ax.legend(loc="upper left", bbox_to_anchor=(1.01, 1), borderaxespad=0)
    ax.spines[["top", "right"]].set_visible(False)
    fig.tight_layout()
    path = os.path.join(out_dir, "rating_sentiment.png")
    fig.savefig(path, dpi=cfg["visualization"]["dpi"], facecolor="white")
    plt.close(fig)
    logger.info("차트 저장: %s", path)
    return path
