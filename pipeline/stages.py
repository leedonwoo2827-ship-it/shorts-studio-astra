# -*- coding: utf-8 -*-
"""단계와 묶음 — 좌측 레일이 이것을 그대로 그린다.

★ **표는 여기 한 곳뿐이다.** 화면(static/js/main.js)도 CLI(scripts/make.py)도
  서버(server.py)도 이 표를 읽는다. 표가 두 벌이면 화면과 실제가 갈린다.

★ **묶음(GROUPS)이 이 파일의 요점이다.**

      [ 대본 만들기 ]   재료 · 대본 · 발음 · 음성 · 자막 · 장면지시
      ────────────
      [ 영상 만들기 ]   장면 제작
      ────────────
      [ 전체 빌드  ]    컴포지션 · 빌드
      ── 넘기는 것 ──
                        결과

  묶음 단추는 그 안을 순서대로 돌린다. 그런데 **단계 줄은 여전히 하나씩
  누를 수 있다.** 묶음은 편의고 낱개가 원칙이다 — 대본은 읽고 고쳐야 하고
  장면은 보고 다시 받아야 한다. 전체를 한 단추로 흘려보내면 고칠 순간을 놓친다.

★ `costs` 가 참인 단계만 돈을 쓴다. 화면에 `$` 로 뜬다 — 누르기 전에 보여야 한다.

★ **뒤 단계를 무효로 만드는 규칙**(`invalidates`)을 사람이 기억하게 두면
  낡은 화면으로 빌드하고 나중에 왜 안 맞는지 찾게 된다.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from core import paths


@dataclass(frozen=True)
class Stage:
    key: str
    name: str
    costs: bool = False              # 크레딧을 쓰는가 (화면에 $)
    rule: bool = False               # 이 줄 앞에 금을 긋는다 (「넘기는 것」)
    needs: tuple = ()                # 앞 단계 키
    invalidates: tuple = ()          # 이 단계를 다시 돌리면 낡는 단계


@dataclass(frozen=True)
class Screen:
    """화면 하나. 단계 여러 개를 **탭으로** 담을 수 있다.

    ★ 단계와 화면을 **1:1 로 두지 않는다.** 대본·발음·음성·자막·장면지시는
      전부 「대본을 확정하는 일」이라 한 화면에서 탭으로 오가는 것이 맞다.
      레일에 열 줄이 늘어서 있으면 무엇이 한 덩어리인지 안 보인다.
    """
    key: str
    name: str
    stages: tuple                    # 이 화면이 탭으로 담는 단계
    hint: str = ""


@dataclass(frozen=True)
class Group:
    key: str
    label: str                       # 단추에 적히는 말
    stages: tuple                    # 이 묶음이 순서대로 돌리는 단계
    screens: tuple = ()              # 레일에 이 묶음 아래로 뜨는 화면
    primary: bool = False            # 진한 단추(하나만) / 나머지는 하얀 단추
    hint: str = ""


STAGES: List[Stage] = [
    Stage("source",  "재료",      needs=(),
          invalidates=("script", "speech", "tts", "subs", "artspec",
                       "art", "compose", "build")),
    Stage("script",  "대본",      costs=True, needs=("source",),
          invalidates=("speech", "tts", "subs", "artspec", "art",
                       "compose", "build")),
    Stage("speech",  "발음",      needs=("script",),
          invalidates=("tts", "subs", "compose", "build")),
    Stage("tts",     "음성",      needs=("speech",),
          invalidates=("subs", "compose", "build")),
    Stage("subs",    "자막",      needs=("tts",),
          invalidates=("compose", "build")),
    Stage("artspec", "장면 지시", costs=True, needs=("script",),
          invalidates=("art", "compose", "build")),

    Stage("art",     "장면 제작", costs=True, needs=("artspec",),
          invalidates=("compose", "build")),

    Stage("compose", "컴포지션",  needs=("subs", "art"),
          invalidates=("build",)),
    Stage("build",   "빌드",      needs=("compose",)),

    Stage("result",  "결과",      costs=True, rule=True, needs=("build",)),
]

BY_KEY: Dict[str, Stage] = {s.key: s for s in STAGES}

GROUPS: List[Group] = [
    Group("plan", "대본 만들기", primary=True,
          stages=("source", "script", "speech", "tts", "subs", "artspec"),
          screens=("source", "script"),
          hint="원문에서 대본·음성·자막·장면 지시까지. 대본과 장면 지시가 크레딧을 씁니다."),
    Group("video", "영상 만들기",
          stages=("art",),
          screens=("art",),
          hint="아스트라가 씬마다 움직이는 장면을 코드로 짭니다. 가장 비싼 자리입니다."),
    Group("build", "전체 빌드",
          stages=("compose", "build"),
          screens=("compose", "build"),
          hint="타이밍을 계산해 굽습니다. 크레딧을 쓰지 않습니다."),
]

BY_GROUP: Dict[str, Group] = {g.key: g for g in GROUPS}

# ★ 레일에 뜨는 줄은 **단계가 아니라 화면**이다. 단계 열 개를 여섯 줄로 줄인다.
#   「대본」 화면 하나가 탭 다섯 개(대본·발음·음성·자막·장면지시)를 담는다 —
#   그 다섯은 전부 「대본을 확정하는 일」이고, 오가며 고치는 것이 실제 작업이다.
SCREENS: List[Screen] = [
    Screen("source", "재료", ("source",),
           "장(章) 파일을 넣고 추출본을 손봅니다."),
    Screen("script", "대본", ("script", "speech", "tts", "subs", "artspec"),
           "대본을 확정하는 일 전부 — 문구·발음·음성·자막·장면 지시."),
    Screen("art", "장면 제작", ("art",),
           "아스트라가 움직이는 장면을 코드로 씁니다."),
    Screen("compose", "미리보기", ("compose",),
           "굽기 전에 그대로 재생해 보고 승인합니다."),
    Screen("build", "빌드", ("build",),
           "1080x1920 mp4 로 굽습니다."),
    Screen("result", "결과", ("result",),
           "유튜브에 올릴 글."),
]

BY_SCREEN: Dict[str, Screen] = {sc.key: sc for sc in SCREENS}
SCREEN_OF: Dict[str, str] = {k: sc.key for sc in SCREENS for k in sc.stages}

# CLI 의 `make.py all` 만 쓰는 전체 순서. 화면에는 이 단추가 없다 —
# 스크립트로 밤에 돌릴 때를 위한 것이다.
ALL_ORDER: tuple = tuple(k for g in GROUPS for k in g.stages)

# 예전 이름으로 부르던 자리를 위해 남겨 둔다(컴포지션+빌드).
VIDEO_ORDER: tuple = BY_GROUP["build"].stages


def _script(slug: str) -> Dict[str, Any]:
    p = paths.script_json(slug)
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


def state(slug: str) -> Dict[str, str]:
    """단계마다 `done` · `part` · `""`. **파일을 보고 판단한다** — 별도 상태
    파일을 두지 않는다. 상태 파일과 실제가 갈리면 실제가 옳고 파일은 거짓말이다.
    """
    from pipeline import s6_art

    doc = _script(slug)
    scenes = doc.get("scenes") or []
    n = len(scenes)
    out: Dict[str, str] = {s.key: "" for s in STAGES}

    if paths.source_md(slug).exists():
        out["source"] = "done"
    if n:
        out["script"] = "done"

    if n:
        got = sum(1 for s in scenes if (s.get("narration_text") or "").strip())
        out["speech"] = "done" if got == n else ("part" if got else "")

        got = sum(1 for s in scenes if float(s.get("audio_sec") or 0) > 0
                  and paths.wav(slug, int(s.get("no") or 0)).exists())
        out["tts"] = "done" if got == n else ("part" if got else "")

        got = sum(1 for s in scenes if s.get("cues"))
        out["subs"] = "done" if got == n else ("part" if got else "")

    sp = paths.art_spec(slug)
    if sp.exists():
        try:
            rows = json.loads(sp.read_text(encoding="utf-8")).get("scenes") or []
        except Exception:  # noqa: BLE001
            rows = []
        out["artspec"] = "done" if (n and len(rows) == n) else ("part" if rows else "")

    have = s6_art.present(slug)
    if n:
        out["art"] = "done" if len(have) >= n else ("part" if have else "")

    if (paths.comp_dir(slug) / "index.html").exists():
        out["compose"] = "done"
    b = paths.latest_build(slug)
    if b:
        out["build"] = "done"
        if (b / "유튜브.txt").exists():
            out["result"] = "done"
    return out


def stale(slug: str) -> List[str]:
    """산출물이 **입력보다 오래된** 단계. 화면이 「다시 돌려야 한다」고 말해 준다."""
    def mtime(p: Path) -> float:
        return p.stat().st_mtime if p.exists() else 0.0

    sj = mtime(paths.script_json(slug))
    out: List[str] = []
    comp = mtime(paths.comp_dir(slug) / "index.html")
    if comp and sj > comp + 1:
        out.append("compose")
    b = paths.latest_build(slug)
    bt = mtime(b / "정보.json") if b else 0.0
    if bt and comp > bt + 1:
        out.append("build")
    sp = mtime(paths.art_spec(slug))
    if sp and sj > sp + 1:
        out.append("artspec")
    return out


def as_json(slug: Optional[str] = None) -> Dict[str, Any]:
    """화면이 받는 모양 — 묶음과 단계를 함께 준다."""
    st = state(slug) if slug else {}
    sl = set(stale(slug)) if slug else set()
    stage_rows = [{"key": s.key, "name": s.name, "costs": s.costs, "rule": s.rule,
                   "needs": list(s.needs), "state": st.get(s.key, ""),
                   "stale": s.key in sl}
                  for s in STAGES]
    group_rows = [{"key": g.key, "label": g.label, "primary": g.primary,
                   "stages": list(g.stages), "screens": list(g.screens),
                   "hint": g.hint,
                   "costs": any(BY_KEY[k].costs for k in g.stages)}
                  for g in GROUPS]

    def roll(keys) -> str:
        """화면 하나의 상태 — 담긴 단계를 합쳐 본다.
        하나라도 안 됐으면 `part`, 전부 됐으면 `done`, 전부 안 됐으면 빈 값."""
        vals = [st.get(k, "") for k in keys]
        if vals and all(v == "done" for v in vals):
            return "done"
        return "part" if any(vals) else ""

    screen_rows = [{"key": sc.key, "name": sc.name, "stages": list(sc.stages),
                    "hint": sc.hint,
                    "costs": any(BY_KEY[k].costs for k in sc.stages),
                    "state": roll(sc.stages),
                    "stale": any(k in sl for k in sc.stages)}
                   for sc in SCREENS]
    return {"groups": group_rows, "stages": stage_rows, "screens": screen_rows}
