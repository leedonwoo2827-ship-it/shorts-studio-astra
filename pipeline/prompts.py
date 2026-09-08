# -*- coding: utf-8 -*-
"""프롬프트는 코드 밖 텍스트다 — `llm/prompts/*.md`.

★ 치환은 `str.format` 이 아니라 `str.replace` 다. 프롬프트에 마크다운 표와
  JSON 예시가 들어가는데, `format` 은 `{` 를 만나면 죽는다.

★ 프롬프트 본문은 단계 캐시의 `input_hash` 에 들어간다 — 프롬프트를 고치면
  그 단계가 자동으로 무효가 된다. 그래서 `text()` 가 원문을 그대로 돌려준다.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Dict

DIR = Path(__file__).resolve().parents[1] / "llm" / "prompts"


def text(name: str) -> str:
    p = DIR / f"{name}.md"
    if not p.exists():
        raise FileNotFoundError(f"프롬프트가 없습니다: {p}")
    return p.read_text(encoding="utf-8")


def render(name: str, **vals: Any) -> str:
    """`{key}` 를 값으로 갈아 넣는다. 남은 `{...}` 는 그대로 둔다(JSON 예시다)."""
    s = text(name)
    for k, v in vals.items():
        s = s.replace("{" + k + "}", str(v))
    return s


def fingerprint(name: str, **vals: Any) -> str:
    return hashlib.sha256(render(name, **vals).encode("utf-8")).hexdigest()[:16]
