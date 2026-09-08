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
    """한 씬의 움직임 — 변동 · 거드는 것 · 연쇄의 박자 전부."""
    out = [x for x in (r.get("change"), r.get("support")) if x]
    out += [str(b.get("what") or "") for b in (r.get("beats") or [])]
    return [x for x in out if x]


def find_overlap(r: Dict[str, Any], mot_sec: float) -> List[str]:
    """연쇄가 **순차인지** 본다. 겹치면 셋이 동시에 움직여 아무것도 안 보인다.

    반복 대신 연쇄로 가는 것이 이 형식의 요점이라, 창이 겹치는 순간 그 이득이
    사라진다. 막지 않고 알려 준다 — 사람이 그 줄만 고치면 된다.
    """
    bad: List[str] = []
    beats = sorted((r.get("beats") or []), key=lambda b: float(b.get("at") or 0))
    prev_end = -1.0
    for b in beats:
        at, until = float(b.get("at") or 0), float(b.get("until") or 0)
        if until <= at:
            bad.append(f"씬 {r.get('no')}: 박자 길이가 0 이하입니다 ({at}~{until})")
        elif at < prev_end - 0.01:
            bad.append(f"씬 {r.get('no')}: 박자가 겹칩니다 ({at}초가 앞 박자 "
                       f"{prev_end}초 안으로 들어옵니다)")
        if until > mot_sec + 0.01:
            bad.append(f"씬 {r.get('no')}: 박자가 동작 창({mot_sec}초)을 넘습니다 "
                       f"({until}초)")
        prev_end = max(prev_end, until)
    return bad


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


