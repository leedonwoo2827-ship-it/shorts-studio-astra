# -*- coding: utf-8 -*-
"""장별원고 들여오기 — 쇼츠공방 I 의 `chNN_bundle` → 이 레포의 프로젝트.

    python tools/import_bundle.py ch09 --mbti ENFP
    python tools/import_bundle.py --all --mbti ENFP        # 전 장

쇼츠공방 I 이 한 장(章)마다 `chNN_script.json` 을 갖고 있다. 스물두 씬의
`narration_text` 는 이미 사람이 검수한 원고라, PDF 를 다시 긁어 낼 이유가 없다.

    <SERIES>/input/chNN_bundle/script/chNN_script.json
      → <작업물루트>/<slug>/00_기획/chNN_원고.md   (+ source.json)

★ **여기서 대본을 만들지 않는다.** 마크다운까지만 놓고 멈춘다. 그 다음은 화면의
  「재료 → 원고 → 구조 → 대본」이 그대로 맡는다 — 길을 두 벌 두면 한쪽만 고쳐진다.

★ **소제목을 살려서 넘긴다.** 줄글 한 덩어리로 주면 「원고」 단계가 헤딩 하나짜리
  덩어리를 받고, 그러면 대본이 첫 단락만 잡고 뒷장을 버린다(README 실측).
  씬 제목이 이미 절 제목 노릇을 하므로 `##` 로 올려 준다.

★ **PDF 가 오면 이 도구를 쓰지 않는다.** 원문이 있으면 원문이 낫다 — 이 길은
  이미 검수된 장별원고를 이어 쓰려고 뚫은 것이다.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core import config, paths, persona           # noqa: E402
from core.atomic_io import atomic_write_json, atomic_write_text  # noqa: E402


def series_root() -> Path:
    """쇼츠공방 I 의 자산 루트. 설정에 없으면 환경변수를 본다."""
    raw = (config.get("paths.series_root")
           or os.environ.get("SHORTS_SERIES_ROOT") or "").strip()
    if not raw:
        raise SystemExit(
            "시리즈 루트를 모릅니다. config.local.json 에 paths.series_root 를 적거나 "
            "SHORTS_SERIES_ROOT 환경변수를 주세요. (예: D:/00work/_series)")
    return Path(raw)


def series_name() -> str:
    return str(config.get("paths.series") or "baeum")


def bundle_dir(ch: str) -> Path:
    return series_root() / series_name() / "input" / f"{ch}_bundle"


def find_script(ch: str) -> Path:
    d = bundle_dir(ch)
    hits = sorted(d.glob("script/*_script.json"))
    if not hits:
        raise SystemExit(f"장별원고가 없습니다: {d / 'script'}")
    return hits[0]


def to_markdown(doc: Dict[str, Any], ch: str) -> str:
    """장별원고 JSON → 마크다운. 씬 제목이 `##`, 내레이션이 본문이다.

    `scene_meta.era` 가 있으면 제목 옆에 붙인다 — 연도는 「구조」 단계가 사실 표로
    뽑아 가는 재료이고, 본문에만 묻어 두면 놓친다.
    """
    title = str(doc.get("title") or ch)
    sub = str(doc.get("subtitle") or "").strip()

    out: List[str] = [f"# {title}"]
    if sub:
        out.append(f"\n{sub}")

    for s in doc.get("scenes") or []:
        head = str(s.get("title") or "").strip() or f"씬 {s.get('scene')}"
        era = str((s.get("scene_meta") or {}).get("era") or "").strip()
        out.append(f"\n## {head}" + (f" ({era})" if era else ""))
        body = str(s.get("narration_text") or "").strip()
        if body:
            out.append(f"\n{body}")
        # 씬 부제는 그 절이 무엇을 말하는지 한 줄로 요약한다. 「구조」가 절을
        # 알아보는 데 쓰이므로 버리지 않는다.
        cap = str((s.get("scene_meta") or {}).get("subtitle") or "").strip()
        if cap and cap != head:
            out.append(f"\n*{cap}*")
    return "\n".join(out) + "\n"


def import_one(ch: str, *, mbti: str = "", fmt: str = "",
               overwrite: bool = False) -> str:
    src = find_script(ch)
    doc = json.loads(src.read_text(encoding="utf-8"))

    chapter = doc.get("chapter")
    if chapter is None:
        m = re.search(r"(\d+)", ch)
        chapter = int(m.group(1)) if m else 0
    title = str(doc.get("title") or ch)
    who = persona.normalize(mbti)

    # `09_03ENFP-배움` — 장 번호·발행 순서·유형·제목. 같은 장의 열여섯 유형이
    # 탐색기에서 한자리에 모인다.
    slug = paths.chapter_slug(chapter, who, title)

    root = paths.project(slug)
    if root.exists() and not overwrite:
        print(f"  건너뜀 (이미 있음): {slug}")
        return slug

    paths.ensure(slug)
    md_name = f"{ch}_원고.md"
    atomic_write_text(str(paths.plan_dir(slug) / md_name), to_markdown(doc, ch))
    atomic_write_json(str(paths.source_json(slug)), {
        "file": md_name,
        "title": f"{chapter}장 {title}",
        "format": (fmt or config.get("shorts.format", "narrative")).strip(),
        "voice": config.get("narration.voice", "F2"),
        "speed": config.get("narration.speed", 1.2),
        "mbti": who,
        "mood": persona.mood(who),
        # 어디서 왔는지 남긴다. 나중에 원문 PDF 로 다시 뽑을 때 무엇을 갈아 끼우는지
        # 알아야 한다.
        "imported_from": str(src),
        "chapter": chapter,
    }, indent=2)
    print(f"  들여옴: {slug}  ({len(doc.get('scenes') or [])}씬 · {md_name})")
    return slug


def all_chapters() -> List[str]:
    d = series_root() / series_name() / "input"
    return sorted(p.name[:-len("_bundle")] for p in d.glob("ch*_bundle")
                  if (p / "script").is_dir())


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="쇼츠공방 I 의 장별원고를 들여온다")
    ap.add_argument("chapters", nargs="*", help="ch09 처럼. 비우고 --all 을 쓰면 전 장")
    ap.add_argument("--all", action="store_true", help="시리즈의 모든 장")
    ap.add_argument("--mbti", default="", help="무드로 입힐 유형 (예: ENFP)")
    ap.add_argument("--fmt", default="", help="narrative | listicle")
    ap.add_argument("--overwrite", action="store_true", help="있으면 덮어쓴다")
    a = ap.parse_args(argv)

    chs = all_chapters() if a.all else list(a.chapters)
    if not chs:
        ap.error("장을 고르거나 --all 을 주세요.")
    if a.mbti and not persona.normalize(a.mbti):
        ap.error(f"MBTI 16유형이 아닙니다: {a.mbti}")

    print(f"작업물 루트: {paths.PROJECTS}")
    for ch in chs:
        import_one(ch, mbti=a.mbti, fmt=a.fmt, overwrite=a.overwrite)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
