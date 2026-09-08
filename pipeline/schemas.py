# -*- coding: utf-8 -*-
"""모델이 돌려줄 JSON 모양 — draft-07.

★ 스키마는 **모델을 묶는 유일한 수단**이다. 프롬프트에 "이렇게 주세요"라고 적는
  것만으로는 안 된다. `additionalProperties: false` 를 반드시 붙인다 — 없으면
  모델이 자기 좋을 대로 필드를 늘려 놓고, 그걸 나중에 코드가 조용히 무시한다.

★ 글자 수 상한은 스키마에도 **박아 둔다**(maxLength). 프롬프트에만 적으면 지키다
  말고, 화면이 깨진 뒤에야 알게 된다.
"""
from __future__ import annotations

from typing import Any, Dict

# 후크 한 줄 상한. 1080px 폭에 Black Han Sans 92px 이면 12자에서 꽉 찬다.
HOOK_MAX = 12
# 자막 한 씬 상한. 30초/3컷이면 씬당 66자인데, 여유를 두고 90자에서 끊는다.
SRT_MAX = 90


DRAFT_SCHEMA: Dict[str, Any] = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "type": "object",
    "additionalProperties": False,
    "required": ["html"],
    "properties": {
        # HTML 한 덩어리로 받는다. 블록·표·골격을 따로 받지 않는 이유는 다음
        # 단계가 **파서**이기 때문이다 — 모델이 배열을 맞춰 주는 것보다
        # 코드가 HTML 을 읽는 것이 어긋날 여지가 없다(41_26 이 그렇게 했다).
        "html": {"type": "string", "minLength": 200, "maxLength": 120000},
        "warnings": {"type": "array", "maxItems": 8,
                     "items": {"type": "string", "maxLength": 200}},
    },
}

SCRIPT_SCHEMA: Dict[str, Any] = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "type": "object",
    "additionalProperties": False,
    "required": ["title", "hashtags", "scenes"],
    "properties": {
        "title": {"type": "string", "maxLength": 60},
        # 영상 내내 상단에 박혀 있는 후크. 씬마다 갈리지 않는다 — 보다 들어온
        # 사람이 무슨 영상인지 알아야 한다. `mark` 는 line2 안에서 강조할 낱말이고,
        # 비우면 line2 줄 전체가 강조색이 된다(레퍼런스가 둘 다 쓴다).
        "hook_fixed": {
            "type": "object",
            "additionalProperties": False,
            "required": ["line1", "line2"],
            "properties": {
                "line1": {"type": "string", "minLength": 1, "maxLength": HOOK_MAX},
                "line2": {"type": "string", "minLength": 1, "maxLength": HOOK_MAX},
                "mark": {"type": "string", "maxLength": HOOK_MAX},
            },
        },
        # ★ 태그는 **검색에 걸리라고** 다는 것이다. 다섯 개 상한을 두었더니
        #   「#오픈소스 #리눅스 #자유소프트웨어 #오픈코스웨어 #무크」처럼 넓은 일반어만
        #   남고 정작 사람이 찾는 이름(#MIT #토르발스 #제록스)이 밀려났다. 쇼츠공방 I
        #   은 같은 장에 여덟 개를 달았고 절반이 고유명사였다.
        "hashtags": {
            "type": "array", "minItems": 5, "maxItems": 10,
            # 해시태그 한 개. 공백 금지는 코드(_clean_hashtags)가 잡는다 —
            # 스키마에 백슬래시 이스케이프를 넣으면 파일마다 다르게 새어 나간다.
            "items": {"type": "string", "minLength": 2, "maxLength": 21,
                      "pattern": "^#"},
        },
        "scenes": {
            "type": "array", "minItems": 1, "maxItems": 8,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["no", "role", "hook_line1", "hook_line2",
                             "srt_text", "image_brief", "source"],
                "properties": {
                    "no": {"type": "integer", "minimum": 1, "maximum": 8},
                    # `item` — 목록형의 한 항목. 숫자가 주인공인 씬이다.
                    "role": {"enum": ["hook", "body", "item", "close"]},
                    "hook_line1": {"type": "string", "minLength": 1, "maxLength": HOOK_MAX},
                    "hook_line2": {"type": "string", "minLength": 1, "maxLength": HOOK_MAX},
                    "srt_text": {"type": "string", "minLength": 8, "maxLength": SRT_MAX},
                    "image_brief": {"type": "string", "minLength": 10, "maxLength": 300},
                    "source": {"type": "string", "minLength": 5, "maxLength": 400},
                    # 구조.json 의 `facts[].id`. 이 씬이 어느 사실을 쓰는지 못 박는다 —
                    # 장면 지시가 그 사실의 값·단위·표를 받아서 claim 을 세운다.
                    "fact": {"type": "string", "maxLength": 24},
                },
            },
        },
    },
}

