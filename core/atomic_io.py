"""원자적 파일 쓰기.

평범한 `open("w") + json.dump` 는 첫 쓰기에서 파일을 잘라 버리고 그 다음에 내용을
채운다. 그 사이에 프로세스가 죽으면 잘린 파일 또는 빈 파일이 남는다. 우리가 쓰는
대상은 BOOK 트리의 원천 데이터(240문항)라서 그건 곧 데이터 유실이다.

임시 형제 파일에 쓰고 fsync 한 뒤 `os.replace` 로 갈아 끼운다.

★ aim-local 원본에서 두 곳을 고쳤다. 둘 다 바이트 충실도 문제다.
  1) `ensure_ascii=False` — 원본은 기본값(True)이라 한글이 \\uXXXX 로 escape 된다.
     실측한 02/_index.json 은 한글이 그대로 들어 있다.
  2) `newline=""`      — 원본은 텍스트 모드 기본 개행 변환을 쓴다. 개행을 우리가
     정하고 파이썬이 손대지 못하게 한다.

★★ 개행은 **파일에서 감지한다** (2026-08-03). 상수로 두면 안 된다.

   업로드본은 "02/*.md 는 LF 전용" 을 상수로 박아 뒀다. 그건 원격 세션(리눅스)에서
   측정한 값이고, 이 PC 의 같은 파일들은 **CRLF** 다 — 240개 md · 두 색인 ·
   05/lesson 24개 전부. 반대로 `_rounds/*.json` 과 `03/*.md` 는 LF 다.
   같은 트리 안에서 갈린다. 원인은 만든 쪽 파이썬이 텍스트 모드로 썼는지 여부이고
   (Windows 텍스트 모드가 "\\n" → "\\r\\n" 으로 바꾼다), 우리가 고를 문제가 아니다.

   그래서 규칙은 하나다 — **읽은 파일의 개행을 그대로 다시 쓴다.**
   · LF 로 강제하면 이 PC 의 266개 파일이 첫 저장에서 전부 바뀐다.
   · CRLF 로 강제하면 리눅스에서 다시 동기화된 다음 판이 전부 바뀐다.
   · 감지하면 어느 쪽이 와도 그 파일만 손댄다. 왕복 검증도 그때 비로소 의미가 있다.
"""

from __future__ import annotations

import json
import os
from typing import Any, Optional

LF = "\n"
CRLF = "\r\n"


def file_newline(path: str) -> Optional[str]:
    """디스크 파일이 쓰는 개행. 파일이 없거나 개행이 없으면 None.

    첫 개행 하나만 본다 — 섞여 있는 파일은 우리 대상에 없고, 있다면 그건 이미
    손상이라 감지가 아니라 진단이 필요한 상황이다(왕복 검증이 잡는다).
    """
    try:
        with open(path, "rb") as f:
            head = f.read(65536)
    except OSError:
        return None
    i = head.find(b"\n")
    if i < 0:
        return None
    return CRLF if i > 0 and head[i - 1:i] == b"\r" else LF


def with_newline(text: str, newline: str) -> str:
    """text 의 개행을 newline 하나로 통일한다. 먼저 LF 로 접고 다시 펼친다 —
    바로 치환하면 이미 CRLF 인 줄이 CRCRLF 가 된다."""
    flat = text.replace(CRLF, LF)
    return flat if newline == LF else flat.replace(LF, newline)


def atomic_write_json(
    path: str,
    data: Any,
    *,
    indent: Optional[int] = None,
    trailing_newline: bool = False,
) -> None:
    """`data` 를 JSON 으로 원자적으로 저장한다.

    임시 파일 이름에 PID 를 붙여, 같은 파일을 저장하는 두 프로세스가 rename
    대상에서 충돌하지 않게 한다.

    trailing_newline: 실측한 02/_index.json · difficulty_stats.json 은 끝에 개행이
        **없다**. 기본을 False 로 둔 이유다. 개행을 붙이는 파일이 생기면 그때 켠다.
    """
    text = json.dumps(data, ensure_ascii=False, indent=indent)
    if trailing_newline:
        text += "\n"
    atomic_write_text(path, text)


def atomic_write_text(path: str, text: str) -> None:
    """텍스트를 원자적으로 저장한다. 개행은 문자열 그대로 나간다 — 손대지 않는다.

    ★ 개행 결정은 이 함수의 일이 아니다. `services.book.paths.to_disk()` 한 곳에서
      정하고 호출자가 이미 맞춘 문자열을 넘긴다. 두 군데서 바꾸면 CRCRLF 가 된다.
    """
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = f"{path}.tmp.{os.getpid()}"
    with open(tmp, "w", encoding="utf-8", newline="") as f:
        f.write(text)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def backup_sibling(path: str, suffix: str = ".bak") -> bool:
    """저장 전 .bak 형제를 남긴다. 실패해도 저장을 막지 않는다."""
    if not os.path.isfile(path):
        return False
    try:
        with open(path, "rb") as src, open(path + suffix, "wb") as dst:
            dst.write(src.read())
        return True
    except OSError:
        return False
