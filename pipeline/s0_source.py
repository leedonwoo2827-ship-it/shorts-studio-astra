# -*- coding: utf-8 -*-
"""입력 두 갈래 — **문 A: 단어 한 줄** · **문 B: 문서파일(단행본)**.

    문 A  "인공지능의 역사"                 → 모델이 전부 쓴다
    문 B  책 PDF / DOCX / TXT / MD / HTML  → 모델이 **그 글에 근거해서만** 쓴다

★ **왜 두 문을 한 파일에 두나.** 아래 단계(S1 개요)가 받는 것은 어느 쪽이든
  `Source` 하나다. 두 문의 차이는 여기서 끝난다 — S1·S2·합성·렌더는 어느 문으로
  들어왔는지 모른다. 문을 하나 더 붙일 때(URL, 유튜브 자막 …) 고칠 자리도 여기뿐이다.

## 문 B 는 두 걸음이다 — 이게 핵심 설계다

    ① 파일  →  source.md   (결정론 추출. 모델을 부르지 않는다)
                    ↓
              **사람이 보고 고친다**
                    ↓
    ② source.md  →  장 인식  →  개요(모델, 돈)

**왜 md 를 사이에 두나.** 조판된 책 PDF 는 그냥 넣을 수 있는 물건이 아니다.
실측(2026-09-01, 실제 단행본 한 장):

    291                          ← 쪽번호
    닫힌 교실, 열린 화면            ← 진짜 장 제목
    14장                          ← 쪽 장식이 **본문 한가운데** 있다
    배움을 설계하는 기술의 역사       ← 책 제목, 매 쪽 반복
    …를 팬데믹으로                  ← 문장이 줄 중간에서 끊긴다
    규정했다.

이걸 그대로 모델에 넣으면 **부를 때마다 그 값을 내고** 내용도 흐려진다. 그리고
정규식으로 장 경계를 아무리 영리하게 추측해도 책마다 틀린다 — `8장에서 다뤘던…`
이라는 **본문 문장**이 장 시작으로 잡혔다.

md 를 사이에 두면 그 문제가 사라진다. 사람이 한 번 보고 `## ` 를 찍어 주면 장 인식은
추측이 아니라 **정확**해지고, 같은 md 로 영상을 여러 편 만들 수 있다.

★ 추출은 **결정론**이다 — 모델을 부르지 않는다. 같은 파일이면 같은 md 가 나와야
  캐시(input_hash)가 의미를 갖는다.
"""
from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

# 이 길이를 넘으면 "통째로 주기"를 포기하고 장을 골라 달라고 한다.
# 6만 자 ≈ 2만 토큰 — 개요 한 번에 그 정도가 상한이라고 보는 것이 안전하다.
WHOLE_LIMIT = 60_000

# ★ `장` 뒤에 **조사가 붙으면 제목이 아니다.** 실측(2026-09-01): 본문 문장
#   「8장에서 다뤘던 ‘SCORM에서 xAPI로’의 진화…」가 장 시작으로 잡혔다.
#   조사가 붙었다는 것은 그 말이 문장 속에서 쓰였다는 뜻이다.
_JOSA = r"(?!에서|에는|에|은|는|이|가|을|를|의|과|와|도|만|부터|까지|보다|처럼)"

# 장 제목으로 볼 것. 긴 것부터 — `제3장` 이 `3장` 보다 먼저 잡혀야 한다.
_HEAD_PATTERNS = (
    re.compile(r"^\s*(#{1,3}\s+.{1,80})\s*$"),                      # 마크다운이 가장 확실
    re.compile(r"^\s*(제\s*\d+\s*[장부편]" + _JOSA + r"\s*\.?\s*.{0,60})\s*$"),
    re.compile(r"^\s*(\d+\s*[장부편]" + _JOSA + r"\s*\.?\s*.{0,60})\s*$"),
    re.compile(r"^\s*(Chapter\s+\d+\b.{0,60})\s*$", re.IGNORECASE),
    re.compile(r"^\s*(\d+\.\d*\s+\S.{0,70})\s*$"),                  # 1. / 1.2 절 번호
)

