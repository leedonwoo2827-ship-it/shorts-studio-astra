# -*- coding: utf-8 -*-
"""S1 대본 — 장(章) 원문에서 30초 쇼츠 대본을 짠다. **모델을 부른다(돈).**

들어오는 것: `00_기획/source.md` (S0 이 만든 결정론 추출본. 사람이 고칠 수 있다)
나가는 것:   `01_대본/script.json`

한 번만 부른다. 씬마다 부르면 호출당 최소 비용이 씬 수만큼 곱해진다.

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
from .schemas import SCRIPT_SCHEMA

SYSTEM = (
    "너는 교양 단행본을 세로 쇼츠로 옮기는 대본가다. "
    "원문에 없는 사실을 지어내지 않는다. "
    "글자 수 예산을 절대 넘기지 않는다. "
    "반드시 제시된 JSON 스키마대로만 답한다."
)

# 원문이 길면 앞뒤로 잘라 보낸다 — 장 하나는 보통 이 안에 든다.
MAX_SOURCE_CHARS = 24000


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


def _budget_report(scenes: List[Dict[str, Any]], cuts: int) -> Tuple[int, int, float]:
    total = sum(len(s.get("srt_text") or "") for s in scenes)
    budget = config.budget_chars(cuts)
    cps = config.get("narration.chars_per_sec", 6.51) * config.get("narration.speed", 1.2)
    return total, budget, total / cps if cps else 0.0


# 근거를 여러 조각 이어 붙일 때 쓰는 구분자. 모델이 무엇을 쓸지 정해 줄 수는
# 없으니(프롬프트로 시켜도 `(…)` 로 잇는다) 실제로 쓰는 것을 다 받는다.
_FRAG_SPLIT = re.compile(r"\s*(?:/|\(\s*(?:…|\.\.\.)\s*\)|…|\.\.\.|\[\s*…\s*\])\s*")

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
    flat = re.sub(r"\s+", "", md)
    bad: List[int] = []
    for s in scenes:
        raw = (s.get("source") or "").strip()
        frags = [f.strip() for f in _FRAG_SPLIT.split(raw)]
        checkable = [re.sub(r"\s+", "", f) for f in frags if len(f) >= 12]
        if not checkable:
            continue
        if any(f in flat for f in checkable):
            continue
        tight = re.sub(r"\s+", "", raw)
        if any(tight[i:i + _WINDOW] in flat
               for i in range(0, max(1, len(tight) - _WINDOW + 1))):
            continue
        bad.append(int(s.get("no") or 0))
    return bad


def _trim_source(md: str) -> str:
    if len(md) <= MAX_SOURCE_CHARS:
        return md
    half = MAX_SOURCE_CHARS // 2
    return md[:half] + "\n\n…(중략)…\n\n" + md[-half:]


def run(slug: str, *, cuts: Optional[int] = None,
        on_activity: Optional[Callable[[str], None]] = None) -> Dict[str, Any]:
    """`01_대본/script.json` 을 만들고 그 내용을 돌려준다."""
    md_path = paths.source_md(slug)
    if not md_path.exists():
        raise FileNotFoundError("먼저 「재료」 단계를 돌려 source.md 를 만드세요.")
    md = _trim_source(md_path.read_text(encoding="utf-8"))

    cuts = int(cuts or config.get("shorts.cuts", 3))
    seconds = float(config.get("shorts.seconds", 30.0))
    budget = config.budget_chars(cuts)

    user = prompts.render(
        "script",
        budget_chars=budget, cps=config.get("narration.chars_per_sec", 6.51),
        speed=config.get("narration.speed", 1.2), seconds=seconds, cuts=cuts,
    ) + "\n\n---\n\n# 원문\n\n" + md

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
              f"씬 수({cuts})와 뜻은 그대로 두고 **문장만 줄여** 다시 주세요."
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

    if len(scenes) != cuts:
        warnings.append(f"씬을 {cuts}개로 요청했는데 {len(scenes)}개가 왔습니다.")

    # 원문에 없는 근거를 적었는지 — 무료 검산. 막지 않고 알려만 준다.
    unverified = verify_sources(scenes, md)
    if unverified:
        warnings.append(f"씬 {unverified} 의 근거 구절을 원문에서 찾지 못했습니다. "
                        f"지어낸 사실일 수 있습니다 — 그 씬을 확인하세요.")

    for i, s in enumerate(scenes, 1):
        s["no"] = i                                   # 번호는 코드가 정한다
        s["srt_text"] = re.sub(r"\s+", " ", (s.get("srt_text") or "")).strip()

    doc: Dict[str, Any] = {
        "schema_version": 1,
        "slug": slug,
        "title": (out.get("title") or "").strip(),
        "hashtags": _clean_hashtags(out.get("hashtags") or []),
        "cuts": len(scenes),
        "seconds": seconds,
        "voice": config.get("narration.voice", "F2"),
        "speed": config.get("narration.speed", 1.2),
        "scenes": scenes,
        "budget": {"chars": total, "limit": budget, "est_sec": round(est, 1)},
        "cost_usd": round(cost, 4),
        "warnings": warnings,
    }
    atomic_write_json(str(paths.script_json(slug)), doc, indent=2)
    return doc
