# -*- coding: utf-8 -*-
"""설정 — 한 곳에서만 읽는다.

우선순위: 환경변수 → config.local.json → config.json → 코드 기본값.

`config.local.json` 은 **이 PC 것**이다(gitignore). `setup.bat` 이 기계마다 다른
값(파이썬 경로 등)만 여기에 적는다. 레포에 든 `config.json` 은 손대지 않는다.

★ 이 레포는 **다른 폴더를 참조하지 않는다.** 모든 경로는 레포 안이거나,
  사용자가 config 에 직접 적은 것뿐이다.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict

ROOT = Path(__file__).resolve().parents[1]

_DEFAULTS: Dict[str, Any] = {
    "port": 8899,
    # 씬 수는 기본값이 없다 — 재료가 정한다. `cuts_max` 는 상한일 뿐이다.
    "shorts": {"format": "narrative", "seconds_min": 20.0, "seconds_max": 30.0,
               "cuts_max": 8, "cue_max": 26, "cue_max_listicle": 12,
               "gap_sec": 0.12},
    "narration": {"chars_per_sec": 6.51, "voice": "F2", "speed": 1.2, "total_step": 8},
    "compose": {"width": 1080, "height": 1920, "fps": 30,
                "band_top": 300, "band_bottom": 320,
                "ivory": "#F6F1E8", "ink": "#1F4E79",
                "accent": "#E07A2F", "text": "#334155", "sub_ink": "#9DC3E6"},
    "image": {"size": "1024x1536", "format": "png",
              "reserve_top_pct": 15, "reserve_bottom_pct": 15,
              "concurrency": 2, "retries": 2},
    "render": {"quality": "standard", "format": "mp4", "workers": 0},
    "tts": {"engine": "edge", "timeout_ms": 300000},
    "models": {"draft": "claude-opus-5", "script": "claude-opus-5",
               "artspec": "claude-opus-5", "meta": "claude-sonnet-5"},
    "effort": {"draft": "high", "script": "high",
               "artspec": "high", "meta": "medium"},
    "budget_usd": {"per_stage": 1.5, "warn_total": 5.0},
    # 작업물이 쌓이는 루트. 비워 두면 레포 안 `projects/`.
    "paths": {"projects_root": ""},
}

# 환경변수로 덮을 수 있는 것만 — 나머지는 파일로만 바꾼다
_ENV = {
    "SHORTS_PORT": ("port", int),
    "SHORTS_FORMAT": ("shorts.format", str),
    "SHORTS_TTS_ENGINE": ("tts.engine", str),
    "SHORTS2_PROJECTS_ROOT": ("paths.projects_root", str),
}


def _merge(base: Dict[str, Any], over: Dict[str, Any]) -> Dict[str, Any]:
    """딕셔너리는 파고들어 합치고, 나머지는 덮는다."""
    out = dict(base)
    for k, v in (over or {}).items():
        if k.startswith("_"):          # _주석 같은 메모는 흘려보낸다
            continue
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


def _read(path: Path) -> Dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except Exception as e:  # noqa: BLE001
        raise RuntimeError(f"{path.name} 를 읽지 못했습니다: {e}") from e


_cache: Dict[str, Any] | None = None


def load(reload: bool = False) -> Dict[str, Any]:
    global _cache
    if _cache is not None and not reload:
        return _cache
    cfg = _merge(_DEFAULTS, _read(ROOT / "config.json"))
    cfg = _merge(cfg, _read(ROOT / "config.local.json"))
    for env_key, (dotted, cast) in _ENV.items():
        raw = os.environ.get(env_key)
        if raw is None or raw == "":
            continue
        node = cfg
        parts = dotted.split(".")
        for p in parts[:-1]:
            node = node.setdefault(p, {})
        try:
            node[parts[-1]] = cast(raw)
        except Exception:  # noqa: BLE001
            pass
    _cache = cfg
    return cfg


def get(dotted: str, default: Any = None) -> Any:
    """`get("compose.width")` 처럼 점으로 파고든다."""
    node: Any = load()
    for part in dotted.split("."):
        if not isinstance(node, dict) or part not in node:
            return default
        node = node[part]
    return node


def seconds_range() -> tuple[float, float]:
    """목표 길이 범위 `(min, max)`. 사람이 정하는 둘 중 하나다(다른 하나는 형식).

    예전 `shorts.seconds` 하나만 있는 설정 파일도 읽는다 — 그 값을 max 로 본다.
    """
    lo = get("shorts.seconds_min")
    hi = get("shorts.seconds_max")
    if hi is None:
        hi = get("shorts.seconds", 30.0)      # 옛 설정
    if lo is None:
        lo = max(1.0, float(hi) - 10.0)
    return float(lo), float(hi)


def budget_chars(cuts: int | None = None) -> int:
    """대본 글자 예산.

        (목표 초 - 씬 사이 숨 합) x 실측 낭독속도 x 배속

    ★ 숨을 빼는 이유 — 씬이 3개면 사이가 2개고, 그 시간에는 아무 말도 안 한다.
      안 빼면 대본이 목표보다 그만큼 길어지고, 30초에 맞추려던 영상이 넘친다.

    ★ 예산은 `seconds_max` 로 넉넉히 잡는다. 대본이 재료가 부르는 만큼 담게 두고,
      실제 길이는 **음성 실측**이 정한다 — 여기서 조여 놓으면 씬 수를 손으로 정하던
      옛 문제가 이름만 바꿔 돌아온다.

    ★ `cuts` 를 주면 그 씬 수의 숨을 뺀다. 안 주면 상한(`cuts_max`)으로 본다 —
      숨을 넉넉히 빼는 쪽이 안전하다(예산이 조금 작아진다).

    ★ `chars_per_sec` 는 **엔진마다 다르다.** config 의 `_실측` 메모를 보라.
      TTS 엔진을 바꾸면 한 편 굽고 다시 재서 이 값을 갱신해야 한다.
    """
    n = int(cuts or get("shorts.cuts_max", 8))
    breath = max(0, n - 1) * float(get("shorts.gap_sec", 0.12))
    speakable = max(1.0, seconds_range()[1] - breath)
    return round(speakable
                 * get("narration.chars_per_sec", 6.51)
                 * get("narration.speed", 1.2))
