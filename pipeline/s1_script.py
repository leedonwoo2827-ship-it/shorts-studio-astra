# -*- coding: utf-8 -*-
"""S1 대본 — 갈아 놓은 재료에서 세로 쇼츠 대본을 짠다. **모델을 부른다(돈).**

들어오는 것: `00_기획/구조.json`  (원고 → 파서가 뽑은 절 목록과 사실 표)
             `00_기획/source.md`  (원문 — 근거 검산에만 쓴다)
나가는 것:   `01_대본/script.json`

한 번만 부른다. 씬마다 부르면 호출당 최소 비용이 씬 수만큼 곱해진다.

★ **원문 덩어리를 넣지 않는다.** 예전에는 `source.md` 를 24,000자로 잘라 넣었고,
  그러면 대본이 **첫 단락만 잡고 뒷장을 버렸다**(실측 2026-09-08: 18쪽 중 1쪽).
  이제 `구조.json` 의 절 목록과 사실 표를 넣는다 — 원문의 몇십 분의 일이라
  절단이 없고, 사실마다 근거 구절이 붙어 있어 지어낼 필요가 없다.

★ **씬 수를 강제하지 않는다.** 예전에는 `cuts` 를 사람이 넣어 프롬프트에
  「씬 수는 4개다」로 박았다. 그러면 원문이 18쪽이든 2쪽이든 대본이 4로 맞춰
  나온다 — v01~v13 이 갈피를 못 잡은 원인 중 하나가 이것이었다. 이제 상한
  (`cuts_max`)과 글자 예산만 주고, 몇 걸음이 필요한지는 재료가 정한다.

★ **글자 예산이 이 단계의 전부다.** 30초는 음성으로 199자 안팎이고, 모델은 늘
  넘긴다. 그래서 두 번 막는다 — 프롬프트에 예산을 박고(`{budget_chars}`),
  받은 뒤에 다시 재서 넘으면 한 번 더 부른다(`_retry_over_budget`).
  그래도 넘으면 **자르지 않고 경고만 남긴다.** 말을 잘라 붙이면 문장이 깨지고,
  깨진 문장은 TTS 에서 더 이상하게 들린다. 사람이 고칠 자리다.
"""
from __future__ import annotations

import re
from typing import Any, Callable, Dict, List, Optional, Tuple

from core import config
from core.atomic_io import atomic_write_json
from core import paths
from llm import structured
from . import prompts
from . import s0c_structure
from .schemas import SCRIPT_SCHEMA

SYSTEM = (
    "너는 교양 단행본을 세로 쇼츠로 옮기는 대본가다. "
    "원문에 없는 사실을 지어내지 않는다. "
    "글자 수 예산을 절대 넘기지 않는다. "
    "반드시 제시된 JSON 스키마대로만 답한다."
)

# 재료 요약 상한. 절 제목과 사실 표는 원문의 몇십 분의 일이라 이 안에 다 든다.
MAX_DIGEST_CHARS = 6000


def _clean_hashtags(tags: List[str]) -> List[str]:
    """공백·중복·빈 것을 걷어낸다. 스키마는 `#` 로 시작하는지까지만 본다."""
    out, seen = [], set()
    for t in tags or []:
        t = "#" + re.sub(r"\s+", "", str(t).lstrip("#"))
        if len(t) < 2 or t in seen:
            continue
        seen.add(t)
        out.append(t)
    return out[:5]


def _budget_report(scenes: List[Dict[str, Any]],
                   cuts: Optional[int] = None) -> Tuple[int, int, float]:
    total = sum(len(s.get("srt_text") or "") for s in scenes)
    budget = config.budget_chars(cuts)
    cps = config.get("narration.chars_per_sec", 6.51) * config.get("narration.speed", 1.2)
    return total, budget, total / cps if cps else 0.0


