"""CLI — argparse 서브커맨드 10개.

  import     CSV 적재            → raw_reviews
  add        리뷰 1건 직접 입력  → raw_reviews
  clean      정제(규칙 5종·중복) → clean_reviews
  analyze    감정 + 신뢰도       → clean_reviews.sentiment
  extract    키워드·요약·개선 제안 → extractions
  list       목록 조회(필터·정렬·페이지네이션)
  show       상세 조회
  stats      통계 요약
  dashboard  차트 + 리포트 + HTML 대시보드
  export     CSV / JSONL

**단계를 나눈 이유**: 각 단계의 비용과 실패 성격이 다르다. 적재는 파일 I/O, 정제는 계산,
분석은 돈이 든다. 한 명령으로 묶으면 분석이 실패했을 때 적재부터 다시 해야 한다.
나눠 두면 실패한 단계만 다시 돌린다 — SQLite 가 그 사이를 잇는다.

exit code 는 함수가 **return** 한다(`sys.exit` 를 안에서 부르지 않는다). 테스트가
`main([...])` 를 직접 부를 수 있어야 하기 때문이다.
"""

from __future__ import annotations

import argparse
import logging
import sys
from typing import Sequence

from . import ai, alert, charts, clean, config as config_module, dashboard, export, ingest
from . import stats as stats_module
from . import storage

logger = logging.getLogger("reviewlens")


def setup_logging(verbose: bool = False) -> None:
    """INFO/WARNING/ERROR 로그를 stderr 로 낸다.

    stdout 은 리포트·목록처럼 파이프로 넘길 산출물의 자리다 —
    `reviewlens stats | less` 를 했을 때 진행 메시지가 섞이면 안 된다.
    """
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


def build_parser() -> argparse.ArgumentParser:
    """서브커맨드 10개를 정의한다."""
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

    p_add = sub.add_parser("add", help="리뷰 1건 직접 입력")
    p_add.add_argument("--text", required=True, help="리뷰 본문")
    p_add.add_argument("--id", dest="review_id", help="리뷰 식별자(없으면 자동 생성)")
    p_add.add_argument("--product")
    p_add.add_argument("--rating", type=int)
    p_add.add_argument("--date", dest="created_at", help="YYYY-MM-DD")
    p_add.set_defaults(func=_cmd_add)

    p_clean = sub.add_parser("clean", help="정제 후 clean 저장소로")
    p_clean.add_argument("--policy", choices=["skip", "upsert"], help="중복 처리(기본은 설정)")
    p_clean.add_argument("--all", action="store_true", help="이미 정제한 raw 도 다시 처리")
    p_clean.set_defaults(func=_cmd_clean)

    p_an = sub.add_parser("analyze", help="AI 감정 분석 + 신뢰도")
    group = p_an.add_mutually_exclusive_group()
    group.add_argument("--all", action="store_true", help="전부 다시 분석")
    group.add_argument("--unanalyzed", action="store_true", help="아직 분석 안 한 것만(기본)")
    group.add_argument("--id", dest="review_id", help="리뷰 1건만")
    p_an.add_argument("--limit", type=int)
    p_an.set_defaults(func=_cmd_analyze)

    p_ex = sub.add_parser("extract", help="키워드·요약·개선 제안 추출")
    p_ex.add_argument("--sentiment", choices=["긍정", "중립", "부정"])
    p_ex.add_argument("--product")
    p_ex.add_argument("--date-from", dest="date_from")
    p_ex.add_argument("--date-to", dest="date_to")
    p_ex.set_defaults(func=_cmd_extract)

    p_list = sub.add_parser("list", help="목록 조회 (필터·정렬·페이지네이션)")
    p_list.add_argument("--sentiment", choices=["긍정", "중립", "부정"])
    p_list.add_argument("--rating", type=int)
    p_list.add_argument("--rating-min", dest="rating_min", type=int)
    p_list.add_argument("--product")
    p_list.add_argument("--date-from", dest="date_from")
    p_list.add_argument("--date-to", dest="date_to")
    p_list.add_argument("--status", choices=["analyzed", "unanalyzed"])
    p_list.add_argument("--sort", choices=list(storage.SORT_COLUMNS), default="date")
    p_list.add_argument("--asc", action="store_true", help="오름차순(기본은 내림차순)")
    p_list.add_argument("--page", type=int, default=1)
    p_list.add_argument("--size", type=int, default=10)
    p_list.set_defaults(func=_cmd_list)

    p_show = sub.add_parser("show", help="리뷰 1건 상세")
    p_show.add_argument("review_id", help="리뷰 식별자 (list 로 확인)")
    p_show.set_defaults(func=_cmd_show)

    p_stats = sub.add_parser("stats", help="통계 요약")
    # 기준일을 바꿀 수 있게 한다 — 과거 어느 시점에 경고가 떴을지 되짚어 볼 수 있어야 한다.
    p_stats.add_argument("--as-of", dest="as_of", help="알림 기준일 YYYY-MM-DD(기본: 최신 리뷰일)")
    p_stats.set_defaults(func=_cmd_stats)

    p_dash = sub.add_parser("dashboard", help="차트 + 리포트 + HTML 대시보드")
    p_dash.add_argument("--format", choices=["md", "txt"], default="md", help="리포트 포맷")
    p_dash.add_argument("--no-charts", action="store_true")
    p_dash.add_argument("--no-html", action="store_true", help="HTML 대시보드를 만들지 않는다")
    p_dash.add_argument("--as-of", dest="as_of", help="알림 기준일 YYYY-MM-DD(기본: 최신 리뷰일)")
    p_dash.set_defaults(func=_cmd_dashboard)

    p_exp = sub.add_parser("export", help="CSV / JSONL 내보내기")
    p_exp.add_argument("--format", choices=["csv", "jsonl", "both"], default="csv")
    p_exp.add_argument("--sentiment", choices=["긍정", "중립", "부정"])
    p_exp.add_argument("--rating-min", dest="rating_min", type=int)
    p_exp.add_argument("--product")
    p_exp.set_defaults(func=_cmd_export)

    return parser


