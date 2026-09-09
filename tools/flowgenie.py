# -*- coding: utf-8 -*-
"""FlowGenie 다리 — **가운데 그림을 사람이 받아 온다.**

    내보내기   script.json + 장면지시.json  →  04_장면/_반입/flowgenie.json
    (사람)     FlowGenie 사이드패널에 넣고 16:9 로 돌린다 → PNG 가 내려온다
    가져오기   다운로드/FlowGenie/*.png  →  04_장면/001-1.png …

FlowGenie 는 이 레포 밖에 사는 크롬 확장이다
(`github.com/leedonwoo2827-ship-it/flowgenie`). JSON 프롬프트 목록을 넣으면
Google Flow(ImageFX)를 몰아 이미지를 만들고 자동으로 내려받는다.

★ **`image_filename` 에 우리가 쓸 이름을 그대로 박는다.** FlowGenie 가 그 이름으로
  저장하므로 받아서 이름을 고칠 일이 없다. 이름 규칙은 `s6_art.parse_name` 이
  읽는 것과 같은 것이다 — `001-2.png` = 씬 1 · 조각 2.

★ **화면비 16:9 는 사람이 사이드패널에서 한 번 고른다.** JSON 에 그 칸이 없다.
  잘못 고르면 그림이 카드에 `cover` 로 잘려 들어가므로 로그에 적어 둔다.

★ **가져올 때 정규화한다.** `.gif` 나 애니메이션 `.webp` 는 ffmpeg 로 PNG
  시퀀스(`001-2-01.png` …)로 풀어 넣는다. 진짜 GIF 을 그대로 두면 렌더가
  GSAP 시계를 되감아 찍는데 GIF 은 되감을 API 가 없어서 **오류도 경고도 없이
  첫 프레임에 멈춘다.** 풀어 넣으면 플립북 길로 들어와 제대로 넘어간다.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from core import config, paths
from core.atomic_io import atomic_write_json

# 반입 폴더 — 사람이 받은 그림을 여기에 넣는다. 씬 그림과 섞이지 않게 하위 폴더다.
INBOX = "_반입"
JOB = "flowgenie.json"
# 움직이는 한 장 → PNG 시퀀스로 풀 대상
_UNPACK = (".gif", ".webp")
_KEEP = (".png", ".jpg", ".jpeg", ".webp", ".svg", ".mp4", ".webm")


def inbox(slug: str) -> Path:
    return paths.art_dir(slug) / INBOX


def _download_dir() -> Optional[Path]:
    """FlowGenie 가 내려놓는 곳. 설정에 있으면 그것, 없으면 `~/Downloads/FlowGenie`."""
    v = str(config.get("art.import_from") or "").strip()
    p = Path(os.path.expanduser(v)) if v else (Path.home() / "Downloads" / "FlowGenie")
    return p if p.exists() else None


# ── 내보내기 ──────────────────────────────────────────────────────────────
# 화풍 머리말. 꼭지마다 붙는다 — 열 장을 따로 만드는데 화풍이 갈리면 한 편으로
# 안 보인다. 설정(`art.flowgenie_style`)으로 갈아 쓸 수 있다.
DEFAULT_STYLE = (
    "Flat vector illustration, ivory background (#F6F1E8), uniform stroke width, "
    "deep blue (#1F4E79) and light blue (#9DC3E6) with a single warm orange accent "
    "(#E07A2F). Calm, editorial, no gradients, no glow, no vignette. "
    "16:9 horizontal composition. "
    "★ ABSOLUTELY NO TEXT, letters, numbers, labels, signs, captions or watermarks "
    "anywhere in the image."
)


def _style() -> str:
    return str(config.get("art.flowgenie_style") or DEFAULT_STYLE).strip()


def export(slug: str, *, on_log: Optional[Callable[[str], None]] = None) -> Dict[str, Any]:
    """`04_장면/_반입/flowgenie.json` 을 쓴다. **조각 하나에 그림 하나.**

    ★ 조각 수가 곧 그림 수다 — 조각 하나가 컷 하나이므로. 자막을 고쳐 조각이
      늘거나 줄면 여기서 다시 내보내면 된다(크레딧 0).
    """
    log = on_log or (lambda _m: None)
    sj = paths.script_json(slug)
    if not sj.exists():
        raise FileNotFoundError("먼저 「대본」·「자막」 단계를 돌리세요.")
    doc = json.loads(sj.read_text(encoding="utf-8"))
    scenes = doc.get("scenes") or []
    if not scenes:
        raise RuntimeError("씬이 없습니다.")

    # 장면지시의 `cells[].what` 이 **조각마다 한 줄**이다. 없으면 씬의
    # `image_brief` 로 물러선다 — 그래도 사람이 손으로 고칠 자리가 생긴다.
    spec: Dict[int, List[Dict[str, Any]]] = {}
    sp = paths.art_spec(slug)
    if sp.exists():
        try:
            for r in (json.loads(sp.read_text(encoding="utf-8")).get("scenes") or []):
                spec[int(r.get("no") or 0)] = r.get("cells") or []
        except Exception:  # noqa: BLE001
            spec = {}

    style = _style()
    model = str(config.get("art.flowgenie_model") or "nano_banana")
    items: List[Dict[str, Any]] = []
    thin: List[str] = []
    for s in scenes:
        no = int(s.get("no") or 0)
        cues = s.get("cues") or []
        cells = spec.get(no) or []
        brief = str(s.get("image_brief") or "").strip()
        if cells and len(cells) < len(cues):
            thin.append(f"{no}({len(cells)}/{len(cues)})")
        for m, cue in enumerate(cues, start=1):
            what = ""
            if m <= len(cells):
                what = str((cells[m - 1] or {}).get("what") or "").strip()
            what = what or brief or str(s.get("srt_text") or "").strip()[:200]
            items.append({
                "scene": len(items) + 1,
                "title": str(s.get("card_title") or s.get("hook_line1") or "").strip(),
                # ★ 우리가 쓸 이름 그대로. 받아서 고칠 일이 없다.
                "image_filename": f"{no:03d}-{m}.png",
                "prompt": f"{what}\n\n{style}",
                "model": model,
                "narration_seconds": round(float(cue.get("d") or 0.0), 2),
                "visual_description": what,
                "reference_image": None,
            })

    job = {"chapter": 1, "title": str(doc.get("title") or slug), "scenes": items}
    d = inbox(slug)
    d.mkdir(parents=True, exist_ok=True)
    atomic_write_json(str(d / JOB), job, indent=2)

    log(f"  FlowGenie JSON — 그림 {len(items)}장 · {d / JOB}")
    log("  ★ 사이드패널에서 **화면비 16:9** 로 고르세요. 다른 비율로 만들면 "
        "카드에 잘려 들어갑니다.")
    if thin:
        log(f"  ⚠ 씬 {', '.join(thin)} 은 장면지시의 칸이 조각보다 적습니다 "
            f"(칸/조각) — 남는 조각은 같은 지시를 다시 씁니다. "
            f"「장면 지시」를 다시 돌리면 조각 수에 맞춰 나옵니다.")
    if not spec:
        log("  ⚠ 장면지시.json 이 없어 `image_brief` 로 프롬프트를 썼습니다 — "
            "「장면 지시」를 돌리면 조각마다 다른 그림 지시가 나옵니다.")
    return {"json": str(d / JOB), "images": len(items), "dir": str(d)}


# ── 가져오기 ──────────────────────────────────────────────────────────────
def _ffmpeg() -> str:
    ff = shutil.which("ffmpeg")
    if not ff:
        raise RuntimeError("ffmpeg 가 PATH 에 없습니다. setup.bat 안내를 보세요.")
    return ff


def _unpack(src: Path, dst_dir: Path, stem: str, cap: int) -> List[str]:
    """움직이는 한 장(`.gif`·애니 `.webp`)을 PNG 시퀀스로 푼다.

    ★ **진짜 GIF 을 그대로 두면 안 된다.** 렌더러는 GSAP 시계를 되감아 가며 찍는데
      GIF 은 벽시계로 돌고 되감을 API 가 없다 — 오류도 경고도 없이 첫 프레임에
      멈춘다(SMIL 은 `setCurrentTime()` 이라는 손잡이가 있어서 고칠 수 있었지만
      GIF 엔 그것이 없다). 풀어 넣으면 플립북 길로 들어와 제대로 넘어간다.

    ★ 상한을 넘는 프레임은 **균등 간격으로 골라 낸다.** 앞에서 잘라 버리면
      움직임의 **끝**이 사라지는데, 끝이 그 움직임의 뜻인 경우가 많다.
    """
    tmp = dst_dir / f"_풀기_{stem}"
    if tmp.exists():
        shutil.rmtree(tmp)
    tmp.mkdir(parents=True)
    subprocess.run([_ffmpeg(), "-y", "-loglevel", "error", "-i", str(src),
                    "-vsync", "0", str(tmp / "%03d.png")], check=True)
    got = sorted(tmp.glob("*.png"))
    if not got:
        shutil.rmtree(tmp, ignore_errors=True)
        return []
    if len(got) > cap:
        step = (len(got) - 1) / (cap - 1) if cap > 1 else 0
        got = [got[min(len(got) - 1, round(i * step))] for i in range(cap)]
    names: List[str] = []
    for k, f in enumerate(got, start=1):
        name = f"{stem}-{k:02d}.png"
        shutil.copy2(f, dst_dir / name)
        names.append(name)
    shutil.rmtree(tmp, ignore_errors=True)
    return names


def _wanted(slug: str) -> List[str]:
    """이번에 받아야 하는 파일 이름. `flowgenie.json` 이 있으면 그것이 목록이다."""
    j = inbox(slug) / JOB
    if not j.exists():
        return []
    try:
        d = json.loads(j.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return []
    return [str(s.get("image_filename") or "") for s in (d.get("scenes") or [])
            if s.get("image_filename")]


def bring_in(slug: str, *, on_log: Optional[Callable[[str], None]] = None) -> Dict[str, Any]:
    """`_반입/` 과 다운로드 폴더에서 그림을 `04_장면/` 으로 올린다.

    이름이 `flowgenie.json` 의 `image_filename` 과 맞는 것만 가져온다 — 다운로드
    폴더에는 지난 편의 그림도 섞여 있으므로 아무거나 끌어오면 엉뚱한 그림이 붙는다.
    """
    log = on_log or (lambda _m: None)
    art = paths.art_dir(slug)
    art.mkdir(parents=True, exist_ok=True)
    box = inbox(slug)
    box.mkdir(parents=True, exist_ok=True)
    cap = max(1, int(config.get("art.flip_frames_max", 12)))

    want = _wanted(slug)
    if not want:
        log("  ⚠ `_반입/flowgenie.json` 이 없습니다 — 먼저 **내보내기**를 누르세요. "
            "그 파일이 「무엇을 받아야 하는지」의 목록입니다.")
        return {"moved": [], "missing": [], "unpacked": [], "skipped": 0}

    # 뒤질 곳 — 반입 폴더 먼저, 그다음 다운로드 폴더.
    srcs: List[Path] = [box]
    dl = _download_dir()
    if dl:
        srcs.append(dl)

    moved: List[str] = []
    unpacked: List[str] = []
    missing: List[str] = []
    for name in want:
        stem = Path(name).stem                 # 001-2
        hit: Optional[Path] = None
        for d in srcs:
            for ext in _KEEP + _UNPACK:
                cand = d / f"{stem}{ext}"
                if cand.is_file():
                    hit = cand
                    break
            if hit:
                break
        if not hit:
            missing.append(name)
            continue
        ext = hit.suffix.lower()
        if ext in _UNPACK and _is_animated(hit):
            names = _unpack(hit, art, stem, cap)
            if names:
                unpacked.append(f"{hit.name}→{len(names)}장")
                moved.extend(names)
                continue
            # 못 풀었으면 그대로 두지 않는다 — 애니 파일을 그냥 옮기면
            # 렌더에서 첫 프레임에 멈춘다. 없는 것으로 센다.
            missing.append(name)
            log(f"  ⚠ {hit.name} 을 프레임으로 못 풀었습니다 — 건너뜁니다.")
            continue
        shutil.copy2(hit, art / f"{stem}{ext}")
        moved.append(f"{stem}{ext}")

    log(f"  {len(want) - len(missing)}/{len(want)} 들어옴"
        + (f" · 풀어 넣음 {', '.join(unpacked)}" if unpacked else ""))
    if missing:
        log(f"  없음: {', '.join(missing)}")
        log(f"  넣을 곳: {box}")
    return {"moved": moved, "missing": missing, "unpacked": unpacked,
            "dir": str(box), "wanted": len(want)}


def _is_animated(p: Path) -> bool:
    """움직이는 한 장인가. `.gif` 는 늘, `.webp` 는 프레임이 둘 이상일 때만.

    정지 `.webp` 를 굳이 PNG 로 풀면 화질만 잃는다.
    """
    if p.suffix.lower() == ".gif":
        return True
    try:
        r = subprocess.run([_ffmpeg().replace("ffmpeg", "ffprobe"),
                            "-v", "error", "-select_streams", "v:0",
                            "-count_frames", "-show_entries", "stream=nb_read_frames",
                            "-of", "default=nw=1:nk=1", str(p)],
                           capture_output=True, text=True, timeout=30)
        return int((r.stdout or "0").strip() or 0) > 1
    except Exception:  # noqa: BLE001
        return False
