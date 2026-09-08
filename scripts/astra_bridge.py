# -*- coding: utf-8 -*-
"""아스트라 브리지 — **움직이는 장면을 코드로 쓰게 하는 유일한 프로세스.**

    python scripts/astra_bridge.py <job.json> <result.json>

★ **왜 별도 프로세스인가.** 이 앱은 인증이 둘이다 — Claude(대본·지시)와
  ChatGPT(장면). 코드로 잇지 않고 **프로세스로 가른다.** 이 프로세스는
  `codex` CLI 만 부르고 Claude 쪽 경로(`~/.claude/`)를 열지 않는다.

★ `OPENAI_API_KEY` 를 지우고 시작한다. 오래된 export 가 구독 대신 키로 나가면
  모르는 사이에 과금된다.

★ **결과는 파일이다.** stdout 은 진행 로그뿐 — 섞으면 cp949 에서 깨진다.

★ 모델이 쓴 SVG 를 **그대로 믿지 않는다.** 파싱해서
  - 루트가 `<svg>` 인가
  - viewBox 가 우리가 준 규격인가
  - `<script>` · 외부 `href` 가 없는가   (렌더는 로컬 Chrome 에서 돈다)
  - 글자(`<text>`)가 없는가              (글자는 앱이 얹는다)
  를 본다. 하나라도 어긋나면 그 씬은 실패로 돌린다 — 깨진 SVG 를 넣으면
  렌더가 조용히 빈 화면을 굽는다.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import traceback
from pathlib import Path
from typing import Any, Dict, List, Tuple

ROOT = Path(__file__).resolve().parents[1]


def _init() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
        except Exception:  # noqa: BLE001
            pass
    for k in ("OPENAI_API_KEY", "OPENAI_BASE_URL", "OPENAI_ORG_ID"):
        os.environ.pop(k, None)


# ── SVG 검사 ────────────────────────────────────────────────────────────
_SVG_BLOCK = re.compile(r"<svg\b.*?</svg\s*>", re.IGNORECASE | re.DOTALL)
_FENCE = re.compile(r"```(?:svg|xml|html)?\s*(.*?)```", re.IGNORECASE | re.DOTALL)
_BANNED = (
    (re.compile(r"<script\b", re.I), "<script> 가 들어 있습니다"),
    (re.compile(r"<foreignObject\b", re.I), "<foreignObject> 는 렌더에서 불안정합니다"),
    (re.compile(r"<text\b", re.I), "<text> 가 있습니다 — 글자는 앱이 얹습니다"),
    (re.compile(r"""(?:href|xlink:href)\s*=\s*["']\s*(?:https?:)?//""", re.I),
     "바깥 주소를 가리킵니다 — 렌더 중 네트워크를 쓰면 결정론이 깨집니다"),
    (re.compile(r"""(?:src|href)\s*=\s*["']\s*data:(?!image/)""", re.I),
     "그림이 아닌 data: 를 물고 있습니다"),
)


def extract_svg(raw: str) -> str:
    """모델 답에서 SVG 한 덩어리만 꺼낸다. 코드펜스도 설명문도 걷어낸다."""
    for m in _FENCE.finditer(raw):
        hit = _SVG_BLOCK.search(m.group(1))
        if hit:
            return hit.group(0)
    hit = _SVG_BLOCK.search(raw)
    return hit.group(0) if hit else ""


