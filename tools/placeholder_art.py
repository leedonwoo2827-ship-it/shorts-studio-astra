# -*- coding: utf-8 -*-
"""자리표시 장면 — **장면값을 쓰지 않고** 나머지 전부를 시험한다.

    python tools/placeholder_art.py <slug> [--force]

씬마다 `04_이미지/NNN.png` 를 만든다. 진짜 그림과 **같은 규격**이다 —
2:3 세로, 아이보리 바탕, 위아래 15% 는 비어 있다. 그래서 이걸로 렌더해 보면
띠·자막·후크가 그림칸을 침범하지 않는지 눈으로 확인된다.

★ 왜 필요한가. 그림 한 장이 이 파이프라인에서 가장 비싼 조각이고, ChatGPT
  로그인이 만료되면 아예 못 받는다. 그때도 **컴포지션과 렌더는 시험할 수 있어야
  한다** — 안 그러면 로그인을 고치기 전까지 아무것도 확인할 수 없다.

★ 비운 칸의 경계를 옅은 선으로 그려 준다. 진짜 그림이 그 선을 넘었는지
  비교해 볼 기준이 된다.

★ **두루마리를 흉내낸다.** 장면 지시에 칸이 여러 개면 그만큼 **세로로 긴**
  자리표시를 만들고 칸마다 다른 무늬를 넣는다. 그래야 카메라가 칸에서 칸으로
  뛰는 것이 크레딧 0원으로 눈에 보인다 — 이게 이 도구의 가장 중요한 쓸모다.
  칸이 하나면 예전과 똑같은 한 장이 나온다.

ffmpeg 만 쓴다(이미 필수 준비물이다). 이미지 라이브러리를 더 깔지 않는다.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core import config, console, paths     # noqa: E402

# 자리표시는 씬마다 다른 무늬여야 한다 — 다 같으면 씬이 넘어갔는지 안 보인다.
_SHAPES = ("bars", "grid", "steps", "rings", "diag", "blocks", "cols", "dots")


def _filters(no: int, w: int, h: int, top: int, bot: int,
             ivory: str, ink: str, sub: str) -> str:
    """`drawbox` 만으로 씬마다 다른 무늬를 만든다. 무늬는 **그림칸 안에만** 둔다."""
    art_top, art_bot = top, h - bot
    ah = art_bot - art_top
    f = []
    shape = _SHAPES[(no - 1) % len(_SHAPES)]

    if shape == "bars":
        for i in range(5):
            bh = int(ah * (0.16 + 0.14 * i))
            f.append(f"drawbox=x={int(w * 0.10) + i * int(w * 0.16)}"
                     f":y={art_bot - bh}:w={int(w * 0.11)}:h={bh}"
                     f":color={ink if i % 2 == 0 else sub}@0.85:t=fill")
    elif shape == "grid":
        for r in range(4):
            for c in range(3):
                f.append(f"drawbox=x={int(w * 0.10) + c * int(w * 0.28)}"
                         f":y={art_top + int(ah * 0.06) + r * int(ah * 0.23)}"
                         f":w={int(w * 0.22)}:h={int(ah * 0.16)}"
                         f":color={ink if (r + c) % 2 == 0 else sub}@0.75:t=fill")
    elif shape == "steps":
        for i in range(6):
            f.append(f"drawbox=x={int(w * 0.08) + i * int(w * 0.14)}"
                     f":y={art_bot - int(ah * (0.12 + 0.13 * i))}"
                     f":w={int(w * 0.12)}:h={int(ah * 0.10)}"
                     f":color={ink}@{0.35 + 0.10 * i:.2f}:t=fill")
    elif shape == "rings":
        for i in range(5):
            s = int(min(w, ah) * (0.20 + 0.14 * i))
            f.append(f"drawbox=x={(w - s) // 2}:y={art_top + (ah - s) // 2}"
                     f":w={s}:h={s}:color={ink if i % 2 == 0 else sub}@0.55:t=14")
    elif shape == "diag":
        for i in range(9):
            f.append(f"drawbox=x={int(w * 0.05) + i * int(w * 0.10)}"
                     f":y={art_top + int(ah * 0.05) + i * int(ah * 0.09)}"
                     f":w={int(w * 0.16)}:h={int(ah * 0.10)}"
                     f":color={sub if i % 3 else ink}@0.7:t=fill")
    elif shape == "blocks":
        for i, (fx, fy, fw, fh) in enumerate((
                (0.06, 0.05, 0.50, 0.42), (0.60, 0.05, 0.34, 0.20),
                (0.60, 0.29, 0.34, 0.18), (0.06, 0.52, 0.30, 0.43),
                (0.40, 0.52, 0.54, 0.43))):
            f.append(f"drawbox=x={int(w * fx)}:y={art_top + int(ah * fy)}"
                     f":w={int(w * fw)}:h={int(ah * fh)}"
                     f":color={ink if i % 2 == 0 else sub}@0.7:t=fill")
    elif shape == "cols":
        for i in range(7):
            f.append(f"drawbox=x={int(w * 0.06) + i * int(w * 0.13)}"
                     f":y={art_top + int(ah * 0.10)}:w={int(w * 0.09)}"
                     f":h={int(ah * 0.80)}:color={ink}@{0.25 + 0.09 * i:.2f}:t=fill")
    else:  # dots
        for r in range(5):
            for c in range(4):
                s = int(w * 0.08)
                f.append(f"drawbox=x={int(w * 0.10) + c * int(w * 0.22)}"
                         f":y={art_top + int(ah * 0.08) + r * int(ah * 0.18)}"
                         f":w={s}:h={s}:color={sub if (r * c) % 2 else ink}@0.8:t=fill")

    # 비운 칸의 경계 — 진짜 그림이 이 선을 넘었는지 비교하는 기준
    f.append(f"drawbox=x=0:y={art_top}:w={w}:h=3:color={ink}@0.30:t=fill")
    f.append(f"drawbox=x=0:y={art_bot - 3}:w={w}:h=3:color={ink}@0.30:t=fill")
    return ",".join(f)


def main() -> int:
    console.init()
    ap = argparse.ArgumentParser(prog="placeholder_art.py")
    ap.add_argument("slug")
    ap.add_argument("--force", action="store_true",
                    help="이미 있는 그림도 덮어쓴다")
    a = ap.parse_args()

    import json
    sj = paths.script_json(a.slug)
    if not sj.exists():
        print("먼저 「대본」 단계를 돌리세요.")
        return 2
    scenes = json.loads(sj.read_text(encoding="utf-8")).get("scenes") or []
    if not scenes:
        print("씬이 없습니다.")
        return 2

    w, h = (int(x) for x in str(config.get("image.size", "1024x1536")).split("x"))
    top = round(h * int(config.get("image.reserve_top_pct", 15)) / 100)
    bot = round(h * int(config.get("image.reserve_bottom_pct", 15)) / 100)
    ivory = config.get("compose.ivory", "#F6F1E8").lstrip("#")
    ink = config.get("compose.ink", "#1F4E79").lstrip("#")
    sub = config.get("compose.sub_ink", "#9DC3E6").lstrip("#")

    # 장면 지시가 있으면 칸 수를 읽는다. 없으면 한 칸(예전과 같음).
    cells: dict = {}
    sp = paths.art_spec(a.slug)
    if sp.exists():
        try:
            for r in (json.loads(sp.read_text(encoding="utf-8")).get("scenes") or []):
                cells[int(r.get("no") or 0)] = max(1, len(r.get("cells") or []) or 1)
        except Exception:  # noqa: BLE001
            cells = {}

    out_dir = paths.art_dir(a.slug)
    out_dir.mkdir(parents=True, exist_ok=True)
    made = []
    for s in scenes:
        no = int(s.get("no") or 0)
        nc = cells.get(no, 1)
        dst = out_dir / f"{no:03d}.png"
        if dst.exists() and not a.force:
            print(f"  {dst.name} 이미 있음 — 건너뜀 (--force 로 덮어쓰기)")
            continue
        # 칸마다 다른 무늬. 무늬 번호를 씬·칸으로 굴려 옆 칸과 안 같게 한다.
        parts = []
        for k in range(nc):
            parts.append(_filters(no + k, w, h, top, bot, ivory,
                                  f"0x{ink}", f"0x{sub}"))
        if nc == 1:
            cmd = ["ffmpeg", "-y", "-loglevel", "error",
                   "-f", "lavfi", "-i", f"color=c=0x{ivory}:s={w}x{h}",
                   "-vf", parts[0], "-frames:v", "1", str(dst)]
        else:
            # 칸을 위아래로 이어 붙인다 — vstack 이 두루마리를 만든다.
            cmd = ["ffmpeg", "-y", "-loglevel", "error"]
            for _ in range(nc):
                cmd += ["-f", "lavfi", "-i", f"color=c=0x{ivory}:s={w}x{h}"]
            chain = "".join(f"[{k}:v]{parts[k]}[c{k}];" for k in range(nc))
            chain += "".join(f"[c{k}]" for k in range(nc))
            chain += f"vstack=inputs={nc}[v]"
            cmd += ["-filter_complex", chain, "-map", "[v]",
                    "-frames:v", "1", str(dst)]
        subprocess.run(cmd, check=True)
        made.append(dst.name)
        print(f"  {dst.name} ({w}x{h * nc}, 칸 {nc}개, 칸마다 위 {top}px / "
              f"아래 {bot}px 비움)")

    print(f"자리표시 {len(made)}장. 이제 「컴포지션」→「빌드」를 돌려 보세요.")
    if any(v > 1 for v in cells.values()):
        print("칸이 여러 개인 씬이 있습니다 — 미리보기에서 카메라가 칸을 뛰는지 보세요.")
    print("아스트라 장면(001.svg)을 받으면 그쪽이 자동으로 우선합니다.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
