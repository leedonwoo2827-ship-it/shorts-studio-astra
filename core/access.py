# -*- coding: utf-8 -*-
"""접속 범위 — **누가 무엇을 누를 수 있나.**

이 도구는 사용자 본인의 Claude 구독으로 돈다. 브라우저는 리모컨일 뿐이고, 실제
호출은 서버가 도는 PC 에서 그 PC 주인의 자격증명으로 나간다. 그래서 LAN 에 그냥
열면 **팀원의 요청을 내 구독으로 대행**하는 것이 되고, 그것은 Anthropic 약관이
금지하는 바로 그것이다:

    "Anthropic does not permit third-party developers to offer Claude.ai login
     into their own applications, or to route requests through Free, Pro, or Max
     plan credentials on behalf of their users."
    — code.claude.com/docs/en/legal-and-compliance

반대로 **본인이 본인 구독으로 쓰는 것**은 명시적으로 허용된다. 그래서 규칙은 하나다:

    루프백(127.0.0.1)에서 온 요청  →  전부 허용        내가 내 것을 쓴다
    그 밖의 주소에서 온 요청        →  **읽기 전용**    보고 받아가기만

읽기 전용이면 대행이 아니다 — 이미 만들어진 것을 보여 주는 것뿐이고, 그 사이에
모델 호출이 한 번도 일어나지 않는다. 팀원이 직접 만들려면 자기 PC 에서 자기
Claude 로그인으로 돌리면 된다(`setup.bat` 이 그것을 위해 있다).
"""
from __future__ import annotations

import ipaddress
import os
from typing import Optional

# 읽기 전용 손님도 부를 수 있는 것. **모델을 부르지 않는 것만** 여기 들어온다.
GUEST_GET_PREFIXES = (
    "/",
    "/static/",
    "/vendor/",
    "/api/projects",          # 목록 · 상세 · 미리보기 · 영상 · 자막 · 마크다운
    "/api/jobs/",             # 진행 상황 구경
    "/api/dict",              # 발음사전 보기
    "/api/llm/status",        # 연결 상태 칩 (호출 아님)
    "/api/imagegen/status",   # 그림 로그인 상태 칩 (호출 아님)
    "/api/stages",            # 파이프라인 표
    "/api/config",            # 화면이 뜨는 데 필요하다 — 규격·엔진 이름뿐이고
                              # 경로나 자격증명은 담지 않는다(server.get_config)
)


def lan_enabled() -> bool:
    return (os.environ.get("SHORTS_LAN") or "").strip() not in ("", "0", "false", "False")


def host() -> str:
    """묶을 주소. LAN 을 켜지 않으면 루프백에만 묶는다."""
    return "0.0.0.0" if lan_enabled() else "127.0.0.1"


def is_local(client_host: Optional[str]) -> bool:
    if not client_host:
        return False
    try:
        return ipaddress.ip_address(client_host).is_loopback
    except ValueError:
        return client_host in ("localhost", "::1")


def guest_may(method: str, path: str) -> bool:
    """읽기 전용 손님이 이 요청을 해도 되는가.

    ★ `"/"` 는 **정확히 일치할 때만** 통과시킨다. `startswith("/")` 로 보면
      모든 GET 이 통과해 목록이 장식이 된다 — 실제로 그랬다. 지금은 비밀
      GET 이 없어서 사고가 아니지만, 새 GET 을 하나 더할 때 사고가 된다.
    """
    if method.upper() not in ("GET", "HEAD"):
        return False
    for p in GUEST_GET_PREFIXES:
        if path == p:
            return True
        if p.endswith("/") and len(p) > 1 and path.startswith(p):
            return True
        if not p.endswith("/") and len(p) > 1 and path.startswith(p + "/"):
            return True
    return False


DENY_MESSAGE = (
    "이 화면은 다른 PC 에서는 **보기만** 됩니다.\n\n"
    "만드는 단계는 이 도구를 띄운 PC 주인의 Claude 구독으로 실행됩니다. "
    "그것을 대신 돌려 주는 것은 Anthropic 약관이 금지합니다.\n\n"
    "직접 만들려면 이 저장소를 받아 setup.bat 을 실행하고, "
    "터미널에서 claude 로 한 번 로그인하세요 — 그러면 본인 구독으로 돕니다."
)
