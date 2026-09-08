# -*- coding: utf-8 -*-
"""구조 — 원고 HTML 을 읽어 대본이 쓸 재료 목록을 만든다. **크레딧을 쓰지 않는다.**

들어오는 것: `00_기획/원고.html`
나가는 것:   `00_기획/구조.json`

★ **왜 파서인가.** 41_26 이 이미 이 방식이었다. 그쪽 `_cache/s2c-capture.json` 이
  `"model": "", "cost_usd": 0` 으로 증거를 남겼다 — 원고 HTML 만 모델이 쓰고,
  블록·수치 추출은 결정론 코드였다. 모델에게 배열을 맞춰 달라고 하면 어긋나고,
  어긋나면 조용히 틀린다.

★ **41_26 의 버그는 고쳤다.** 그쪽 `html_text` 는 표 셀을 구분자 없이 이어 붙여
  「성장의 제약토지의 수확 체감환경의 용량 한계」를 만들었다. 대본이 숫자를
  골라 써야 하는데 그러면 못 가른다 — 여기서는 `tables[].rows` 로 셀을 살리고,
  셀마다 행머리·열머리를 붙여 `facts` 로 세운다.

★ 블록 규칙은 41_26 그대로다 — `<ul>` 은 블록이 아니고 **`<li>` 마다** 한 블록,
  `<table>` 도 아니고 **`<tr>` 마다**, `<svg>` 는 **그 자체가** 한 블록.
  `id` 는 `<절>.<블록>` 점 표기라 절이 하나 끼어도 앞 번호만 밀린다.

★ 41_26 의 `html_times`(블록별 등장 시각)는 **넣지 않는다.** 그쪽은 HTML 을 화면에
  그대로 띄우는 17분 롱폼이라 필요했다. 우리는 아스트라가 SVG 를 새로 쓰고
  타이밍은 `s7_compose` 가 음성 실측으로 잡는다.
"""
from __future__ import annotations

import re
from html import unescape
from html.parser import HTMLParser
from typing import Any, Callable, Dict, List, Optional, Tuple

from core.atomic_io import atomic_write_json
from core import paths

# 블록으로 세는 태그. 나머지는 담는 그릇이거나 꾸미개다.
BLOCK_TAGS = ("p", "li", "tr", "svg")

# ── 수치 뽑기 ──────────────────────────────────────────────────────────────
# 원문에 묻혀 있던 것들: 1페니 · 1년에 2배 · 7만 명 · 100만 명 · 10퍼센트 미만 ·
# 5퍼센트 미만 · 7,000명 · 24년. 줄글로 두면 아무도 못 쓰고, 표로 세우면 대본이
# 골라 쓴다. 그것이 이 파일의 요점이다.
_SCALE = {"조": 10 ** 12, "억": 10 ** 8, "만": 10 ** 4, "천": 10 ** 3}
_NUM = r"\d+(?:,\d{3})*(?:\.\d+)?"
_YEAR = re.compile(r"(1[5-9]\d{2}|20\d{2})\s*년?")
_RATIO = re.compile(rf"({_NUM})\s*(?:%|퍼센트)")
_FOLD = re.compile(rf"({_NUM})\s*배")
# ★ 단위가 **겹친다**. 「2만5천 명」은 25,000 이고 「1억2천만」도 있다.
#   실측(2026-09-08): 겹친 것을 못 다뤄 「첫해 2만5천 명이 등록했다」를
#   5,000명으로 읽었다 — 2만을 놓치고 5천만 집었다.
_UNITS_TAIL = "명|원|건|통|개|권|곳|해|년|쪽|페니|파운드|달러"
_SCALED_RUN = rf"{_NUM}\s*(?:조|억|만|천)(?:\s*{_NUM}\s*(?:조|억|만|천))*(?:\s*{_NUM})?"
_COUNTED = re.compile(rf"(?P<v>{_SCALED_RUN}|{_NUM})\s*(?P<u>{_UNITS_TAIL})")
_PIECE = re.compile(rf"({_NUM})\s*(조|억|만|천)?")


def _scaled(run: str) -> float:
    """「2만5천」 → 25000 · 「1억2천만」 → 120,000,000 · 「7,000」 → 7000.

    단위가 붙은 조각을 각각 곱해 더한다. 마지막 조각에 단위가 없으면 **가장 작은
    단위보다 한 자리 아래**로 보지 않고 그냥 더한다 — 「2만5」 같은 표기는
    한국어에서 안 쓰므로 그 경우가 없다.
    """
    total = 0.0
    seen = False
    for num, unit in _PIECE.findall(run):
        if not num:
            continue
        seen = True
        total += _f(num) * _SCALE.get(unit or "", 1)
    return total if seen else 0.0


