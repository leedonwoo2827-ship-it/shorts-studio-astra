# -*- coding: utf-8 -*-
"""원고 — 줄글 한 덩어리를 소제목이 살아 있는 HTML 로 다시 짠다. **모델을 부른다(돈).**

들어오는 것: `00_기획/source.md`   (S0 이 만든 결정론 추출본)
나가는 것:   `00_기획/원고.html`   (사람이 고칠 수 있다)

★ **왜 이 단계가 생겼나.** PDF 추출이 소제목을 본문에 붙여 버린다. 실측
  (2026-09-08, 18쪽 한 장): 헤딩이 **한 개**뿐인 100줄 덩어리가 나왔고 —
  「…교실의 문피트먼의 실험은」, 「빛과 그림자— …배신통신교육은」 —
  대본 단계가 그 덩어리에서 **첫 단락만 잡고 나머지 17쪽을 버렸다.**

★ **왜 HTML 인가.** 다음 단계가 파서다. 모델에게 배열을 맞춰 달라고 하는 것보다
  HTML 을 주게 하고 코드가 태그를 읽는 것이 어긋날 여지가 없다 — 41_26 이
  그렇게 했고, 그쪽 구조화 단계는 `model: ""`, `cost_usd: 0` 이었다.

★ 폴더 번호를 새로 끼우지 않았다. `01_원고/` 를 만들면 `01_대본`~`06_완성` 이
  전부 밀려 이미 만든 프로젝트가 깨진다. 원고·구조는 둘 다 「재료를 갈아 내는
  일」이라 `00_기획/` 이 제자리다.
"""
from __future__ import annotations

import re
from typing import Any, Callable, Dict, List, Optional

from core import config
from core.atomic_io import atomic_write_text, atomic_write_json
from core import paths
from llm import structured
from . import prompts
from .schemas import DRAFT_SCHEMA

SYSTEM = (
    "너는 단행본 한 장을 읽고 재료를 세워 놓는 편집자다. "
    "원문에 없는 사실을 지어내지 않는다. "
    "원문의 절을 하나도 버리지 않는다 — 뒷장을 앞장보다 얇게 쓰지 않는다. "
    "숫자는 줄글에 묻어 두지 않고 표로 세운다. "
    "반드시 제시된 JSON 스키마대로만 답한다."
)

# 원문이 길면 앞뒤로 잘라 보낸다. 대본 단계(24,000)보다 넉넉하게 준다 —
# 이 단계의 일이 바로 「뒷장을 안 버리는 것」이라 뒤를 자르면 앞뒤가 안 맞는다.
MAX_SOURCE_CHARS = 60000

# 내보내도 되는 태그. `div`·`span`·`class`·`style` 은 파서가 쓰지 않으므로 막는다.
_ALLOWED = {
    "h2", "p", "ul", "ol", "li", "b", "i", "em", "strong",
    "table", "thead", "tbody", "tr", "th", "td",
    "svg", "g", "defs", "marker", "line", "polyline", "polygon",
    "path", "rect", "circle", "ellipse", "text", "tspan", "title",
}
_TAG_OPEN = re.compile(r"<\s*([A-Za-z][A-Za-z0-9]*)")
_BANNED = re.compile(
    r"<\s*(?:script|style|iframe|foreignObject|object|embed|link|meta)\b",
    re.IGNORECASE,
)
_VIEWBOX = re.compile(r'viewBox\s*=\s*"([^"]*)"')
_H2 = re.compile(r"<\s*h2\b[^>]*>(.*?)<\s*/\s*h2\s*>", re.IGNORECASE | re.DOTALL)
_QUOTE = re.compile(r'data-quote\s*=\s*"')
_BLOCK = re.compile(r"<\s*(p|li|tr|svg)\b", re.IGNORECASE)


def _strip_wrapper(html: str) -> str:
    """모델이 `<html><body>` 를 씌워 보내면 벗긴다. 조각만 쓴다."""
    html = re.sub(r"<!DOCTYPE[^>]*>", "", html, flags=re.IGNORECASE)
    for tag in ("html", "head", "body"):
        html = re.sub(rf"<\s*/?\s*{tag}\b[^>]*>", "", html, flags=re.IGNORECASE)
    return html.strip()