# 근거를 여러 조각 이어 붙일 때 쓰는 구분자. 모델이 무엇을 쓸지 정해 줄 수는
# 없으니(프롬프트로 시켜도 `(…)` 로 잇는다) 실제로 쓰는 것을 다 받는다.
_FRAG_SPLIT = re.compile(r"\s*(?:/|\(\s*(?:…|\.\.\.)\s*\)|…|\.\.\.|\[\s*…\s*\])\s*")

# ★ 비교 전에 **문장부호를 맞춘다.** 실측(2026-09-08): 모델이 원문의 굽은
#   따옴표(‘’“”)를 곧은 것으로 정규화해 보냈고, 근거 55개 중 8개가
#   「원문에 없다」는 오탐으로 떴다. 사실은 원문 그대로였다 — 검산이 문장부호를
#   안 맞춰 놓고 없다고 한 것이다.
_PUNCT = {
    "‘": "'", "’": "'", "“": '"', "”": '"',
    "–": "-", "—": "-", "―": "-", "−": "-",
    "…": "...", "·": "", "・": "",
}


def tighten(s: str) -> str:
    """공백을 지우고 문장부호를 맞춘 꼴. 인용 대조는 이 꼴로만 한다."""
    for a, b in _PUNCT.items():
        s = s.replace(a, b)
    return re.sub(r"\s+", "", s)


# 조각이 하나도 안 맞을 때 마지막으로 보는 창 길이. 20자면 우연히 겹치지 않는다.
_WINDOW = 20


def verify_sources(scenes: List[Dict[str, Any]], md: str) -> List[int]:
    """`source` 에 적힌 구절이 **원문에 그대로 있는지** 본다. 무료 검산이다.

    ★ 이 검산이 「지어낸 사실」을 잡는 가장 싼 그물이다. 모델이 내용을 바꿔 놓고도
      근거처럼 적어 두면 화면에 나가기 전까지 아무도 모른다.

    비교 전에 **공백을 다 지운다.** 조판 PDF 는 줄바꿈이 낱말 가운데를 지나가서,
    추출본과 인용의 띄어쓰기가 서로 다르다.

    두 단계로 본다.
      1. 구분자로 쪼갠 조각 중 **하나라도** 원문에 있으면 통과.
      2. 하나도 없으면 20자 창을 굴려 본다 — 모델이 예상 못 한 방식으로 이어
         붙였을 때 살려 주는 그물이다. 실제로 `(…)` 로 잇는 일이 있었다.

    돌려주는 것은 **의심스러운 씬 번호**다. 막지 않는다 — 원문을 사람이 고쳤을
    수도 있고, 그때는 이 경고가 틀린다. 판단은 사람이 한다.
    """
    flat = tighten(md)
    bad: List[int] = []
    for s in scenes:
        raw = (s.get("source") or "").strip()
        frags = [f.strip() for f in _FRAG_SPLIT.split(raw)]
        checkable = [tighten(f) for f in frags if len(f) >= 12]
        if not checkable:
            continue
        if any(f in flat for f in checkable):
            continue
        tight = tighten(raw)
        if any(tight[i:i + _WINDOW] in flat
               for i in range(0, max(1, len(tight) - _WINDOW + 1))):
            continue
        bad.append(int(s.get("no") or 0))
    return bad


def _fact_ids(struct: Dict[str, Any]) -> set:
    return {str(f.get("id")) for f in (struct.get("facts") or [])}


