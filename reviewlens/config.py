"""설정 로드 — `config.json` + 환경변수.

**나누는 기준**: 공개해도 되는 값(중복 정책·정제 임계값·색·알림 기준)은 `config.json`,
공개하면 안 되는 값(API 키)은 환경변수. 파일 하나에 섞으면 설정을 공유할 때마다 키를
지워야 한다.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

CONFIG_FILE = "config.json"
LLM_KEY_NAME = "GEMINI_API_KEY"  # 값이 아니라 **이름만** 코드에 둔다


def load_dotenv(path: str = ".env") -> None:
    """`.env` 를 환경변수로 올린다. 이미 있는 값은 덮어쓰지 않는다(터미널 값이 우선)."""
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            if key and key not in os.environ:
                os.environ[key] = value.strip().strip('"').strip("'")


def load_config(path: str = CONFIG_FILE) -> dict:
    """설정 파일을 읽는다. 없거나 깨졌으면 무엇을 고쳐야 하는지 알려 준다."""
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError as exc:
        raise ValueError(f"설정 파일이 없습니다: {path} (저장소의 config.json 을 복사하세요)") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"설정 파일이 올바른 JSON 이 아닙니다({path}): {exc}") from exc


def get_key(name: str = LLM_KEY_NAME) -> str | None:
    """환경변수에서 키를 읽는다. 없으면 None — 호출한 쪽이 안내 후 결정한다."""
    value = os.environ.get(name, "").strip()
    return value or None


def missing_key_message(name: str = LLM_KEY_NAME) -> str:
    """키가 없을 때의 안내문. ⚠ 실제 키 값은 어디에도 출력하지 않는다."""
    return (
        f"[안내] 환경변수 {name} 가 설정되어 있지 않습니다 — AI 단계를 실행할 수 없습니다.\n"
        f"  macOS/Linux : export {name}=\"YOUR_KEY\"\n"
        f"  PowerShell  : $env:{name}=\"YOUR_KEY\"\n"
        f"  또는 .env 파일에 {name}=YOUR_KEY (.gitignore 에 있어 커밋되지 않습니다)"
    )


def ensure_dir(path: str) -> str:
    """폴더가 없으면 만든다 → 그 경로. 저장 직전에 부른다."""
    Path(path).mkdir(parents=True, exist_ok=True)
    return path
