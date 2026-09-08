# -*- coding: utf-8 -*-
"""S4 자막 — SRT + 큐. **모델을 부르지 않는다(무료).**

씬 하나의 자막을 **읽을 수 있는 덩어리(큐)로 쪼개고**, 그 씬의 실측 음성 길이를
글자 수 비율로 나눠 준다. 낱말 단위 정렬(whisper)을 쓰지 않는 이유는 30초짜리에
그 무게를 지고 갈 값이 없기 때문이다 — 글자 비율로도 눈에 어긋나지 않는다.

    씬 3  audio_sec 5.30   "우편 요금이 1페니로 통일되자 / 지식도 편지를 타기 시작했습니다"
                            ├ 0.00~2.42 (16자)
                            └ 2.42~5.30 (19자)

★ 쪼개는 자리는 **띄어쓰기와 쉼표**다. 낱말 가운데를 자르지 않는다.
★ SRT 사본에는 **UTF-8 BOM** 을 붙인다. 없으면 윈도우 플레이어가 cp949 로 오탐해
  그럴듯하게 깨진 한글을 보여 준다 — 깨진 걸 알아채기 어려운 종류의 깨짐이다.
"""
from __future__ import annotations

import csv
import json
import re
from typing import Any, Dict, List, Tuple

from core import config, paths
from core.atomic_io import atomic_write_json, atomic_write_text

# 세로 화면 아래 띠는 두 줄까지 읽힌다. 한 줄 ~13자 × 2 = 26자에서 끊는다.
CUE_MAX = 26
CUE_MIN = 8
_SPLIT = re.compile(r"(?<=[,·;:])\s+|\s+")


def split_cues(text: str, limit: int = CUE_MAX) -> List[str]:
    """낱말을 지키면서 `limit` 자 안팎으로 쪼갠다."""
    text = re.sub(r"\s+", " ", (text or "").strip())
    if not text:
        return []
    words = [w for w in _SPLIT.split(text) if w]
    cues: List[str] = []
    cur = ""
    for w in words:
        cand = f"{cur} {w}".strip()
        if cur and len(cand) > limit:
            cues.append(cur)
            cur = w
        else:
            cur = cand
    if cur:
        # 마지막 조각이 너무 짧으면 앞에 붙인다 — 한 낱말만 깜빡이면 산만하다.
        # 단 **붙여서 한도를 넘기면 붙이지 않는다** — 한도를 넘긴 자막은 화면에서
        # 세 줄이 되어 그림칸을 먹는다. 짧은 큐가 그보다 낫다.
        merged = f"{cues[-1]} {cur}" if cues else ""
        if cues and len(cur) < CUE_MIN and len(merged) <= limit:
            cues[-1] = merged
        else:
            cues.append(cur)
    return cues


def _spread(cues: List[str], dur: float) -> List[Tuple[float, float]]:
    """글자 수 비율로 시간을 나눈다. 합은 정확히 `dur` 이다."""
    if not cues:
        return []
    weights = [max(1, len(c)) for c in cues]
    total = sum(weights)
    spans: List[Tuple[float, float]] = []
    acc = 0.0
    for i, w in enumerate(weights):
        seg = dur * w / total
        start = acc
        end = dur if i == len(weights) - 1 else round(acc + seg, 3)
        spans.append((round(start, 3), end))
        acc = end
    return spans


def _ts(sec: float) -> str:
    sec = max(0.0, float(sec))
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    return f"{int(h):02d}:{int(m):02d}:{s:06.3f}".replace(".", ",")


def run(slug: str) -> Dict[str, Any]:
    doc = _load(slug)
    scenes = doc.get("scenes") or []
    gap = float(config.get("shorts.gap_sec", 0.12))

    clock = 0.0
    srt_rows: List[str] = []
    csv_rows: List[List[Any]] = []
    idx = 0
    for s in scenes:
        no = int(s.get("no") or 0)
        dur = float(s.get("audio_sec") or 0.0)
        if dur <= 0:
            # 음성이 아직 없으면 예산으로 임시 배치한다 — 화면에서 흐름은 볼 수 있다
            cps = config.get("narration.chars_per_sec", 6.51) * config.get("narration.speed", 1.2)
            dur = round(len(s.get("narration_text") or s.get("srt_text") or "") / max(cps, 0.1), 2)
            s["audio_estimated"] = True
        else:
            s.pop("audio_estimated", None)

        s["start_sec"] = round(clock, 3)
        s["dur_sec"] = round(dur, 3)

        cues = split_cues(s.get("srt_text") or "")
        spans = _spread(cues, dur)
        s["cues"] = [{"t": st, "d": round(en - st, 3), "text": c}
                     for c, (st, en) in zip(cues, spans)]

        for c, (st, en) in zip(cues, spans):
            idx += 1
            srt_rows.append(f"{idx}\n{_ts(clock + st)} --> {_ts(clock + en)}\n{c}\n")
            csv_rows.append([no, idx, round(clock + st, 3), round(clock + en, 3),
                             round(en - st, 3), c])

        clock += dur + gap

    total = round(max(0.0, clock - gap), 3)
    doc["total_sec"] = total
    atomic_write_json(str(paths.script_json(slug)), doc, indent=2)

    # ★ BOM — 없으면 cp949 오탐이 「그럴듯하게 깨진 한글」을 만든다
    atomic_write_text(str(paths.srt(slug)), "﻿" + "\n".join(srt_rows))

    cue_path = paths.cue_csv(slug)
    cue_path.parent.mkdir(parents=True, exist_ok=True)
    with open(cue_path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["씬", "큐", "시작(초)", "끝(초)", "길이(초)", "자막"])
        w.writerows(csv_rows)

    return {"cues": idx, "total_sec": total,
            "estimated": [int(s["no"]) for s in scenes if s.get("audio_estimated")]}


def _load(slug: str) -> Dict[str, Any]:
    p = paths.script_json(slug)
    if not p.exists():
        raise FileNotFoundError("먼저 「대본」 단계를 돌리세요.")
    return json.loads(p.read_text(encoding="utf-8"))