def run(slug: str, *, cuts: Optional[int] = None, fmt: Optional[str] = None,
        on_activity: Optional[Callable[[str], None]] = None) -> Dict[str, Any]:
    """`01_대본/script.json` 을 만들고 그 내용을 돌려준다.

    `cuts` 는 **시험용 강제**다. 평소에는 주지 않는다 — 주면 옛 문제가 돌아온다.
    """
    st_path = paths.structure_json(slug)
    if not st_path.exists():
        raise FileNotFoundError("먼저 「구조」 단계를 돌려 구조.json 을 만드세요.")
    import json as _json
    struct = _json.loads(st_path.read_text(encoding="utf-8"))
    digest = s0c_structure.digest(struct, limit=MAX_DIGEST_CHARS)

    # 근거 검산에만 쓴다. 프롬프트에는 넣지 않는다.
    md_path = paths.source_md(slug)
    md = md_path.read_text(encoding="utf-8") if md_path.exists() else ""

    fmt = (fmt or config.get("shorts.format", "narrative")).strip() or "narrative"
    lo, hi = config.seconds_range()
    cuts_max = int(config.get("shorts.cuts_max", 8))
    budget = config.budget_chars(cuts)     # cuts 가 없으면 상한으로 숨을 뺀다

    tmpl = "script_listicle" if fmt == "listicle" else "script"
    user = prompts.render(
        tmpl,
        budget_chars=budget, cps=config.get("narration.chars_per_sec", 6.51),
        speed=config.get("narration.speed", 1.2),
        seconds_min=lo, seconds_max=hi, cuts_max=cuts_max,
    ) + "\n\n---\n\n# 재료\n\n" + digest

    if cuts:
        # 시험용 강제. 평소 경로에는 이 문장이 붙지 않는다.
        user += f"\n\n---\n\n# 강제\n씬 수를 정확히 **{cuts}개**로 맞춰 주세요."

    out, cost = structured("script", SYSTEM, user, SCRIPT_SCHEMA, on_activity=on_activity)
    scenes = list(out.get("scenes") or [])

    total, budget, est = _budget_report(scenes, cuts)
    warnings: List[str] = []
    if total > budget:
        # 한 번만 더 준다. 두 번째도 넘으면 사람이 고치는 게 빠르다.
        over = total - budget
        retry_user = (
            user
            + f"\n\n---\n\n# 다시\n앞선 답이 예산을 **{over}자** 넘겼습니다"
              f"(합계 {total}자 / 예산 {budget}자).\n"
              f"씬 수({len(scenes)})와 뜻은 그대로 두고 **문장만 줄여** 다시 주세요."
        )
        out2, cost2 = structured("script", SYSTEM, retry_user, SCRIPT_SCHEMA,
                                 on_activity=on_activity)
        cost += cost2
        scenes2 = list(out2.get("scenes") or [])
        total2, _, est2 = _budget_report(scenes2, cuts)
        if scenes2 and total2 < total:
            out, scenes, total, est = out2, scenes2, total2, est2
        if total > budget:
            warnings.append(f"대본이 예산을 {total - budget}자 넘습니다"
                            f"(합계 {total}자 · 추정 {est:.1f}초). 자막 화면에서 줄이세요.")

    if cuts and len(scenes) != cuts:
        warnings.append(f"씬을 {cuts}개로 강제했는데 {len(scenes)}개가 왔습니다.")
    if len(scenes) > cuts_max:
        warnings.append(f"씬이 상한({cuts_max})을 넘어 {len(scenes)}개입니다. "
                        f"그림 값이 그만큼 늘어납니다.")

    # 근거를 어디서 가져왔는지 — 무료 검산. 막지 않고 알려만 준다.
    #
    # ★ **두 갈래로 가른다.** 대본은 원문을 직접 못 본다 — 구조.json 만 본다.
    #   그래서 근거가 원문에 없는 경우가 두 가지고, 뜻이 전혀 다르다.
    #     ① 구조.json 에도 없다  → **지어냈다.** 이게 잡아야 하는 것이다.
    #     ② 구조.json 에는 있다  → 원고 본문을 옮겼다. 한 다리 건넜을 뿐
    #        추적은 된다. 실측(2026-09-08)으로 이쪽이 훨씬 흔하다.
    #   예전에는 둘을 묶어 「지어낸 사실일 수 있습니다」로 겁을 줬다.
    if md:
        unverified = verify_sources(scenes, md)
        if unverified:
            # 구조.json 의 본문·근거를 다 이어 붙여 한 번 더 대조한다.
            pool = tighten(" ".join(
                [str(b.get("text") or "") for b in (struct.get("blocks") or [])]
                + [str(b.get("quote") or "") for b in (struct.get("blocks") or [])]
                + [str(f.get("quote") or "") for f in (struct.get("facts") or [])]))
            made_up, secondhand = [], []
            for no in unverified:
                sc = next((x for x in scenes if int(x.get("no") or 0) == no), {})
                t = tighten(str(sc.get("source") or ""))
                hit = any(t[i:i + _WINDOW] in pool
                          for i in range(0, max(1, len(t) - _WINDOW + 1)))
                (secondhand if hit else made_up).append(no)
            if made_up:
                warnings.append(f"씬 {made_up} 의 근거를 원문에서도 구조에서도 "
                                f"찾지 못했습니다 — **지어낸 사실일 수 있습니다.** "
                                f"그 씬을 확인하세요.")
            if secondhand:
                warnings.append(f"씬 {secondhand} 의 근거는 원고 본문을 옮긴 것입니다"
                                f"(원문 그대로는 아님). 사실 표의 「근거」 칸을 쓰면 "
                                f"원문까지 추적됩니다.")

    # 사실 참조가 실제로 있는 id 인지. 없는 id 를 적으면 장면 지시가 근거를 못 받는다.
    known = _fact_ids(struct)
    ghost = sorted({(s.get("fact") or "") for s in scenes} - known - {""})
    if ghost:
        warnings.append(f"구조.json 에 없는 사실 id 를 적었습니다: {', '.join(ghost[:6])}")
    if fmt == "listicle":
        noref = [int(s.get("no") or 0) for s in scenes
                 if s.get("role") == "item" and not (s.get("fact") or "").strip()]
        if noref:
            warnings.append(f"항목 {noref} 에 fact 가 없습니다. 목록형은 항목마다 "
                            f"사실 하나가 규칙입니다 — 그림이 장소만 그리게 됩니다.")
        if not (out.get("hook_fixed") or {}).get("line1"):
            warnings.append("고정 후크(hook_fixed)가 없습니다. 목록형은 후크가 "
                            "영상 내내 상단에 박혀 있어야 합니다.")

    for i, s in enumerate(scenes, 1):
        s["no"] = i                                   # 번호는 코드가 정한다
        s["srt_text"] = re.sub(r"\s+", " ", (s.get("srt_text") or "")).strip()

    hook_fixed = out.get("hook_fixed") or {}
    mark = (hook_fixed.get("mark") or "").strip()
    line2 = (hook_fixed.get("line2") or "")
    if mark and mark not in line2:
        # `mark` 는 `line2` 안에 그대로 있어야 강조를 씌울 수 있다. 없으면 버린다 —
        # 없는 낱말을 찾다 실패하면 줄 전체가 강조로 떨어지는 편이 낫다.
        warnings.append(f"강조 낱말 「{mark}」이 후크 둘째 줄에 없어 줄 전체를 강조합니다.")
        hook_fixed["mark"] = ""

    doc: Dict[str, Any] = {
        "schema_version": 1,
        "slug": slug,
        "title": (out.get("title") or "").strip(),
        "hashtags": _clean_hashtags(out.get("hashtags") or []),
        "format": fmt,
        "hook_fixed": hook_fixed,
        "cuts": len(scenes),
        "seconds": hi,
        "seconds_min": lo,
        "seconds_max": hi,
        "voice": config.get("narration.voice", "F2"),
        "speed": config.get("narration.speed", 1.2),
        "scenes": scenes,
        "budget": {"chars": total, "limit": budget, "est_sec": round(est, 1)},
        "cost_usd": round(cost, 4),
        "warnings": warnings,
    }
    atomic_write_json(str(paths.script_json(slug)), doc, indent=2)
    return doc
