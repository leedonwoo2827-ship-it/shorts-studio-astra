# -*- coding: utf-8 -*-
"""페르소나(무드) — 어조는 고정값이 아니라 매개변수다.

`config.json` 의 `narration._페르소나` 가 적어 둔 숙제가 이것이다:

    참조 영상의 「따뜻한 / 정겹군요 / 느껴지네요」는 ENFP 페르소나였고,
    우리 script.md 는 「하십시오체」로 못 박혀 있다.

같은 장(章)을 MBTI 16유형으로 열여섯 번 내보내는 것이 쇼츠공방 I 의 캠페인
방식이다. 원고는 **장별로만** 있고 무드는 **생성 시점에** 입힌다 — 그래서
씬에 무드를 저장하지 않는다.

★ **무드는 어조에만.** 소재·고유명사는 재료에 있는 것만 쓴다. 쇼츠공방 I 에서
  ESFP 무드가 원본에 없던 「라디오 파티」를 지어낸 사고가 있었다. 무드가 단어까지
  만들면 그것은 환각이다 — `TONE_ONLY` 가 그 경계를 못박는다.
"""
from __future__ import annotations

from typing import Dict, List, Optional

MBTI16: List[str] = ["ISTJ", "ISFJ", "INFJ", "INTJ", "ISTP", "ISFP", "INFP", "INTP",
                     "ESTP", "ESFP", "ENFP", "ENTP", "ESTJ", "ESFJ", "ENFJ", "ENTJ"]

# 라운드(한 MBTI 로 전 장을 한 바퀴) 진행 순서. 쇼츠공방 I 의 근거를 그대로 잇는다 —
# ① 인구 비율(감각형 73%) ② 쇼츠 참여도(외향·감각·감정형이 즉각 소구).
ROUND_ORDER: List[str] = ["ESFP", "ESFJ", "ENFP", "ESTP", "ISFJ", "ISFP", "ISTJ", "ESTJ",
                          "ENTP", "ENFJ", "INFP", "INTP", "ISTP", "INTJ", "ENTJ", "INFJ"]

# 유형별 지속 페르소나 한 줄. 쇼츠공방 I `shortsmaker/campaign.py:MBTI_MOODS` 와 같다 —
# 두 공방이 같은 캠페인을 나눠 만들므로 무드가 갈리면 9장에서 톤이 튄다.
MOODS: Dict[str, str] = {
    "ISTJ": "믿음직한 정공법 — 검증된 사실로 차곡차곡",
    "ISFJ": "따뜻한 보살핌 — 사람을 챙기는 시선",
    "INFJ": "의미심장한 통찰 — 깊은 뜻을 짚어줌",
    "INTJ": "냉철한 분석 — 원리와 큰 그림",
    "ISTP": "쿨한 실용 — 작동 원리·핵심만",
    "ISFP": "감성적 미감 — 장면과 분위기",
    "INFP": "진정성 있는 울림 — 가치와 마음",
    "INTP": "호기심 탐구 — '왜?'를 파고듦",
    "ESTP": "짜릿한 반전 — 즉각적 흥미·스릴",
    "ESFP": "활기찬 즐거움 — 신나고 생생하게",
    "ENFP": "설레는 가능성 — 상상과 영감",
    "ENTP": "도발적 역발상 — 통념 비틀기",
    "ESTJ": "단호한 결론 — 핵심 교훈·실행",
    "ESFJ": "다정한 공감 — 함께 느끼는 따뜻함",
    "ENFJ": "영감 주는 리더십 — 동기부여·비전",
    "ENTJ": "강력한 임팩트 — 큰 야망·결단",
}

# ── 방어망 상수 ──────────────────────────────────────────────────────────
# 쇼츠공방 I `knowledges/01-llm-환각-잡기.md` 패턴 1·2. 생성·검증 프롬프트가
# **같은 문장**을 쓴다 — 규칙이 두 벌이면 한쪽으로 굽고 다른 쪽으로 검수하게 된다.

INDEP = ("각 자막은 그 자체로 완결된 독립 문장입니다. 주어와 서술어를 갖추고, 앞/뒤 씬을 "
         "가리키는 접속어·지시어('이에 맞서·뒤이어·그래서·결국·그·이·저·이런·이렇게' 등)에 "
         "의존하지 마세요. 어떤 순서로 읽어도 그 문장 하나만으로 이해돼야 합니다.")

TONE_ONLY = ("★ 무드는 **어조에만** 씁니다. 핵심 소재·고유명사·수치는 재료에 실제로 나온 것만 "
             "쓰세요. 어려운 말은 쉬운 일반어로 풀어도 되지만(뜻은 유지), 재료에 없는 새 소재어"
             "(예: '파티·축제·콘서트')를 지어내지 마세요. 무드는 어미·에너지·문형으로만 드러납니다.")

ENDINGS = ("문장 끝맺음(어미)을 줄마다 다르게 섞으세요. '~했죠/~했습니다'만 반복하지 말고 "
           "'~했어요 / ~거든요 / ~인데요 / ~답니다 / ~게 됩니다 / 질문형(?) / 감탄형(!)' 을 "
           "번갈아 쓰고, 같은 어미가 연속으로 나오지 않게 하세요.")

# 무드가 없을 때의 기본 어조. 예전 script.md 에 박혀 있던 값이다.
DEFAULT_TONE = "하십시오체. 담담하고 또렷하게."


def normalize(mbti: Optional[str]) -> str:
    """`enfp` · ` ENFP ` → `ENFP`. 16유형이 아니면 빈 문자열."""
    v = (mbti or "").strip().upper()
    return v if v in MOODS else ""


def mood(mbti: Optional[str]) -> str:
    return MOODS.get(normalize(mbti), "")


def tone_block(mbti: Optional[str] = None, custom_mood: str = "") -> str:
    """프롬프트에 끼울 어조 블록. 무드가 없으면 예전 그대로 하십시오체.

    ★ 이 블록 하나가 `script.md` · 후크 재생성 · 자막 재생성 셋에 같이 들어간다.
      셋이 다른 어조를 쓰면 한 영상 안에서 톤이 갈린다.
    """
    m = normalize(mbti)
    line = (custom_mood or "").strip() or MOODS.get(m, "")
    if not m and not line:
        return DEFAULT_TONE
    who = f"**{m} 유형**이 좋아할 톤" if m else "아래 무드"
    return (f"{who}으로 말합니다 — 무드: 「{line}」\n"
            f"{TONE_ONLY}\n{ENDINGS}")


def round_no(mbti: str) -> int:
    """발행 순서 번호. 쇼츠공방 I 화면의 「N리스트」와 같은 수다 — ENFP 는 3.

    16유형이 아니면 0. 폴더 이름에 쓰이므로 **순서가 바뀌면 옛 폴더와 어긋난다** —
    `ROUND_ORDER` 를 재정렬할 일이 생기면 그때 이름도 같이 옮겨야 한다.
    """
    who = normalize(mbti)
    return ROUND_ORDER.index(who) + 1 if who in ROUND_ORDER else 0
