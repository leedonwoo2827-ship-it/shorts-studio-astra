# -*- coding: utf-8 -*-
"""콘솔 출력 인코딩 — 모든 진입점이 맨 먼저 부른다.

**왜 필요한가.** Windows 기본 콘솔은 cp949 다. 한글은 되지만 `—`(U+2014),
`★`, `→` 같은 글자에서 `UnicodeEncodeError` 로 **프로그램이 죽는다.** 실제로
smoke_claude 가 마지막 성공 메시지를 찍다가 죽었다 — 검사는 다 통과한 뒤였다.

★ `errors="replace"` 를 쓴다. 로그 한 줄이 예쁘지 않은 것과 작업이 죽는 것 중
  후자가 훨씬 나쁘다. 진짜 결과는 언제나 파일로 남기고(tts_bridge 규약),
  콘솔은 진행 표시용으로만 쓴다.
"""
from __future__ import annotations

import sys


def init() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
        except Exception:  # noqa: BLE001 — 파이프로 연결된 경우 등. 죽이지 않는다
            pass