def make_camera(cues: List[Dict[str, Any]], n_cells: int,
                scene_sec: float) -> List[Dict[str, Any]]:
    """**자막 큐 경계에서 카메라를 만든다.** 모델이 시각을 찍지 않는다.

    큐는 음성 실측에서 나오므로(`s4_subs`) 카메라도 실측에 맞고, 어긋날 여지가
    없다. 자막 조각과 화면이 **같은 시각에 튀는 것**이 리듬의 전부다 —
    따로 두면 둘 다 죽는다.

    칸보다 큐가 많으면 칸을 되쓰되 `좁히기` 로 변화를 준다. 같은 칸을 같은
    크기로 두 번 보여 주면 컷이 안 생긴 것처럼 보인다.
    """
    if n_cells <= 0:
        return []
    if not cues:
        return [{"at": 0.0, "cell": 1, "move": "고정"}]

    shots: List[Dict[str, Any]] = []
    seen: Dict[int, int] = {}
    for i, cue in enumerate(cues):
        cell = (i % n_cells) + 1
        seen[cell] = seen.get(cell, 0) + 1
        if i == 0:
            move = "고정"           # 첫 컷은 뛸 곳이 없다
        elif seen[cell] > 1:
            move = "좁히기"         # 되쓰는 칸 — 같은 그림을 다르게 본다
        else:
            move = "뛰기"
        shots.append({"at": round(float(cue.get("t") or 0.0), 3),
                      "cell": cell, "move": move})
    return shots


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

    cells_per = max(1, int(config.get("art.cells_per_scroll", 3)))
    max_scrolls = max(1, int(config.get("art.max_scrolls", 4)))

    # 구조.json — 씬이 가리키는 사실의 값·단위·표·골격을 프롬프트에 붙인다.
    # 「비율이 주장이면 셀 수 있는 것을 놓아라」는 지시가 그때 실제 숫자를 갖는다.
    struct: Dict[str, Any] = {}
    sp = paths.structure_json(slug)
    if sp.exists():
        try:
            struct = json.loads(sp.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            struct = {}
    facts = {str(f.get("id")): f for f in (struct.get("facts") or [])}
    tables = {str(t.get("id")): t for t in (struct.get("tables") or [])}
    blk_table = {str(t.get("block")): str(t.get("id")) for t in (struct.get("tables") or [])}
    skels = {str(k.get("block")): k for k in (struct.get("skeletons") or [])}

    def evidence(s: Dict[str, Any]) -> List[str]:
        """이 씬이 쓰는 사실의 값·표·골격. 없으면 빈 목록이다."""
        fid = (s.get("fact") or "").strip()
        f = facts.get(fid)
        if not f:
            return []
        out = [f"  ★ 이 씬의 사실: [{f['kind']}] {f['label']} = "
               f"{f['value']}{f['unit']}" + (f" ({f['year']}년)" if f.get("year") else "")]
        tid = blk_table.get(str(f.get("block")))
        t = tables.get(tid) if tid else None
        if t:
            out.append("    표: " + " / ".join(t.get("head") or []))
            for row in (t.get("rows") or [])[:4]:
                out.append("        " + " · ".join(row))
        k = skels.get(str(f.get("block")))
        if k:
            out.append(f"    도해 초안 [{k.get('kind')}]: {k.get('aria', '')[:120]}")
        return out

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

    def n_cells(s: Dict[str, Any]) -> int:
        """이 씬을 칸 몇 개로 그릴까. **자막 조각 수가 정한다** — 조각 하나가 컷
        하나이므로 조각이 잦은 씬은 칸이 더 필요하다. 상한은 `cells_per_scroll`."""
        cues = s.get("cues") or []
        return max(1, min(cells_per, len(cues) or 1))

    def line(s: Dict[str, Any]) -> str:
        mot, full = window(s)
        tail = ("  ← 마무리 씬: 남은 시간은 화면이 정지한 채 말이 이어진다"
                if (s.get("role") or "") == "close" else "")
        cues = s.get("cues") or []
        nc = n_cells(s)
        rows = [
            f"- 씬 {s['no']} ({s.get('role') or 'body'}) · 화면에 {full}초 있고 "
            f"**동작은 {mot}초 안에 끝낸다**{tail}",
            f"  자막: 「{s.get('srt_text', '')}」",
        ]
        if cues:
            rows.append("  자막 조각 (조각 하나가 컷 하나다): "
                        + " | ".join(f"{c.get('t')}초 「{c.get('text')}」" for c in cues))
        rows.append(f"  ★ 이 씬은 **칸 {nc}개**짜리 두루마리다. 칸마다 다른 사물, "
                    f"칸마다 다른 채움(낱개·꽉·여백).")
        rows += [
            f"  장면 요지: {s.get('image_brief', '')}",
            f"  원문 근거: {s.get('source', '')}",
        ]
        rows += evidence(s)
        return "\n".join(rows)

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
    overlap: List[str] = []
    for s in scenes:
        no = int(s["no"])
        r = got.get(no)
        if not r:
            missing.append(no)
            continue
        mot, full = window(s)

        # 칸 — 모델이 준 것을 쓰되 수를 코드가 맞춘다. 자막 조각 수가 칸 수를
        # 정하므로 모델이 더 주거나 덜 주면 여기서 자르거나 채운다.
        want = n_cells(s)
        cells = [dict(c) for c in (r.get("cells") or [])][:want]
        while len(cells) < want:
            cells.append({"no": len(cells) + 1,
                          "what": (r.get("stage") or "")[:200] or "앞 칸과 같은 무대",
                          "fill": "여백"})
        for i, cell in enumerate(cells, 1):
            cell["no"] = i
            cell.setdefault("fill", "꽉")

        beats = [dict(b) for b in (r.get("beats") or [])]
        overlap += find_overlap({**r, "no": no, "beats": beats}, mot)

        cam = make_camera(s.get("cues") or [], len(cells), full)

        rows.append({
            "no": no,
            "file": f"{no:03d}.svg",
            "sec": mot,                   # 동작이 끝나야 하는 시각
            "scene_sec": full,            # 화면에 있는 시간
            "role": s.get("role") or "body",
            "claim": r["claim"].strip(),
            "stage": r["stage"].strip(),
            "layout": r["layout"].strip(),
            "change": r["change"].strip(),
            "support": (r.get("support") or "").strip(),
            "palette_note": (r.get("palette_note") or "").strip(),
            # ── 두루마리 ──
            # `canvas_h` 는 칸 수 x 화면 높이다. 아스트라가 이 높이로 viewBox 를
            # 잡고, 카메라가 칸 사이를 끊어 뛴다. 값은 코드가 정한다 — 모델이
            # 정하면 칸 경계가 화면과 안 맞아 그림이 반쪽으로 잘린다.
            "canvas_h": height * len(cells),
            "cells": cells,
            "beats": beats,
            "camera": cam,
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
        "cells_total": sum(len(r.get("cells") or []) for r in rows),
        "cuts_total": sum(len(r.get("camera") or []) for r in rows),
        "file_naming": "파일 앞 세 자리가 씬 번호다. 004.svg → 4번 씬. "
                       "직접 만든 장면을 04_장면/ 에 같은 이름으로 넣어도 된다. "
                       "움직이는 장면은 .svg, 정지 그림은 .png 다.",
        "scenes": rows,
        "cost_usd": round(cost, 4),
        "warnings": ([f"씬 {missing} 의 지시가 오지 않았습니다."] if missing else [])
                    + warn_loopy + overlap
                    + ([f"두루마리가 {len(rows)}장입니다 — 상한 {max_scrolls}장을 "
                        f"넘어 아스트라가 {len(rows) * 2.5:.0f}분 걸립니다. "
                        f"매일 한 편 돌리려면 art.cells_per_scroll 을 올리세요."]
                       if len(rows) > max_scrolls else []),
    }
    atomic_write_json(str(paths.art_spec(slug)), doc_out, indent=2)
    return doc_out


def _load(slug: str) -> Dict[str, Any]:
    p = paths.script_json(slug)
    if not p.exists():
        raise FileNotFoundError("먼저 「대본」 단계를 돌리세요.")
    return json.loads(p.read_text(encoding="utf-8"))