# 셀이 맨 숫자(`7.6`)일 때. 단위는 열머리에 있다 — 「성장률(%/연)」.
_BARE = re.compile(rf"^\s*({_NUM})\s*$")
_UNITS = r"%|퍼센트|\$|달러|원|명|년|배|건|개"
# ★ 괄호 안을 **먼저** 본다. 안 그러면 「평균수명(년)」에서 '평균수명' 의 `명` 을
#   먼저 집어 71년이 71명이 된다 — 실측으로 그랬다.
_UNIT_PAREN = re.compile(rf"[(（][^)）]*?({_UNITS})")
_UNIT_ANY = re.compile(rf"({_UNITS})")


def _unit_of(*heads: str) -> str:
    for h in heads:
        m = _UNIT_PAREN.search(h or "")
        if m:
            return m.group(1)
    for h in heads:
        m = _UNIT_ANY.search(h or "")
        if m:
            return m.group(1)
    return ""


def _f(s: str) -> float:
    return float(str(s).replace(",", ""))


def _facts_in(text: str) -> List[Tuple[str, float, str, Optional[int]]]:
    """한 조각에서 `(kind, value, unit, year)` 를 뽑는다. 순서는 좁은 것부터다 —
    「10퍼센트」를 `_COUNTED` 가 먼저 집으면 단위가 엉킨다."""
    got: List[Tuple[str, float, str, Optional[int]]] = []
    seen: set = set()

    def add(kind: str, v: float, unit: str, yr: Optional[int]) -> None:
        key = (kind, v, unit)
        if key not in seen:
            seen.add(key)
            got.append((kind, v, unit, yr))

    year = None
    ym = _YEAR.search(text)
    if ym:
        year = int(ym.group(1))

    for m in _RATIO.finditer(text):
        add("비율", _f(m.group(1)), "%", year)
    for m in _FOLD.finditer(text):
        add("수치", _f(m.group(1)), "배", year)
    for m in _COUNTED.finditer(text):
        v = _scaled(m.group("v"))
        unit = m.group("u")
        # 「1840년」은 수치가 아니라 연도다. `_YEAR` 가 이미 잡았다.
        if unit == "년" and 1500 <= v <= 2100:
            continue
        add("수치", v, unit, year)
    if not got and year:
        add("연표", float(year), "년", year)
    return got


def _label_for(text: str, limit: int = 40) -> str:
    """사실의 이름. 숫자를 뺀 앞머리를 쓴다 — 화면에 뜰 글이 아니라 대본이 고를 이름이다."""
    s = re.sub(r"\s+", " ", text).strip()
    s = re.sub(r"^[·\-–—•\s]+", "", s)
    return s[:limit].rstrip(" ,.·") or "무제"


# ── HTML 읽기 ─────────────────────────────────────────────────────────────
_SVG_BLOCK = re.compile(r"<\s*svg\b.*?<\s*/\s*svg\s*>", re.IGNORECASE | re.DOTALL)
_ARIA = re.compile(r'aria-label\s*=\s*"([^"]*)"', re.IGNORECASE)
_SVG_TEXT = re.compile(r"<\s*text\b[^>]*>(.*?)<\s*/\s*text\s*>",
                       re.IGNORECASE | re.DOTALL)
_TAGS = re.compile(r"<[^>]+>")


def _skeleton_kind(aria: str, svg: str) -> str:
    """골격이 무엇을 보이는가. 다음 단계가 claim 을 세울 때 힌트로 쓴다."""
    a = aria + " "
    if any(w in a for w in ("대비", "맞선", "왼쪽", "오른쪽", "비교")):
        return "대비"
    if any(w in a for w in ("비율", "중", "퍼센트", "칸")):
        return "비율"
    if any(w in a for w in ("늘어", "줄어", "곡선", "추세", "성장", "증가", "감소")):
        return "추세"
    return "추세" if "polyline" in svg else "대비"


