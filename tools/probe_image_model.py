# -*- coding: utf-8 -*-
"""어느 모델이 그림 엔드포인트에서 통하는지 찾는다.

    python tools/probe_image_model.py [모델 [모델 ...]]

★ **왜 필요한가.** `codex debug models` 가 주는 목록과
  `/backend-api/codex/responses` 가 받아 주는 목록이 **다르다.**
  실측(2026-09-08): CLI 는 `gpt-5.5` 를 list 로 내주는데 같은 계정으로
  이미지 요청을 보내면 `model_not_found` 404 가 온다.
  그래서 목록을 믿지 않고 직접 한 번 찔러 본다.

★ 성공하면 **작은 그림 한 장 값이 든다.** 그래서 첫 성공에서 멈춘다.
  프롬프트도 일부러 가장 싼 모양으로 둔다.

찾은 이름은 `config.local.json` 의 `image.model` 에 적으면 된다 —
`config.json` 은 레포 기본값이라 건드리지 않는다.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core import console                      # noqa: E402

# 흔한 후보. 인자로 주면 그것만 본다.
CANDIDATES = [
    "gpt-5.5", "gpt-5.4", "gpt-5.4-mini", "gpt-5.3-codex", "gpt-5.2",
    "gpt-image-1", "gpt-image-1-mini", "gpt-4o",
]

TINY = "A single small solid navy circle centered on a plain ivory background."


def main() -> int:
    console.init()
    import imagegen.codex_image as cx
    from imagegen.auth_status import status

    st = status()
    print(f"로그인: {'유효' if st['ok'] else '만료'} — {st['message']}")
    if not st["ok"]:
        print(st["how"])
        return 2

    models = sys.argv[1:] or CANDIDATES
    print(f"\n후보 {len(models)}개를 하나씩 찔러 봅니다. 첫 성공에서 멈춥니다.\n")

    for m in models:
        cx.CODEX_MODEL = m                    # 모듈 전역을 갈아 끼운다
        print(f"  {m:18s} ", end="", flush=True)
        try:
            raw, meta = cx.generate_image(TINY, size="1024x1536", output_format="png")
        except Exception as e:                # noqa: BLE001
            msg = str(e).replace("\n", " ")
            if "model_not_found" in msg or "does not exist" in msg:
                print("없음 (model_not_found)")
            elif "NotAuthenticated" in type(e).__name__:
                print(f"로그인 문제 — {msg[:90]}")
                return 2
            else:
                print(f"실패 — {type(e).__name__}: {msg[:110]}")
            continue

        out = ROOT / "_probe.png"
        out.write_bytes(raw)
        print(f"통함!  {len(raw) // 1024} KB  ->  {out.name}")
        print(f"\n이 이름을 config.local.json 에 적으세요:")
        print('  { "image": { "model": "%s" } }' % m)
        return 0

    print("\n통하는 모델이 없습니다. codex CLI 를 올려 보세요:")
    print("  npm i -g @openai/codex@latest")
    print("그다음  codex debug models  로 목록을 다시 보고, 새 이름을 인자로 주세요.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
