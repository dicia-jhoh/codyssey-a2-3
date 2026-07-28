"""수집 — CSV 파일 적재(`import`)와 리뷰 1건 직접 입력(`add`).

파일과 수동 입력을 **같은 raw 테이블**에 넣는 이유: 뒤 단계(정제·분석)가 출처를 신경 쓰지
않아도 되게 하기 위해서다. 어디서 왔는지는 `method` 컬럼에 남으므로 나중에 구분할 수 있다.

CSV 를 고른 이유: 엑셀에서 그대로 저장할 수 있고, 쇼핑몰 리뷰 내려받기가 대개 CSV 다.
`csv.DictReader` 는 표준 라이브러리라 추가 설치가 없다.
"""

from __future__ import annotations

import csv
import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

# 리뷰 텍스트가 담긴 열 이름 후보. 쇼핑몰마다 다르므로 순서대로 찾는다.
TEXT_COLUMNS = ("text", "review", "review_text", "content", "리뷰", "내용")
ID_COLUMNS = ("review_id", "id", "리뷰번호")
RATING_COLUMNS = ("rating", "score", "star", "별점", "평점")
DATE_COLUMNS = ("created_at", "date", "written_at", "작성일")
PRODUCT_COLUMNS = ("product", "item", "product_name", "제품", "상품명")


def now_iso() -> str:
    """현재 시각 ISO8601. 저장되는 모든 시각을 이 함수 하나로 만든다."""
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def _pick(row: dict, candidates: tuple[str, ...]) -> str | None:
    """여러 이름 후보 중 실제로 있는 열의 값을 돌려준다.

    열 이름을 하나로 고정하지 않는 이유: 리뷰 CSV 는 출처마다 헤더가 다르다.
    사용자에게 "열 이름을 text 로 바꾸세요"라고 요구하는 대신 우리가 맞춘다.
    """
    for name in candidates:
        if name in row and str(row[name]).strip():
            return str(row[name]).strip()
    return None


def read_csv(path: str) -> list[dict]:
    """CSV → raw 레코드 목록. 파일·인코딩 문제는 ValueError 로 올린다.

    `utf-8-sig` 로 여는 이유: 엑셀이 저장한 CSV 는 맨 앞에 BOM 이 붙는다. 그대로 읽으면
    **첫 열 이름이 `\\ufeffreview_id`** 가 되어 헤더 매칭이 조용히 실패한다.
    """
    try:
        with open(path, encoding="utf-8-sig", newline="") as f:
            rows = list(csv.DictReader(f))
    except FileNotFoundError as exc:
        raise ValueError(f"파일을 찾을 수 없습니다: {path}") from exc
    except UnicodeDecodeError as exc:
        raise ValueError(
            f"파일 인코딩을 읽을 수 없습니다({path}). UTF-8 로 저장했는지 확인하세요: {exc}"
        ) from exc

    if not rows:
        raise ValueError(f"데이터 행이 없습니다: {path}")

    records = []
    for index, row in enumerate(rows, start=1):
        # 원본 행을 통째로 남긴다 — 지금 안 쓰는 열도 나중에 필요해질 수 있다.
        records.append(
            {
                "ingested_at": now_iso(),
                "source": path,
                "method": "csv",
                "payload": {**row, "_row_number": index},
            }
        )
    logger.info("CSV 읽기: %s %d행", path, len(records))
    return records


def make_manual_record(text: str, *, review_id: str | None, product: str | None,
                       rating: int | None, created_at: str | None) -> dict:
    """`add` 명령으로 들어온 리뷰 1건 → raw 레코드.

    review_id 가 없으면 시각으로 만든다 — 멱등키가 없으면 중복 판정을 할 수 없다.
    """
    generated_id = review_id or f"MANUAL-{now_iso().replace(':', '').replace('-', '')}"
    return {
        "ingested_at": now_iso(),
        "source": "manual",
        "method": "manual",
        "payload": {
            "review_id": generated_id,
            "product": product,
            "rating": rating,
            "created_at": created_at,
            "text": text,
        },
    }


def extract_fields(payload: dict) -> dict:
    """원본 행에서 우리가 쓰는 필드만 골라낸다(열 이름이 달라도 찾아 준다)."""
    return {
        "review_id": _pick(payload, ID_COLUMNS),
        "product": _pick(payload, PRODUCT_COLUMNS),
        "rating": _pick(payload, RATING_COLUMNS),
        "created_at": _pick(payload, DATE_COLUMNS),
        "text": _pick(payload, TEXT_COLUMNS),
    }
