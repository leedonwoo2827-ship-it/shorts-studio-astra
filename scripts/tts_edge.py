# -*- coding: utf-8 -*-
"""edge-tts 브리지 — **파일로만 대화한다.**

    콘솔  →  job.json    {"items":[{"no":3,"text":"…"}], "voice":"F2", "speed":1.2, …}
             ↓  python scripts/tts_edge.py <job.json> <result.json>
    콘솔  ←  result.json {"items":[{"no":3,"file":"003.wav","sec":5.3}], …}

★ **stdout 을 파싱하지 않는다.** 진행 로그와 결과가 한 스트림에 섞이면 cp949
  콘솔에서 깨진다(실제로 겪는 문제). 결과는 항상 파일이다.

★ edge-tts 는 mp3 를 준다. 씬 길이는 **실측 오디오 길이**로 정해야 하므로
  ffmpeg 로 wav(48k mono)로 옮기고 그때 길이를 잰다 — 추정하지 않는다.

★ 배속은 edge 의 `rate=+20%` 로 준다. ffmpeg atempo 로 늘이면 음정이 뜬다.

이 스크립트는 표준 라이브러리 + edge_tts + ffmpeg 만 쓴다. 앱 모듈을 import
하지 않는다 — 나중에 엔진을 다른 venv 로 떼어 내도 그대로 돌아야 한다.
"""
from __future__ import annotations

import asyncio
import json
import shutil
import subprocess
import sys
import traceback
import wave
from pathlib import Path

DEFAULT_VOICE = "ko-KR-SunHiNeural"


def _init_console() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
        except Exception:  # noqa: BLE001
            pass


def _rate(speed: float) -> str:
    """1.2 → `+20%`. edge 는 정수 퍼센트만 받는다."""
    pct = int(round((float(speed) - 1.0) * 100))
    return f"{pct:+d}%"


def _wav_sec(path: Path) -> float:
    with wave.open(str(path), "rb") as w:
        return round(w.getnframes() / float(w.getframerate()), 3)


def _to_wav(mp3: Path, wav_path: Path, ffmpeg: str) -> None:
    subprocess.run(
        [ffmpeg, "-y", "-loglevel", "error", "-i", str(mp3),
         "-ac", "1", "-ar", "48000", "-c:a", "pcm_s16le", str(wav_path)],
        check=True,
    )


def main() -> int:
    _init_console()
    if len(sys.argv) < 3:
        print("usage: tts_edge.py <job.json> <result.json>", file=sys.stderr)
        return 2
    job_path, out_path = Path(sys.argv[1]), Path(sys.argv[2])
    job = json.loads(job_path.read_text(encoding="utf-8"))
    result = {"items": [], "engine": "edge", "error": None}

    try:
        import edge_tts  # noqa: PLC0415

        ffmpeg = shutil.which("ffmpeg")
        if not ffmpeg:
            raise RuntimeError("ffmpeg 가 PATH 에 없습니다. setup.bat 안내를 보세요.")

        out_dir = Path(job["out_dir"])
        out_dir.mkdir(parents=True, exist_ok=True)
        tmp_dir = out_dir / "_tmp"
        tmp_dir.mkdir(exist_ok=True)
        voice = job.get("edge_voice") or DEFAULT_VOICE
        rate = _rate(job.get("speed") or 1.0)

        async def go() -> None:
            for it in job["items"]:
                no = int(it["no"])
                text = (it.get("text") or "").strip()
                if not text:
                    continue
                mp3 = tmp_dir / f"{no:03d}.mp3"
                wav_path = out_dir / f"{no:03d}.wav"
                v = it.get("edge_voice") or voice
                try:
                    comm = edge_tts.Communicate(text, v, rate=rate)
                    await comm.save(str(mp3))
                    _to_wav(mp3, wav_path, ffmpeg)
                    sec = _wav_sec(wav_path)
                except Exception as e:  # noqa: BLE001
                    result["items"].append({"no": no, "error": f"{type(e).__name__}: {e}"})
                    print(f"[{no}] 실패 {e}", flush=True)
                    continue
                result["items"].append({"no": no, "file": wav_path.name,
                                        "sec": sec, "voice": v})
                print(f"[{no}] {sec:.1f}s {wav_path.name} ({v})", flush=True)

        asyncio.run(go())
        shutil.rmtree(tmp_dir, ignore_errors=True)
    except Exception:  # noqa: BLE001
        result["error"] = traceback.format_exc(limit=6)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return 1 if result["error"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
