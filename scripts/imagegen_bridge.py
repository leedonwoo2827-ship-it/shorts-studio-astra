# -*- coding: utf-8 -*-
"""그림 브리지 — **ChatGPT 인증을 만지는 유일한 프로세스.**

    python scripts/imagegen_bridge.py <job.json> <result.json>

★ **왜 별도 프로세스인가.** 이 앱은 인증이 두 개다 — Claude(대본·지시문)와
  ChatGPT(그림). summary-showcase 가 남긴 경고가 정확하다:
  「인증 주체가 다른 것을 코드로 이으면 사고가 난다.」
  그래서 코드로 잇지 않고 **프로세스로 가른다.** 이 프로세스는
  `~/.codex/auth.json` 만 읽고, Claude 쪽 경로(`~/.claude/`)를 열지 않는다.

★ `OPENAI_API_KEY` 를 지우고 시작한다. 오래된 export 가 구독 대신 키로 나가면
  **모르는 사이에 과금**된다.

★ 결과는 파일이다. stdout 은 진행 로그뿐이다 — 섞으면 cp949 에서 깨진다.
"""
from __future__ import annotations

import json
import os
import sys
import traceback
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _init() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
        except Exception:  # noqa: BLE001
            pass
    # 구독으로만 나간다 — 키가 있으면 무력화한다
    for k in ("OPENAI_API_KEY", "OPENAI_BASE_URL", "OPENAI_ORG_ID"):
        os.environ.pop(k, None)
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))


def main() -> int:
    _init()
    if len(sys.argv) < 3:
        print("usage: imagegen_bridge.py <job.json> <result.json>", file=sys.stderr)
        return 2
    job = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    out_path = Path(sys.argv[2])
    result = {"items": [], "error": None}

    try:
        from imagegen.auth_status import status as auth_status
        from imagegen.codex_image import NotAuthenticated, generate_image

        # ★ **누르기 전에 막는다.** 만료된 토큰으로 재시도를 돌리면 씬 수 x 재시도
        #   횟수만큼 헛돈다(실측: 3장 x 3회 = 9번의 401 을 보고서야 알았다).
        st = auth_status()
        if not st["ok"]:
            raise RuntimeError(" ".join([st["message"], st["how"]]))

        out_dir = Path(job["out_dir"])
        out_dir.mkdir(parents=True, exist_ok=True)
        size = job.get("size") or "1024x1536"
        fmt = job.get("format") or "png"
        retries = int(job.get("retries") or 2)
        workers = max(1, int(job.get("concurrency") or 1))

        def one(item: dict) -> dict:
            no = int(item["no"])
            name = item.get("file") or f"{no:03d}.{fmt}"
            prompt = item["prompt"]
            if item.get("negative"):
                # 백엔드에 negative 필드가 없다 — 문장으로 붙이는 것이 유일한 방법이다
                prompt += f"\nAvoid: {item['negative']}"
            last = ""
            for attempt in range(1, retries + 2):
                try:
                    raw, meta = generate_image(prompt, size=size, output_format=fmt)
                    (out_dir / name).write_bytes(raw)
                    print(f"[{no}] {len(raw) // 1024}KB {name}", flush=True)
                    return {"no": no, "file": name, "bytes": len(raw),
                            "model": meta.get("model")}
                except NotAuthenticated as e:
                    # 로그인 문제는 **재시도로 낫지 않는다.** 즉시 접는다.
                    print(f"[{no}] 로그인 필요 — 재시도하지 않습니다", flush=True)
                    return {"no": no, "error": f"NotAuthenticated: {e}", "fatal": True}
                except Exception as e:  # noqa: BLE001
                    last = f"{type(e).__name__}: {e}"
                    print(f"[{no}] {attempt}회 실패 {last}", flush=True)
            return {"no": no, "error": last}

        with ThreadPoolExecutor(max_workers=workers) as ex:
            result["items"] = list(ex.map(one, job["items"]))
    except Exception:  # noqa: BLE001
        result["error"] = traceback.format_exc(limit=6)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return 1 if result["error"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
