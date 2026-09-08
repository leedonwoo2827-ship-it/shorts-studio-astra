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

SCRIPT_SCHEMA: Dict[str, Any] = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "type": "object",
    "additionalProperties": False,
    "required": ["title", "hashtags", "scenes"],
    "properties": {
        "title": {"type": "string", "maxLength": 60},
        "hashtags": {
            "type": "array", "minItems": 2, "maxItems": 5,
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
                    "role": {"enum": ["hook", "body", "close"]},
                    "hook_line1": {"type": "string", "minLength": 1, "maxLength": HOOK_MAX},
                    "hook_line2": {"type": "string", "minLength": 1, "maxLength": HOOK_MAX},
                    "srt_text": {"type": "string", "minLength": 8, "maxLength": SRT_MAX},
                    "image_brief": {"type": "string", "minLength": 10, "maxLength": 300},
                    "source": {"type": "string", "minLength": 5, "maxLength": 400},
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
                "required": ["no", "stage", "layout", "motion"],
                "properties": {
                    "no": {"type": "integer", "minimum": 1, "maximum": 8},
                    # 무엇이 있는 장면인가. 규격·금지목록은 코드가 붙인다 —
                    # 모델이 매번 다시 쓰면 그 문장이 흔들리고, 흔들리면 결과가 흔들린다.
                    "stage": {"type": "string", "minLength": 20, "maxLength": 600},
                    "layout": {"type": "string", "minLength": 20, "maxLength": 600},
                    # ★ 이 배열이 이 스키마의 요점이다. 한 씬에 셋을 넘기지 않는다 —
                    #   동시에 셋이 움직이면 30초 화면에서 아무것도 안 보인다.
                    #   각 줄은 「무엇이 · 어떻게 · 언제」를 담아야 해서 하한을 둔다.
                    "motion": {
                        "type": "array", "minItems": 1, "maxItems": 3,
                        "items": {"type": "string", "minLength": 15, "maxLength": 240},
                    },
                    "palette_note": {"type": "string", "maxLength": 300},
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