def check_svg(svg: str, width: int, height: int) -> List[str]:
    """돌려주는 것은 **문제 목록**이다. 비어 있으면 통과."""
    bad: List[str] = []
    if not svg:
        return ["답에서 <svg> 를 찾지 못했습니다"]
    for pat, why in _BANNED:
        if pat.search(svg):
            bad.append(why)
    vb = re.search(r'viewBox\s*=\s*["\']([^"\']+)["\']', svg, re.I)
    if not vb:
        bad.append("viewBox 가 없습니다")
    else:
        nums = vb.group(1).replace(",", " ").split()
        if len(nums) != 4:
            bad.append(f"viewBox 가 이상합니다: {vb.group(1)}")
        else:
            try:
                w, h = float(nums[2]), float(nums[3])
                if abs(w - width) > 1 or abs(h - height) > 1:
                    bad.append(f"viewBox 가 {w:.0f}x{h:.0f} 입니다 — "
                               f"{width}x{height} 이어야 합니다")
            except ValueError:
                bad.append(f"viewBox 숫자를 읽지 못했습니다: {vb.group(1)}")
    # 움직이지 않으면 이 단계를 쓸 이유가 없다
    if not re.search(r"<animate|<animateTransform|<animateMotion|@keyframes", svg, re.I):
        bad.append("움직이는 부분이 없습니다 (animate 도 @keyframes 도 없음)")

    # ★ **되돌아오는 동작을 잡는다.** 처음 값으로 돌아오면 한 번만 돌려도
    #   「나갔다 돌아옴」으로 보이고, 그것이 반복처럼 읽힌다.
    #   실측(2026-09-08): repeatCount="indefinite" 를 시켰더니 이음새가 안 보이게
    #   values 를 A;B;A 로 썼고, 반복을 껐는데도 구성이 이상하다는 말을 들었다.
    values = re.findall(r'values\s*=\s*"([^"]+)"', svg)
    if values:
        loops = 0
        for v in values:
            parts = [x.strip() for x in v.split(";") if x.strip()]
            if len(parts) >= 3 and parts[0] == parts[-1]:
                loops += 1
        if loops and loops * 2 >= len(values):
            bad.append(f"동작 {loops}/{len(values)}개가 처음 값으로 되돌아옵니다 — "
                       f"한 방향으로만 가서 그 자리에 멈추세요 (values 첫 값 != 마지막 값)")
    if re.search(r'repeatCount\s*=\s*"indefinite"', svg, re.I):
        bad.append("repeatCount=indefinite 가 있습니다 — 한 번만 돌고 멈춰야 합니다")
    return bad


# ── codex 호출 ──────────────────────────────────────────────────────────
def _codex_bin() -> List[str]:
    """Windows 의 `codex.cmd` 는 cmd.exe 를 거치므로 인용이 샌다.
    가능하면 node 로 js 진입점을 직접 부른다."""
    import shutil

    w = shutil.which("codex")
    if not w:
        raise RuntimeError("codex 를 찾지 못했습니다. `npm i -g @openai/codex@latest`")
    p = Path(w)
    if p.suffix.lower() in (".cmd", ".bat", ".ps1"):
        js = p.parent / "node_modules" / "@openai" / "codex" / "bin" / "codex.js"
        node = shutil.which("node")
        if js.is_file() and node:
            return [node, str(js)]
    return [str(p)]


def ask(prompt: str, model: str, timeout: int, cwd: Path,
        refs: List[str] | None = None) -> Tuple[str, str]:
    """`codex exec` 한 번. (본문, 오류) 를 돌려준다.

    ★ `-s read-only` 로 샌드박스를 건다. 장면을 쓰는 데 파일을 만질 이유가 없고,
      모델이 레포를 건드리면 그 자체가 사고다.
    ★ `--skip-git-repo-check` — 프로젝트 폴더가 git 이 아닐 수 있다.
    """
    cmd = _codex_bin() + ["exec", "-m", model, "-s", "read-only",
                          "--skip-git-repo-check", "--color", "never"]
    # ★ **화풍은 말로 설명하지 말고 보여 준다.** `-i` 로 기준 그림을 붙인다.
    #   실측(2026-09-08): 「실루엣으로 그려라」고 적었더니 뭉개진 검은 형체가
    #   나왔다. 기대한 것은 얼굴·옷 주름·소품이 있는 밀도였다.
    #
    # ★ **프롬프트는 stdin 으로 넘긴다.** `-i` 는 파일을 여러 개 받는 가변 인자라
    #   `-i a.png b.png <프롬프트>` 로 쓰면 **프롬프트까지 이미지로 삼킨다**
    #   (실측: "No prompt provided via stdin" 으로 네 씬이 다 실패했다).
    #   stdin 은 그 문제도 없고 긴 프롬프트가 명령줄 길이 제한에 걸리지도 않는다.
    files = [str(Path(r).resolve()) for r in (refs or []) if Path(r).is_file()]
    if files:
        cmd += ["-i"] + files
    try:
        r = subprocess.run(cmd, cwd=str(cwd), input=prompt,
                           capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=timeout)
    except subprocess.TimeoutExpired:
        return "", f"{timeout}초를 넘겼습니다"
    out = (r.stdout or "") + "\n" + (r.stderr or "")
    if r.returncode != 0 and "<svg" not in out:
        return "", out.strip()[-400:] or f"exit={r.returncode}"
    return out, ""


