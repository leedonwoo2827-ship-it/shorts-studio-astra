# -*- coding: utf-8 -*-
"""S3 음성 — 발음 대본을 소리로. **측정된 길이가 씬 길이를 정한다.**

이 앱의 두 번째 계약이다. 대본 글자 수로 씬 길이를 **추정하지 않는다** —
추정하면 자막이 통째로 밀린다. 반대 방향은 없다.

    narration_text  →  02_음성/003.wav  →  audio_sec (실측)  →  씬 길이

★ **스탬프로 재합성을 아낀다.** `audio_of = sha256(voice|speed|text)[:16]` 이
  그대로면 그 씬은 건드리지 않는다. 발음 한 줄 고쳤을 때 씬 하나만 다시 굽는다.

★ 엔진은 두 갈래고 **브리지는 별도 프로세스**다.
    edge          무료·온라인. 이 레포의 기본. `scripts/tts_edge.py`
    voicewright   Supertonic 3(고품질). config 에 경로를 적은 사람만. `scripts/tts_bridge.py`
  브리지를 프로세스로 떼는 이유는 onnxruntime 이 앱 venv 와 충돌하고, 굽는 도중에
  콘솔을 닫을 수 있어야 하기 때문이다.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from core import config, paths
from core.atomic_io import atomic_write_json

ROOT = Path(__file__).resolve().parents[1]


def stamp(voice: str, speed: float, text: str) -> str:
    raw = f"{voice}|{speed}|{text}".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:16]


def _edge_voice(voice: str) -> str:
    table = config.get("tts.edge_voice", {}) or {}
    return table.get(voice) or table.get("F2") or "ko-KR-SunHiNeural"


def _engine_python() -> str:
    """브리지를 돌릴 파이썬. 지정이 없으면 지금 이 파이썬이다."""
    p = config.get("tts.python")
    return str(p) if p else sys.executable


def run(slug: str, *, force: bool = False,
        only: Optional[List[int]] = None,
        on_log: Optional[Callable[[str], None]] = None) -> Dict[str, Any]:
    doc = _load(slug)
    scenes = doc.get("scenes") or []
    voice = str(doc.get("voice") or config.get("narration.voice", "F2"))
    speed = float(doc.get("speed") or config.get("narration.speed", 1.2))
    engine = str(config.get("tts.engine", "edge"))

    if engine == "none":
        return {"engine": "none", "made": [], "kept": [],
                "warning": "TTS 엔진이 꺼져 있습니다. 02_음성/ 에 직접 wav 를 넣어도 됩니다."}

    audio_dir = paths.audio_dir(slug)
    audio_dir.mkdir(parents=True, exist_ok=True)

    todo: List[Dict[str, Any]] = []
    kept: List[int] = []
    for s in scenes:
        no = int(s.get("no") or 0)
        text = (s.get("narration_text") or "").strip()
        if not text:
            continue
        if only and no not in only:
            kept.append(no)
            continue
        want = stamp(voice, speed, text)
        have = s.get("audio_of")
        if not force and have == want and paths.wav(slug, no).exists():
            kept.append(no)
            continue
        item: Dict[str, Any] = {"no": no, "text": text}
        if engine == "edge":
            item["edge_voice"] = _edge_voice(voice)
        todo.append(item)

    if not todo:
        return {"engine": engine, "made": [], "kept": kept}

    job: Dict[str, Any] = {
        "items": todo, "out_dir": str(audio_dir),
        "voice": voice, "speed": speed,
        "total_step": int(config.get("narration.total_step", 8)),
    }
    # ★ **없으면 edge 로 물러선다.** VoiceWright 는 이 레포 밖에 사는 남의 폴더다
    #   (numpy·torch 가 든 제 venv 로 돌아야 한다). 레포만 옮긴 사람에게는 그 폴더가
    #   없는데, 예전에는 그때 음성 단계가 통째로 죽었다 — 이 레포는 「다른 폴더에
    #   의존하지 않는다」가 원칙이므로 **좋은 목소리는 있으면 쓰고 없으면 포기한다.**
    #   조용히 바꾸지는 않는다. 소리가 달라지는 것은 사람이 알아야 한다.
    fell_back = False
    if engine == "voicewright":
        vw = str(config.get("tts.voicewright_dir") or "").strip()
        vw_py = str(config.get("tts.python") or "").strip()
        why = ""
        if not vw:
            why = "tts.voicewright_dir 가 비어 있습니다"
        elif not Path(vw).is_dir():
            why = f"그 폴더가 없습니다: {vw}"
        elif vw_py and not Path(vw_py).is_file():
            why = f"그 파이썬이 없습니다: {vw_py}"
        if why:
            if on_log:
                on_log(f"⚠ VoiceWright 를 쓸 수 없어 edge 로 굽습니다 — {why}")
            engine = "edge"
            # ★ 파이썬도 같이 되돌린다. `tts.python` 은 VoiceWright venv 를 가리키고
            #   있는데, edge 스크립트를 그 파이썬으로 부르면 이번엔 edge_tts 가
            #   없다고 죽는다 — 물러선 자리에서 또 넘어지는 꼴이다.
            fell_back = True

    if engine == "voicewright":
        job["voicewright_dir"] = config.get("tts.voicewright_dir")
        job["assets_dir"] = config.get("tts.assets_dir")
        job["edge_voice"] = None
        script = ROOT / "scripts" / "tts_bridge.py"
    else:
        job["edge_voice"] = _edge_voice(voice)
        script = ROOT / "scripts" / "tts_edge.py"

    job_path = audio_dir / "_tts_job.json"
    res_path = audio_dir / "_tts_result.json"
    atomic_write_json(str(job_path), job, indent=2)

    timeout = float(config.get("tts.timeout_ms", 300000)) / 1000.0
    proc = subprocess.Popen(
        [sys.executable if fell_back else _engine_python(),
         str(script), str(job_path), str(res_path)],
        cwd=str(ROOT), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, encoding="utf-8", errors="replace",
    )
    try:
        for line in proc.stdout or []:                      # 진행만 흘린다
            line = line.rstrip()
            if line and on_log:
                on_log(line)
        proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        raise RuntimeError(f"TTS 가 {timeout:.0f}초를 넘겼습니다.")

    result = json.loads(res_path.read_text(encoding="utf-8")) if res_path.exists() else {}
    if result.get("error"):
        raise RuntimeError(f"TTS 실패:\n{result['error']}")

    by_no = {int(i["no"]): i for i in result.get("items") or []}
    made, failed = [], []
    for s in scenes:
        no = int(s.get("no") or 0)
        got = by_no.get(no)
        if not got:
            continue
        if got.get("error"):
            failed.append({"no": no, "error": got["error"]})
            continue
        s["audio_sec"] = float(got["sec"])
        s["audio_of"] = stamp(voice, speed, (s.get("narration_text") or "").strip())
        s["audio"] = f"{paths.AUDIO}/{got['file']}"
        made.append(no)

    total = round(sum(float(s.get("audio_sec") or 0) for s in scenes), 2)
    doc["audio_total_sec"] = total
    atomic_write_json(str(paths.script_json(slug)), doc, indent=2)

    out: Dict[str, Any] = {"engine": engine, "made": made, "kept": kept,
                           "total_sec": total}
    if failed:
        out["failed"] = failed
    # 길이는 **범위**다. 컷이 잦으면 20초도 좋다 — 넘거나 못 미칠 때만 알린다.
    lo, hi = config.seconds_range()
    lo = float(doc.get("seconds_min") or lo)
    hi = float(doc.get("seconds_max") or doc.get("seconds") or hi)
    if total > hi + 1.0:
        out["warning"] = (f"음성 합계가 {total:.1f}초로 목표 범위 "
                          f"{lo:.0f}~{hi:.0f}초를 넘습니다. 항목을 빼거나 "
                          f"자막 화면에서 문장을 줄이세요.")
    elif total and total < lo - 1.0:
        out["warning"] = (f"음성 합계가 {total:.1f}초로 목표 범위 "
                          f"{lo:.0f}~{hi:.0f}초에 못 미칩니다. 재료에 담을 사실이 "
                          f"더 있는지 「구조」 탭에서 보세요.")
    return out


def _load(slug: str) -> Dict[str, Any]:
    p = paths.script_json(slug)
    if not p.exists():
        raise FileNotFoundError("먼저 「대본」·「발음」 단계를 돌리세요.")
    return json.loads(p.read_text(encoding="utf-8"))
