# -*- coding: utf-8 -*-
"""경로는 여기 한 곳에만 산다.

프로젝트는 **레포 안** `projects/<slug>/` 에 쌓인다. 다른 폴더를 참조하지 않는다 —
노트북에 레포만 통째로 옮기면 작업물까지 같이 간다.

    projects/<slug>/
      00_기획/     원본 파일 · source.json          ← 사람이 넣는 것은 여기뿐
      01_대본/     script.json ★ · overrides.json · 발음교정표.txt
      02_음성/     001.wav …                        (실측 길이가 씬 길이를 정한다)
      03_자막/     <slug>.srt · cue-sheet.csv
      04_이미지/   이미지프롬프트.json · 001.png …
      05_컴포지션/ index.html · assets/ · vendor/
      06_완성/     v01_MMDD-HHMM/<slug>.mp4 · 유튜브.txt · 정보.json
                   최신.txt   ← 최신 빌드 폴더 이름. 빌드는 쌓이고 덮어쓰지 않는다
"""
from __future__ import annotations

import re
import unicodedata
from datetime import datetime
from pathlib import Path
from typing import List, Optional

ROOT = Path(__file__).resolve().parents[1]
PROJECTS = ROOT / "projects"
TEMPLATES = ROOT / "templates"
STATIC = ROOT / "static"
FONTS = STATIC / "fonts"

PLAN = "00_기획"
SCRIPT = "01_대본"
AUDIO = "02_음성"
SUBS = "03_자막"
SCENEART = "04_장면"
COMPOSE = "05_컴포지션"
DONE = "06_완성"
STAGE_DIRS = (PLAN, SCRIPT, AUDIO, SUBS, SCENEART, COMPOSE, DONE)

_BAD = re.compile(r'[<>:"/\|?*\x00-\x1f]')


def slugify(title: str, when: Optional[datetime] = None) -> str:
    """`YYMMDD-제목`. 한글은 그대로 둔다 — 폴더 이름이 곧 사람이 읽는 이름이다."""
    when = when or datetime.now()
    name = unicodedata.normalize("NFC", (title or "무제").strip())
    name = _BAD.sub("", name).strip(" .")
    name = re.sub(r"\s+", "-", name)[:40] or "무제"
    return f"{when:%y%m%d}-{name}"


def project(slug: str) -> Path:
    """프로젝트 루트. `..` 로 레포 밖을 가리키는 slug 는 거부한다."""
    p = (PROJECTS / slug).resolve()
    if not str(p).startswith(str(PROJECTS.resolve())):
        raise ValueError(f"레포 밖을 가리키는 이름입니다: {slug!r}")
    return p


def ensure(slug: str) -> Path:
    root = project(slug)
    for d in STAGE_DIRS:
        (root / d).mkdir(parents=True, exist_ok=True)
    return root


def plan_dir(slug: str) -> Path:      return project(slug) / PLAN
def script_json(slug: str) -> Path:   return project(slug) / SCRIPT / "script.json"
def overrides(slug: str) -> Path:     return project(slug) / SCRIPT / "overrides.json"
def pron_table(slug: str) -> Path:    return project(slug) / SCRIPT / "발음교정표.txt"
def source_md(slug: str) -> Path:     return project(slug) / PLAN / "source.md"
def source_json(slug: str) -> Path:   return project(slug) / PLAN / "source.json"
def audio_dir(slug: str) -> Path:     return project(slug) / AUDIO
def wav(slug: str, no: int) -> Path:  return project(slug) / AUDIO / f"{no:03d}.wav"
def subs_dir(slug: str) -> Path:      return project(slug) / SUBS
def srt(slug: str) -> Path:           return project(slug) / SUBS / f"{slug}.srt"
def cue_csv(slug: str) -> Path:       return project(slug) / SUBS / "cue-sheet.csv"
def art_dir(slug: str) -> Path:       return project(slug) / SCENEART
def art_spec(slug: str) -> Path:      return project(slug) / SCENEART / "장면지시.json"
def comp_dir(slug: str) -> Path:      return project(slug) / COMPOSE
def done_dir(slug: str) -> Path:      return project(slug) / DONE
def latest_txt(slug: str) -> Path:    return project(slug) / DONE / "최신.txt"


def new_build_dir(slug: str, when: Optional[datetime] = None) -> Path:
    """`v01_0908-1530`. 번호는 이어지고 **덮어쓰지 않는다.**"""
    when = when or datetime.now()
    root = done_dir(slug)
    root.mkdir(parents=True, exist_ok=True)
    n = 1 + sum(1 for p in root.iterdir() if p.is_dir() and p.name.startswith("v"))
    d = root / f"v{n:02d}_{when:%m%d-%H%M}"
    d.mkdir(parents=True, exist_ok=True)
    return d


def latest_build(slug: str) -> Optional[Path]:
    f = latest_txt(slug)
    if f.exists():
        p = done_dir(slug) / f.read_text(encoding="utf-8").strip()
        if p.is_dir():
            return p
    dirs = sorted((p for p in done_dir(slug).glob("v*") if p.is_dir()), key=lambda p: p.name)
    return dirs[-1] if dirs else None


def list_projects() -> List[str]:
    if not PROJECTS.exists():
        return []
    return sorted(p.name for p in PROJECTS.iterdir()
                  if p.is_dir() and not p.name.startswith((".", "_")))
