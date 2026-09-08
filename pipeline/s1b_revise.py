# -*- coding: utf-8 -*-
"""S1b 대본 다듬기 — 검증 · 후크 다시 · 자막 다시. **모델을 부른다(돈).**

대본을 한 번 뽑고 끝내지 않는다. 쇼츠공방 I 이 172편을 내며 얻은 결론은
**단계를 겹쳐야 안정된다**는 것이었다(그쪽 `knowledges/README.md` 의 5단계 방어망).

    1  독립 완결 문장   씬 간 의존을 없앤다      → 고쳐도 수렴한다
    2  그라운딩         씬마다 [근거] 동봉       → 지어내지 않는다
    3  전체 사실검증    대본 직후 한 번          → 왜곡을 1차로 잡는다
    4  씬별 검토        사람이 의심 씬만 다시    → 잔여 오류
    5  대안 분리        AI 는 원문 불변·대안만   → 손수정이 안 지워진다

1·2 는 `llm/prompts/script.md` 와 `core/persona.py` 가 맡고, **3·4·5 가 이 모듈**이다.

★ **검증은 고치지 않는다.** 여기서 자막을 직접 갈아 끼우면 사람이 손으로 다듬어
  놓은 것까지 덮어쓴다. 쇼츠공방 I 이 전체 재작성(`tidy_all`)을 만들어 놓고 화면에서
  뺀 이유가 그것이다 — 수렴은 빠른데 손수정이 사라진다. 이 모듈의 `verify` 는
  대안(`alts`)만 돌려주고, 적용은 화면에서 사람이 누른다.

★ **씬마다 부르지 않는다.** 호출당 최소 비용이 붙어서 스물두 씬이면 스물두 배가
  된다. 씬별 검토도 같은 함수에 씬 하나만 담아 부르는 것이다.
"""
from __future__ import annotations

import json
from typing import Any, Callable, Dict, Iterable, List, Optional

from core import config, paths, persona
from core.atomic_io import atomic_write_json
from llm import structured
from . import prompts
from .schemas import CAPTIONS_SCHEMA, HOOKS_SCHEMA, VERIFY_SCHEMA

SYSTEM_VERIFY = (
    "너는 교양 콘텐츠 사실 검증 편집자다. "
    "근거에 없는 사실을 새로 만들지 않는다. "
    "자막을 직접 고치지 않고 판단과 대안만 낸다. "
    "반드시 제시된 JSON 스키마대로만 답한다."
)
SYSTEM_WRITE = (
    "너는 교양 단행본을 세로 쇼츠로 옮기는 대본가다. "
    "근거에 없는 사실을 지어내지 않는다. "
    "반드시 제시된 JSON 스키마대로만 답한다."
)

# 근거 인용 길이. 쇼츠공방 I 실측값(220자)을 잇는다 — 사실 판단에는 충분하고
# 씬이 스물이 넘어도 토큰이 터지지 않는다.
SOURCE_CUT = 220


def _load(slug: str) -> Dict[str, Any]:
    p = paths.script_json(slug)
    if not p.exists():
        raise FileNotFoundError("먼저 「대본」 단계를 돌리세요.")
    return json.loads(p.read_text(encoding="utf-8"))


def _save(slug: str, doc: Dict[str, Any]) -> None:
    atomic_write_json(str(paths.script_json(slug)), doc, indent=2)


def _pick(scenes: List[Dict[str, Any]],
          only: Optional[Iterable[int]]) -> List[Dict[str, Any]]:
    """`only` 가 있으면 그 씬만. 씬별 검토가 이 길로 온다."""
    if not only:
        return list(scenes)
    want = {int(n) for n in only}
    return [s for s in scenes if int(s.get("no") or 0) in want]


def _tone(slug: str) -> str:
    from .s1_script import read_persona
    return persona.tone_block(*read_persona(slug))


