# -*- coding: utf-8 -*-
"""S9 결과 — 유튜브에 올릴 글. **모델을 부른다(돈, 싼 모델).**

나가는 것: `06_완성/<최신빌드>/유튜브.txt`

★ 업로드를 **자동으로 하지 않는다.** 제목·설명·태그·고정댓글까지 만들고 멈춘다.
  올리는 순간은 사람이 판단할 자리다 — 되돌리기 어렵고, 채널 평판이 걸린다.
"""
from __future__ import annotations

import json
from typing import Any, Callable, Dict, Optional

from core import config, paths, persona
from core.atomic_io import atomic_write_json, atomic_write_text
from llm import structured
from . import prompts, s1_script
from .schemas import META_SCHEMA

SYSTEM = (
    "너는 유튜브 쇼츠 채널을 운영하는 편집자다. "
    "낚시 제목을 쓰지 않고, 영상에 없는 내용을 설명에 적지 않는다. "
    "반드시 제시된 JSON 스키마대로만 답한다."
)


def run(slug: str, *, source_line: str = "",
        on_activity: Optional[Callable[[str], None]] = None) -> Dict[str, Any]:
    doc = json.loads(paths.script_json(slug).read_text(encoding="utf-8"))
    scenes = doc.get("scenes") or []
    if not scenes:
        raise RuntimeError("씬이 없습니다. 먼저 「대본」 단계를 돌리세요.")

    script_txt = "\n".join(f"{s.get('no')}. {s.get('srt_text')}" for s in scenes)
    meta_json = paths.source_json(slug)
    book = ""
    if meta_json.exists():
        m = json.loads(meta_json.read_text(encoding="utf-8"))
        book = f"{m.get('file', '')} — {m.get('title', '')}".strip(" —")

    out, cost = structured("meta", SYSTEM, prompts.render(
        "meta", title=doc.get("title") or "", script=script_txt,
        hashtags="  ".join(doc.get("hashtags") or []),
        source_line=source_line or book or "(출처 미지정)",
        # 올릴 글도 같은 무드로 — 대본은 ENFP 톤인데 제목만 하십시오체면 튄다.
        tone_block=persona.tone_block(*s1_script.read_persona(slug)),
    ), META_SCHEMA, on_activity=on_activity)

    build = paths.latest_build(slug)
    if build is None:
        raise RuntimeError("빌드가 없습니다. 먼저 「빌드」 단계를 돌리세요.")

    txt = "\n".join([
        "[제목]", out["title"], "",
        "[설명]", out["description"], "",
        "[태그]", ", ".join(out["tags"]), "",
        "[고정댓글]", out["pinned_comment"], "",
        "-" * 50,
        "설명 안의 {원본링크} 는 롱폼 영상 주소로 바꿔 넣으세요.",
        "영상은 쇼츠로 올리고, 설명과 고정댓글에 롱폼 링크를 걸어 트래픽을 보내세요.",
    ])
    atomic_write_text(str(build / "유튜브.txt"), txt)
    atomic_write_json(str(build / "유튜브.json"),
                      {**out, "cost_usd": round(cost, 4)}, indent=2)
    return {**out, "cost_usd": round(cost, 4), "file": str(build / "유튜브.txt")}
