# -*- coding: utf-8 -*-
"""S2 발음 — `srt_text` → `narration_text`. **모델을 부르지 않는다(무료).**

세 텍스트를 절대 섞지 않는다. 이 앱의 첫 번째 계약이다.

    hook_line1/2    화면 위쪽 띠에 얹히는 글자
    srt_text        화면 아래쪽 띠에 얹히는 자막
    narration_text  TTS 가 읽는 글자        ← 이 단계가 만드는 것

★ 규칙은 `core/honorific.for_speech` 한 곳뿐이다. 규칙이 두 벌이면 언젠가 서로
  다르게 읽는다 — 한쪽으로 굽고 다른 쪽으로 검수하게 된다.

★ **사람 손이 항상 이긴다.** `01_대본/발음교정표.txt` 에 적힌 씬은 규칙을 건너뛰고
  적힌 대로 읽는다. 규칙이 못 잡는 고유명사가 늘 남는다.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Tuple

from core import paths
from core.atomic_io import atomic_write_json, atomic_write_text
from core.honorific import for_speech

# `001: 읽을 글자` — 씬 번호로 찾는다. 주석·빈 줄은 건너뛴다.
_LINE = re.compile(r"^\s*(\d{1,3})\s*:\s*(.+?)\s*$")

_HEADER = """# 발음교정표 — 규칙이 못 잡는 것만 여기 적습니다.
#
#   씬번호: 실제로 읽을 글자
#
# 예)  003: 우편 요금이 일 페니로 통일되자 지식도 편지를 타기 시작했습니다.
#
# 적힌 씬은 규칙을 건너뛰고 **적힌 대로** 읽습니다.
# 고친 뒤 「음성」을 다시 돌리면 그 씬만 다시 만들어집니다.
"""


def read_table(slug: str) -> Dict[int, str]:
    p = paths.pron_table(slug)
    if not p.exists():
        return {}
    out: Dict[int, str] = {}
    for line in p.read_text(encoding="utf-8").splitlines():
        if line.lstrip().startswith("#"):
            continue
        m = _LINE.match(line)
        if m:
            out[int(m.group(1))] = m.group(2)
    return out


def ensure_table(slug: str) -> None:
    """빈 표를 깔아 둔다 — 있어야 사람이 열어 본다."""
    p = paths.pron_table(slug)
    if not p.exists():
        atomic_write_text(str(p), _HEADER)


def run(slug: str) -> Dict[str, Any]:
    doc = _load(slug)
    table = read_table(slug)
    ensure_table(slug)

    changed: List[int] = []
    for s in doc.get("scenes") or []:
        no = int(s.get("no") or 0)
        src = (s.get("srt_text") or "").strip()
        manual = table.get(no)
        new = manual.strip() if manual else for_speech(src)
        if new != (s.get("narration_text") or ""):
            changed.append(no)
        s["narration_text"] = new
        s["narration_from"] = "표" if manual else "규칙"

    atomic_write_json(str(paths.script_json(slug)), doc, indent=2)
    return {"changed": changed, "scenes": len(doc.get("scenes") or []),
            "manual": sorted(table)}


def _load(slug: str) -> Dict[str, Any]:
    import json
    p = paths.script_json(slug)
    if not p.exists():
        raise FileNotFoundError("먼저 「대본」 단계를 돌리세요.")
    return json.loads(p.read_text(encoding="utf-8"))
