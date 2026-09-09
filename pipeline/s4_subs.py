# -*- coding: utf-8 -*-
"""S4 자막 — SRT + 큐. **모델을 부르지 않는다(무료).**

씬 하나의 자막을 **읽을 수 있는 덩어리(큐)로 쪼개고**, 각 조각이 **실제로 그 말이
나오는 순간**에 뜨게 시각을 매긴다.

    씬 3  audio_sec 5.30   "우편 요금이 1페니로 통일되자 / 지식도 편지를 타기 시작했습니다"
                            ├ 0.00~2.42   ← marks: 문장1 첫 낱말
                            └ 2.42~5.30   ← marks: 문장2 첫 낱말 「지식도」 t=2.42

★ **문장을 앵커로 삼는다.** `s3_tts` 가 받아 온 `marks`(edge 의 `WordBoundary`)는
  **`narration_text`(발음교정본)의 어절**이고, 자막은 `srt_text` 에서 쪼갠다.
  둘은 글자가 다르다 — 「1840년」이 「천팔백사십 년」으로 읽히므로 낱말끼리는
  못 맞춘다. 그런데 **문장은 그대로 남는다.** 그래서 문장 경계만 마크에 붙이고,
  한 문장이 여러 조각으로 갈린 경우에만 그 문장 안에서 글자 수로 나눈다.

  실측(edge-tts 7.2.8, ko-KR-SunHiNeural, 네 표본): 마크 수 = `narration_text`
  어절 수가 **정확히 맞았고**, 문장별 어절 수로 마크를 순서대로 소비하면 문장
  경계가 제 낱말에 떨어졌다. 그래서 이 대응을 쓴다.

★ **못 맞추면 글자 수 비율로 물러선다** (`_spread`). 마크가 없는 엔진
  (voicewright)도 있고, 발음교정이 문장을 가르면 문장 수가 어긋난다. 그때는
  `cues_estimated` 를 세워 사람이 알 수 있게 한다. 조용히 틀리는 것이 가장 나쁘다.

★ 쪼개는 자리는 **띄어쓰기와 쉼표**다. 낱말 가운데를 자르지 않는다.

★ **조각 하나가 화면 한 컷이다.** 잘 도는 세로 쇼츠는 자막이 6~10자 조각으로
  흐르고 조각마다 화면이 바뀐다 — 컷당 1.5~2초, 30초에 15~20컷. 우리 v13 은
  씬 4개에 씬당 큐 2개라 컷이 4개였고, 그것이 「역동적이지 않다」의 정체였다.
  그래서 목록형은 한도를 12자로 줄인다(`shorts.cue_max_listicle`). 조각이
  잦아지면 컷이 잦아지고, 카메라가 그 경계에서 칸을 뛴다.

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

from . import s3_tts

# 세로 화면 아래 띠는 두 줄까지 읽힌다. 한 줄 ~13자 x 2 = 26자에서 끊는다.
# 목록형은 한 줄만 쓰고 잦게 끊는다 — 조각 하나가 컷 하나라서다.
CUE_MAX = 26
CUE_MIN = 8


def cue_limit(fmt: str = "") -> int:
    """자막 한 조각의 **강제 분할 한도**. 문장이 이보다 길면 그때만 쪼갠다."""
    if (fmt or "").strip() == "listicle":
        return int(config.get("shorts.cue_max_listicle", CUE_MAX))
    return int(config.get("shorts.cue_max", CUE_MAX))


_SPLIT = re.compile(r"(?<=[,·;:])\s+|\s+")
# 문장 끝. 한국어 종결부호 + 뒤에 공백이나 끝.
_SENT = re.compile(r"(?<=[.!?…])\s+|(?<=[.!?…])$")


def split_cues(text: str, limit: int = CUE_MAX) -> List[str]:
    """자막을 **문장 단위로** 자른다. 문장이 한도를 넘을 때만 더 쪼갠다.

    ★ **왜 문장 단위인가.** 실측(2026-09-08): 조각을 12자로 줄여 33초에 컷을
      23개 냈더니 「화면 전환이 너무 빠르다」는 판정이 나왔다.
      레퍼런스 쇼츠가 1.5~2초 컷인 것은 **실사 영상**이라 그 속도로 읽히기
      때문이고, 손으로 그린 벡터 도해는 읽는 데 시간이 더 걸린다.
      컷 수를 늘리는 것이 목표가 아니라 **읽히는 것**이 목표다.
    """
    return [c for g in split_cues_grouped(text, limit) for c in g]


def sentences(text: str) -> List[str]:
    """문장으로 나눈다. `srt_text` 와 `narration_text` 에 같은 자를 댄다."""
    text = re.sub(r"\s+", " ", (text or "").strip())
    if not text:
        return []
    return [s.strip() for s in _SENT.split(text) if s and s.strip()]


def split_cues_grouped(text: str, limit: int = CUE_MAX) -> List[List[str]]:
    """**문장마다 한 묶음**으로 조각을 낸다.

    묶음을 유지하는 것이 요점이다 — 시각을 붙일 때 「이 조각이 몇 번째 문장의
    것인가」를 알아야 문장 경계를 마크에 맞출 수 있다. 평탄화해 버리면 그 정보가
    사라지고, 그러면 다시 글자 수 비율밖에 쓸 것이 없다.
    """
    out: List[List[str]] = []
    for sent in sentences(text):
        if len(sent) <= limit:
            out.append([sent])
        else:
            out.append(_chop(sent, limit))   # 너무 긴 문장만 어절로 쪼갠다
    return out


def _chop(text: str, limit: int) -> List[str]:
    """한 문장이 한도를 넘을 때만 어절 경계로 쪼갠다. 낱말을 자르지 않는다."""
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


# 문장 시각이 겹치지 않게 두는 최소 간격. 자막이 두 줄 동시에 뜨는 것을 막는다.
_MIN_STEP = 0.05


def align(groups: List[List[str]], marks: List[Dict[str, Any]],
          dur: float, narration: str) -> List[Tuple[float, float]] | None:
    """조각 시각을 **실제 발화 시각**에 붙인다. 못 맞추면 `None`.

    맞추는 방법은 문장 앵커다 (머리글 참고):
        1. `narration_text` 를 문장으로 나누고 문장마다 어절 수를 센다
        2. 그 수로 `marks` 를 순서대로 소비해 **문장 첫 낱말의 시각**을 얻는다
        3. 문장 i 의 구간 = [문장 i 시작, 문장 i+1 시작)
        4. 한 문장이 여러 조각이면 **그 구간 안에서만** 글자 수로 나눈다

    `None` 을 돌려주는 자리를 넉넉히 뒀다. 반쯤 맞은 시각은 틀린 시각보다 나쁘다 —
    사람이 「정렬됐다」고 믿게 만든다.
    """
    if not marks or not narration or dur <= 0 or not groups:
        return None

    sents = sentences(narration)
    if len(sents) != len(groups):
        return None                      # 발음교정이 문장을 갈랐다/붙였다
    counts = [len(x.split()) for x in sents]
    if sum(counts) != len(marks):
        return None                      # 어절과 마크가 안 맞는다

    # 문장 첫 낱말의 시각
    starts: List[float] = []
    acc = 0
    for n in counts:
        if acc >= len(marks):
            return None
        starts.append(float(marks[acc].get("t") or 0.0))
        acc += n

    # ★ 첫 문장은 **씬 머리에 붙인다.** 실측으로 첫 마크가 0.09~0.10 초라,
    #   그대로 쓰면 씬마다 자막 없는 프레임 세 장이 앞에 붙는다.
    starts[0] = 0.0
    for i in range(1, len(starts)):     # 단조 증가 · 씬 안쪽
        lo = starts[i - 1] + _MIN_STEP
        starts[i] = min(max(starts[i], lo), dur)
    if starts[-1] >= dur:
        return None                      # 마지막 문장이 들어갈 자리가 없다

    spans: List[Tuple[float, float]] = []
    for i, g in enumerate(groups):
        s0 = starts[i]
        s1 = starts[i + 1] if i + 1 < len(starts) else dur
        if s1 - s0 <= 0:
            return None
        for a, b in _spread(g, s1 - s0):
            spans.append((round(s0 + a, 3), round(s0 + b, 3)))
    if not spans:
        return None
    spans[-1] = (spans[-1][0], round(dur, 3))   # 끝은 정확히 씬 끝
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
    fmt = str(doc.get("format") or config.get("shorts.format", "narrative"))
    limit = cue_limit(fmt)

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

        groups = split_cues_grouped(s.get("srt_text") or "", limit)
        cues = [c for g in groups for c in g]
        # 음성이 아직 없으면 마크가 있어도 그 음성의 것이 아니다 — 쓰지 않는다.
        narr = s.get("narration_text") or ""
        # ★ 마크가 **이 글**에서 나온 것일 때만 쓴다 (지문 대조).
        fresh = s.get("marks_of") == s3_tts.text_stamp(narr)
        spans = (None if (s.get("audio_estimated") or not fresh)
                 else align(groups, s.get("marks") or [], dur, narr))
        if spans is None:
            spans = _spread(cues, dur)
            if cues:
                s["cues_estimated"] = True
        else:
            s.pop("cues_estimated", None)
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
    doc["cue_limit"] = limit

    # 길이가 목표 범위를 벗어났는지. **막지 않는다** — 말을 잘라 붙이면 문장이
    # 깨지고, 깨진 문장은 TTS 에서 더 이상하게 들린다. 사람이 고칠 자리다.
    lo, hi = config.seconds_range()
    warn = [w for w in (doc.get("warnings") or [])
            if "목표 길이" not in str(w)]
    if total and total > hi + 0.5:
        warn.append(f"길이가 {total:.1f}초로 목표 길이({lo:.0f}~{hi:.0f}초)를 넘습니다. "
                    f"항목을 빼거나 문장을 줄이세요.")
    elif total and total < lo - 0.5:
        warn.append(f"길이가 {total:.1f}초로 목표 길이({lo:.0f}~{hi:.0f}초)에 못 미칩니다. "
                    f"재료에 담을 사실이 더 있는지 보세요.")
    doc["warnings"] = warn
    atomic_write_json(str(paths.script_json(slug)), doc, indent=2)

    # ★ BOM — 없으면 cp949 오탐이 「그럴듯하게 깨진 한글」을 만든다
    atomic_write_text(str(paths.srt(slug)), "﻿" + "\n".join(srt_rows))

    cue_path = paths.cue_csv(slug)
    cue_path.parent.mkdir(parents=True, exist_ok=True)
    with open(cue_path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["씬", "큐", "시작(초)", "끝(초)", "길이(초)", "자막"])
        w.writerows(csv_rows)

    return {"cues": idx, "total_sec": total, "cue_limit": limit,
            "estimated": [int(s["no"]) for s in scenes if s.get("audio_estimated")],
            "cue_estimated": [int(s["no"]) for s in scenes if s.get("cues_estimated")]}


def _load(slug: str) -> Dict[str, Any]:
    p = paths.script_json(slug)
    if not p.exists():
        raise FileNotFoundError("먼저 「대본」 단계를 돌리세요.")
    return json.loads(p.read_text(encoding="utf-8"))