def _items(scenes: List[Dict[str, Any]], *, with_caption: bool = True) -> str:
    """씬 하나 = 한 덩어리. **[근거] 를 자막 옆에 나란히 둔다** — 이것이 그라운딩이다.

    근거 없이 자막만 주면 모델은 그 문장의 *문체*만 보고 그럴듯하게 부풀린다.
    참고할 사실의 출처가 프롬프트 안에 없으니 자기 사전지식으로 메우고, 그것이 환각이다.
    """
    out: List[str] = []
    for s in scenes:
        no = int(s.get("no") or 0)
        src = (s.get("source") or "").strip()[:SOURCE_CUT]
        block = [f"[씬{no}]",
                 f"[근거] {src or '(근거가 비었다 — 이 씬은 특히 의심하라)'}"]
        if with_caption:
            block.append(f"[자막] {(s.get('srt_text') or '').strip()}")
        out.append("\n".join(block))
    return "\n\n".join(out)


# ── 3·4·5단계 · 사실검증 ────────────────────────────────────────────────
def verify(slug: str, *, only: Optional[Iterable[int]] = None,
           on_activity: Optional[Callable[[str], None]] = None) -> Dict[str, Any]:
    """자막이 근거를 왜곡하는지 본다. **고치지 않고** 판단과 대안만 돌려준다.

    `only` 에 씬 번호를 주면 그 씬만 — 화면의 씬별 「검토」 단추가 이 길이다.
    결과는 `script.json` 의 `verify` 에 남겨 화면을 새로 그려도 남아 있게 한다.
    """
    doc = _load(slug)
    scenes = _pick(doc.get("scenes") or [], only)
    if not scenes:
        return {"results": {}, "ng": [], "cost_usd": 0.0}

    user = prompts.render("verify", indep=persona.INDEP, tone_block=_tone(slug),
                          items=_items(scenes))
    out, cost = structured("verify", SYSTEM_VERIFY, user, VERIFY_SCHEMA,
                           on_activity=on_activity)

    results: Dict[str, Any] = {}
    for r in out.get("results") or []:
        results[str(int(r.get("no") or 0))] = {
            "ok": bool(r.get("ok")),
            "reason": (r.get("reason") or "").strip(),
            "alts": [str(a).strip() for a in (r.get("alts") or []) if str(a).strip()],
        }

    # 부분 검토는 그 씬만 덮어쓴다 — 나머지 씬의 지난 판정은 살려 둔다.
    keep = dict(doc.get("verify") or {}) if only else {}
    keep.update(results)
    doc["verify"] = keep
    doc["verify_cost_usd"] = round(float(doc.get("verify_cost_usd") or 0) + cost, 4)
    _save(slug, doc)
    return {"results": results,
            "ng": [k for k, v in results.items() if not v["ok"]],
            "cost_usd": cost}


def apply_alt(slug: str, no: int, text: str) -> Dict[str, Any]:
    """사람이 고른 대안을 그 씬에 적용한다. **5단계의 마지막 관문이 여기다.**

    적용하면 그 씬의 판정을 지운다 — 낡은 빨간 딱지가 남아 있으면 고친 것을
    또 고치게 된다. 규칙이 만든 발음도 같이 버린다.
    """
    doc = _load(slug)
    text = (text or "").strip()
    if not text:
        raise ValueError("빈 문장은 적용하지 않습니다.")
    hit = False
    for s in doc.get("scenes") or []:
        if int(s.get("no") or 0) == int(no):
            s["srt_text"] = text
            if s.get("narration_from") != "손":
                s.pop("narration_text", None)
            hit = True
    if not hit:
        raise ValueError(f"씬 {no} 가 없습니다.")
    v = dict(doc.get("verify") or {})
    v.pop(str(int(no)), None)
    doc["verify"] = v
    _save(slug, doc)
    return {"no": int(no), "srt_text": text}