ARTSPEC_SCHEMA: Dict[str, Any] = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "type": "object",
    "additionalProperties": False,
    "required": ["scenes"],
    "properties": {
        "scenes": {
            "type": "array", "minItems": 1, "maxItems": 8,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["no", "claim", "stage", "layout", "change"],
                "properties": {
                    "no": {"type": "integer", "minimum": 1, "maximum": 8},

                    # ★ **이 필드가 이 스키마의 요점이다.**
                    #   먼저 「그 문장이 무엇을 주장하는가」를 적게 한다.
                    #   실측(2026-09-08): 이게 없으니 낱말을 글자 그대로 옮겼다 —
                    #   「대학을 설계했습니다」에 설계도면을 그리고,
                    #   「우편이 쌓이는데」에 봉투를 쌓았다. 문장이 말한 것은
                    #   비유이거나 관계인데 배경만 그린 것이다.
                    "claim": {"type": "string", "minLength": 10, "maxLength": 200},

                    # 1차 설계 — 정지 상태로 성립하는 상황 한 장
                    "stage": {"type": "string", "minLength": 20, "maxLength": 600},
                    "layout": {"type": "string", "minLength": 20, "maxLength": 600},

                    # 변동 — 그 위에서 바뀌는 **단 하나**. 이것이 곧 주장이다.
                    "change": {"type": "string", "minLength": 20, "maxLength": 300},
                    # 거드는 것 하나까지만. 셋이 동시에 움직이면 아무것도 안 보인다.
                    "support": {"type": "string", "maxLength": 240},

                    "palette_note": {"type": "string", "maxLength": 300},

                    # ── 두루마리 ────────────────────────────────────────────
                    # 화면보다 긴 지면을 칸으로 나눠 그리게 하고, 카메라가 칸에서
                    # 칸으로 **끊어 뛴다**. 뛰는 것이 컷이다.
                    # 실측(2026-09-08): 씬 4개면 30초에 컷이 4개다. 잘 도는 쇼츠는
                    # 15~20개다. 씬을 늘려 컷을 늘리면 씬 하나가 아스트라 2분30초라
                    # 비용이 막는다 — 두루마리는 값 하나에 컷 여럿이다.
                    "cells": {
                        "type": "array", "minItems": 1, "maxItems": 5,
                        "items": {
                            "type": "object",
                            "additionalProperties": False,
                            "required": ["no", "what"],
                            "properties": {
                                "no": {"type": "integer", "minimum": 1, "maximum": 5},
                                "what": {"type": "string", "minLength": 10, "maxLength": 300},
                                # 칸마다 채움을 달리한다. 전부 꽉 채우면 리듬이 없다.
                                "fill": {"enum": ["낱개", "꽉", "여백"]},
                            },
                        },
                    },

                    # ── 동작 연쇄 ───────────────────────────────────────────
                    # 반복이 아니라 **순차**다. 각각 한 방향으로 가서 그 자리에
                    # 멈추므로 되돌아오는 값 검사기를 그대로 통과한다.
                    # 창이 겹치면 코드가 거른다 — 셋이 동시에 움직이면 안 보인다.
                    "beats": {
                        "type": "array", "maxItems": 4,
                        "items": {
                            "type": "object",
                            "additionalProperties": False,
                            "required": ["at", "until", "what"],
                            "properties": {
                                "at": {"type": "number", "minimum": 0},
                                "until": {"type": "number", "minimum": 0},
                                "what": {"type": "string", "minLength": 8, "maxLength": 200},
                            },
                        },
                    },
                },
            },
        }
    },
}


META_SCHEMA: Dict[str, Any] = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "type": "object",
    "additionalProperties": False,
    "required": ["title", "description", "tags", "pinned_comment"],
    "properties": {
        "title": {"type": "string", "minLength": 5, "maxLength": 100},
        "description": {"type": "string", "minLength": 20, "maxLength": 1200},
        "tags": {"type": "array", "minItems": 3, "maxItems": 15,
                 "items": {"type": "string", "maxLength": 30}},
        "pinned_comment": {"type": "string", "minLength": 10, "maxLength": 400},
    },
}


# ── 대본 다듬기 3종 (s1b_revise) ─────────────────────────────────────────
# ★ 셋 다 **씬 번호를 키로 돌려받는다.** 배열 순서로 받으면 모델이 씬 하나를
#   빠뜨렸을 때 그 뒤가 통째로 한 칸씩 밀리는데, 그것이 조용히 통과한다.

VERIFY_SCHEMA: Dict[str, Any] = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "type": "object",
    "additionalProperties": False,
    "required": ["results"],
    "properties": {
        "results": {
            "type": "array", "minItems": 1, "maxItems": 12,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["no", "ok", "reason", "alts"],
                "properties": {
                    "no": {"type": "integer", "minimum": 1, "maximum": 99},
                    "ok": {"type": "boolean"},
                    # 짧게. 길게 쓰라고 하면 거기서 또 지어낸다.
                    "reason": {"type": "string", "maxLength": 80},
                    "alts": {"type": "array", "minItems": 1, "maxItems": 3,
                             "items": {"type": "string", "minLength": 4,
                                       "maxLength": SRT_MAX}},
                },
            },
        },
    },
}

HOOKS_SCHEMA: Dict[str, Any] = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "type": "object",
    "additionalProperties": False,
    "required": ["line1", "line2"],
    "properties": {
        "line1": {"type": "string", "minLength": 1, "maxLength": HOOK_MAX},
        "line2": {"type": "string", "minLength": 1, "maxLength": HOOK_MAX},
        "mark": {"type": "string", "maxLength": HOOK_MAX},
    },
}

CAPTIONS_SCHEMA: Dict[str, Any] = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "type": "object",
    "additionalProperties": False,
    "required": ["captions"],
    "properties": {
        "captions": {
            "type": "array", "minItems": 1, "maxItems": 12,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["no", "srt_text"],
                "properties": {
                    "no": {"type": "integer", "minimum": 1, "maximum": 99},
                    "srt_text": {"type": "string", "minLength": 4,
                                 "maxLength": SRT_MAX},
                },
            },
        },
    },
}
