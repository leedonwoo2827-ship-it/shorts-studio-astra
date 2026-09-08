# -*- coding: utf-8 -*-
"""그림 쪽 인증 상태 — **누르기 전에 알려 준다.**

★ `codex login status` 를 믿지 말 것. 그것은 파일이 있는지만 본다.
  실측(2026-09-08): access_token 은 8월 20일에 만료되고 refresh_token 도 죽은
  상태였는데 `codex login status` 는 「Logged in using ChatGPT」라고 답했다.
  그 말을 믿고 그림 단계를 눌러 3장 x 3회 재시도를 다 태우고 나서야 401 을 봤다.

  그래서 여기서는 **토큰의 만료 시각을 직접 읽는다.** JWT 의 `exp` 클레임만
  본다 — 서명을 검증하지도, 내용을 어디로 보내지도 않는다.

★ 이 파일도 `~/.codex/auth.json` 만 읽는다. Claude 쪽 경로는 열지 않는다.
"""
from __future__ import annotations

import base64
import json
import os
import time
from pathlib import Path
from typing import Any, Dict, Optional

AUTH_PATH = Path(os.environ.get("CODEX_AUTH_PATH",
                                str(Path.home() / ".codex" / "auth.json")))

# 만료가 이만큼 안 남았으면 「곧 만료」로 본다. 그림 3장이 몇 분 걸린다.
SOON_SEC = 10 * 60


def _exp(token: str) -> Optional[int]:
    """JWT 의 `exp` 만 꺼낸다. 서명은 보지 않는다 — 우리 것이 아니다."""
    if token.count(".") != 2:
        return None
    body = token.split(".")[1]
    body += "=" * (-len(body) % 4)
    try:
        claims = json.loads(base64.urlsafe_b64decode(body))
    except Exception:  # noqa: BLE001
        return None
    exp = claims.get("exp")
    return int(exp) if isinstance(exp, (int, float)) else None


def status() -> Dict[str, Any]:
    """`ok` 가 참일 때만 그림 단계를 눌러 볼 값이 있다."""
    out: Dict[str, Any] = {
        "provider": "chatgpt",
        "label": "ChatGPT (구독 OAuth)",
        "path": str(AUTH_PATH),
        "installed": AUTH_PATH.is_file(),
        "ok": False,
        "expires_at": None,
        "message": "",
        "how": "터미널에서 `codex login` 을 실행해 ChatGPT 계정으로 로그인하세요.",
    }
    if not out["installed"]:
        out["message"] = "~/.codex/auth.json 이 없습니다 — 아직 로그인하지 않았습니다."
        return out

    try:
        data = json.loads(AUTH_PATH.read_text(encoding="utf-8"))
    except Exception as e:  # noqa: BLE001
        out["message"] = f"auth.json 을 읽지 못했습니다: {e}"
        return out

    tokens = data.get("tokens") if isinstance(data.get("tokens"), dict) else {}
    access = tokens.get("access_token")
    refresh = tokens.get("refresh_token")
    if not isinstance(access, str) or not access:
        out["message"] = "auth.json 에 access_token 이 없습니다."
        return out
    out["has_refresh"] = bool(refresh)

    exp = _exp(access)
    now = int(time.time())
    if exp is None:
        # 만료를 알 수 없으면 막지 않는다 — 형식이 바뀌었을 수도 있다
        out["ok"] = True
        out["message"] = "만료 시각을 읽을 수 없습니다. 그냥 시도합니다."
        return out

    out["expires_at"] = time.strftime("%Y-%m-%d %H:%M", time.localtime(exp))
    if exp <= now:
        days = (now - exp) // 86400
        out["message"] = (f"토큰이 {out['expires_at']} 에 만료되었습니다"
                          f"({days}일 지남). 다시 로그인해야 그림을 받을 수 있습니다.")
        if not refresh:
            out["message"] += " refresh_token 도 없습니다."
        return out

    out["ok"] = True
    if exp - now < SOON_SEC:
        out["message"] = (f"토큰이 {out['expires_at']} 에 만료됩니다 — "
                          f"그림을 받는 중에 끊길 수 있습니다.")
    else:
        out["message"] = f"로그인됨 (토큰 {out['expires_at']} 까지)"
    return out