# 쪽번호로만 이루어진 줄
_PAGE_NO = re.compile(r"^\s*[-–—]?\s*\d{1,4}\s*[-–—]?\s*$")

# 본문·제목에 **붙어 있는** 쪽 표시. 실측(2026-09-01, 원고 HTML):
#     25. 재정정책의 세 가지 시차489489쪽
#     29. 1,000억 달러를 줄이면 무엇이 늘어나는가492492-493쪽
# 걷어내지 않으면 내레이션이 「사백팔십구 사백팔십구 쪽」을 소리 내어 읽는다.
# 41개 제목 전부에 붙어 있어서 영상 내내 나온다.
#
# ★ **글자에 붙어 있는 것만** 잡는다. 「자세한 내용은 150쪽 을 보라」처럼 사람이
#   뜻을 담아 쓴 것은 앞에 공백이 있다 — 그건 건드리지 않는다.
# 앞 글자가 **숫자가 아닐 때만** 잡는다. `(?<=\S)` 로 하면 「150쪽」의 `1` 을
# 글자로 보고 「50쪽」만 지워 「1」이 남는다(실측).
_PAGE_MARK = re.compile(r"(?<=[^\s\d])\d{2,}(?:\s*[-–—~]\s*\d{1,4})?\s*쪽")


def strip_page_marks(text: str):
    """글자에 붙은 쪽 표시를 걷어낸다. → (걷어낸 글, 걷어낸 개수)"""
    n = len(_PAGE_MARK.findall(text or ""))
    return _PAGE_MARK.sub("", text or ""), n


# 문장이 끝났다고 볼 끝글자. 여기서 안 끝나면 다음 줄과 이어진 문장이다.
_SENT_END = re.compile(r"[.!?。！？…:;”’\"')\]】」』]\s*$")


@dataclass
class Section:
    """장 하나. `text` 는 그 장의 본문 전체."""
    idx: int
    title: str
    text: str

    @property
    def chars(self) -> int:
        return len(self.text)

    def to_dict(self, *, with_text: bool = False) -> Dict[str, Any]:
        d: Dict[str, Any] = {
            "idx": self.idx,
            "title": self.title,
            "chars": self.chars,
            "head": self.text[:180].replace("\n", " ").strip(),
        }
        if with_text:
            d["text"] = self.text
        return d


@dataclass
class Source:
    """S1 이 받는 유일한 입력. 두 문의 차이가 여기서 끝난다."""
    door: str                      # "keyword" | "document"
    topic: str = ""                # 문 A 의 단어·주제. 문 B 에서는 파일명·책 제목
    filename: str = ""             # 문 B 만
    text: str = ""                 # 문 B: 선택된 범위의 본문. 문 A: 빈 문자열
    sections: List[Section] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    @property
    def chars(self) -> int:
        return len(self.text)

    @property
    def needs_scope(self) -> bool:
        """사람이 장 범위를 골라야 하는가."""
        return self.door == "document" and self.chars > WHOLE_LIMIT

    def to_dict(self) -> Dict[str, Any]:
        return {
            "door": self.door,
            "topic": self.topic,
            "filename": self.filename,
            "chars": self.chars,
            "needs_scope": self.needs_scope,
            "whole_limit": WHOLE_LIMIT,
            "sections": [s.to_dict() for s in self.sections],
            "warnings": self.warnings,
        }


# ── 문 A ───────────────────────────────────────────────────────────────────
def from_keyword(topic: str) -> Source:
    """단어·주제 한 줄. 이게 전부다."""
    t = (topic or "").strip()
    if not t:
        raise ValueError("주제를 입력하세요.")
    return Source(door="keyword", topic=t)


