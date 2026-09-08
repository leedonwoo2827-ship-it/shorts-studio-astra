# -*- coding: utf-8 -*-
"""S7 컴포지션 — 타이밍을 계산하고 `05_컴포지션/index.html` 을 굽는다. **무료.**

★ **시간 계산은 여기 한 곳뿐이다.** 템플릿은 받은 숫자를 찍기만 한다.
  계산이 두 곳에 있으면 언젠가 서로 달라지고, 그때 화면과 소리가 갈린다.

    씬 시작   앞 씬들의 (실측 오디오 길이 + 숨) 누적
    씬 길이   실측 오디오 길이 + 숨 (마지막 씬은 숨 없음)
    총 길이   마지막 씬의 끝. 루트 data-duration 과 정확히 같아야 한다

★ 마지막에 **단언으로 검산한다.** 씬이 빈틈 없이 맞물리는지, 마지막 씬이 루트
  길이에 정확히 떨어지는지. 어긋난 채 렌더하면 마지막 자막이나 소리가 잘리고,
  그건 렌더가 다 끝난 뒤에야 보인다.

★ 그림은 2:3, 화면은 9:16 이다. 폭을 맞추면 위아래가 남는데 **남는 자리도 같은
  아이보리라 안 보인다.** 그래서 비율을 억지로 늘리거나 좌우를 자르지 않는다.
"""
from __future__ import annotations

import json
import re
import shutil
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from jinja2 import Environment, FileSystemLoader, StrictUndefined

from core import config, paths
from pipeline import s6_art

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE_DIR = ROOT / "templates" / "shorts_9x16"
FONTS = ROOT / "static" / "fonts"

# 그림 원본 비율. 백엔드가 주는 세로 판이 2:3 이다.
ART_RATIO = 3 / 2


