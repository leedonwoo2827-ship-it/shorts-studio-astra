# -*- coding: utf-8 -*-
"""레포 자체 점검 — 조용히 망가지는 종류만 본다.

    python tools/lint_repo.py

문법 검사기가 잡아 주는 것은 여기서 다시 보지 않는다. 여기서 보는 것은
**돌기는 도는데 틀린** 것들이다.

1. **소스에 섞인 제어문자.** 실측(2026-09-08): `s7_compose.py` 의 정규식에
   단어경계 escape 가 **백스페이스 문자(0x08)** 로 들어가, 패턴이 조용히
   아무것도 못 잡았다. 문법 오류도 아니고 예외도 안 났다 — 장면이 칸을 뚫고
   나온 화면을 보고서야 알았다. 자동으로 파일을 고치는 작업에서 반복되는 실수다.

2. **.bat 의 CRLF 와 ASCII.** LF 로 저장된 배치 파일은 cmd.exe 가 라벨과 goto 를
   잘못 읽어 「지정된 파일을 찾을 수 없습니다」로 죽는다. 한글이 섞이면 cp949
   콘솔에서 라벨이 깨져 **읽을 수 없는 안내문**이 된다.

3. **.bat 의 `echo` 안 리다이렉션.** `echo A -> B` 는 화면에 안 뜨고 `B` 라는
   파일을 만든다. 실측: `Claude`·`ChatGPT` 두 파일이 레포 뿌리에 생겼다.

4. **GSAP 유료 플러그인.** `drawSVG` 같은 Club 플러그인은 무료 빌드에 없고,
   없으면 예외도 없이 **아무 일도 안 일어난다.**
"""
from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import List, Tuple

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from core import console  # noqa: E402

SKIP_DIRS = {"node_modules", ".venv-app", ".venv", "__pycache__", "projects",
             "_plan", ".git", "_spike"}

CTRL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")
# `echo ... > x` 는 리다이렉션. `^>` 로 이스케이프했거나 `>>`·`>nul` 은 정상.
BAT_ECHO = re.compile(r"^\s*echo\b.*?(?<!\^)>(?!>|nul)", re.IGNORECASE)
CLUB = ("drawSVG", "MorphSVG", "SplitText", "ScrollSmoother", "MotionPathHelper")


def walk(*globs: str):
    for g in globs:
        for p in ROOT.rglob(g):
            if SKIP_DIRS & set(p.parts):
                continue
            yield p


def main() -> int:
    console.init()          # cp949 콘솔에서 한글·기호가 죽는 것을 막는다
    bad: List[Tuple[str, str]] = []

    # 1. 제어문자
    for p in walk("*.py", "*.js", "*.j2", "*.css", "*.html", "*.mjs"):
        try:
            text = p.read_text(encoding="utf-8")
        except Exception:  # noqa: BLE001
            continue
        for i, line in enumerate(text.splitlines(), 1):
            if CTRL.search(line):
                bad.append((f"{p.relative_to(ROOT)}:{i}",
                            f"제어문자가 섞였습니다 — {line.strip()[:80]!r}"))

    # 2·3. 배치 파일
    for p in walk("*.bat"):
        raw = p.read_bytes()
        rel = str(p.relative_to(ROOT))
        if b"\r\n" not in raw:
            bad.append((rel, "CRLF 가 아닙니다 — cmd.exe 가 goto/라벨을 잘못 읽습니다"))
        try:
            raw.decode("ascii")
        except UnicodeDecodeError:
            bad.append((rel, "ASCII 가 아닙니다 — cp949 콘솔에서 안내문이 깨집니다"))
        for i, line in enumerate(raw.decode("utf-8", "replace").splitlines(), 1):
            if BAT_ECHO.search(line):
                bad.append((f"{rel}:{i}",
                            f"echo 안의 > 가 리다이렉션입니다 (^> 로 쓰세요) — "
                            f"{line.strip()[:70]!r}"))

    # 4. GSAP 유료 플러그인
    for p in walk("*.j2", "*.js", "*.html"):
        if "vendor" in p.parts:
            continue
        try:
            text = p.read_text(encoding="utf-8")
        except Exception:  # noqa: BLE001
            continue
        for i, line in enumerate(text.splitlines(), 1):
            if line.lstrip().startswith(("#", "//", "/*", "*", "{#")):
                continue                      # 주석에서 「쓰지 말라」고 적은 것은 통과
            for name in CLUB:
                if name in line:
                    bad.append((f"{p.relative_to(ROOT)}:{i}",
                                f"{name} 은 GSAP 유료 플러그인입니다 — "
                                f"무료 빌드에서는 조용히 아무 일도 안 합니다"))

    if not bad:
        print("점검 통과 — 조용히 망가지는 것은 없습니다.")
        return 0
    print(f"{len(bad)}건:")
    for where, why in bad:
        print(f"  {where}\n      {why}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