# ── 문 B ①: 파일 → 쪽 목록 ────────────────────────────────────────────────
def _pdf_pages(p: Path) -> List[str]:
    """PDF → 쪽 목록.

    ★ pypdf 의 `Ignoring wrong pointing object …` 경고를 잠재운다. 조판 도구가
      남긴 흠집이고 우리가 손쓸 수 있는 것이 아닌데, 쪽마다 한 줄씩 나와서
      정작 봐야 할 로그를 밀어낸다.
    """
    import logging
    lg = logging.getLogger("pypdf")
    prev = lg.level
    lg.setLevel(logging.ERROR)
    try:
        from pypdf import PdfReader
        return [(pg.extract_text() or "") for pg in PdfReader(str(p)).pages]
    finally:
        lg.setLevel(prev)


def _docx_pages(p: Path) -> List[str]:
    import docx
    out: List[str] = []
    for para in docx.Document(str(p)).paragraphs:
        s = (para.text or "").strip()
        if not s:
            continue
        # 워드 제목 스타일을 마크다운 제목으로 — 여기서 구조가 공짜로 나온다
        st = (para.style.name or "").lower() if para.style is not None else ""
        if st.startswith("heading"):
            digits = "".join(ch for ch in st if ch.isdigit()) or "1"
            out.append("#" * min(int(digits), 3) + " " + s)
        else:
            out.append(s)
    return ["\n".join(out)]


_TAG = re.compile(r"<[^>]+>")
_SCRIPT_STYLE = re.compile(r"<(script|style)\b.*?</\1>", re.IGNORECASE | re.DOTALL)
_ENTITIES = (
    ("&nbsp;", " "), ("&amp;", "&"), ("&lt;", "<"), ("&gt;", ">"),
    ("&quot;", '"'), ("&#39;", "'"), ("&mdash;", "—"),
)


def _html_pages(raw: str) -> List[str]:
    s = _SCRIPT_STYLE.sub(" ", raw)
    s = re.sub(
        r"<h([1-3])\b[^>]*>(.*?)</h\1>",
        lambda m: "\n" + "#" * int(m.group(1)) + " " + _TAG.sub("", m.group(2)).strip() + "\n",
        s, flags=re.IGNORECASE | re.DOTALL)
    s = re.sub(r"</(p|div|li|tr|br)\s*>", "\n", s, flags=re.IGNORECASE)
    s = _TAG.sub(" ", s)
    for a, b in _ENTITIES:
        s = s.replace(a, b)
    return [s]


def read_pages(path: str | Path) -> tuple[List[str], List[str]]:
    """파일 → 쪽 목록. 두 번째 값은 경고."""
    p = Path(path)
    warn: List[str] = []
    if not p.is_file():
        raise FileNotFoundError(f"파일이 없습니다: {p}")
    suf = p.suffix.lower()
    if suf == ".pdf":
        pages = _pdf_pages(p)
        if len("".join(pages).strip()) < 200:
            # 스캔 PDF — 글자가 없고 그림만 있다. OCR 은 이 프로젝트 범위 밖이다.
            warn.append("PDF 에서 글자가 거의 안 나왔습니다. 스캔본이면 OCR 이 먼저 필요합니다.")
    elif suf == ".docx":
        pages = _docx_pages(p)
    elif suf in (".html", ".htm"):
        pages = _html_pages(p.read_text(encoding="utf-8", errors="replace"))
    elif suf in (".txt", ".md", ".markdown"):
        # utf-8-sig — BOM 이 붙은 파일이 실제로 온다
        pages = [p.read_text(encoding="utf-8-sig", errors="replace")]
    elif suf == ".hwp":
        raise ValueError("HWP 는 아직 지원하지 않습니다. PDF 나 DOCX 로 저장해 주세요.")
    else:
        raise ValueError(f"모르는 확장자입니다: {suf} (pdf · docx · txt · md · html)")
    return pages, warn


