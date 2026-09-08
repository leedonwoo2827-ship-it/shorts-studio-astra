# -*- coding: utf-8 -*-
"""TTS 브리지 — **다른 venv 에서 도는 유일한 코드.**

콘솔(.venv-app)은 fastapi 를, 엔진(.venv)은 onnxruntime 를 쓴다. 둘을 한 venv 에
넣으면 충돌하고, 렌더 도중에 콘솔을 닫을 수도 있어야 한다. 그래서 **파일로만 대화한다.**

    콘솔  →  job.json   {"items":[{"no":5,"text":"…"}], …}
             ↓  이 스크립트를 엔진 venv 의 python 으로 실행
    콘솔  ←  result.json {"items":[{"no":5,"file":"005.wav","sec":4.1}], …}

stdout 을 파싱하지 않는다 — 진행 로그와 결과가 섞이면 한글 콘솔 인코딩에서
깨진다(실제로 겪는 문제). 결과는 항상 파일이다.

    python tts_bridge.py <job.json> <result.json>
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import traceback
from pathlib import Path


def _init_console() -> None:
    """cp949 콘솔에서 한글·기호 출력이 UnicodeEncodeError 로 죽는 것을 막는다.

    ★ core.console 을 import 하지 않는다 — 여기는 **venv 경계**다. 이 스크립트가
      의지할 수 있는 것은 표준 라이브러리뿐이라는 것이 이 파일의 계약이다.
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
        except Exception:  # noqa: BLE001
            pass


def main() -> int:
    _init_console()
    if len(sys.argv) < 3:
        print("usage: tts_bridge.py <job.json> <result.json>", file=sys.stderr)
        return 2
    job_path, out_path = Path(sys.argv[1]), Path(sys.argv[2])
    job = json.loads(job_path.read_text(encoding="utf-8"))

    # 경로는 job 이 정한다 — 이 스크립트는 voicewright 설치 위치를 모른다
    vw_dir = job.get("voicewright_dir")
    if vw_dir and vw_dir not in sys.path:
        sys.path.insert(0, vw_dir)
    if job.get("assets_dir"):
        os.environ["VOICEWRIGHT_ASSETS_DIR"] = job["assets_dir"]
    os.environ.setdefault("VOICEWRIGHT_USE_GPU", "auto")

    result = {"items": [], "sample_rate": 0, "error": None}
    try:
        from voicewright.audio_io import write_wav
        from voicewright.engine import Engine

        out_dir = Path(job["out_dir"])
        out_dir.mkdir(parents=True, exist_ok=True)
        voice = job.get("voice") or "F2"
        speed = float(job.get("speed") or 1.0)
        step = int(job.get("total_step") or 8)

        async def go():
            eng = await Engine.get()
            result["sample_rate"] = eng.sample_rate
            for it in job["items"]:
                no = int(it["no"])
                text = (it.get("text") or "").strip()
                if not text:
                    continue
                name = f"{no:03d}.wav"
                # ★ 항목별 voice 를 허용한다(원본은 잡 전체에 하나였다).
                #   씬마다 화자가 갈릴 수 있고, voicewright 는 배치당 스타일이
                #   하나뿐이라 어차피 직렬 호출이다 — 비용이 없다.
                v = (it.get("voice") or voice).upper()
                sp = float(it.get("speed") or speed)
                try:
                    wav = await eng.synth(text, voice_code=v, lang="ko",
                                          speed=sp, total_step=step)
                except Exception as e:  # noqa: BLE001
                    result["items"].append({"no": no, "error": f"{type(e).__name__}: {e}"})
                    print(f"[{no}] 실패 {e}", flush=True)
                    continue
                write_wav(out_dir / name, wav, eng.sample_rate)
                sec = round(len(wav) / float(eng.sample_rate), 2)
                result["items"].append({"no": no, "file": name, "sec": sec, "voice": v})
                print(f"[{no}] {sec:.1f}s {name} ({v})", flush=True)

        asyncio.run(go())
    except Exception:  # noqa: BLE001
        result["error"] = traceback.format_exc(limit=6)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return 1 if result["error"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
