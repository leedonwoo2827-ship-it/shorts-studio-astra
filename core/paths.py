# -*- coding: utf-8 -*-
"""경로는 여기 한 곳에만 산다.

프로젝트는 **작업물 루트** 아래 `<slug>/` 에 쌓인다. 그 루트는 설정이 정한다:

    1. 환경변수 `SHORTS2_PROJECTS_ROOT`
    2. `config.local.json` 의 `paths.projects_root`  ← 이 PC 것
    3. 없으면 레포 안 `projects/`                    ← 예전 그대로

★ **왜 밖으로 뺐나.** 레포 안에 쌓으면 `git pull` · 레포 교체 · 재클론이 작업물을
  건드린다. 그리고 쇼츠공방 I 이 이미 `_series/<시리즈>/output` 에 결과를 떨구고
  있어서, 둘을 같은 루트에 모아야 한 장(章)의 산출물이 한자리에 보인다.
  루트를 안 적으면 예전처럼 레포 안에 쌓이므로 **가져만 온 사람은 달라지는 게 없다.**

    <작업물루트>/<slug>/                       slug = `09-배움` (한 장 = 한 폴더)
      00_기획/     원본 파일 · source.json          ← 사람이 넣는 것은 여기뿐
                   source.md · 원고.html · 구조.json   (재료를 갈아 내는 세 단계)
                   현재유형.txt  ← 지금 보고 있는 유형(`03ENFP`). 여기만 공용이다
      01_대본/03ENFP/  script.json ★ · overrides.json · 발음교정표.txt
      02_음성/03ENFP/  001.wav …                    (실측 길이가 씬 길이를 정한다)
      03_자막/03ENFP/  03ENFP_<slug>.srt · cue-sheet.csv
      04_장면/03ENFP/  장면지시.json · 001.svg …
      05_컴포지션/03ENFP/ index.html · assets/
      06_완성/03ENFP/  v01_MMDD-HHMM/<slug>.mp4 · 유튜브.txt · 정보.json
                       최신.txt  ← 최신 빌드 폴더 이름. 빌드는 쌓이고 덮어쓰지 않는다

    ★ 유형 폴더는 **쓸 때만** 생긴다. 열여섯 개를 미리 깔지 않는다.
    ★ 현재유형.txt 가 없으면 옛 평평한 구조로 그대로 돈다 — 컨셉을 옮겨도 막히지 않는다.
"""
from __future__ import annotations

import os
import re
import unicodedata
from datetime import datetime
from pathlib import Path
from typing import List, Optional

ROOT = Path(__file__).resolve().parents[1]


def _projects_root() -> Path:
    """작업물이 쌓이는 루트. 환경변수 → config → 레포 안 `projects/`.

    ★ import 시점에 한 번만 읽지 않는다. 설정을 고치고 서버를 다시 띄우면 바로
      듣게 하려는 것이고, 무엇보다 `core.config` 를 모듈 최상단에서 부르면
      import 순환이 생긴다.
    """
    raw = (os.environ.get("SHORTS2_PROJECTS_ROOT") or "").strip()
    if not raw:
        from core import config          # 지연 import — 순환 방지
        raw = str(config.get("paths.projects_root") or "").strip()
    return Path(raw).expanduser().resolve() if raw else ROOT / "projects"


class _ProjectsRoot(os.PathLike):
    """`paths.PROJECTS` 를 예전처럼 쓰게 두면서 설정을 매번 읽는 얇은 껍데기.

    옛 코드가 `PROJECTS / slug` · `PROJECTS.exists()` 처럼 쓰고 있어서 상수를
    함수로 바꾸면 호출부를 전부 고쳐야 한다. `Path` 로 위임한다.
    """
    def __fspath__(self) -> str:      return str(_projects_root())
    def __truediv__(self, other):     return _projects_root() / other
    def __getattr__(self, name):      return getattr(_projects_root(), name)
    def __str__(self) -> str:         return str(_projects_root())
    def __repr__(self) -> str:        return f"PROJECTS({_projects_root()})"


PROJECTS = _ProjectsRoot()
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