def strip_furniture(pages: List[str]) -> tuple[List[str], List[str]]:
    """머리말·꼬리말·쪽번호를 걷어낸다. **책 조판 PDF 에서 이게 없으면 못 쓴다.**

    판정은 **반복**이다. 서식(글꼴·위치)은 pypdf 가 주지 않으니 쓸 수 없다.
      · 짧은 줄(40자 이하)이
      · 세 쪽 이상, 그리고 전체 쪽의 30% 이상에서 똑같이 나오면 → 장식이다.
    본문 문장이 그렇게 반복될 일은 없다. 쪽번호만 있는 줄은 반복과 무관하게 버린다.

    ★ 쪽이 셋 미만이면 반복 판정을 하지 않는다 — 표본이 없으면 본문을 지울 위험만 있다.
    """
    dropped: List[str] = []
    if len(pages) < 3:
        return ([("\n".join(ln for ln in t.split("\n") if not _PAGE_NO.match(ln)))
                 for t in pages], dropped)

    seen: Counter = Counter()
    for t in pages:
        # 한 쪽 안에서 두 번 나와도 한 번으로 센다
        for ln in {x.strip() for x in t.split("\n") if 0 < len(x.strip()) <= 40}:
            seen[ln] += 1

    need = max(3, int(len(pages) * 0.3))
    furniture = {ln for ln, n in seen.items() if n >= need}
    dropped = sorted(furniture, key=lambda x: -seen[x])

    out: List[str] = []
    for t in pages:
        keep = [ln for ln in t.split("\n")
                if ln.strip() not in furniture and not _PAGE_NO.match(ln)]
        out.append("\n".join(keep))
    return out, dropped


def join_wraps(text: str) -> str:
    """조판 때문에 문장 중간에서 끊긴 줄을 이어 붙인다.

    책 PDF 는 한 문단이 여러 줄로 쪼개져 나온다 — 「…를 팬데믹으로 / 규정했다.」
    그대로 두면 자막·대본 단계에서 줄바꿈이 문장 경계로 오인된다.

    ★ 제목 줄(`#`)과 빈 줄은 건드리지 않는다. 문장 끝 부호로 끝나는 줄도 그대로 둔다.
    ★ 한글끼리 이을 때는 공백을 넣지 않는다 — 「팬데믹으로규정했다」가 아니라
      원래 줄 끝에 있던 공백이 살아 있으면 그것을 쓰고, 없으면 붙인다.
    """
    out: List[str] = []
    for raw in text.split("\n"):
        ln = raw.rstrip()
        if not ln.strip():
            out.append("")
            continue
        if ln.lstrip().startswith("#"):
            out.append(ln.strip())
            continue
        prev = out[-1] if out else ""
        if prev and not prev.startswith("#") and not _SENT_END.search(prev):
            sep = "" if prev.endswith(" ") else (
                "" if (prev and ord(prev[-1]) > 0x1100 and ln.lstrip()[:1]
                       and ord(ln.lstrip()[0]) > 0x1100) else " ")
            out[-1] = prev.rstrip() + sep + ln.strip() if sep == "" else prev + sep + ln.strip()
        else:
            out.append(ln.strip())
    return "\n".join(out)


def to_markdown(path: str | Path, *, title: str = "") -> tuple[str, List[str]]:
    """파일 → **사람이 읽고 고칠 수 있는 마크다운**. 이것이 문 B 의 1단계 산출물이다."""
    p = Path(path)
    pages, warn = read_pages(p)
    pages, dropped = strip_furniture(pages)
    if dropped:
        warn.append("쪽 장식으로 보고 걷어냄: " + " · ".join(repr(x) for x in dropped[:6]))

    body = "\n\n".join(pages)
    body = body.replace("\r\n", "\n").replace("\r", "\n")
    body = re.sub(r"[ \t]+", " ", body)
    body, n_marks = strip_page_marks(body)
    if n_marks:
        warn.append(f"글자에 붙은 쪽 표시 {n_marks}개를 걷어냈습니다 "
                    f"(예: 「…시차489489쪽」 → 「…시차」).")
    body = join_wraps(body)
    body = re.sub(r"\n{3,}", "\n\n", body).strip()

    # 이미 찾은 제목을 `## ` 로 올려 둔다 — 사람이 고칠 출발점이다
    lines: List[str] = []
    for ln in body.split("\n"):
        if ln.startswith("#"):
            lines.append(ln)
            continue
        hit = None
        if ln.strip() and len(ln) <= 90:
            for pat in _HEAD_PATTERNS[1:]:          # 마크다운 패턴은 위에서 이미 처리
                m = pat.match(ln)
                if m:
                    hit = m.group(1).strip()
                    break
        lines.append(f"## {hit}" if hit else ln)

    head = f"# {title or p.stem}\n\n"
    md = head + "\n".join(lines).strip() + "\n"
    warn.append("이 마크다운을 **보고 고친 뒤** 개요를 만드세요. "
                "`## ` 로 시작하는 줄이 장 경계입니다.")
    return md, warn


