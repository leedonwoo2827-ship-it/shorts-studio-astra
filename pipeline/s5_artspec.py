# -*- coding: utf-8 -*-
"""S5 장면 지시 — 씬마다 **무엇이 어떻게 움직이는지**. **모델을 부른다(돈).**

나가는 것: `04_장면/장면지시.json`

★ **이 단계는 그림을 설명하지 않는다. 동작을 설명한다.**
  다음 단계(아스트라)가 이 지시를 받아 애니메이션 SVG 를 코드로 짠다.
  「역동적으로 움직인다」 같은 말은 코드로 옮길 수 없으므로 스키마와 프롬프트
  양쪽에서 막는다 — `motion` 은 **무엇이 · 어떻게 · 언제**를 담아야 한다.

★ **규격과 금지 목록은 코드가 쓴다.** 41_26(새뮤얼슨 26장, 33장 성공)에서
  검증된 문법을 세로로 옮긴 것이고, 문장 하나만 흔들려도 결과가 흔들린다.
  모델에게 맡기면 매번 다르게 쓴다. 모델이 쓰는 것은 내용뿐이다.

★ **장면 안에 글자를 넣지 않는다.** 글자는 앱이 위아래 띠에 얹는다.
  그래야 오타 수정·모션·다국어가 공짜가 된다.
"""
from __future__ import annotations

import json
from typing import Any, Callable, Dict, List, Optional

from core import config, paths
from core.atomic_io import atomic_write_json
from llm import structured
from . import prompts
from .schemas import ARTSPEC_SCHEMA

SYSTEM = (
    "너는 모션 그래픽 감독이다. "
    "먼저 그 문장이 무엇을 주장하는지 정하고, 그 주장이 보이도록 무대를 짜고, "
    "무대 위에서 하나만 바꾼다. "
    "낱말을 그림으로 옮기지 않는다 — 문장이 참이라고 말하는 것을 그린다. "
    "장면 안에 글자를 절대 넣지 않는다. "
    "사람의 몸을 그리지 않는다. "
    "반드시 제시된 JSON 스키마대로만 답한다."
)


def band_note(width: int, height: int, top: int, bottom: int, ivory: str) -> str:
    """비워 둘 자리 — 좌표까지 못 박는다. 퍼센트만 주면 눈대중으로 비운다."""
    return (
        f"화면 규격: 세로 {width}×{height}. **위 {top}px 와 아래 {bottom}px 는 "
        f"비워 둔다** — 그 자리에 앱이 후크와 자막을 얹는다. 장면은 "
        f"y={top}~{height - bottom} 안에서만 움직인다. 바탕은 어디나 "
        f"아이보리({ivory}) 라서 빈 자리가 티나지 않는다"
    )


# ★ 되풀이·왕복을 뜻하는 말. 지시에 이 말이 들어가면 다음 단계가 왕복하는
#   코드를 쓰고, 화면이 8초 내내 안절부절못한다(실측 2026-09-08).
#   여기서 잡아 한 번 더 물어보는 것이 장면을 다시 받는 것보다 훨씬 싸다.
# ★ 마무리 씬의 동작 창 비율. 0.6 이면 동작이 60% 지점에서 끝나고 남은 40% 는
#   정지한 화면 위로 마무리 말이 얹힌다 — 사용자가 정한 마무리 모양이다.
CLOSE_MOTION_RATIO = 0.6

_LOOPY = ("주기", "반복", "왕복", "흔들", "깜빡", "진동", "오간다", "오가며",
          "되돌아", "되풀이", "번갈아", "커졌다", "작아졌다", "눌렸다",
          "펄럭", "출렁", "떨린")


def motions(r: Dict[str, Any]) -> List[str]:
    """한 씬의 움직임 — 변동 하나 + 거드는 것 하나(있으면)."""
    return [x for x in (r.get("change"), r.get("support")) if x]


def find_loopy(rows: List[Dict[str, Any]]) -> List[str]:
    """되풀이를 뜻하는 말이 든 동작 줄을 찾아 돌려준다."""
    hits: List[str] = []
    for r in rows:
        for m in motions(r):
            for w in _LOOPY:
                if w in m:
                    hits.append(f"씬 {r['no']}: 「{w}」 — {m[:70]}")
                    break
    return hits