def _cmd_import(args, cfg: dict) -> int:
    try:
        records = ingest.read_csv(args.file)
    except ValueError as exc:
        print(f"[중단] {exc}", file=sys.stderr)
        return 1
    with storage.connect(cfg["storage"]["db_path"]) as conn:
        for record in records:
            storage.insert_raw(conn, record)
    print(f"적재 {len(records)}건 (원본 저장소)")
    return 0


def _cmd_add(args, cfg: dict) -> int:
    record = ingest.make_manual_record(
        args.text, review_id=args.review_id, product=args.product,
        rating=args.rating, created_at=args.created_at,
    )
    with storage.connect(cfg["storage"]["db_path"]) as conn:
        storage.insert_raw(conn, record)
    print(f"리뷰 1건 적재 (review_id={record['payload']['review_id']})")
    print("  → `clean` 을 실행해야 분석 대상이 됩니다")
    return 0


def _cmd_clean(args, cfg: dict) -> int:
    policy = args.policy or cfg.get("duplicate_policy", "skip")
    result = clean.run_clean(cfg["storage"]["db_path"], cfg, policy=policy,
                             only_uncleaned=not args.all)
    print(
        f"정제 대상 {result['total']} · 신규 {result['inserted']} · 중복 {result['skipped']}"
        f" · 갱신 {result['updated']} · 제외 {result['invalid']}"
    )
    for reason, count in (result.get("reasons") or {}).items():
        print(f"    제외 — {reason}: {count}건")
    return 0


def _cmd_analyze(args, cfg: dict) -> int:
    api_key = config_module.get_key()
    if not api_key:
        print(config_module.missing_key_message(), file=sys.stderr)
        return 1
    target = "all" if args.all else ("id" if args.review_id else "unanalyzed")
    result = ai.run_analyze(cfg["storage"]["db_path"], api_key, cfg, target=target,
                            review_id=args.review_id, limit=args.limit)
    print(f"분석 대상 {result['target']} · 완료 {result['done']} · 실패 {result['failed']}")
    return 0


def _cmd_extract(args, cfg: dict) -> int:
    api_key = config_module.get_key()
    if not api_key:
        print(config_module.missing_key_message(), file=sys.stderr)
        return 1
    result = ai.run_extract(cfg["storage"]["db_path"], api_key, cfg, sentiment=args.sentiment,
                            product=args.product, date_from=args.date_from, date_to=args.date_to)
    if result is None:
        print("추출 실패 또는 대상 없음 (로그를 확인하세요)", file=sys.stderr)
        return 1
    print(f"추출 완료 — 긍정 키워드 {len(result.get('positive_keywords') or [])}개, "
          f"부정 키워드 {len(result.get('negative_keywords') or [])}개, "
          f"개선 제안 {len(result.get('improvements') or [])}개")
    return 0


def _cmd_list(args, cfg: dict) -> int:
    if args.page < 1 or args.size < 1:
        print("[중단] --page 와 --size 는 1 이상이어야 합니다", file=sys.stderr)
        return 1

    filters = dict(sentiment=args.sentiment, rating=args.rating, rating_min=args.rating_min,
                   product=args.product, date_from=args.date_from, date_to=args.date_to,
                   status=args.status)
    offset = (args.page - 1) * args.size

    with storage.connect(cfg["storage"]["db_path"]) as conn:
        total = storage.count_clean(conn, **filters)
        rows = storage.select_clean(conn, **filters, sort=args.sort, desc=not args.asc,
                                    limit=args.size, offset=offset)

    if total == 0:
        print("조건에 맞는 리뷰가 없습니다")
        return 0

    # 올림 나눗셈 — 11건을 10개씩 보면 2페이지다.
    pages = (total + args.size - 1) // args.size
    order = "오름차순" if args.asc else "내림차순"
    print(f"총 {total}건 · {args.page}/{pages} 페이지 · 정렬 {args.sort} {order}")
    print(f"{'리뷰ID':<8}{'작성일':<12}{'별점':<5}{'감정':<5}{'신뢰':<6}본문")
    print("-" * 84)
    for row in rows:
        rating = f"★{row['rating']}" if row["rating"] else "-"
        sentiment = row["sentiment"] or "-"
        confidence = f"{row['confidence']:.2f}" if row["confidence"] is not None else "-"
        # 본문이 길면 표가 무너진다 — 잘라내되 잘렸음을 …로 알린다
        text = row["text"] if len(row["text"]) <= 40 else row["text"][:39] + "…"
        print(f"{row['review_id']:<8}{row['created_at'] or '-':<12}{rating:<5}"
              f"{sentiment:<5}{confidence:<6}{text}")

    if args.page < pages:
        print(f"\n다음 페이지: --page {args.page + 1}")
    return 0


