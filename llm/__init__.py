# -*- coding: utf-8 -*-
"""LLM 진입점 — 여기 말고 다른 데서 프로바이더를 만들지 않는다.

이 레포가 부르는 모델은 **Claude Code 구독 OAuth** 하나뿐이다. API 키를 쓰지 않고,
`ANTHROPIC_API_KEY` 같은 오래된 환경변수는 무력화한다(`scrubbed_env`).

그림 쪽 인증(ChatGPT)은 `imagegen/` 이 따로 들고 있다. **두 인증은 서로의 경로를
읽지 않고, 같은 프로세스에서 돌지도 않는다.** 섞으면 사고가 난다.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from core import config
from .claude_provider import ClaudeProvider, find_cli, status  # noqa: F401
from .errors import NotAuthenticated, ProviderError, QuotaExceeded  # noqa: F401


def budget_for(stage: str) -> float:
    """이 단계에 허용할 돈. `budget_usd.<단계>` 가 있으면 그것이 이긴다.

    ★ 단계마다 드는 값이 다르다. 실측(2026-09-08): 「원고」 단계는 16,212자를
      읽고 HTML 원고를 통째로 써 내므로 출력 토큰이 커서 공통 상한 $1.5 를
      **넘겨 죽었다**(`Reached maximum budget`). 반면 「자막」·「결과」는 훨씬
      싸다. 공통 상한 하나로 묶으면 비싼 단계가 못 돌거나 싼 단계에 과한 여유를
      준다 — 그래서 단계별로 덮을 수 있게 둔다.
    """
    v = config.get(f"budget_usd.{stage}")
    if v is None:
        v = config.get("budget_usd.per_stage", 1.5)
    return float(v)


def provider(stage: str, *, on_activity=None) -> ClaudeProvider:
    """단계 이름으로 모델·추론강도·예산을 골라 프로바이더를 만든다."""
    return ClaudeProvider(
        model=config.get(f"models.{stage}", "") or "",
        effort=config.get(f"effort.{stage}") or None,
        budget_usd=budget_for(stage),
        on_activity=on_activity,
    )


def structured(stage: str, system: str, user: str, schema: Dict[str, Any],
               *, on_activity=None) -> tuple[Dict[str, Any], float]:
    """한 번 부르고 (결과, 비용) 을 준다.

    ★ **호출당 최소 비용이 붙는다.** 씬마다 따로 부르지 말고 한 번에 묶어라.
    """
    p = provider(stage, on_activity=on_activity)
    out = p.structured(system, [{"role": "user", "content": user}], schema=schema)
    return out, float(getattr(p, "last_cost_usd", 0.0) or 0.0)
