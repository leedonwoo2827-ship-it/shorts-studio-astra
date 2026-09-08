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

# 확장자 → 움직이는가. 컴포지션이 이것을 보고 심는 방식을 고른다.
ANIMATED = (".svg",)
STILL = (".png", ".jpg", ".jpeg", ".webp")


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


def is_animated(name: str) -> bool:
    return Path(name).suffix.lower() in ANIMATED


def run(slug: str, *, force: bool = False, only: Optional[List[int]] = None,
        model: Optional[str] = None,
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
    for line in proc.stdout or []:
        line = line.rstrip()
        if line and on_log:
            on_log(line)
    proc.wait()

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
