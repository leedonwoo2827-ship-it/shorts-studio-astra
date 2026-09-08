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


def stamp(spec: Dict[str, Any]) -> str:
    """지시가 바뀌었는지 보는 도장. 장면 내용에 영향을 주는 것만 넣는다."""
    raw = json.dumps({k: spec.get(k) for k in ("claim", "stage", "layout",
                                               "change", "support",
                                               "palette_note", "sec")},
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
        todo.append({"no": no, "file": r["file"], "sec": r.get("sec"),
                     "scene_sec": r.get("scene_sec"),
                     "claim": r.get("claim", ""),
                     "stage": r["stage"], "layout": r["layout"],
                     "change": r.get("change", ""),
                     "support": r.get("support", ""),
                     "palette_note": r.get("palette_note", "")})

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