def build_prompt(job: Dict[str, Any], sc: Dict[str, Any]) -> str:
    """씬 하나를 그리게 하는 말. **주장 → 무대 → 변동** 순서로 준다.

    ★ 순서가 뜻을 만든다. 무대를 먼저 주면 배경만 그리고 주장이 사라진다 —
      실측(2026-09-08): 「백만 중 열에 하나」에 광부 사택 부엌을 그렸다.
    """
    c, pal = job["canvas"], job["palette"]
    w, h = c["width"], c["height"]
    top, bot = c["band_top"], c["band_bottom"]
    lines = [
        "세로 쇼츠의 한 씬을 **움직이는 SVG** 로 만들어 주세요.",
        "답은 SVG 하나만 주세요. 설명도 코드펜스도 붙이지 마세요.",
        "",
        "[이 씬이 말하려는 것 — 가장 중요합니다]",
        f"  {sc.get('claim') or '(없음)'}",
        "  화면을 보는 사람이 이것을 **눈으로 알아채야** 합니다.",
        "  낱말을 그리지 말고, 이 주장이 보이도록 그리세요.",
        "",
        "[무대 — 변화가 없어도 그림으로 성립해야 합니다]",
        f"  {sc['stage']}",
        "",
        "[배치]",
        f"  {sc['layout']}",
        "",
        "[변동 — 무대 위에서 바뀌는 단 하나. 이것이 곧 위 주장입니다]",
        f"  {sc['change']}",
    ]
    if sc.get("support"):
        lines += ["", "[거드는 것 — 주인공이 끝난 뒤에 시작합니다]",
                  f"  {sc['support']}"]
    lines += [
        "",
        "[규격]",
        f'  viewBox="0 0 {w} {h}" · width/height 속성은 넣지 마세요',
        f"  이 장면은 화면에 {sc.get('scene_sec', sc['sec'])}초 있습니다.",
        f"  **애니메이션은 {sc['sec']}초 안에 전부 끝나고 그 자리에 멈춥니다** —",
        '  모든 애니메이션에 `fill="freeze"` 를 붙이고 `repeatCount` 는 쓰지 마세요.',
        f"  마지막 동작의 begin + dur 이 {sc['sec']}초를 넘지 않게 하세요.",
        "  남은 시간에는 화면이 정지한 채 내레이션이 이어집니다 — 의도한 모양입니다.",
        f"  바탕: 화면 전체를 {pal['ivory']} 단색으로 채우는 <rect> 를 맨 처음에.",
        "  네 귀퉁이까지 같은 밝기 — 어두운 배경·비네팅·발광 금지.",
        f"  **위 {top}px 와 아래 {bot}px 는 비워 두세요** (앱이 후크와 자막을 얹습니다).",
        f"  장면은 y={top}~{h - bot} 안에서만 그리고 움직이세요.",
        "",
        "[화풍]",
        f"  {job['style_hint']}",
        f"  진한 파랑 {pal['ink']} · 밝은 파랑 {pal['sub_ink']} ·"
        f" 포인트 {pal.get('point', '#DEEBF7')} · 강조 {pal['accent']}",
        f"  {sc.get('palette_note', '')}",
        "  플랫 벡터에 은은한 입체감, 균일한 선 굵기. 그라데이션은 옅게만.",
        "",
        "[반드시 지킬 것]",
        "  · **글자를 넣지 마세요.** <text> 금지. 숫자는 막대나 칸의 길이로.",
        "  · <script>·바깥 주소(http/https)·<foreignObject> 금지 — 로컬에서 렌더합니다.",
        "  · 움직임은 SMIL(<animate>, <animateTransform>) 로. CSS 애니메이션은 쓰지 마세요.",
        "  · **한 방향으로만.** values 의 첫 값과 마지막 값이 같으면 안 됩니다.",
        '    좋음 values="0;1" · 나쁨 values="80;120;80" (나갔다 돌아옴 = 반복처럼 보임)',
        "  · **사람의 몸을 그리지 마세요.** 얼굴·팔다리 관절은 손으로 쓰는 벡터로는",
        "    망가집니다. 사람은 흔적으로 — 빈 의자와 편지, 장화와 램프, 쌓인 교재.",
        "  · 밀도는 **사물과 공간**에서 냅니다. 직선과 원으로 이루어진 것을 촘촘히.",
        "    선을 긋는 애니메이션(stroke-dasharray + stroke-dashoffset)이 주된 손입니다.",
        "  · path 를 아끼지 마세요. 60~150개면 기준 그림만 한 밀도가 나옵니다.",
        "  · 실존 로고 금지.",
        "",
        "[붙인 그림에 대하여]",
        "  · 화풍 기준입니다. 색·선·밀도를 이만큼 맞추세요.",
        "  · 그 그림에는 글자가 있지만 **글자는 참고하지 마세요.**",
        "  · 내용을 베끼지 마세요 — 위 [무대] 에 적힌 것을 그립니다.",
    ]
    return chr(10).join(lines)