def check(html: str) -> List[str]:
    """원고를 훑어 사람이 봐야 할 것만 돌려준다. **막지 않는다** — 고칠 자리를 알려 준다."""
    bad: List[str] = []

    if _BANNED.search(html):
        bad.append("script·style·iframe 같은 태그가 섞여 있습니다. 지우세요.")

    used = {m.group(1).lower() for m in _TAG_OPEN.finditer(html)}
    extra = sorted(used - {t.lower() for t in _ALLOWED})
    if extra:
        bad.append(f"쓰지 않기로 한 태그가 있습니다: {', '.join(extra[:6])}")

    heads = _H2.findall(html)
    if len(heads) < 2:
        bad.append(f"절(h2)이 {len(heads)}개입니다. 소제목 복원이 이 단계의 첫째 일입니다.")

    # 골격 viewBox 는 고정값이어야 한다. 다르면 다음 단계가 좌표를 못 읽는다.
    for vb in _VIEWBOX.findall(html):
        if " ".join(vb.split()) != "0 0 520 190":
            bad.append(f'골격 viewBox 가 "{vb}" 입니다 — "0 0 520 190" 이어야 합니다.')
            break

    # 표 셀이 붙었는지. 41_26 이 여기서 틀렸다 — 셀을 구분자 없이 이어 붙여
    # 「성장의 제약토지의 수확 체감환경의 용량 한계」가 되었다.
    for row in re.findall(r"<\s*tr\b[^>]*>(.*?)<\s*/\s*tr\s*>", html,
                          re.IGNORECASE | re.DOTALL):
        if not re.search(r"<\s*(td|th)\b", row, re.IGNORECASE):
            bad.append("표에 td·th 없이 글자만 든 행이 있습니다. 셀을 나누세요.")
            break

    blocks = len(_BLOCK.findall(html))
    quotes = len(_QUOTE.findall(html))
    # 프롬프트는 **숫자가 든 블록에만** 근거를 요구한다(전부에 붙이면 원고가 두
    # 배가 되어 예산을 넘긴다). 그래서 기준을 낮게 잡는다 — 아예 없을 때만 잡는다.
    if blocks and quotes < blocks * 0.3:
        bad.append(f"블록 {blocks}개 중 {quotes}개에만 data-quote 가 있습니다. "
                   f"근거 없는 블록은 다음 단계가 버립니다.")

    # 뒷장이 앞장보다 얇은지 — 이 단계에서 가장 흔한 실패다.
    parts = re.split(r"<\s*h2\b", html, flags=re.IGNORECASE)[1:]
    if len(parts) >= 4:
        half = len(parts) // 2
        front = sum(len(p) for p in parts[:half]) / max(1, half)
        back = sum(len(p) for p in parts[half:]) / max(1, len(parts) - half)
        if back < front * 0.5:
            bad.append(f"뒷절이 앞절의 절반도 안 됩니다(앞 {front:.0f}자 / 뒤 {back:.0f}자). "
                       f"뒷장을 버렸을 수 있습니다.")
    return bad


def _trim_source(md: str) -> str:
    if len(md) <= MAX_SOURCE_CHARS:
        return md
    half = MAX_SOURCE_CHARS // 2
    return md[:half] + "\n\n…(중략)…\n\n" + md[-half:]


def run(slug: str, *,
        on_activity: Optional[Callable[[str], None]] = None) -> Dict[str, Any]:
    """`00_기획/원고.html` 을 만들고 요약을 돌려준다."""
    md_path = paths.source_md(slug)
    if not md_path.exists():
        raise FileNotFoundError("먼저 「재료」 단계를 돌려 source.md 를 만드세요.")
    md = _trim_source(md_path.read_text(encoding="utf-8"))

    user = prompts.text("draft") + "\n\n" + md
    out, cost = structured("draft", SYSTEM, user, DRAFT_SCHEMA, on_activity=on_activity)

    html = _strip_wrapper(str(out.get("html") or ""))
    if not html:
        raise ValueError("원고가 비어 왔습니다. 다시 돌려 보세요.")

    warnings = [str(w) for w in (out.get("warnings") or [])][:8]
    warnings += check(html)

    atomic_write_text(str(paths.draft_html(slug)), html)

    info = {
        "sections": len(_H2.findall(html)),
        "blocks": len(_BLOCK.findall(html)),
        "tables": len(re.findall(r"<\s*table\b", html, re.IGNORECASE)),
        "skeletons": len(re.findall(r"<\s*svg\b", html, re.IGNORECASE)),
        "chars": len(html),
        "cost_usd": round(cost, 4),
        "warnings": warnings,
    }
    # 사람이 화면에서 보는 요약. 원고 자체는 HTML 파일이라 여기에 담지 않는다.
    atomic_write_json(str(paths.plan_dir(slug) / "원고.json"), info, indent=2)
    return info