def _esc(s: str) -> str:
    return (str(s or "").replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


def _kenburns(i: int, dur: float) -> Dict[str, float]:
    """씬마다 방향을 바꾼다 — 같은 방향으로만 밀면 30초가 한 덩어리로 보인다.

    배율은 항상 1보다 크다. 1.0 을 지나가면 빈 가장자리가 화면에 물린다.
    """
    zoom_in = (i % 2 == 0)
    lo, hi = 1.04, 1.11
    # 오래 머무는 씬은 더 천천히 — 짧은 씬에 같은 폭을 주면 어지럽다
    span = min(1.0, dur / 10.0)
    hi = lo + (hi - lo) * max(0.45, span)
    drift = 26 * (1 if i % 4 in (0, 3) else -1)
    if zoom_in:
        return {"from": round(lo, 3), "to": round(hi, 3),
                "x0": 0.0, "y0": 0.0, "x1": float(drift), "y1": float(-drift * 0.6)}
    return {"from": round(hi, 3), "to": round(lo, 3),
            "x0": float(drift), "y0": float(-drift * 0.6), "x1": 0.0, "y1": 0.0}


def _accent(i: int, role: str, start: float, dur: float,
            width: int, height: int, band_top: int, band_bottom: int) -> Dict[str, Any]:
    """강조 도형 — 그림 위에 얹어 시선을 끈다. 씬 성격으로 고른다.

    ★ 자리는 **두 띠를 피한 안전대**에서만 잡는다. 띠 안으로 들어가면 후크·자막과
      겹쳐 둘 다 안 읽힌다.
    """
    safe_top = band_top + 120
    safe_bot = height - band_bottom - 130
    at = round(start + min(1.1, dur * 0.34), 3)

    if role == "close":
        # 닫는 씬 — 큰 고리로 화면 가운데를 감싼다
        return {"kind": "ring", "cx": width // 2, "cy": (safe_top + safe_bot) // 2,
                "rx": int(width * 0.36), "ry": int((safe_bot - safe_top) * 0.30),
                "rot": -4, "at": at}
    if i % 3 == 0:
        cx = int(width * (0.34 if i % 2 == 0 else 0.66))
        cy = int(safe_top + (safe_bot - safe_top) * 0.42)
        return {"kind": "ring", "cx": cx, "cy": cy,
                "rx": int(width * 0.23), "ry": int(width * 0.17),
                "rot": -8 if i % 2 == 0 else 7, "at": at}
    if i % 3 == 1:
        # 화살표 — 왼쪽 아래에서 오른쪽 위로. 시선 방향을 만든다
        x0, y0 = int(width * 0.20), int(safe_bot - (safe_bot - safe_top) * 0.16)
        x1, y1 = int(width * 0.76), int(safe_top + (safe_bot - safe_top) * 0.22)
        head = 34
        d = (f"M {x0} {y0} L {x1} {y1} "
             f"M {x1} {y1} l {-head} {int(head * 0.28)} "
             f"M {x1} {y1} l {int(-head * 0.28)} {head}")
        return {"kind": "arrow", "d": d, "at": at}
    cx = int(width * (0.72 if i % 2 == 0 else 0.28))
    cy = int(safe_top + (safe_bot - safe_top) * 0.58)
    return {"kind": "dot", "cx": cx, "cy": cy, "r": 26, "at": at}


def _subset_fonts(dst: Path, text: str, *, on_log: Callable[[str], None]) -> List[str]:
    """본문에 쓰인 글자만 남겨 woff2 로 깎는다.

    ★ `--unicodes` 에 `U+AC00-D7A3`(한글 음절 11,172자)을 **넣지 마라.**
      서브셋이 스스로 무력화돼 원본 6MB 가 그대로 실린다. 본문 한글은
      `--text-file` 이 이미 전부 잡는다.

    ★ **글이 확정된 뒤의 마지막 단계다.** 글을 고치고 다시 안 깎으면 없는 글자가
      맑은 고딕으로 튄다.
    """
    from fontTools import subset as ft_subset

    always = ("U+0020-007E,U+00A0,U+2013-2014,U+2018-201D,U+2026,U+203B,"
              "U+2022,U+00B7")
    faces = [("Pretendard-Regular.ttf", "Pretendard-Regular.woff2"),
             ("Pretendard-Bold.ttf", "Pretendard-Bold.woff2"),
             ("BlackHanSans-Regular.ttf", "BlackHanSans-Regular.woff2")]
    dst.mkdir(parents=True, exist_ok=True)
    txt = dst / "_subset_chars.txt"
    txt.write_text("".join(sorted(set(text))), encoding="utf-8")

    made: List[str] = []
    for src_name, out_name in faces:
        src = FONTS / src_name
        if not src.is_file():
            on_log(f"  ⚠ 폰트가 없습니다: {src.name}")
            continue
        ft_subset.main([str(src), f"--text-file={txt}", f"--unicodes={always}",
                        "--layout-features=*", "--flavor=woff2",
                        "--no-hinting", "--desubroutinize",
                        f"--output-file={dst / out_name}"])
        made.append(out_name)
    txt.unlink(missing_ok=True)
    if made:
        kb = sum((dst / m).stat().st_size for m in made) / 1024
        on_log(f"  폰트 서브셋 {len(made)}종 · {kb:.0f} KB (원본 3종 = 6,400 KB)")
    return made


# 여는 <svg> 태그. 경계를 단어경계로 잡지 않는다 — 이 파일을 스크립트로
# 고치는 과정에서 그 escape 가 제어문자로 들어가 패턴이 조용히 아무것도
# 못 잡은 적이 있다. 그 바람에 루트 width/height 가 안 떼여 장면이 칸을
# 뚫고 나왔다. 그래서 백슬래시가 없는 모양으로 쓴다 —
# 「svg 다음 글자가 영문이 아니다」로 경계를 잡으면 <svgfoo> 는 안 걸린다.
_SVG_OPEN = re.compile("<svg(?=[^a-zA-Z])[^>]*>", re.IGNORECASE)


_ID_ATTR = re.compile(r'\bid\s*=\s*"([^"]+)"')
_HREF_REF = re.compile(r'\b((?:xlink:)?href)\s*=\s*"#([^"]+)"')
_URL_REF = re.compile(r'url\(\s*#([^)\s]+)\s*\)')


def _namespace_ids(svg: str, prefix: str) -> tuple[str, int]:
    """SVG 안의 모든 `id` 에 씬 접두어를 붙이고 참조도 같이 바꾼다.

    ★ **이것이 여러 SVG 를 한 HTML 에 심을 때의 핵심이다.**
      실측(2026-09-08): 아스트라가 쓴 세 장면이 전부 `id="scene"` 을 썼다.
      한 문서에 나란히 심으니 `url(#scene)` · `href="#scene"` 이 모두
      **첫 번째** 것으로 붙어, 씬 2·3 의 그림칸이 통째로 비었다.
      오류도 경고도 없었다 — 영상을 보고서야 알았다.

    바꾸는 것은 세 가지뿐이다.
      `id="x"`            → `id="s02-x"`
      `href="#x"`         → `href="#s02-x"`   (xlink:href 도 같이)
      `url(#x)`           → `url(#s02-x)`     (fill·clip-path·mask 가 쓴다)

    SMIL 의 `begin="a.end"` 같은 **id 참조 문법은 건드리지 않는다** — 그것까지
    손대면 모델이 쓴 타이밍을 우리가 다시 해석하는 셈이고, 그러다 깨진다.
    대신 그 문법을 쓴 SVG 는 접두어를 붙이지 않고 그대로 둔다(아래 참조).
    """
    names = set(_ID_ATTR.findall(svg))
    if not names:
        return svg, 0

    # ★ `begin="foo.end"` 처럼 **id 를 값 안에서 참조**하는 SMIL 문법이 있으면
    #   접두어를 안전하게 붙일 수 없다. 그럴 때는 손대지 않는다 —
    #   충돌 위험보다 타이밍을 깨는 쪽이 더 나쁘다. 대신 경고로 남긴다.
    for m in re.finditer(r'\bbegin\s*=\s*"([^"]*)"', svg):
        for token in re.split(r"[;\s]+", m.group(1)):
            head = token.split(".")[0].strip()
            if head and head in names:
                return svg, -1

    def sub_id(m: re.Match) -> str:
        return f'id="{prefix}{m.group(1)}"'

    def sub_href(m: re.Match) -> str:
        name = m.group(2)
        return f'{m.group(1)}="#{prefix}{name}"' if name in names else m.group(0)

    def sub_url(m: re.Match) -> str:
        name = m.group(1)
        return f"url(#{prefix}{name})" if name in names else m.group(0)

    svg = _ID_ATTR.sub(sub_id, svg)
    svg = _HREF_REF.sub(sub_href, svg)
    svg = _URL_REF.sub(sub_url, svg)
    return svg, len(names)


def _inline_svg(src: Path, prefix: str = "") -> tuple[str, int]:
    """SVG 를 HTML 에 심을 수 있게 다듬는다. `(본문, 바꾼 id 수)`.

    ★ `width`/`height` 속성을 **떼어낸다.** 남아 있으면 CSS 로 칸에 맞추는 것을
      이기고 원래 크기로 튀어나온다.
    ★ `<?xml ...?>` 선언과 DOCTYPE 도 뗀다 — HTML 안에서는 쓸 데가 없고,
      선언이 본문 중간에 있으면 파서가 거기서 멈춘다.
    ★ `id` 는 씬마다 다른 이름으로 바꾼다 — `_namespace_ids` 의 머리말 참조.
    ★ 그 밖의 내용은 손대지 않는다. 모델이 쓴 애니메이션을 다시 해석하지 않는다.
    """
    raw = src.read_text(encoding="utf-8", errors="replace")
    raw = re.sub(r"<\?xml[^>]*\?>", "", raw)
    raw = re.sub(r"<!DOCTYPE[^>]*>", "", raw, flags=re.IGNORECASE)

    m = _SVG_OPEN.search(raw)
    if m:
        tag = m.group(0)
        tag = re.sub(r'\s(?:width|height)\s*=\s*"[^"]*"', "", tag, flags=re.I)
        tag = re.sub(r"\s(?:width|height)\s*=\s*'[^']*'", "", tag, flags=re.I)
        if "preserveAspectRatio" not in tag:
            tag = tag[:-1] + ' preserveAspectRatio="xMidYMid slice">'
        raw = raw[:m.start()] + tag + raw[m.end():]

    n = 0
    if prefix:
        raw, n = _namespace_ids(raw, prefix)
    return raw.strip(), n


_ANIM_TAG = re.compile(r"<animate(?:Transform|Motion)?(?=[^a-zA-Z])[^>]*>",
                       re.IGNORECASE)
_HAS_BEGIN = re.compile(r'\bbegin\s*=', re.IGNORECASE)
_REPEAT = re.compile(r'\srepeatCount\s*=\s*"[^"]*"', re.IGNORECASE)
_FILL_ATTR = re.compile(r'\sfill\s*=\s*"(?:freeze|remove)"', re.IGNORECASE)


def phase_svg(svg: str, start: float) -> tuple:
    """장면 애니메이션을 **씬이 화면에 뜨는 순간에 맞춰 한 번만** 돌게 만든다.

    ★ **이것이 「촐싹거림」의 원인이었다.** SMIL 시계는 문서 전체 시간이라,
      씬 2 의 SVG 는 문서 0초부터 이미 돌고 있다. 씬 2 가 7.9초에 화면에 뜨는
      순간 그 애니메이션은 **이미 끝나가는 중**이고 곧 처음부터 다시 시작한다.
      씬 3 은 두 번째 루프 중간에 등장한다. 셋이 서로 다른 위상으로 돌아
      화면이 안절부절못한다. 실측(2026-09-08) — 영상을 보고서야 알았다.

    두 가지를 바꾼다.
      1. `begin` 이 없는 애니메이션에 `begin="<씬 시작>s"` 를 넣는다.
         → 씬이 뜨는 순간 애니메이션도 처음부터 시작한다.
      2. `repeatCount="indefinite"` 를 떼고 `fill="freeze"` 를 붙인다.
         → 한 번 돌고 **그 자리에 멈춘다.** 되돌아가지 않으니 차분하다.
         사용자가 "끝에 멈추고 마무리 코멘트해도 된다"고 한 것이 이 모양이다.

    `begin` 이 이미 있는 것은 건드리지 않는다 — 모델이 짠 순서가 있고,
    거기에 우리가 값을 더하면 그 순서를 다시 해석하는 셈이다.
    돌려주는 것은 무엇을 몇 개 바꿨는지다(로그로 보여 준다).
    """
    stat = {"begin": 0, "shift": 0, "freeze": 0, "kept": 0}

    def shift_begin(val: str) -> Optional[str]:
        """`begin` 값에 씬 시작을 **더한다.** 못 더하면 None.

        ★ 모델은 씬 안의 상대 시각으로 적는다 — 「0.4초에 시작」. 그런데 SMIL
          시계는 **문서 전체 시간**이라 그대로 두면 문서 0.4초에 터진다.
          씬 2 는 5.45초에 뜨는데 그 애니메이션은 이미 끝나 있다 —
          **정지 화면으로 나온다.** 실측(2026-09-08)으로 씬 2·3·4 가 그랬다.

        `a.end` 처럼 다른 요소를 가리키는 값은 건드리지 않는다. 그것까지 손대면
        모델이 짠 순서를 우리가 다시 해석하는 셈이고, 그러다 깨진다.
        """
        parts = [x.strip() for x in val.split(";") if x.strip()]
        if not parts:
            return None
        out = []
        for x in parts:
            m2 = re.fullmatch(r"([+-]?(?:\d+\.?\d*|\.\d+))(s|ms)?", x)
            if not m2:
                return None            # id 참조·indefinite·wallclock 등
            n = float(m2.group(1))
            if m2.group(2) == "ms":
                n /= 1000.0
            out.append(f"{n + start:.3f}s")
        return ";".join(out)

    def fix(m: "re.Match[str]") -> str:
        tag = m.group(0)
        self_close = tag.rstrip().endswith("/>")
        inner = tag.rstrip()[:-2] if self_close else tag.rstrip()[:-1]
        inner = inner.rstrip()

        mb = re.search(r'\bbegin\s*=\s*"([^"]*)"', inner, re.IGNORECASE)
        if mb is None:
            inner += f' begin="{start:.3f}s"'
            stat["begin"] += 1
        else:
            moved = shift_begin(mb.group(1))
            if moved is None:
                stat["kept"] += 1      # 참조식 — 그대로 둔다
            else:
                inner = inner[:mb.start()] + f'begin="{moved}"' + inner[mb.end():]
                stat["shift"] += 1

        if _REPEAT.search(inner):
            inner = _REPEAT.sub("", inner).rstrip()
            if not _FILL_ATTR.search(inner):
                inner += ' fill="freeze"'
            stat["freeze"] += 1
        return inner + ("/>" if self_close else ">")

    return _ANIM_TAG.sub(fix, svg), stat


def run(slug: str, *, on_log: Optional[Callable[[str], None]] = None) -> Dict[str, Any]:
    log = on_log or (lambda _m: None)
    doc = _load(slug)
    scenes_in = doc.get("scenes") or []
    if not scenes_in:
        raise RuntimeError("씬이 없습니다. 먼저 「대본」 단계를 돌리세요.")

    c = config.get("compose", {}) or {}
    width = int(c.get("width", 1080))
    height = int(c.get("height", 1920))
    fps = int(c.get("fps", 30))
    band_top = int(c.get("band_top", 300))
    band_bottom = int(c.get("band_bottom", 320))
    gap = float(config.get("shorts.gap_sec", 0.12))
    art_h = int(round(width * ART_RATIO))

    have_art = s6_art.present(slug)

    # ── 타이밍 ────────────────────────────────────────────────────────────
    scenes: List[Dict[str, Any]] = []
    cues: List[Dict[str, Any]] = []
    clock = 0.0
    n = len(scenes_in)
    for i, s in enumerate(scenes_in):
        no = int(s.get("no") or i + 1)
        audio_sec = float(s.get("audio_sec") or 0.0)
        if audio_sec <= 0:
            cps = (config.get("narration.chars_per_sec", 6.51)
                   * config.get("narration.speed", 1.2))
            audio_sec = round(len(s.get("narration_text") or s.get("srt_text") or "")
                              / max(cps, 0.1), 2)
        dur = round(audio_sec + (gap if i < n - 1 else 0.0), 3)
        start = round(clock, 3)

        for cue in (s.get("cues") or []):
            cues.append({"start": round(start + float(cue["t"]), 3),
                         "dur": round(float(cue["d"]), 3),
                         "text": _esc(cue["text"])})

        scenes.append({
            "no": no,
            "role": s.get("role") or "body",
            "start": start,
            "dur": dur,
            "audio_sec": round(audio_sec, 3),
            "hook_line1": _esc(s.get("hook_line1") or ""),
            "hook_line2": _esc(s.get("hook_line2") or ""),
            "art": have_art.get(no),
            "animated": bool(have_art.get(no) and s6_art.is_animated(have_art[no])),
            "kb": _kenburns(i, dur),
            "accent": _accent(i, s.get("role") or "body", start, dur,
                              width, height, band_top, band_bottom),
        })
        clock += dur

    total = round(clock, 3)

    # ── 검산 — 어긋난 채 렌더하면 다 끝난 뒤에야 보인다 ────────────────────
    for a, b in zip(scenes, scenes[1:]):
        got = round(a["start"] + a["dur"], 3)
        if abs(got - b["start"]) > 0.002:
            raise AssertionError(f"씬 {a['no']}에서 {b['no']} 로 넘어가는 "
                                 f"이음새가 어긋납니다: {got} vs {b['start']}")
    last_end = round(scenes[-1]["start"] + scenes[-1]["dur"], 3)
    if abs(last_end - total) > 0.002:
        raise AssertionError(f"마지막 씬이 총 길이에 안 떨어집니다: {last_end} vs {total}")
    for cue in cues:
        if round(cue["start"] + cue["dur"], 3) > total + 0.002:
            raise AssertionError(f"자막 큐가 총 길이를 넘습니다: {cue['text'][:20]}")

    # ── 자산 ──────────────────────────────────────────────────────────────
    out = paths.comp_dir(slug)
    if out.exists():
        shutil.rmtree(out)
    (out / "assets").mkdir(parents=True, exist_ok=True)
    (out / "audio").mkdir(parents=True, exist_ok=True)
    (out / "vendor").mkdir(parents=True, exist_ok=True)

    shutil.copy2(TEMPLATE_DIR / "gsap.min.js", out / "vendor" / "gsap.min.js")

    # ★ 움직이는 장면은 **파일로 두지 않고 HTML 안에 심는다.**
    #   `<img src="x.svg">` 로 넣으면 브라우저가 SVG 를 그림으로만 취급해
    #   **SMIL 애니메이션이 돌지 않는다**(실측). 인라인이어야 움직인다.
    #   정지 그림은 그대로 파일로 두고 배경으로 깐다.
    for sc in scenes:
        name = sc["art"]
        if not name:
            continue
        src = paths.art_dir(slug) / name
        if sc["animated"]:
            # 씬마다 다른 접두어 — 한 문서에 나란히 심어도 id 가 안 겹친다
            sc["svg"], n = _inline_svg(src, prefix=f"s{sc['no']:02d}-")
            # ★ 씬이 화면에 뜨는 순간에 애니메이션도 시작하게 위상을 맞춘다.
            #   안 맞추면 씬마다 다른 지점에서 시작해 화면이 안절부절못한다.
            sc["svg"], ph = phase_svg(sc["svg"], sc["start"])
            if any(ph.get(k) for k in ("begin", "shift", "freeze")):
                log(f"  씬 {sc['no']} 위상 맞춤 — 씬 시작으로 밀기 {ph['shift']}개 · "
                    f"시작 주입 {ph['begin']}개 · 한 번만 돌고 멈춤 {ph['freeze']}개"
                    + (f" · 참조식 유지 {ph['kept']}개" if ph["kept"] else ""))
            if n < 0:
                log(f"  ⚠ 씬 {sc['no']}: SMIL 이 id 를 값으로 참조해 접두어를 "
                    f"붙이지 않았습니다 — 다른 씬과 id 가 겹치면 그림이 사라집니다")
            elif n:
                sc["ids"] = n
        else:
            shutil.copy2(src, out / "assets" / name)

    audio_n = 0
    for sc in scenes:
        src = paths.wav(slug, sc["no"])
        if src.exists():
            shutil.copy2(src, out / "audio" / f"{sc['no']:03d}.wav")
            audio_n += 1
        else:
            sc["audio_sec"] = 0.0          # 소리가 없으면 audio 태그를 내지 않는다

    screen_text = "".join(
        [str(doc.get("title") or ""), " ".join(doc.get("hashtags") or [])]
        + [s["hook_line1"] + s["hook_line2"] for s in scenes]
        + [q["text"] for q in cues]
    )
    _subset_fonts(out / "assets" / "fonts", screen_text, on_log=log)

    # ── 렌더 ──────────────────────────────────────────────────────────────
    env = Environment(loader=FileSystemLoader(str(TEMPLATE_DIR)),
                      undefined=StrictUndefined, keep_trailing_newline=True)
    html = env.get_template("index.html.j2").render(
        title=_esc(doc.get("title") or slug),
        width=width, height=height, fps=fps, total=total,
        art_h=art_h, band_top=band_top, band_bottom=band_bottom,
        ivory=c.get("ivory", "#F6F1E8"), ink=c.get("ink", "#1F4E79"),
        accent=c.get("accent", "#E07A2F"), text=c.get("text", "#334155"),
        sub_ink=c.get("sub_ink", "#9DC3E6"),
        theme_css=(TEMPLATE_DIR / "theme.css").read_text(encoding="utf-8"),
        scenes=scenes, cues=cues,
        hashtags=_esc("  ".join(doc.get("hashtags") or [])),
    )
    (out / "index.html").write_text(html, encoding="utf-8", newline="\n")

    log(f"  씬 {len(scenes)} · 자막 큐 {len(cues)} · 소리 {audio_n} · 총 {total:.2f}초")
    return {"dir": str(out), "total_sec": total, "scenes": len(scenes),
            "cues": len(cues), "audio": audio_n,
            "art": sorted(have_art), "fps": fps,
            "animated": [s["no"] for s in scenes if s["animated"]],
            "still": [s["no"] for s in scenes if s["art"] and not s["animated"]],
            "missing_art": [s["no"] for s in scenes if not s["art"]],
            "missing_audio": [s["no"] for s in scenes if s["audio_sec"] <= 0]}


def _load(slug: str) -> Dict[str, Any]:
    p = paths.script_json(slug)
    if not p.exists():
        raise FileNotFoundError("먼저 「대본」 단계를 돌리세요.")
    return json.loads(p.read_text(encoding="utf-8"))