class _Reader(HTMLParser):
    """절·블록·표를 한 번에 읽는다. SVG 는 미리 빼 두고 자리표시로 만난다."""

    def __init__(self, svgs: Dict[str, str]) -> None:
        super().__init__(convert_charrefs=True)
        self._svgs = svgs
        self.sections: List[Dict[str, Any]] = []
        self.blocks: List[Dict[str, Any]] = []
        self.tables: List[Dict[str, Any]] = []

        self._sec = 0                 # 지금 절 번호 (0 = 절 밖)
        self._bno = 0                 # 절 안의 블록 번호
        self._buf: List[str] = []      # 글자 모으는 곳
        self._open: Optional[str] = None
        self._quote = ""
        self._in_h2 = False
        # 표
        self._tbl: Optional[Dict[str, Any]] = None
        self._row: List[str] = []
        self._row_head = False
        self._cell: Optional[List[str]] = None

    # -- 도우미 --------------------------------------------------------------
    def _sec_id(self) -> str:
        return f"s{self._sec}" if self._sec else "s0"

    def _next_id(self) -> str:
        self._bno += 1
        return f"{self._sec}.{self._bno}"

    def _push(self, tag: str, text: str, extra: Optional[Dict[str, Any]] = None) -> None:
        text = re.sub(r"\s+", " ", text).strip()
        if not text:
            return
        row = {"id": self._next_id(), "tag": tag, "text": text,
               "chars": len(text), "quote": self._quote,
               "section": self._sec_id()}
        if extra:
            row.update(extra)
        self.blocks.append(row)
        if self.sections:
            self.sections[-1]["block_ids"].append(row["id"])

    # -- 태그 ----------------------------------------------------------------
    def handle_starttag(self, tag: str, attrs) -> None:
        tag = tag.lower()
        a = {k.lower(): (v or "") for k, v in attrs}

        if tag == "h2":
            self._sec += 1
            self._bno = 0
            self._in_h2 = True
            self._buf = []
            return

        if tag == "table":
            self._tbl = {"id": f"t{len(self.tables) + 1}", "block": "",
                         "head": [], "rows": [], "quote": "",
                         "section": self._sec_id()}
            return

        if tag == "tr" and self._tbl is not None:
            self._row = []
            self._row_head = False
            self._quote = unescape(a.get("data-quote", ""))
            return

        if tag in ("td", "th") and self._tbl is not None:
            self._cell = []
            if tag == "th":
                self._row_head = True
            return

        if tag == "svg":
            key = a.get("data-k", "")
            raw = self._svgs.get(key, "")
            aria = (_ARIA.search(raw).group(1) if _ARIA.search(raw) else "")
            # 골격의 글자를 이어 텍스트로 삼는다 — 41_26 이 `[그림] …` 로 한 것과 같다.
            inner = " ".join(_TAGS.sub("", t).strip()
                             for t in _SVG_TEXT.findall(raw))
            inner = re.sub(r"\s+", " ", inner).strip()
            self._quote = unescape(a.get("data-quote", ""))
            self._push("svg", f"[그림] {aria or inner}".strip(),
                       {"aria": aria, "svg_text": inner, "skeleton": key})
            return

        if tag in ("p", "li"):
            self._open = tag
            self._buf = []
            self._quote = unescape(a.get("data-quote", ""))

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()

        if tag == "h2" and self._in_h2:
            title = re.sub(r"\s+", " ", "".join(self._buf)).strip()
            self.sections.append({"id": self._sec_id(), "title": title or f"{self._sec}절",
                                  "block_ids": []})
            self._in_h2 = False
            self._buf = []
            return

        if tag in ("td", "th") and self._cell is not None:
            self._row.append(re.sub(r"\s+", " ", "".join(self._cell)).strip())
            self._cell = None
            return

        if tag == "tr" and self._tbl is not None:
            if self._row_head and not self._tbl["head"]:
                self._tbl["head"] = list(self._row)
            elif any(c for c in self._row):
                self._tbl["rows"].append(list(self._row))
            # ★ 셀을 ` · ` 로 잇는다. 41_26 은 구분자 없이 붙여 못 가르게 됐다.
            bid = self._next_id()
            self.blocks.append({"id": bid, "tag": "tr",
                                "text": " · ".join(c for c in self._row if c),
                                "chars": sum(len(c) for c in self._row),
                                "quote": self._quote, "section": self._sec_id(),
                                "table": self._tbl["id"]})
            if self.sections:
                self.sections[-1]["block_ids"].append(bid)
            if not self._tbl["block"]:
                self._tbl["block"] = bid
                self._tbl["quote"] = self._quote
            self._row = []
            return

        if tag == "table" and self._tbl is not None:
            if self._tbl["rows"] or self._tbl["head"]:
                self.tables.append(self._tbl)
            self._tbl = None
            return

        if tag == self._open and tag in ("p", "li"):
            self._push(tag, "".join(self._buf))
            self._open = None
            self._buf = []

    def handle_data(self, data: str) -> None:
        if self._cell is not None:
            self._cell.append(data)
        elif self._in_h2 or self._open:
            self._buf.append(data)