def chapter_slug(chapter: int, mbti: str, title: str = "") -> str:
    """장 프로젝트의 폴더 이름 — `03ENFP_09-배움`.

        03      발행 순서(두 자리)    → 쇼츠공방 I 의 「3리스트」와 같은 수
        ENFP    유형
        09      장 번호(두 자리)
        배움    장 제목

    ★ **유형이 앞이다.** 한 유형으로 열일곱 장을 한 바퀴 도는 것이 한 「리스트」이고,
      그것이 실제 작업 단위다(쇼츠공방 I 의 「3리스트 · ENFP」). 유형을 앞에 두면
      한 바퀴가 탐색기에서 한 덩어리로 모이고, 그 안이 장 순서로 선다.

    ★ **날짜를 앞에 두지 않는다.** `slugify` 는 `YYMMDD-` 를 붙이는데, 그러면
      10장이 1장 옆에 붙고 한 바퀴가 만든 날짜로 흩어진다.

    ★ 올린 파일로 만드는 프로젝트는 장 번호가 없으므로 `slugify` 를 그대로 쓴다.
    """
    from core import persona                 # 지연 import — 순환 방지
    who = persona.normalize(mbti)
    rr = persona.round_no(who)
    head = f"{rr:02d}{who}_{int(chapter):02d}" if who else f"{int(chapter):02d}"
    name = _BAD.sub("", unicodedata.normalize("NFC", (title or "").strip())).strip(" .")
    name = re.sub(r"\s+", "-", name)[:32]
    return f"{head}-{name}" if name else head


def project(slug: str) -> Path:
    """프로젝트 루트. `..` 로 작업물 루트 밖을 가리키는 slug 는 거부한다."""
    root = _projects_root()
    p = (root / slug).resolve()
    if not str(p).startswith(str(root)):
        raise ValueError(f"작업물 루트 밖을 가리키는 이름입니다: {slug!r}")
    return p


# ── 유형(무드) 층 ────────────────────────────────────────────────────────
# ★ **한 장(章) = 한 폴더.** 같은 장을 열여섯 유형으로 내보내지만 원고는 한 벌이다.
#   유형마다 폴더를 통째로 복사하면 원고 오타 하나를 열여섯 군데 고쳐야 한다.
#
#       09-배움/
#         00_기획/            ← 공용. 원본·source.md·원고.html·구조.json
#         01_대본/03ENFP/     ← 여기부터 유형별. 무드가 대본을 바꾸면
#         02_음성/03ENFP/       음성·자막·장면이 줄줄이 바뀐다
#         …
#         06_완성/03ENFP/v01_…
#
# ★ 어느 유형을 보고 있는지는 `00_기획/현재유형.txt` 한 줄이 정한다. 경로 함수에
#   인자를 늘리지 않는 이유는 호출부가 수십 곳이고, 잡은 어차피 프로젝트당 하나만
#   돌아서 「지금 작업 중인 유형」이 둘일 수 없기 때문이다.

_VARIANT_FILE = "현재유형.txt"
# 유형을 타는 단계 — 00_기획 만 공용이다
VARIANT_DIRS = (SCRIPT, AUDIO, SUBS, SCENEART, COMPOSE, DONE)


def variant(slug: str) -> str:
    """지금 보고 있는 유형 태그(`03ENFP`). 없으면 빈 문자열 — 옛 프로젝트가 그렇다."""
    f = project(slug) / PLAN / _VARIANT_FILE
    try:
        return f.read_text(encoding="utf-8").strip()
    except (FileNotFoundError, NotADirectoryError):
        return ""


def set_variant(slug: str, tag: str) -> str:
    tag = (tag or "").strip()
    d = project(slug) / PLAN
    d.mkdir(parents=True, exist_ok=True)
    (d / _VARIANT_FILE).write_text(tag, encoding="utf-8")
    if tag:
        for k in VARIANT_DIRS:
            (project(slug) / k / tag).mkdir(parents=True, exist_ok=True)
    return tag