# ── AI 후크 다시 ────────────────────────────────────────────────────────
def regen_hooks(slug: str,
                on_activity: Optional[Callable[[str], None]] = None) -> Dict[str, Any]:
    """영상 내내 고정인 상단 후크를 다른 각도로 다시 뽑는다.

    ★ 후크는 **씬마다 갈리지 않는다.** 보다 들어온 사람이 무슨 영상인지 알아야
      한다. 그래서 `hook_fixed` 하나를 바꾸고 씬별 후크도 같은 값으로 맞춘다 —
      두 자리가 어긋나면 서사형에서 화면 위 띠가 씬마다 튄다.
    """
    doc = _load(slug)
    scenes = doc.get("scenes") or []
    cur = doc.get("hook_fixed") or {}
    current = f"{cur.get('line1') or '(없음)'} / {cur.get('line2') or '(없음)'}"

    user = prompts.render("hooks_regen", tone_block=_tone(slug), current=current,
                          items=_items(scenes, with_caption=False))
    out, cost = structured("script", SYSTEM_WRITE, user, HOOKS_SCHEMA,
                           on_activity=on_activity)

    line1 = (out.get("line1") or "").strip()
    line2 = (out.get("line2") or "").strip()
    doc["hook_fixed"] = {"line1": line1, "line2": line2,
                         "mark": (out.get("mark") or "").strip()}
    for s in scenes:
        s["hook_line1"], s["hook_line2"] = line1, line2
    doc["hook_cost_usd"] = round(float(doc.get("hook_cost_usd") or 0) + cost, 4)
    _save(slug, doc)
    return {"hook_fixed": doc["hook_fixed"], "cost_usd": cost}


# ── AI 자막 다시 ────────────────────────────────────────────────────────
def regen_captions(slug: str, *, only: Optional[Iterable[int]] = None,
                   on_activity: Optional[Callable[[str], None]] = None
                   ) -> Dict[str, Any]:
    """씬별 자막(= 음성이 읽는 글)을 무드에 맞춰 다시 쓴다.

    ★ **한 번에 전부** 다시 쓴다. 씬 하나씩 고치면 국소 최적화가 전체를 망치고,
      한 씬을 고칠 때마다 이웃이 어색해져 끝나지 않는다(두더지잡기).
      독립 완결 문장 규칙과 짝이 되어야 이것이 수렴한다.

    ★ 자막이 바뀌면 **그 씬 음성이 낡는다.** 여기서는 표시만 남기고 다시 굽는 것은
      「음성」 단계가 한다 — 화면이 기억하게 두면 고쳐 놓고 굽는 것을 잊는다.
    """
    doc = _load(slug)
    all_scenes = doc.get("scenes") or []
    scenes = _pick(all_scenes, only)
    if not scenes:
        return {"captions": {}, "touched": [], "cost_usd": 0.0}
    last_no = int(all_scenes[-1].get("no") or 0) if all_scenes else 0

    user = prompts.render(
        "captions_regen", indep=persona.INDEP, tone_block=_tone(slug),
        budget_chars=config.budget_chars(len(all_scenes)),
        last_no=last_no, items=_items(scenes))
    out, cost = structured("script", SYSTEM_WRITE, user, CAPTIONS_SCHEMA,
                           on_activity=on_activity)

    new: Dict[int, str] = {}
    for c in out.get("captions") or []:
        t = (c.get("srt_text") or "").strip()
        if t:
            new[int(c.get("no") or 0)] = t

    touched: List[int] = []
    v = dict(doc.get("verify") or {})
    for s in all_scenes:
        no = int(s.get("no") or 0)
        if no in new and new[no] != s.get("srt_text"):
            s["srt_text"] = new[no]
            # 자막이 바뀌면 규칙이 만든 발음도 낡는다. 사람이 손으로 적은 발음은
            # 건드리지 않는다 — 「사람 손이 이긴다」(s2_speech).
            if s.get("narration_from") != "손":
                s.pop("narration_text", None)
            v.pop(str(no), None)       # 지난 판정은 이제 다른 문장에 대한 것이다
            touched.append(no)
    doc["verify"] = v
    doc["caption_cost_usd"] = round(float(doc.get("caption_cost_usd") or 0) + cost, 4)
    _save(slug, doc)
    return {"captions": {str(k): t for k, t in new.items()},
            "touched": sorted(touched), "cost_usd": cost}
