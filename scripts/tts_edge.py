# -*- coding: utf-8 -*-
"""edge-tts 브리지 — **파일로만 대화한다.**

    콘솔  →  job.json    {"items":[{"no":3,"text":"…"}], "voice":"F2", "speed":1.2, …}
             ↓  python scripts/tts_edge.py <job.json> <result.json>
    콘솔  ←  result.json {"items":[{"no":3,"file":"003.wav","sec":5.3,
                                    "marks":[{"t":0.0,"d":0.35,"text":"우편"},…]}], …}

★ **stdout 을 파싱하지 않는다.** 진행 로그와 결과가 한 스트림에 섞이면 cp949
  콘솔에서 깨진다(실제로 겪는 문제). 결과는 항상 파일이다.

★ edge-tts 는 mp3 를 준다. 씬 길이는 **실측 오디오 길이**로 정해야 하므로
  ffmpeg 로 wav(48k mono)로 옮기고 그때 길이를 잰다 — 추정하지 않는다.

★ 배속은 edge 의 `rate=+20%` 로 준다. ffmpeg atempo 로 늘이면 음정이 뜬다.

★ **`marks` — 낱말이 언제 나오는지.** `Communicate.save()` 를 쓰면 edge 가 주는
  `WordBoundary` 이벤트가 그냥 버려진다. `stream()` 으로 돌면 오디오 조각과 함께
  낱말 시각이 같이 오고, 그것으로 자막 조각을 **글자 수 추정이 아니라 실제 발화
  시각**에 붙일 수 있다(`s4_subs`). 크레딧도 새 의존성도 들지 않는다.
  offset·duration 은 **100나노초 틱**이라 1e7 로 나눠 초로 만든다.

★ **`boundary="WordBoundary"` 를 반드시 준다.** edge-tts 의 기본값은
  `SentenceBoundary` 라서, 안 주면 문장 하나에 이벤트가 **한 개**만 오고 낱말
  시각은 아예 오지 않는다. 실측(edge-tts 7.2.8): 같은 문장에 기본값은
  `SentenceBoundary` 1개, 명시하면 `WordBoundary` 9개(= 어절 9개)였다.

★ **배속 보정을 하지 마라 — offset 은 이미 배속이 적용된 시간선이다.**
  실측(ko-KR-SunHiNeural, 어절 9개 한 문장):
      `+0%`   wav 5.448초   마지막 낱말 끝 4.575초
      `+20%`  wav 4.560초   마지막 낱말 끝 3.821초
  wav 비 1.195 : 낱말끝 비 1.197 — 같이 줄었다. 1.2 로 나누면 **두 번 보정**된다.
  (참고: 첫 낱말 t=0.09~0.10 인데 실제 발화는 0.19~0.21 에 시작한다. 마크가
   0.1초쯤 이르다 — 자막이 낱말보다 살짝 먼저 뜨는 것은 자연스러우니 그대로 쓴다.)

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


# edge 의 offset·duration 단위 — 100나노초 틱.
_TICKS = 10_000_000


async def _stream(comm, mp3: Path) -> list:
    """오디오는 파일로, `WordBoundary` 는 목록으로 받는다.

    `comm.save()` 가 하는 일을 손으로 하는 것뿐이다. 그렇게 해야 낱말 시각이
    버려지지 않는다 — `save()` 는 audio 조각만 쓰고 나머지 이벤트를 흘린다.
    """
    marks: list = []
    with open(mp3, "wb") as fh:
        async for chunk in comm.stream():
            kind = chunk.get("type")
            if kind == "audio":
                data = chunk.get("data")
                if data:
                    fh.write(data)
            elif kind == "WordBoundary":
                marks.append({
                    "t": round(int(chunk.get("offset") or 0) / _TICKS, 3),
                    "d": round(int(chunk.get("duration") or 0) / _TICKS, 3),
                    "text": str(chunk.get("text") or ""),
                })
    return marks


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
                    comm = edge_tts.Communicate(text, v, rate=rate,
                                                boundary="WordBoundary")
                    marks = await _stream(comm, mp3)
                    _to_wav(mp3, wav_path, ffmpeg)
                    sec = _wav_sec(wav_path)
                except Exception as e:  # noqa: BLE001
                    result["items"].append({"no": no, "error": f"{type(e).__name__}: {e}"})
                    print(f"[{no}] 실패 {e}", flush=True)
                    continue
                item = {"no": no, "file": wav_path.name, "sec": sec, "voice": v}
                if marks:
                    item["marks"] = marks
                result["items"].append(item)
                print(f"[{no}] {sec:.1f}s {wav_path.name} ({v}) 낱말 {len(marks)}개",
                      flush=True)

        asyncio.run(go())
        shutil.rmtree(tmp_dir, ignore_errors=True)
    except Exception:  # noqa: BLE001
        result["error"] = traceback.format_exc(limit=6)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return 1 if result["error"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
