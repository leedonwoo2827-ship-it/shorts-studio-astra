# -*- coding: utf-8 -*-
"""CLI — 창 없이 돌릴 때. 화면(run.bat 의 W)과 **같은 코드를 부른다.**

    python scripts/make.py new  <원본파일> [--title 제목] [--cuts 3]
    python scripts/make.py all  <slug> [--skip images]
    python scripts/make.py run  <slug> <단계키> [--force] [--only 3,4]
    python scripts/make.py list
    python scripts/make.py state <slug>
"""
from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core import config, console, paths                    # noqa: E402
from core.atomic_io import atomic_write_json               # noqa: E402
from pipeline import runner, stages                        # noqa: E402


def log(msg: str) -> None:
    print(msg, flush=True)


def cmd_new(a) -> int:
    src = Path(a.source).resolve()
    if not src.is_file():
        log(f"원본 파일이 없습니다: {src}")
        return 2
    title = a.title or src.stem
    slug = paths.slugify(title)
    root = paths.ensure(slug)
    shutil.copy2(src, paths.plan_dir(slug) / src.name)
    atomic_write_json(str(paths.source_json(slug)), {
        "file": src.name, "title": title,
        "cuts": int(a.cuts or config.get("shorts.cuts", 3)),
        "voice": config.get("narration.voice", "F2"),
        "speed": config.get("narration.speed", 1.2),
    }, indent=2)
    log(f"만들었습니다: {root.relative_to(ROOT)}")
    log(f"  다음 → python scripts/make.py all {slug}")
    return 0


def cmd_all(a) -> int:
    runner.run_all(a.slug, log, skip=tuple(a.skip or ()),
                   skip_lint=bool(a.skip_lint))
    return 0


def cmd_run(a) -> int:
    only = [int(x) for x in a.only.split(",")] if a.only else None
    runner.run_stage(a.slug, a.stage, log, force=bool(a.force), only=only,
                     cuts=a.cuts, skip_lint=bool(a.skip_lint))
    return 0


def cmd_list(_a) -> int:
    names = paths.list_projects()
    if not names:
        log("프로젝트가 없습니다. `new` 로 하나 만드세요.")
        return 0
    for n in names:
        st = stages.state(n)
        done = sum(1 for v in st.values() if v == "done")
        log(f"  {n:40s} {done}/{len(st)} 단계")
    return 0


def cmd_state(a) -> int:
    for row in stages.as_json(a.slug)['stages']:
        mark = {"done": "O", "part": "-", "": "."}[row["state"]]
        log(f"  {mark} {row['key']:10s} {row['name']}"
            + ("  $" if row["costs"] else "")
            + ("  (낡음)" if row["stale"] else ""))
    return 0


def main() -> int:
    console.init()
    ap = argparse.ArgumentParser(prog="make.py", add_help=True)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("new");   p.add_argument("source"); p.add_argument("--title")
    p.add_argument("--cuts", type=int); p.set_defaults(fn=cmd_new)

    p = sub.add_parser("all");   p.add_argument("slug")
    p.add_argument("--skip", nargs="*"); p.add_argument("--skip-lint", action="store_true")
    p.set_defaults(fn=cmd_all)

    p = sub.add_parser("run");   p.add_argument("slug")
    p.add_argument("stage", choices=sorted(runner.FUNCS))
    p.add_argument("--force", action="store_true"); p.add_argument("--only")
    p.add_argument("--cuts", type=int); p.add_argument("--skip-lint", action="store_true")
    p.set_defaults(fn=cmd_run)

    p = sub.add_parser("list");  p.set_defaults(fn=cmd_list)
    p = sub.add_parser("state"); p.add_argument("slug"); p.set_defaults(fn=cmd_state)

    a = ap.parse_args()
    try:
        return a.fn(a)
    except Exception as e:
        log(f"\n실패 — {type(e).__name__}: {e}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