# ── 문 B ②: 마크다운 → 장 ────────────────────────────────────────────────
def split_sections(text: str) -> List[Section]:
    """장 제목으로 쪼갠다. 못 찾으면 글자 수로 균등 분할한다.

    ★ **못 찾아도 실패하지 않는다.** 장 제목 없는 원고가 실제로 온다(강의 노트,
      스캔 텍스트). 그때도 사람이 범위를 고를 수 있어야 하므로 균등 분할로 떨어진다.
    """
    lines = text.split("\n")
    marks: List[tuple[int, str]] = []
    for i, ln in enumerate(lines):
        if not ln.strip() or len(ln) > 90:
            continue
        for pat in _HEAD_PATTERNS:
            m = pat.match(ln)
            if m:
                t = re.sub(r"^#+\s*", "", m.group(1)).strip()
                # 문서 제목(`# `)은 장이 아니다
                if ln.lstrip().startswith("# ") and not ln.lstrip().startswith("## "):
                    break
                marks.append((i, t))
                break

    if len(marks) >= 2:
        out: List[Section] = []
        for k, (start, title) in enumerate(marks):
            end = marks[k + 1][0] if k + 1 < len(marks) else len(lines)
            body = "\n".join(lines[start:end]).strip()
            if body:
                out.append(Section(idx=len(out) + 1, title=title, text=body))
        if out:
            return out

    if len(marks) == 1:
        return [Section(idx=1, title=marks[0][1], text=text.strip())]

    # 폴백 — 4만 자씩 균등 분할
    step = 40_000
    if len(text) <= step:
        return [Section(idx=1, title="전체", text=text.strip())]
    return [
        Section(idx=i + 1,
                title=f"{i * step:,}~{min((i + 1) * step, len(text)):,}자",
                text=text[i * step:(i + 1) * step])
        for i in range((len(text) + step - 1) // step)
    ]


def from_markdown(md: str, *, topic: str = "", filename: str = "",
                  pick: Optional[List[int]] = None) -> Source:
    """문 B ②. 사람이 고친 마크다운으로 Source 를 만든다."""
    if not (md or "").strip():
        raise ValueError("문서가 비어 있습니다.")
    sections = split_sections(md)
    warn: List[str] = []
    if pick:
        want = {int(i) for i in pick}
        chosen = [s for s in sections if s.idx in want]
        if not chosen:
            raise ValueError(f"고른 장이 없습니다: {sorted(want)}")
        body = "\n\n".join(s.text for s in chosen)
        warn.append(f"{len(chosen)}/{len(sections)}장 선택 · {len(body):,}자")
    else:
        body = md
    return Source(door="document", topic=(topic or "").strip() or "문서",
                  filename=filename, text=body, sections=sections, warnings=warn)


def from_document(path: str | Path, *, topic: str = "",
                  pick: Optional[List[int]] = None) -> Source:
    """파일에서 바로. (md 를 거치지 않는 CLI 용 지름길)"""
    p = Path(path)
    md, warn = to_markdown(p, title=topic)
    src = from_markdown(md, topic=topic or p.stem, filename=p.name, pick=pick)
    src.warnings = warn + src.warnings
    return src