# ── 사실 세우기 ────────────────────────────────────────────────────────────
def _facts_from(blocks: List[Dict[str, Any]],
                tables: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    seen: set = set()

    def add(kind: str, label: str, value: float, unit: str,
            year: Optional[int], block: str, quote: str) -> None:
        key = (round(value, 4), unit, label[:20])
        if key in seen:
            return
        seen.add(key)
        out.append({
            "id": f"f{len(out) + 1}", "kind": kind, "label": label,
            "value": int(value) if float(value).is_integer() else round(value, 3),
            "unit": unit, "year": year, "block": block, "quote": quote,
        })

    # 표에서 — 행머리·열머리를 붙이면 사실 이름이 저절로 만들어진다.
    #   「등록 학생 · 1895」 = 70000 명
    by_id = {t["id"]: t for t in tables}
    for t in tables:
        head = t["head"]
        for row in t["rows"]:
            rhead = row[0] if row else ""
            for i, cell in enumerate(row[1:], 1):
                col = head[i] if i < len(head) else ""
                label = " · ".join(x for x in (rhead, col) if x) or _label_for(cell)
                cy = _YEAR.search(col)
                yr_col = int(cy.group(1)) if cy else None
                got = _facts_in(cell)
                if not got:
                    # 셀이 맨 숫자면 단위를 **열머리에서** 가져온다.
                    # 「성장률(%/연)」 열의 `7.6` 은 7.6% 다. 이걸 놓치면 지표표가
                    # 통째로 사실 목록에서 사라진다 — 실측으로 그랬다.
                    bm = _BARE.match(cell)
                    if bm:
                        unit = _unit_of(col, rhead)
                        unit = "%" if unit in ("%", "퍼센트") else unit
                        kind = "비율" if unit == "%" else "수치"
                        got = [(kind, _f(bm.group(1)), unit, yr_col)]
                for kind, v, unit, yr in got:
                    add(kind, label, v, unit, yr_col or yr, t["block"], t["quote"])

    # 줄글에서
    for b in blocks:
        if b.get("table") or b["tag"] == "svg":
            continue                     # 표 행은 위에서 이미 봤다
        for kind, v, unit, yr in _facts_in(b["text"]):
            add(kind, _label_for(b["text"]), v, unit, yr, b["id"], b.get("quote", ""))

    # 근거 구절이 없는 사실은 뒤로 보낸다 — 대본이 앞에서부터 고른다.
    # 표에서 나온 것이 줄글에서 나온 것보다 앞이다(행머리·열머리가 붙어 이름이 정확하다).
    tbl_blocks = {t["block"] for t in tables}
    out.sort(key=lambda f: (0 if f.get("quote") else 1,
                            0 if f["block"] in tbl_blocks else 1))
    for i, f in enumerate(out, 1):
        f["id"] = f"f{i}"
    return out


def parse(html: str) -> Dict[str, Any]:
    """원고 HTML 하나를 구조로 바꾼다. 파일을 읽거나 쓰지 않는다 — 시험하기 쉽게."""
    # SVG 를 먼저 빼 둔다. HTMLParser 로는 원본 문자열을 되살릴 수 없다.
    svgs: Dict[str, str] = {}

    def take(m: re.Match) -> str:
        key = f"k{len(svgs) + 1}"
        svgs[key] = m.group(0)
        quote = ""
        q = re.search(r'data-quote\s*=\s*"([^"]*)"', m.group(0))
        if q:
            quote = q.group(1)
        return f'<svg data-k="{key}" data-quote="{quote}"></svg>'

    stripped = _SVG_BLOCK.sub(take, html)

    r = _Reader(svgs)
    r.feed(stripped)
    r.close()

    skeletons = [{"id": k, "block": next((b["id"] for b in r.blocks
                                          if b.get("skeleton") == k), ""),
                  "kind": _skeleton_kind(
                      (_ARIA.search(v).group(1) if _ARIA.search(v) else ""), v),
                  "aria": (_ARIA.search(v).group(1) if _ARIA.search(v) else ""),
                  "svg": v}
                 for k, v in svgs.items()]

    return {
        "sections": r.sections,
        "blocks": r.blocks,
        "tables": r.tables,
        "skeletons": skeletons,
        "facts": _facts_from(r.blocks, r.tables),
    }


def digest(doc: Dict[str, Any], limit: int = 6000) -> str:
    """대본 프롬프트에 넣는 요약. **원문 덩어리를 대신하는 것이 이 함수다.**

    24,000자 절단이 사라지므로 뒷장을 안 버린다 — 절 제목과 사실 목록은
    원문의 몇십 분의 일이라 다 들어간다.
    """
    lines: List[str] = []
    secs = {s["id"]: s["title"] for s in doc.get("sections") or []}
    by_sec: Dict[str, List[Dict[str, Any]]] = {}
    for b in doc.get("blocks") or []:
        by_sec.setdefault(b.get("section", "s0"), []).append(b)

    lines.append("## 절")
    for sid, title in secs.items():
        lines.append(f"- **{sid} {title}**")
        for b in by_sec.get(sid, [])[:4]:
            lines.append(f"    - {b['text'][:120]}")

    facts = doc.get("facts") or []
    if facts:
        lines.append("")
        lines.append("## 사실 (이 표에서 골라 쓴다)")
        lines.append("")
        lines.append("| id | 꼴 | 이름 | 값 | 단위 | 연도 | 근거 |")
        lines.append("|---|---|---|---|---|---|---|")
        for f in facts[:40]:
            q = (f.get("quote") or "")[:60].replace("|", "／")
            lines.append(f"| `{f['id']}` | {f['kind']} | {f['label'][:28]} | "
                         f"{f['value']} | {f['unit']} | {f.get('year') or ''} | {q} |")

    tables = doc.get("tables") or []
    if tables:
        lines.append("")
        lines.append("## 표")
        for t in tables[:6]:
            lines.append(f"- `{t['id']}` " + " / ".join(t["head"]))
            for row in t["rows"][:6]:
                lines.append("    - " + " · ".join(row))

    sk = doc.get("skeletons") or []
    if sk:
        lines.append("")
        lines.append("## 골격 (도해 초안이 이미 있는 것)")
        for s in sk[:8]:
            lines.append(f"- `{s['id']}` [{s['kind']}] {s['aria'][:100]}")

    out = "\n".join(lines)
    return out if len(out) <= limit else out[:limit] + "\n…(줄임)…"


def run(slug: str, *, log: Optional[Callable[[str], None]] = None) -> Dict[str, Any]:
    """`00_기획/구조.json` 을 만들고 그 내용을 돌려준다. **모델을 부르지 않는다.**"""
    src = paths.draft_html(slug)
    if not src.exists():
        raise FileNotFoundError("먼저 「원고」 단계를 돌려 원고.html 을 만드세요.")

    doc = parse(src.read_text(encoding="utf-8"))
    doc = {"schema_version": 1, "slug": slug, **doc}

    warnings: List[str] = []
    if not doc["facts"]:
        warnings.append("사실을 하나도 못 뽑았습니다. 원고에 표가 있는지 보세요 — "
                        "숫자가 <p> 안에 묻혀 있으면 대본이 근거 없이 씁니다.")
    if not doc["tables"]:
        warnings.append("표가 없습니다. 원고 단계에서 수치를 표로 세우게 하세요.")
    thin = [s["id"] for s in doc["sections"] if len(s["block_ids"]) < 2]
    if thin:
        warnings.append(f"블록이 한 개뿐인 절: {', '.join(thin[:6])}")
    doc["warnings"] = warnings

    if log:
        log(f"절 {len(doc['sections'])}개 · 블록 {len(doc['blocks'])}개 · "
            f"표 {len(doc['tables'])}개 · 골격 {len(doc['skeletons'])}개 · "
            f"사실 {len(doc['facts'])}개")
        for f in doc["facts"][:8]:
            log(f"  {f['id']} [{f['kind']}] {f['label']} = {f['value']}{f['unit']}"
                + (f" ({f['year']})" if f.get("year") else ""))
        for w in warnings:
            log(f"  ! {w}")

    atomic_write_json(str(paths.structure_json(slug)), doc, indent=2)
    return doc