def variants(slug: str) -> List[str]:
    """이 장에 만들어져 있는 유형 태그들. `01_대본` 밑을 본다 — 대본이 첫 산출물이다."""
    d = project(slug) / SCRIPT
    if not d.is_dir():
        return []
    return sorted(x.name for x in d.iterdir() if x.is_dir() and not x.name.startswith("."))


def variant_tag(mbti: str) -> str:
    """`ENFP` → `03ENFP`. 발행 순서를 앞에 붙여 폴더가 순서대로 서게 한다."""
    from core import persona                 # 지연 import — 순환 방지
    who = persona.normalize(mbti)
    return f"{persona.round_no(who):02d}{who}" if who else ""


def stage_dir(slug: str, stage: str) -> Path:
    """단계 폴더. 유형을 타는 단계면 그 밑의 유형 폴더까지 내려간다."""
    base = project(slug) / stage
    v = variant(slug) if stage in VARIANT_DIRS else ""
    return base / v if v else base


def ensure(slug: str) -> Path:
    _projects_root().mkdir(parents=True, exist_ok=True)
    root = project(slug)
    for d in STAGE_DIRS:
        (root / d).mkdir(parents=True, exist_ok=True)
    v = variant(slug)
    if v:
        for d in VARIANT_DIRS:
            (root / d / v).mkdir(parents=True, exist_ok=True)
    return root


def plan_dir(slug: str) -> Path:      return project(slug) / PLAN
def script_json(slug: str) -> Path:   return stage_dir(slug, SCRIPT) / "script.json"
def overrides(slug: str) -> Path:     return stage_dir(slug, SCRIPT) / "overrides.json"
def pron_table(slug: str) -> Path:    return stage_dir(slug, SCRIPT) / "발음교정표.txt"
def source_md(slug: str) -> Path:     return project(slug) / PLAN / "source.md"
def source_json(slug: str) -> Path:   return project(slug) / PLAN / "source.json"
# 원고·구조는 `00_기획/` 에 둔다. 폴더 번호를 새로 끼우면 01_대본~06_완성 이 전부
# 밀려 이미 만든 프로젝트가 깨진다. 둘 다 「재료를 갈아 내는 일」이라 제자리도 여기다.
def draft_html(slug: str) -> Path:    return project(slug) / PLAN / "원고.html"
def structure_json(slug: str) -> Path: return project(slug) / PLAN / "구조.json"
def audio_dir(slug: str) -> Path:     return stage_dir(slug, AUDIO)
def wav(slug: str, no: int) -> Path:  return stage_dir(slug, AUDIO) / f"{no:03d}.wav"
def subs_dir(slug: str) -> Path:      return stage_dir(slug, SUBS)
# SRT 이름에 유형을 넣는다 — 이 파일은 폴더를 떠나 자막으로 올라간다
def srt(slug: str) -> Path:
    v = variant(slug)
    return stage_dir(slug, SUBS) / (f"{v}_{slug}.srt" if v else f"{slug}.srt")
def cue_csv(slug: str) -> Path:       return stage_dir(slug, SUBS) / "cue-sheet.csv"
def art_dir(slug: str) -> Path:       return stage_dir(slug, SCENEART)
def art_spec(slug: str) -> Path:      return stage_dir(slug, SCENEART) / "장면지시.json"
def comp_dir(slug: str) -> Path:      return stage_dir(slug, COMPOSE)
def done_dir(slug: str) -> Path:      return stage_dir(slug, DONE)
def latest_txt(slug: str) -> Path:    return stage_dir(slug, DONE) / "최신.txt"


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
    """작업물 루트의 프로젝트 목록.

    ★ 루트를 쇼츠공방 I 과 같이 쓰면(`_series/<시리즈>/output`) 그쪽 mp4 파일과
      섞인다. 파일은 건너뛰고 **단계 폴더를 갖춘 디렉터리만** 프로젝트로 본다 —
      아니면 남의 폴더가 목록에 올라와 열었을 때 빈 화면이 나온다.
    """
    root = _projects_root()
    if not root.exists():
        return []
    return sorted(p.name for p in root.iterdir()
                  if p.is_dir() and not p.name.startswith((".", "_"))
                  and (p / PLAN).is_dir())