def run(slug: str, *, on_activity: Optional[Callable[[str], None]] = None
        ) -> Dict[str, Any]:
    doc = _load(slug)
    scenes = doc.get("scenes") or []
    if not scenes:
        raise RuntimeError("씬이 없습니다. 먼저 「대본」 단계를 돌리세요.")

    img = dict(config.get("image", {}) or {})
    c = config.get("compose", {}) or {}
    ivory = c.get("ivory", "#F6F1E8")
    width, height = int(c.get("width", 1080)), int(c.get("height", 1920))
    top, bottom = int(c.get("band_top", 300)), int(c.get("band_bottom", 320))

    fallback = round(float(doc.get("seconds") or 22.0) / max(1, len(scenes)), 1)

    def window(s: Dict[str, Any]) -> tuple:
        """(동작이 끝나야 하는 시각, 화면에 있는 시간).

        ★ **마무리 씬은 동작 창을 짧게 준다.** 마지막 씬은 동작이 일찍 끝나고
          정지한 화면 위로 마무리 말이 얹혀야 한다. 프롬프트로 부탁하는 것보다
          창을 짧게 주는 쪽이 확실하다 — 모델은 준 길이에 동작을 맞춘다.
        """
        full = round(float(s.get("audio_sec") or fallback), 2)
        if (s.get("role") or "") == "close":
            return round(full * CLOSE_MOTION_RATIO, 2), full
        return full, full

    def line(s: Dict[str, Any]) -> str:
        mot, full = window(s)
        tail = ("  ← 마무리 씬: 남은 시간은 화면이 정지한 채 말이 이어진다"
                if (s.get("role") or "") == "close" else "")
        return "\n".join([
            f"- 씬 {s['no']} ({s.get('role') or 'body'}) · 화면에 {full}초 있고 "
            f"**동작은 {mot}초 안에 끝낸다**{tail}",
            f"  자막: 「{s.get('srt_text', '')}」",
            f"  장면 요지: {s.get('image_brief', '')}",
            f"  원문 근거: {s.get('source', '')}",
        ])

    scene_list = "\n".join(line(s) for s in scenes)
    user = prompts.render("artspec", style_hint=img.get("style_hint", ""),
                          ivory=ivory, sec=fallback, scene_list=scene_list)

    out, cost = structured("artspec", SYSTEM, user, ARTSPEC_SCHEMA,
                           on_activity=on_activity)
    rows_in = list(out.get("scenes") or [])

    # 되풀이가 섞였으면 **한 번만 더 물어본다.** 두 번째도 섞이면 경고만 남긴다 —
    # 사람이 그 줄을 고치는 게 빠르고, 여기서 무한히 되물으면 값만 쓴다.
    loopy = find_loopy(rows_in)
    warn_loopy: List[str] = []
    if loopy:
        # 줄바꿈은 배열로 잇는다 — 이 파일을 스크립트로 고칠 때 escape 가
        # 벗겨져 문자열이 통째로 깨진 적이 있다. 배열이면 그런 일이 없다.
        again = "\n".join([
            user, "", "---", "",
            "# 다시",
            "앞선 답에 **되풀이하는 동작**이 있습니다:",
            *(f"- {h}" for h in loopy),
            "",
            "한 방향으로 한 번만 가서 그 자리에 멈추는 동작으로 바꿔 다시 주세요.",
            "씬 수와 무대는 그대로 두고 `change`·`support` 만 고치세요.",
        ])
        out2, cost2 = structured("artspec", SYSTEM, again, ARTSPEC_SCHEMA,
                                 on_activity=on_activity)
        cost += cost2
        rows2 = list(out2.get("scenes") or [])
        loopy2 = find_loopy(rows2)
        if rows2 and len(loopy2) < len(loopy):
            rows_in, loopy = rows2, loopy2
        if loopy:
            warn_loopy = [f"되풀이하는 동작이 남았습니다 — 「장면 지시」 화면에서 "
                          f"그 줄을 고치세요: {h}" for h in loopy]

    got = {int(r["no"]): r for r in rows_in}

    rows: List[Dict[str, Any]] = []
    missing: List[int] = []
    for s in scenes:
        no = int(s["no"])
        r = got.get(no)
        if not r:
            missing.append(no)
            continue
        rows.append({
            "no": no,
            "file": f"{no:03d}.svg",
            "sec": window(s)[0],          # 동작이 끝나야 하는 시각
            "scene_sec": window(s)[1],    # 화면에 있는 시간
            "role": s.get("role") or "body",
            "claim": r["claim"].strip(),
            "stage": r["stage"].strip(),
            "layout": r["layout"].strip(),
            "change": r["change"].strip(),
            "support": (r.get("support") or "").strip(),
            "palette_note": (r.get("palette_note") or "").strip(),
        })

    doc_out: Dict[str, Any] = {
        "schema_version": 2,
        "slug": slug,
        "title": doc.get("title") or "",
        "canvas": {"width": width, "height": height,
                   "band_top": top, "band_bottom": bottom},
        "band_note": band_note(width, height, top, bottom, ivory),
        "style_hint": img.get("style_hint", ""),
        "palette": {"ivory": ivory, "ink": c.get("ink", "#1F4E79"),
                    "sub_ink": c.get("sub_ink", "#9DC3E6"),
                    "point": c.get("point", "#DEEBF7"),
                    "accent": c.get("accent", "#E07A2F")},
        "count": len(rows),
        "file_naming": "파일 앞 세 자리가 씬 번호다. 004.svg → 4번 씬. "
                       "직접 만든 장면을 04_장면/ 에 같은 이름으로 넣어도 된다. "
                       "움직이는 장면은 .svg, 정지 그림은 .png 다.",
        "scenes": rows,
        "cost_usd": round(cost, 4),
        "warnings": ([f"씬 {missing} 의 지시가 오지 않았습니다."] if missing else [])
                    + warn_loopy,
    }
    atomic_write_json(str(paths.art_spec(slug)), doc_out, indent=2)
    return doc_out


def _load(slug: str) -> Dict[str, Any]:
    p = paths.script_json(slug)
    if not p.exists():
        raise FileNotFoundError("먼저 「대본」 단계를 돌리세요.")
    return json.loads(p.read_text(encoding="utf-8"))
