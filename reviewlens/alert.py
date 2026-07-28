"""보너스 — 감정 변화 알림. 최근 N일 부정 비율이 급증하면 경고한다.

**왜 비율인가**: 부정 리뷰 "건수"만 보면 전체 리뷰가 늘어난 날에 항상 경고가 뜬다.
비율로 봐야 "나빠지고 있는가"를 잰다.

**왜 이전 기간과 비교하나**: 절대 임계값(부정 50% 넘으면 경고)만 쓰면, 원래 부정이 많은
제품에서는 늘 경고가 뜨고 원래 좋던 제품이 나빠지는 것은 놓친다. 둘 다 본다.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta

from . import storage

logger = logging.getLogger(__name__)


def _window(reference: str, days: int) -> tuple[str, str, str, str]:
    """기준일에서 (최근 시작, 최근 끝, 이전 시작, 이전 끝) 을 만든다.

    이전 기간을 같은 길이로 잡는 이유: 3일치와 7일치를 비교하면 표본 크기가 달라 비율이
    흔들린다. 같은 길이로 맞춰야 변화만 남는다.
    """
    end = datetime.strptime(reference, "%Y-%m-%d").date()
    recent_start = end - timedelta(days=days - 1)
    prev_end = recent_start - timedelta(days=1)
    prev_start = prev_end - timedelta(days=days - 1)
    return (
        recent_start.isoformat(), end.isoformat(),
        prev_start.isoformat(), prev_end.isoformat(),
    )


def _ratio(conn, start: str, end: str) -> tuple[int, int, float | None]:
    """구간의 (전체, 부정, 부정비율). 분석된 리뷰가 없으면 비율은 None."""
    rows = storage.select_clean(conn, date_from=start, date_to=end, status="analyzed")
    total = len(rows)
    negative = sum(1 for r in rows if r["sentiment"] == "부정")
    return total, negative, (negative / total if total else None)


def check(db_path: str, cfg: dict, reference: str | None = None) -> tuple[str | None, dict]:
    """부정 급증 여부를 판정 → (경고 문구 또는 None, 판정 근거 dict).

    근거를 함께 돌려주는 이유: 경고만 던지면 "왜?"를 다시 계산해야 한다. 화면·리포트가
    같은 숫자를 쓰도록 한 번에 넘긴다.
    """
    days = cfg["alert"]["window_days"]
    threshold = cfg["alert"]["negative_ratio_threshold"]
    min_reviews = cfg["alert"]["min_reviews"]

    with storage.connect(db_path) as conn:
        if reference is None:
            # 기준일을 '오늘'로 고정하지 않는다 — 과거 데이터를 분석할 때 창이 비어 버린다.
            row = conn.execute(
                "SELECT MAX(created_at) AS d FROM clean_reviews WHERE created_at IS NOT NULL"
            ).fetchone()
            reference = row["d"] if row and row["d"] else date.today().isoformat()

        recent_start, recent_end, prev_start, prev_end = _window(reference, days)
        recent_total, recent_negative, recent_ratio = _ratio(conn, recent_start, recent_end)
        prev_total, prev_negative, prev_ratio = _ratio(conn, prev_start, prev_end)

    evidence = {
        "window_days": days,
        "recent": {"from": recent_start, "to": recent_end, "total": recent_total,
                   "negative": recent_negative, "ratio": recent_ratio},
        "previous": {"from": prev_start, "to": prev_end, "total": prev_total,
                     "negative": prev_negative, "ratio": prev_ratio},
        "threshold": threshold,
        "min_reviews": min_reviews,
    }

    # 표본이 너무 적으면 판정하지 않는다 — 리뷰 2건 중 1건이 부정이어도 50% 다.
    if recent_total < min_reviews:
        logger.info(
            "알림 판정 보류: 최근 %d일 리뷰 %d건 (최소 %d건 필요)",
            days, recent_total, min_reviews,
        )
        return None, evidence

    if recent_ratio is None:
        return None, evidence

    messages = []
    if recent_ratio >= threshold:
        messages.append(
            f"최근 {days}일({recent_start}~{recent_end}) 부정 비율이 "
            f"{recent_ratio * 100:.1f}% ({recent_negative}/{recent_total}건)로 "
            f"기준선 {threshold * 100:.0f}% 를 넘었습니다."
        )
    if prev_ratio is not None and prev_total >= min_reviews:
        delta = recent_ratio - prev_ratio
        if delta >= 0.2:
            messages.append(
                f"직전 같은 기간({prev_start}~{prev_end}) 대비 부정 비율이 "
                f"{prev_ratio * 100:.1f}% → {recent_ratio * 100:.1f}% "
                f"({delta * 100:+.1f}%p) 로 급증했습니다."
            )

    if not messages:
        logger.info("알림 없음: 최근 부정 비율 %.1f%%", recent_ratio * 100)
        return None, evidence

    warning = " ".join(messages)
    logger.warning("감정 변화 경고 — %s", warning)
    return warning, evidence


def format_evidence(evidence: dict) -> str:
    """판정 근거를 표로. 경고가 없을 때도 "무엇을 봤는지" 를 보여 준다."""
    recent, previous = evidence["recent"], evidence["previous"]

    def line(label: str, part: dict) -> str:
        ratio = f"{part['ratio'] * 100:.1f}%" if part["ratio"] is not None else "-"
        return (f"  {label} {part['from']}~{part['to']}  "
                f"리뷰 {part['total']:>3}건 · 부정 {part['negative']:>3}건 · {ratio}")

    return "\n".join([
        f"  창 크기: {evidence['window_days']}일 · 기준선 {evidence['threshold'] * 100:.0f}% · "
        f"최소 표본 {evidence['min_reviews']}건",
        line("최근", recent),
        line("직전", previous),
    ])
