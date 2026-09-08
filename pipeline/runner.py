# -*- coding: utf-8 -*-
"""단계를 실제로 돌리는 곳. 서버도 CLI 도 여기만 부른다.

★ 단계 함수는 **모두 같은 모양**이다 — `(slug, log, **opts) -> dict`.
  모양이 같아야 「전부 만들기」가 표를 따라 그냥 돌 수 있다.

★ 실패하면 **거기서 멈춘다.** 그림이 안 나왔는데 빌드까지 밀고 가면 빈 화면
  영상이 나오고, 그게 성공처럼 보인다.
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from core import config, paths
from core.atomic_io import atomic_write_json, atomic_write_text
from pipeline import (s0_source, s1_script, s2_speech, s3_tts, s4_subs,
                      s5_artspec, s6_art, s6b_mux, s7_compose, s8_render,
                      s9_meta)
from pipeline.stages import ALL_ORDER, BY_GROUP, BY_KEY

Log = Callable[[str], None]


# ── 0 재료 ──────────────────────────────────────────────────────────────
def stage_source(slug: str, log: Log, **_: Any) -> Dict[str, Any]:
    """`00_기획/` 의 원본 파일 → `source.md`. **모델을 부르지 않는다.**

    사람이 넣는 것은 원본 파일 하나뿐이다. 여기서 나온 md 는 **고쳐도 된다** —
    조판된 책 PDF 는 쪽번호·머리글이 본문 한가운데 섞이는데, 그걸 그대로 모델에
    넣으면 부를 때마다 그 값을 내고 내용도 흐려진다.
    """
    plan = paths.plan_dir(slug)
    src = _pick_source(plan)
    if src is None:
        raise FileNotFoundError(
            f"{plan} 에 원본 파일이 없습니다. PDF·DOCX·TXT·MD·HTML 하나를 넣으세요.")

    meta = _source_meta(slug)
    title = meta.get("title") or src.stem
    log(f"  원본 {src.name} 읽는 중")
    md, warns = s0_source.to_markdown(src, title=title)
    atomic_write_text(str(paths.source_md(slug)), md)
    for w in warns:
        log(f"  · {w}")

    meta.update({"file": src.name, "title": title, "chars": len(md)})
    atomic_write_json(str(paths.source_json(slug)), meta, indent=2)
    log(f"  source.md {len(md):,}자 — 고칠 데가 있으면 지금 고치세요")
    return {"chars": len(md), "file": src.name, "warnings": warns}


_SRC_EXT = (".pdf", ".docx", ".md", ".txt", ".html", ".htm")


def _pick_source(plan: Path) -> Optional[Path]:
    if not plan.exists():
        return None
    cands = [p for p in sorted(plan.iterdir())
             if p.is_file() and p.suffix.lower() in _SRC_EXT
             and not p.name.startswith(("_", "source."))]
    return cands[0] if cands else None


def _source_meta(slug: str) -> Dict[str, Any]:
    p = paths.source_json(slug)
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            pass
    return {"cuts": int(config.get("shorts.cuts", 3)),
            "voice": config.get("narration.voice", "F2"),
            "speed": config.get("narration.speed", 1.2)}


# ── 1~8 ────────────────────────────────────────────────────────────────
def stage_script(slug: str, log: Log, **opts: Any) -> Dict[str, Any]:
    meta = _source_meta(slug)
    cuts = int(opts.get("cuts") or meta.get("cuts") or config.get("shorts.cuts", 3))
    log(f"  씬 {cuts}개 · 예산 {config.budget_chars(cuts)}자")
    out = s1_script.run(slug, cuts=cuts, on_activity=lambda m: log(f"  · {m}"))
    b = out.get("budget") or {}
    log(f"  「{out.get('title')}」 씬 {len(out.get('scenes') or [])} · "
        f"{b.get('chars')}자 / {b.get('limit')}자 · 추정 {b.get('est_sec')}초 · "
        f"${out.get('cost_usd', 0):.2f}")
    for w in out.get("warnings") or []:
        log(f"  ⚠ {w}")
    return out


def stage_speech(slug: str, log: Log, **_: Any) -> Dict[str, Any]:
    out = s2_speech.run(slug)
    log(f"  발음 대본 {out['scenes']}씬 — 바뀐 씬 {out['changed'] or '없음'}"
        + (f" · 표에서 읽는 씬 {out['manual']}" if out.get("manual") else ""))
    return out


def stage_tts(slug: str, log: Log, **opts: Any) -> Dict[str, Any]:
    out = s3_tts.run(slug, force=bool(opts.get("force")),
                     only=opts.get("only"), on_log=lambda m: log(f"  {m}"))
    if out.get("engine") == "none":
        log("  ⚠ " + out.get("warning", ""))
        return out
    log(f"  새로 만든 씬 {out['made'] or '없음'} · 그대로 둔 씬 {out['kept'] or '없음'}"
        + (f" · 합계 {out.get('total_sec')}초" if out.get("total_sec") else ""))
    for w in (out.get("failed") or []):
        log(f"  ✗ 씬 {w['no']}: {w['error']}")
    if out.get("warning"):
        log(f"  ⚠ {out['warning']}")
    return out


def stage_subs(slug: str, log: Log, **_: Any) -> Dict[str, Any]:
    out = s4_subs.run(slug)
    log(f"  자막 큐 {out['cues']}개 · 총 {out['total_sec']}초")
    if out.get("estimated"):
        log(f"  ⚠ 씬 {out['estimated']} 은 소리가 없어 길이를 **추정**했습니다. "
            f"「음성」을 돌리면 실측으로 바뀝니다.")
    return out


def stage_artspec(slug: str, log: Log, **_: Any) -> Dict[str, Any]:
    out = s5_artspec.run(slug, on_activity=lambda m: log(f"  · {m}"))
    log(f"  장면 지시 {out['count']}개 · ${out.get('cost_usd', 0):.2f}")
    for r in out.get("scenes") or []:
        log(f"    씬 {r['no']} · 화면 {r.get('scene_sec', r['sec'])}초 · 동작은 {r['sec']}초 안에")
        log(f"      주장 : {r.get('claim', '')}")
        log(f"      무대 : {r.get('stage', '')[:100]}")
        log(f"      변동 : {r.get('change', '')}")
        if r.get("support"):
            log(f"      거듦 : {r['support']}")
    for w in out.get("warnings") or []:
        log(f"  ⚠ {w}")
    return out


def stage_art(slug: str, log: Log, **opts: Any) -> Dict[str, Any]:
    out = s6_art.run(slug, force=bool(opts.get("force")),
                     only=opts.get("only"), model=opts.get("model"),
                     on_log=lambda m: log(f"  {m}"))
    log(f"  모델 {out.get('model')} · 새로 만든 장면 {out['made'] or '없음'} · "
        f"그대로 둔 장면 {out['kept'] or '없음'}")
    for f in (out.get("failed") or []):
        log(f"  ✗ 씬 {f['no']}: {f['error']}")
    if out.get("hint"):
        log(f"  · {out['hint']}")
    return out


def stage_compose(slug: str, log: Log, **_: Any) -> Dict[str, Any]:
    out = s7_compose.run(slug, on_log=log)
    if out.get("animated"):
        log(f"  움직이는 장면: 씬 {out['animated']}")
    if out.get("still"):
        log(f"  정지 그림(켄번스): 씬 {out['still']}")
    if out.get("missing_art"):
        log(f"  ⚠ 씬 {out['missing_art']} 에 장면이 없습니다 — 결이 깔린 채로 나갑니다")
    if out.get("missing_audio"):
        log(f"  ⚠ 씬 {out['missing_audio']} 에 소리가 없습니다")
    return out


def stage_build(slug: str, log: Log, **opts: Any) -> Dict[str, Any]:
    comp = paths.comp_dir(slug)
    build = paths.new_build_dir(slug)
    final = build / f"{slug}.mp4"

    r = s8_render.run(comp, final, skip_lint=bool(opts.get("skip_lint")), on_log=log)

    # ★ mux 는 **파일을 제자리에서 다시 쓴다**(별도 목적지가 없다). 그래서 렌더를
    #   바로 최종 이름으로 받고 그 위에 얹는다. 자막이 없어도 한 번은 돌린다 —
    #   `+faststart` 하나만으로도 값이 있다(HyperFrames 는 moov 를 파일 끝에 둔다).
    srt = paths.srt(slug)
    info_extra: Dict[str, Any] = {}
    if srt.exists():
        info_extra["mux"] = s6b_mux.run(final, srt, on_log=log)
    else:
        log("  자막 SRT 가 없습니다 — 「자막」 단계를 먼저 돌리면 트랙이 얹힙니다")

    doc = json.loads(paths.script_json(slug).read_text(encoding="utf-8"))
    if srt.exists():
        shutil.copy2(srt, build / f"{slug}.srt")
    atomic_write_text(str(build / "대본.txt"), _script_txt(doc))
    atomic_write_json(str(build / "정보.json"), {
        "slug": slug, "title": doc.get("title"),
        "cuts": len(doc.get("scenes") or []),
        "total_sec": doc.get("total_sec"),
        "size_mb": r.get("size_mb"),
        "render_warnings": r.get("warnings"),
        "perf": r.get("perf"),
        **info_extra,
    }, indent=2)
    atomic_write_text(str(paths.latest_txt(slug)), build.name)
    log(f"  {build.name}/{final.name} · {r.get('size_mb')} MB")
    return {"dir": str(build), "mp4": str(final), **r}


def _script_txt(doc: Dict[str, Any]) -> str:
    rows = [f"# {doc.get('title') or ''}", ""]
    for s in doc.get("scenes") or []:
        rows += [f"## 씬 {s.get('no')} ({s.get('role')})  {s.get('audio_sec', 0)}초",
                 f"후크  {s.get('hook_line1')} / {s.get('hook_line2')}",
                 f"자막  {s.get('srt_text')}",
                 f"발음  {s.get('narration_text')}",
                 f"근거  {s.get('source')}", ""]
    rows.append("해시태그  " + "  ".join(doc.get("hashtags") or []))
    return "\n".join(rows)


def stage_result(slug: str, log: Log, **opts: Any) -> Dict[str, Any]:
    out = s9_meta.run(slug, source_line=str(opts.get("source_line") or ""),
                      on_activity=lambda m: log(f"  · {m}"))
    log(f"  「{out['title']}」 태그 {len(out['tags'])}개 · ${out['cost_usd']:.2f}")
    log(f"  {out['file']}")
    return out


FUNCS: Dict[str, Callable[..., Dict[str, Any]]] = {
    "source": stage_source,
    "script": stage_script,
    "speech": stage_speech,
    "tts": stage_tts,
    "subs": stage_subs,
    "artspec": stage_artspec,
    "art": stage_art,
    "compose": stage_compose,
    "build": stage_build,
    "result": stage_result,
}


def run_stage(slug: str, key: str, log: Log, **opts: Any) -> Dict[str, Any]:
    fn = FUNCS.get(key)
    if fn is None:
        raise KeyError(f"모르는 단계입니다: {key}")
    st = BY_KEY[key]
    log(f"[{st.name}] 시작")
    out = fn(slug, log, **opts)
    log(f"[{st.name}] 끝")
    return out


def run_group(slug: str, group: str, log: Log,
              on_stage: Optional[Callable[[int, int, str], None]] = None,
              **opts: Any) -> Dict[str, Any]:
    """묶음 하나를 순서대로. **화면의 큰 단추가 부르는 것이 이것이다.**

    묶음은 편의고 낱개가 원칙이다 — 단계 줄은 여전히 하나씩 누를 수 있다.
    묶음이 왜 이렇게 갈렸는지는 `pipeline/stages.py` 의 머리말에 있다.
    """
    g = BY_GROUP.get(group)
    if g is None:
        raise KeyError(f"모르는 묶음입니다: {group}")
    total = len(g.stages)
    done: Dict[str, Any] = {}
    for key in g.stages:
        if on_stage:
            on_stage(len(done), total, BY_KEY[key].name)
        done[key] = run_stage(slug, key, log, **opts)
    if on_stage:
        on_stage(total, total, "끝")
    return done


def run_all(slug: str, log: Log, *, skip: tuple = (),
            on_stage: Optional[Callable[[int, int, str], None]] = None,
            **opts: Any) -> Dict[str, Any]:
    """표 순서대로 전부. **실패하면 거기서 멈춘다.**

    `on_stage(끝난수, 전체수, 지금단계이름)` 은 진행 막대를 채우는 데 쓴다.
    이것을 넘기지 않으면 화면 막대가 0 아니면 100 밖에 안 보인다 — 30초
    영상 한 편이 몇 분 걸리는데 그동안 막대가 안 움직이면 멈춘 것으로 보인다.
    """
    order = [k for k in ALL_ORDER if k not in skip]
    total = len(order)
    done: Dict[str, Any] = {}
    for key in ALL_ORDER:
        if key in skip:
            log(f"[{BY_KEY[key].name}] 건너뜀")
            continue
        if on_stage:
            on_stage(len(done), total, BY_KEY[key].name)
        done[key] = run_stage(slug, key, log, **opts)
    if on_stage:
        on_stage(total, total, "끝")
    return done