def main() -> int:
    _init()
    if len(sys.argv) < 3:
        print("usage: astra_bridge.py <job.json> <result.json>", file=sys.stderr)
        return 2
    job = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    out_path = Path(sys.argv[2])
    result: Dict[str, Any] = {"items": [], "error": None, "model": job.get("model")}

    try:
        out_dir = Path(job["out_dir"])
        out_dir.mkdir(parents=True, exist_ok=True)
        model = job.get("model") or "gpt-6-astra"
        timeout = int(job.get("timeout_sec") or 600)
        retries = int(job.get("retries") or 1)
        w = int(job["canvas"]["width"])
        h = int(job["canvas"]["height"])

        # ★ 씬을 **하나씩 차례로** 부른다. 아스트라는 5시간 한도가 빡빡해서
        #   동시에 여러 개를 던지면 중간에 끊기고, 그때 어디까지 됐는지 모른다.
        for sc in job["scenes"]:
            no = int(sc["no"])
            name = sc.get("file") or f"{no:03d}.svg"
            last = ""
            for attempt in range(1, retries + 2):
                print(f"[{no}] {model} 에게 장면을 맡깁니다 ({attempt}번째)", flush=True)
                raw, err = ask(build_prompt(job, sc), model, timeout, ROOT,
                               refs=job.get("style_refs") or [])
                if err:
                    last = err
                    low = err.lower()
                    if "requires a newer version" in low:
                        last = (f"{model} 은 지금 codex CLI 로는 못 부릅니다. "
                                f"`npm i -g @openai/codex@latest` 후 다시 하세요.")
                        break
                    if "not exist" in low or "model_not_found" in low:
                        last = f"{model} 이라는 모델이 없습니다. `codex debug models` 로 확인하세요."
                        break
                    print(f"[{no}] 실패 — {last[:160]}", flush=True)
                    continue

                svg = extract_svg(raw)
                bad = check_svg(svg, w, h)
                if bad:
                    last = " · ".join(bad)
                    print(f"[{no}] 검사에 걸림 — {last[:200]}", flush=True)
                    continue

                (out_dir / name).write_text(svg, encoding="utf-8")
                kb = len(svg.encode("utf-8")) // 1024
                print(f"[{no}] {kb}KB {name}", flush=True)
                result["items"].append({"no": no, "file": name,
                                        "bytes": len(svg.encode("utf-8"))})
                last = ""
                break
            if last:
                result["items"].append({"no": no, "error": last})
    except Exception:  # noqa: BLE001
        result["error"] = traceback.format_exc(limit=6)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2),
                        encoding="utf-8")
    return 1 if result["error"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
