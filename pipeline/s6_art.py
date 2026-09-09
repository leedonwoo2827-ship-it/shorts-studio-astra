# -*- coding: utf-8 -*-
"""S6 장면 제작 — 씬마다 **움직이는 장면**. **가장 비싼 단계다.**

들어오는 것: `04_장면/장면지시.json`
나가는 것:   `04_장면/001.svg` … (움직임) 또는 `001.png` (정지)

★ **두 갈래가 한 폴더에 산다.**
      `.svg`  아스트라가 코드로 쓴 애니메이션 장면 — 그림 안이 움직인다
      `.png`  정지 그림(다른 앱에서 뽑은 것, 자리표시) — 컴포지션이 켄번스로 민다
  확장자가 어느 쪽인지 알려 준다. 그래서 정지 그림으로 싸게 시험하고 나중에
  아스트라로 갈아 끼우는 것이 자연스럽다.

★ **폴더 접점을 살려 둔다.** 이 단계가 죽어도 `04_장면/` 에 같은 이름으로 넣으면
  뒤 단계가 그대로 돈다. 자동화는 그 위에 얹은 편의일 뿐이다.

★ 브리지는 **별도 프로세스**다(`scripts/astra_bridge.py`). 인증을 안 섞으려는
  것이 원래 이유인데, 덕분에 코드를 고치면 서버를 안 끄고도 바로 먹는다.

★ 이미 있는 장면은 다시 만들지 않는다. **지시가 바뀐 씬만** 다시 받는다
  (`_of` 스탬프). 여기서 아끼는 것이 아스트라 5시간 한도를 아끼는 것이다.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from core import config, paths
from core.atomic_io import atomic_write_json

ROOT = Path(__file__).resolve().parents[1]

# 확장자 → 어떻게 심는가. 컴포지션이 이것을 보고 고른다.
ANIMATED = (".svg",)                        # 코드로 쓴 애니메이션 — 문서에 인라인한다
VIDEO = (".mp4", ".webm")                   # 영상 — <video> 로 넣고 시계를 맞춘다
STILL = (".png", ".jpg", ".jpeg", ".webp")  # 정지 그림 — 배경으로 깐다
# ★ 우선순위 **순서 그대로**다. 같은 자리에 여러 확장자가 있으면 앞의 것이 이긴다.
#   `.svg` 가 `.png` 를 이기는 기존 규칙(움직이는 쪽이 이긴다)이 그대로 살아 있고,
#   영상이 그 위에 온다.
MEDIA = VIDEO + ANIMATED + STILL


def kind(name: str) -> str:
    """`video` · `svg` · `still` 중 하나. 컴포지션이 심는 방식을 고르는 데 쓴다."""
    ext = Path(name).suffix.lower()
    if ext in VIDEO:
        return "video"
    if ext in ANIMATED:
        return "svg"
    return "still"


def parse_name(stem: str) -> Optional[tuple]:
    """`001-2-03` → `(씬 1, 조각 2, 프레임 3, 프레임번호가_있었나)`. 아니면 `None`.

    ★ **앞 세 자리가 씬**이라는 기존 규칙은 그대로다. 그 뒤에 붙는 것을 이렇게 읽는다:

        001.png          씬1 · 조각1 · 프레임1 (암묵)
        001-2.png        씬1 · 조각2 · 프레임1 (암묵)  ← 조각 경계에서 갈린다 = 컷
        001-2-03.png     씬1 · 조각2 · 프레임3 (명시)  ← 조각 안 플립북
        001-교회.svg     씬1 · 조각1 · 프레임1 (암묵)  ← 설명은 무시 (여태 돌던 방식)
        001-2-교회.png   씬1 · 조각2 · 프레임1 (암묵)

    숫자 토막만 조각·프레임으로 읽고, 숫자가 아닌 것이 나오면 거기부터는 사람이
    붙인 설명이다. 그래서 예전 이름이 그대로 돈다 — 손으로 넣던 파일을 안 깬다.

    ★ 네 번째 값이 **프레임 번호를 실제로 적었는가**다. `001-2.png` 와
      `001-2-01.png` 이 한 폴더에 같이 있으면 둘 다 「조각 2 의 첫 프레임」을
      노리는데, 뭘 고를지 정해져 있지 않으면 **정렬 순서가 정한다** — 즉
      아무도 모르게 한 프레임이 가려진다. `present_many` 가 이 값을 보고
      **명시된 쪽을 살리고 암묵 한 장은 버린다.**
    """
    if len(stem) < 3 or not stem[:3].isdigit():
        return None
    no = int(stem[:3])
    tail = stem[3:]
    nums: List[int] = []
    if tail.startswith("-"):
        for part in tail.split("-")[1:]:
            if part.isdigit() and len(nums) < 2:
                nums.append(int(part))
            else:
                break
    cue = nums[0] if nums else 1
    explicit = len(nums) > 1
    frame = nums[1] if explicit else 1
    return no, max(1, cue), max(1, frame), explicit


def _snap(beats: List[Dict[str, Any]], cues: List[Dict[str, Any]],
          mot_sec: float) -> List[Dict[str, Any]]:
    """박자 시각을 자막 조각에 맞춘다. 글은 모델의 것, 시각은 코드의 것.

    박자 i 는 조각 i 가 시작할 때 시작하고, 다음 조각이 시작할 때 끝난다.
    박자가 조각보다 많으면 남은 것을 마지막 구간에 고르게 나눠 넣는다 —
    창이 겹치면 셋이 동시에 움직여 아무것도 안 보이므로 겹치지 않게만 둔다.
    """
    if not beats:
        return []
    if not cues:
        return beats
    edges = [float(c.get("t") or 0.0) for c in cues]
    end = mot_sec if mot_sec > 0 else (edges[-1] + 1.0)
    out: List[Dict[str, Any]] = []
    for i, b in enumerate(beats):
        if i < len(edges):
            at = edges[i]
            until = edges[i + 1] if i + 1 < len(edges) else end
        else:
            # 조각보다 박자가 많다 — 마지막 조각 구간을 쪼개 나눈다.
            extra = len(beats) - len(edges)
            k = i - len(edges)
            span = max(0.2, (end - edges[-1]) / max(1, extra + 1))
            at = edges[-1] + span * (k + 1)
            until = min(end, at + span)
        out.append({"at": round(at, 3), "until": round(max(at + 0.2, until), 3),
                    "what": str(b.get("what") or "")})
    return out


def stamp(spec: Dict[str, Any]) -> str:
    """지시가 바뀌었는지 보는 도장. 장면 내용에 영향을 주는 것만 넣는다."""
    # 칸·연쇄·두루마리 높이도 넣는다 — 이것들이 바뀌면 그림이 아예 달라진다.
    raw = json.dumps({k: spec.get(k) for k in ("claim", "stage", "layout",
                                               "change", "support",
                                               "palette_note", "sec",
                                               "canvas_h", "cells", "beats")},
                     ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def present(slug: str) -> Dict[int, str]:
    """폴더에 실제로 있는 장면. 앞 세 자리가 씬 번호다 — 뒤 설명은 자유.

    ★ 한 씬에 `.svg` 와 `.png` 가 다 있으면 **움직이는 쪽을 쓴다.**
      정지 그림으로 시험해 본 뒤 아스트라 것을 넣었을 때 자동으로 갈린다.
    """
    out: Dict[int, str] = {}
    d = paths.art_dir(slug)
    if not d.exists():
        return out
    for p in sorted(d.iterdir()):
        ext = p.suffix.lower()
        if ext not in ANIMATED + STILL:
            continue
        head = p.stem[:3]
        if not head.isdigit():
            continue
        no = int(head)
        cur = out.get(no)
        if cur is None or (ext in ANIMATED and Path(cur).suffix.lower() in STILL):
            out[no] = p.name
    return out


def present_many(slug: str) -> Dict[int, List[Dict[str, Any]]]:
    """씬마다 **조각 목록**, 조각마다 **프레임 목록**.

        {1: [{"m": 1, "frames": ["001-1.png"]},
             {"m": 2, "frames": ["001-2-01.png", "001-2-02.png"]}], …}

    ★ **씬에 그림이 몇 장인지 정해져 있지 않다.** 0장일 수도, 조각마다 한 장일
      수도, 한 조각 안에서 GIF 처럼 넘어갈 수도 있다. 그래서 `present()` 처럼
      씬당 하나로 접지 않고 목록으로 준다.

    ★ `present()` 는 **지우지 않는다.** 두루마리 배치가 그것을 쓴다 — 그 배치는
      씬 하나가 두루마리 한 장이라 정말로 씬당 한 파일이다.
    """
    # {씬: {조각: {명시여부: {프레임: 파일}}}}
    out: Dict[int, Dict[int, Dict[bool, Dict[int, str]]]] = {}
    d = paths.art_dir(slug)
    if not d.exists():
        return {}
    for p in sorted(d.iterdir()):
        if not p.is_file() or p.suffix.lower() not in MEDIA:
            continue
        got = parse_name(p.stem)
        if not got:
            continue
        no, cue, frame, explicit = got
        slot = out.setdefault(no, {}).setdefault(cue, {}).setdefault(explicit, {})
        cur = slot.get(frame)
        # 우선순위: MEDIA 의 순서. 앞에 있는 확장자가 이긴다.
        if cur is None or MEDIA.index(p.suffix.lower()) < MEDIA.index(Path(cur).suffix.lower()):
            slot[frame] = p.name

    def frames_of(byexp: Dict[bool, Dict[int, str]]) -> List[str]:
        # ★ 명시된 프레임이 하나라도 있으면 **그쪽만** 쓴다. 섞으면 암묵 한 장이
        #   플립북의 첫 프레임 자리를 조용히 차지한다.
        fr = byexp.get(True) or byexp.get(False) or {}
        return [fr[k] for k in sorted(fr)]

    return {no: [{"m": m, "frames": frames_of(cues[m])} for m in sorted(cues)]
            for no, cues in sorted(out.items())}


def is_animated(name: str) -> bool:
    return Path(name).suffix.lower() in ANIMATED


def run(slug: str, *, force: bool = False, only: Optional[List[int]] = None,
        model: Optional[str] = None,
        should_cancel: Optional[Callable[[], bool]] = None,
        on_log: Optional[Callable[[str], None]] = None) -> Dict[str, Any]:
    sp = paths.art_spec(slug)
    if not sp.exists():
        raise FileNotFoundError("먼저 「장면 지시」 단계를 돌리세요.")
    doc = json.loads(sp.read_text(encoding="utf-8"))
    rows = doc.get("scenes") or []
    if not rows:
        raise RuntimeError("장면 지시가 비어 있습니다.")

    # 자막 조각 — 씬 번호로 찾아 쓴다. 음성 실측에서 나온 시각이라 어긋날 여지가 없다.
    say: Dict[int, list] = {}
    sj = paths.script_json(slug)
    if sj.exists():
        try:
            for s in (json.loads(sj.read_text(encoding="utf-8")).get("scenes") or []):
                say[int(s.get("no") or 0)] = list(s.get("cues") or [])
        except Exception:  # noqa: BLE001
            say = {}

    art_dir = paths.art_dir(slug)
    art_dir.mkdir(parents=True, exist_ok=True)
    have = present(slug)

    todo, kept = [], []
    for r in rows:
        no = int(r["no"])
        if only and no not in only:
            kept.append(no)
            continue
        want = stamp(r)
        got = have.get(no)
        # 정지 그림만 있으면 「아직 안 만든 것」으로 본다 — 자리표시일 수 있다
        if (not force and got and is_animated(got) and r.get("_of") == want):
            kept.append(no)
            continue
        # ★ 필드를 **손으로 고르지 않는다.** 예전에는 목록으로 골라 담았는데,
        #   두루마리를 넣을 때 `canvas_h`·`cells`·`beats` 가 조용히 빠졌다.
        #   결과: 아스트라가 칸 지시를 못 받아 한 화면만 그렸고, 검사기는
        #   `cells` 가 없어 칸 수를 1로 계산해 그 1920px 을 통과시켰다.
        #   **둘이 같은 원인으로 동시에 눈이 멀었다**(실측 2026-09-08).
        #   그래서 이제 통째로 넘기고 코드가 쓰지 않는 것만 뺀다 —
        #   필드가 늘어도 자동으로 따라간다.
        row = {k: v for k, v in r.items() if not k.startswith("_")}
        # ★ 자막 조각 시각을 함께 넘긴다. **말이 그것을 말할 때 그것이 드러나야**
        #   장면이 안 정적이다. 실측(2026-09-08): 이걸 안 주니 아스트라가 그림을
        #   처음부터 다 켜 두고 뒤늦게 2.3~4.0초에 11개를 몰아 터뜨렸다 —
        #   앞 2.3초가 죽고 스티커를 흩뿌린 것처럼 보였다.
        #   장면 지시가 아니라 여기서 붙이는 이유: 자막을 사람이 고치면 조각이
        #   바뀌는데, 그때 장면 지시($)를 다시 돌리게 만들면 안 된다.
        cues = list(say.get(no) or [])
        row["cues"] = [{"t": c.get("t"), "text": c.get("text")} for c in cues]
        # ★ 박자 시각을 **자막 조각에 붙인다.** 안 붙이면 아스트라에게 시간표가
        #   두 개 간다 — 조각은 0.0/1.66/3.49 인데 박자는 0.3/1.5/2.7 이라
        #   어느 쪽에 맞출지 모른다. 말이 기준이므로 말에 맞춘다.
        #   글(`what`)은 모델의 것이고 시각은 코드의 것이다.
        row["beats"] = _snap(row.get("beats") or [], cues,
                             float(r.get("sec") or 0.0))
        todo.append(row)

    if not todo:
        return {"made": [], "kept": kept, "model": model or _model()}

    job = {
        "scenes": todo,
        "out_dir": str(art_dir),
        "model": model or _model(),
        "canvas": doc.get("canvas") or {},
        "palette": doc.get("palette") or {},
        "style_hint": doc.get("style_hint") or "",
        "style_refs": [str((ROOT / r).resolve())
                       for r in (config.get("art.style_refs") or [])
                       if (ROOT / r).is_file()],
        "timeout_sec": int(config.get("art.timeout_sec", 600)),
        "retries": int(config.get("art.retries", 1)),
    }
    job_path = art_dir / "_art_job.json"
    res_path = art_dir / "_art_result.json"
    # ★ 지난 결과를 먼저 지운다 — 브리지가 시작조차 못 하면 지난 실패를
    #   이번 실패로 착각한다(그림 단계에서 실제로 겪었다).
    res_path.unlink(missing_ok=True)
    atomic_write_json(str(job_path), job, indent=2)

    env = dict(os.environ)
    for k in ("OPENAI_API_KEY", "OPENAI_BASE_URL", "OPENAI_ORG_ID"):
        env.pop(k, None)

    proc = subprocess.Popen(
        [sys.executable, str(ROOT / "scripts" / "astra_bridge.py"),
         str(job_path), str(res_path)],
        cwd=str(ROOT), env=env,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, encoding="utf-8", errors="replace",
    )
    # ★ 로그를 읽는 이 자리가 **취소를 볼 수 있는 유일한 곳**이다. 브리지는 씬마다
    #   한 줄씩 뱉으므로, 줄이 올 때마다 깃발을 보고 죽인다. 예전에는 깃발만 세우고
    #   아무도 안 봐서 20분짜리를 못 멈췄다.
    canceled = False
    for line in proc.stdout or []:
        line = line.rstrip()
        if line and on_log:
            on_log(line)
        if should_cancel and should_cancel():
            canceled = True
            if on_log:
                on_log("중지 요청 — 아스트라를 멈춥니다")
            proc.kill()
            break
    proc.wait()
    if canceled:
        # 여기까지 만든 장면은 파일로 남아 있다. 다음에 「장면 받기」를 누르면
        # 그것들은 그대로 두고 나머지만 받는다.
        return {"made": [], "kept": kept, "canceled": True,
                "model": model or _model()}

    if not res_path.exists():
        raise RuntimeError(
            "장면 브리지가 결과를 남기지 못했습니다 — 시작조차 못 했을 수 있습니다"
            f" (exit={proc.returncode}). 위 로그를 보세요.")
    result = json.loads(res_path.read_text(encoding="utf-8"))
    if result.get("error"):
        raise RuntimeError(f"장면 제작 실패:\n{result['error']}")

    by_no = {int(i["no"]): i for i in result.get("items") or []}
    made, failed = [], []
    for r in rows:
        no = int(r["no"])
        got = by_no.get(no)
        if not got:
            continue
        if got.get("error"):
            failed.append({"no": no, "error": got["error"]})
            continue
        r["_of"] = stamp(r)
        r["bytes"] = got.get("bytes")
        made.append(no)
    atomic_write_json(str(sp), doc, indent=2)

    out: Dict[str, Any] = {"made": made, "kept": kept, "model": job["model"]}
    if failed:
        out["failed"] = failed
        out["hint"] = ("실패한 씬은 04_장면/ 에 같은 이름으로 SVG 나 PNG 를 직접 "
                       "넣어도 다음 단계가 그대로 돕니다.")
    return out


def _model() -> str:
    return str(config.get("art.model", "gpt-6-astra"))
