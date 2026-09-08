# -*- coding: utf-8 -*-
"""S8 빌드 — 컴포지션 → MP4. `scripts/render.mjs` 를 서브프로세스로 부른다.

★ **왜 서브프로세스인가.** HyperFrames 는 전부 ESM Node 패키지다. 우리 주 스택은
  Python 이고, 재사용 자산(honorific · jobs · edge-tts)이 전부 Python 이다.
  경계를 한 파일(`render.mjs`)로 좁히고 stdout 태그로만 대화한다.

★ **node 에는 `CREATE_NO_WINDOW` 를 걸지 않는다.** 거꾸로였다 — 이 플래그를 걸면
  node 가 콘솔을 갖지 못하고, 그러면 Chrome 자식들이 물려받을 콘솔이 없어
  **Windows 가 자식마다 새 콘솔을 만들어 준다.** 실측(2026-09-01): 빈 검은 창 11개,
  conhost 프로세스 19개. 플래그를 빼면 node 가 run.bat 의 창을 물려받고
  Chrome 도 그것을 물려받아 새 창이 생기지 않는다.
  (짧게 끝나고 출력을 캡처만 하는 lint 쪽은 그대로 둔다.)

★ **`asyncio.create_subprocess_exec` 를 쓰지 않는다.** Windows + uvicorn `--reload`
  조합에서 깨진다(260721-compiui-short/app/render.py 에 같은 주석이 있다).
  `subprocess.Popen` + 스레드로 읽는다.

★ **먼저 lint 한다.** 린트 에러가 있으면 렌더가 돌아도 layout·contrast 감사가 꺼져
  있어 "통과"처럼 보이는 채로 망가진 영상이 나온다.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from core import config

ROOT = Path(__file__).resolve().parent.parent
RENDER_MJS = ROOT / "scripts" / "render.mjs"

# Windows: 서브프로세스가 콘솔 창을 띄우지 않게
_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0

_TAG = re.compile(r"^\[(stage|progress|warn|perf|done|error)\]\s*(.*)$")


def _npx() -> List[str]:
    """이 repo 의 node_modules 를 쓴다 — 전역 설치에 기대지 않는다."""
    local = ROOT / "node_modules" / ".bin" / ("hyperframes.cmd" if sys.platform == "win32"
                                              else "hyperframes")
    if local.is_file():
        return [str(local)]
    return ["npx", "hyperframes"]


def _run_tagged(cmd: List[str], *, cwd: Path, timeout: int,
                on_log: Callable[[str], None]) -> Dict[str, Any]:
    """태그 줄을 파싱하며 실행. 결과 dict 를 돌려준다."""
    # ★ creationflags 를 주지 않는다 — 위 머리말 참조. 콘솔을 물려받아야
    #   Chrome 워커가 자기 창을 만들지 않는다.
    proc = subprocess.Popen(cmd, cwd=str(cwd), stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, text=True,
                            encoding="utf-8", errors="replace")
    res: Dict[str, Any] = {"warnings": [], "perf": None, "output": None,
                           "error": None, "progress": 0}
    assert proc.stdout is not None
    for raw in proc.stdout:
        line = raw.rstrip()
        if not line:
            continue
        m = _TAG.match(line)
        if not m:
            continue                          # producer 의 내부 로그는 버린다
        kind, body = m.group(1), m.group(2)
        if kind == "stage":
            on_log(f"  · {body}")
        elif kind == "progress":
            pct, _, msg = body.partition(" ")
            try:
                res["progress"] = int(pct)
            except ValueError:
                pass
            # 10% 단위로만 흘린다 — 100줄을 다 찍으면 로그가 무의미해진다
            if res["progress"] % 10 == 0:
                on_log(f"  {res['progress']:>3}% {msg}")
        elif kind == "warn":
            res["warnings"].append(body)
            on_log(f"  ⚠ {body}")
        elif kind == "perf":
            try:
                res["perf"] = json.loads(body)
            except Exception:  # noqa: BLE001
                pass
        elif kind == "done":
            res["output"] = body
        elif kind == "error":
            res["error"] = body
    rc = proc.wait(timeout=timeout)
    res["returncode"] = rc
    return res


def lint(comp_dir: Path, *, on_log: Optional[Callable[[str], None]] = None
         ) -> Dict[str, Any]:
    """정적 계약 검사. **렌더 전에 반드시 통과시킨다.**"""
    log = on_log or (lambda s: None)
    cmd = _npx() + ["lint", str(comp_dir)]
    proc = subprocess.run(cmd, cwd=str(ROOT), capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=300,
                          creationflags=_NO_WINDOW)
    out = (proc.stdout or "") + "\n" + (proc.stderr or "")
    errs = [ln.strip() for ln in out.splitlines() if "✗" in ln]
    m = re.search(r"(\d+)\s*errors?,\s*(\d+)\s*warnings?", out)
    n_err = int(m.group(1)) if m else (1 if errs else 0)
    n_warn = int(m.group(2)) if m else 0
    for e in errs[:8]:
        log(f"  ✗ {e[:200]}")
    log(f"린트 — {n_err} errors, {n_warn} warnings")
    return {"errors": n_err, "warnings": n_warn, "lines": errs, "raw": out}


def run(comp_dir: Path, out_mp4: Path, *,
        skip_lint: bool = False,
        on_log: Optional[Callable[[str], None]] = None) -> Dict[str, Any]:
    """컴포지션 → MP4."""
    cfg = config.load()
    rnd = cfg.get("render") or {}
    comp = cfg.get("compose") or {}
    log = on_log or (lambda s: None)

    comp_dir = Path(comp_dir)
    out_mp4 = Path(out_mp4)
    out_mp4.parent.mkdir(parents=True, exist_ok=True)
    if not (comp_dir / "index.html").is_file():
        raise FileNotFoundError(f"컴포지션이 없습니다: {comp_dir / 'index.html'}")

    if not skip_lint:
        lr = lint(comp_dir, on_log=log)
        if lr["errors"]:
            # ★ 린트 에러를 안고 렌더하면 layout·contrast 감사가 꺼진 채로 돈다
            raise RuntimeError(
                f"린트 에러 {lr['errors']}건 — 먼저 고치세요.\n"
                + "\n".join(lr["lines"][:6]))

    node = "node"
    cmd = [node, str(RENDER_MJS),
           "--dir", str(comp_dir.resolve()),
           "--out", str(out_mp4.resolve()),
           "--fps", str(int(comp.get("fps") or 30)),
           "--quality", str(rnd.get("quality") or "standard")]
    if int(rnd.get("workers") or 0) > 0:
        cmd += ["--workers", str(int(rnd["workers"]))]

    log(f"렌더 시작 — {comp_dir.name} → {out_mp4.name}")
    res = _run_tagged(cmd, cwd=ROOT, timeout=3600, on_log=log)

    if res.get("error"):
        raise RuntimeError(f"렌더 실패:\n{res['error']}")
    if res.get("returncode"):
        raise RuntimeError(f"렌더 실패 (exit={res['returncode']})")
    if not res.get("output"):
        raise RuntimeError("렌더가 출력 경로를 알려주지 않았습니다.")

    p = Path(res["output"])
    size_mb = p.stat().st_size / (1024 * 1024) if p.is_file() else 0
    log(f"렌더 끝 — {p.name} · {size_mb:.1f} MB")
    if res.get("perf"):
        f = res["perf"]
        log(f"  실측: {(f.get('totalElapsedMs') or 0) / 1000:.1f}s "
            f"· 프레임 {f.get('totalFrames')} "
            f"· 최대 RSS {f.get('peakRssMb')} MB")
    return {"output": str(p), "size_mb": round(size_mb, 2),
            "warnings": res["warnings"], "perf": res.get("perf")}