def _cmd_show(args, cfg: dict) -> int:
    with storage.connect(cfg["storage"]["db_path"]) as conn:
        row = storage.get_clean(conn, args.review_id)

    if row is None:
        print(f"{args.review_id} 리뷰를 찾을 수 없습니다 (list 로 확인하세요)", file=sys.stderr)
        return 1

    print("=" * 70)
    print(f"리뷰 {row['review_id']}")
    print("=" * 70)
    print(f"제품     : {row['product'] or '-'}")
    print(f"별점     : {'★' * row['rating'] if row['rating'] else '(없음)'}")
    print(f"작성일   : {row['created_at'] or '(형식을 읽지 못함)'}")
    print(f"언어     : {row['language'] or '-'}")
    print(f"정제 시각 : {row['cleaned_at']}")
    print("\n[본문]")
    print(row["text"])
    print("\n[감정 분석]")
    if row["sentiment"]:
        print(f"  판정   : {row['sentiment']}")
        print(f"  신뢰도 : {row['confidence']:.2f}" if row["confidence"] is not None else "  신뢰도 : -")
        print(f"  분석 시각 : {row['analyzed_at']}")
        if row["confidence"] is not None and row["confidence"] < 0.7:
            print("  ⚠ 신뢰도가 낮습니다 — 사람이 확인하는 것이 좋습니다")
    else:
        print(f"  (아직 분석 전 — `analyze --id {row['review_id']}` 로 분석할 수 있습니다)")
    return 0


def _cmd_stats(args, cfg: dict) -> int:
    data = stats_module.summary(cfg["storage"]["db_path"])
    print(stats_module.format_summary(data))

    # 통계를 볼 때 경고도 함께 본다 — 따로 실행해야 알 수 있으면 아무도 안 본다.
    warning, evidence = alert.check(cfg["storage"]["db_path"], cfg,
                                    reference=getattr(args, "as_of", None))
    print("  [감정 변화 알림]")
    print(alert.format_evidence(evidence))
    print(f"  {'⚠ ' + warning if warning else '이상 없음'}\n")
    return 0


def _cmd_dashboard(args, cfg: dict) -> int:
    db_path = cfg["storage"]["db_path"]
    made: dict[str, str | None] = {
        "감정 분포": None, "시간별 감정 추이": None, "별점별 감정 분포": None,
    }

    if not args.no_charts:
        charts_dir = config_module.ensure_dir(cfg["output"]["charts_dir"])
        with storage.connect(db_path) as conn:
            by_sentiment = storage.group_by_sentiment(conn)
            by_date = storage.group_by_date_sentiment(conn)
            by_rating = storage.group_by_rating_sentiment(conn)
        made["감정 분포"] = charts.chart_sentiment_share(by_sentiment, charts_dir, cfg)
        made["시간별 감정 추이"] = charts.chart_sentiment_trend(by_date, charts_dir, cfg)
        made["별점별 감정 분포"] = charts.chart_rating_sentiment(by_rating, charts_dir, cfg)

    warning, _ = alert.check(db_path, cfg, reference=getattr(args, "as_of", None))

    text = stats_module.build_report(db_path, made, alert=warning)
    report_path = stats_module.save_report(
        text, config_module.ensure_dir(cfg["output"]["reports_dir"]), fmt=args.format
    )
    print(text)  # 산출물은 stdout — 파이프로 넘길 수 있게
    print(f"\n리포트: {report_path}", file=sys.stderr)

    if not args.no_html:
        html_text = dashboard.build_html(db_path, made, alert=warning)
        html_path = dashboard.save_dashboard(
            html_text, config_module.ensure_dir(cfg["output"]["dashboard_dir"])
        )
        print(f"대시보드: {html_path}", file=sys.stderr)
    return 0


def _cmd_export(args, cfg: dict) -> int:
    paths = export.run_export(
        cfg["storage"]["db_path"],
        config_module.ensure_dir(cfg["output"]["exports_dir"]),
        fmt=args.format, sentiment=args.sentiment, rating_min=args.rating_min,
        product=args.product,
    )
    if not paths:
        print("내보낼 데이터가 없습니다", file=sys.stderr)
        return 1
    for path in paths:
        print(path)
    return 0


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
