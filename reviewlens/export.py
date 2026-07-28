"""내보내기 — CSV · JSONL 두 포맷.

**두 포맷을 함께 두는 이유**는 소비자가 다르기 때문이다.

  CSV   = 사람·엑셀. 표로 열어 정렬·필터한다. 줄바꿈이 든 값에 약하다.
  JSONL = 프로그램. 한 줄 = 한 레코드라 스트리밍으로 읽고, 중첩·줄바꿈에 강하다.

리뷰 본문에는 줄바꿈이 들어 있을 수 있다. **CSV 에서는 공백으로 펴고, JSONL 에는 원본
그대로** 넣는다.
"""

from __future__ import annotations

import csv
import json
import logging
import os

from . import storage
from .ingest import now_iso

logger = logging.getLogger(__name__)

FIELDS = [
    "review_id", "product", "rating", "created_at", "language",
    "sentiment", "confidence", "text", "cleaned_at", "analyzed_at",
]


def _row_to_dict(row) -> dict:
    """sqlite3.Row → dict. 내보내기 대상 필드만 고른다."""
    return {field: row[field] for field in FIELDS}


def export_csv(rows, out_dir: str) -> str:
    """CSV 로 내보낸다 → 경로.

    `encoding="utf-8-sig"` 를 쓰는 이유: 엑셀(Windows)이 BOM 없는 UTF-8 CSV 를 열면
    한글이 깨진다. BOM 한 글자가 "이건 UTF-8 이다"를 알려 준다.
    """
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, f"reviews_{now_iso()[:10]}.csv")
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writeheader()
        for row in rows:
            item = _row_to_dict(row)
            # 표 한 칸에 줄바꿈이 들어가면 엑셀에서 행이 밀려 보인다 — 공백으로 편다.
            if item.get("text"):
                item["text"] = str(item["text"]).replace("\n", " ")
            writer.writerow(item)
    logger.info("CSV 저장: %s (%d건)", path, len(rows))
    return path


def export_jsonl(rows, out_dir: str) -> str:
    """JSONL 로 내보낸다 → 경로. 한 줄 = 한 레코드, 원본 줄바꿈 유지."""
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, f"reviews_{now_iso()[:10]}.jsonl")
    with open(path, "w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(_row_to_dict(row), ensure_ascii=False) + "\n")
    logger.info("JSONL 저장: %s (%d건)", path, len(rows))
    return path


def run_export(db_path: str, out_dir: str, fmt: str = "csv", **filters) -> list[str]:
    """내보내기 단계 → 저장된 경로 목록. fmt 는 csv · jsonl · both."""
    with storage.connect(db_path) as conn:
        rows = storage.select_clean(conn, **filters)

    if not rows:
        logger.warning("내보낼 데이터가 없습니다 (필터: %s)", filters)
        return []

    paths: list[str] = []
    if fmt in ("csv", "both"):
        paths.append(export_csv(rows, out_dir))
    if fmt in ("jsonl", "both"):
        paths.append(export_jsonl(rows, out_dir))
    return paths
