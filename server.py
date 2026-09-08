# -*- coding: utf-8 -*-
"""콘솔 — FastAPI. 화면과 CLI 가 **같은 코드를 부른다**(`pipeline/runner.py`).

★ 기본은 **127.0.0.1 전용**이다. `SHORTS_LAN` 을 켜면 0.0.0.0 에 묶이지만,
  그때는 미들웨어가 **바깥에서 온 요청을 읽기 전용으로 묶는다** — 만드는 단계는
  이 PC 주인의 구독으로 돌기 때문이다(`core/access.py`).

★ 단계는 **잡으로 띄우고 폴링으로 읽는다.** 스트리밍을 쓰지 않는 이유는
  브라우저를 새로 고쳐도 로그가 이어져야 하기 때문이다. 프로젝트당 하나만 돈다.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import zlib
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException, Request, UploadFile, File, Form
from fastapi.responses import (FileResponse, HTMLResponse, JSONResponse,
                               PlainTextResponse)
from fastapi.staticfiles import StaticFiles

from core import access, config, console, paths, persona
from core.atomic_io import atomic_write_json, atomic_write_text
from core.jobs import get_registry
from pipeline import runner, s1b_revise, s2_speech, s4_subs, stages

ROOT = Path(__file__).resolve().parent
REG = get_registry()


def _pid(slug: str) -> int:
    """잡 레지스트리는 int 키를 쓴다. slug 를 **안정적으로** 숫자로 바꾼다 —
    `hash()` 는 파이썬 실행마다 달라져서 못 쓴다(PYTHONHASHSEED)."""
    return zlib.crc32(slug.encode("utf-8"))


def _need(slug: str) -> str:
    if slug not in paths.list_projects():
        raise HTTPException(404, f"그런 프로젝트가 없습니다: {slug}")
    return slug


async def _json_body(request: Request) -> Dict[str, Any]:
    """몸이 비어 있어도 죽지 않는다. 화면이 인자 없이 부르는 자리가 있다."""
    try:
        return await request.json() or {}
    except Exception:  # noqa: BLE001
        return {}


def _script(slug: str) -> Dict[str, Any]:
    p = paths.script_json(slug)
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def create_app() -> FastAPI:
    console.init()
    app = FastAPI(title="쇼츠공방 II", docs_url=None, redoc_url=None)
    app.mount("/static", StaticFiles(directory=str(ROOT / "static")), name="static")

    # ★ 플레이어는 **자체 호스팅**한다. CDN 을 쓰면 사내망에서 미리보기가 죽고,
    #   그때 「렌더가 고장났다」고 오해한다. HyperFrames 가 이미 끌고 온 것을 쓴다.
    _player = ROOT / "node_modules" / "@hyperframes" / "player" / "dist"
    if _player.is_dir():
        app.mount("/vendor", StaticFiles(directory=str(_player)), name="vendor")

    # ── 읽기 전용 손님 ────────────────────────────────────────────────────
    @app.middleware("http")
    async def guard(request: Request, call_next):
        if access.lan_enabled() and not access.is_local(
                request.client.host if request.client else None):
            if not access.guest_may(request.method, request.url.path):
                return JSONResponse({"error": access.DENY_MESSAGE,
                                     "readonly": True}, status_code=403)
        return await call_next(request)

    # ── 화면 ──────────────────────────────────────────────────────────────
    @app.get("/", response_class=HTMLResponse)
    def index() -> str:
        return (ROOT / "static" / "index.html").read_text(encoding="utf-8")

    @app.get("/api/stages")
    def stage_table() -> Dict[str, Any]:
        """묶음 + 단계 표. **화면이 이것만 보고 레일을 그린다.**"""
        return stages.as_json(None)

    # ── 연결 상태 ─────────────────────────────────────────────────────────
    @app.get("/api/llm/status")
    def llm_status() -> Dict[str, Any]:
        from llm import status
        return status()

    @app.get("/api/imagegen/status")
    def imagegen_status() -> Dict[str, Any]:
        from imagegen.auth_status import status
        return status()

    @app.get("/api/config")
    def get_config(request: Request) -> Dict[str, Any]:
        """화면이 뜨는 데 필요한 것. 경로도 자격증명도 담지 않는다.

        ★ `readonly` 를 여기서 알려 준다. 손님이 단추를 눌러 보고 403 을 받는
          것보다, **누를 수 없다는 것을 미리 보여 주는 것**이 낫다. 보여 주려고
          공유한 화면인데 눌렀다가 거절당하면 고장인 줄 안다.
        """
        c = config.load()
        guest = access.lan_enabled() and not access.is_local(
            request.client.host if request.client else None)
        return {"shorts": c.get("shorts"), "narration": c.get("narration"),
                "compose": c.get("compose"), "image": {
                    k: v for k, v in (c.get("image") or {}).items()
                    if k in ("size", "reserve_top_pct", "reserve_bottom_pct")},
                "tts": {"engine": (c.get("tts") or {}).get("engine")},
                "budget_chars": config.budget_chars(),
                "lan": access.lan_enabled(),
                "readonly": guest,
                "readonly_why": access.DENY_MESSAGE if guest else ""}

    # ── 프로젝트 ──────────────────────────────────────────────────────────
    @app.get("/api/projects")
    def list_projects() -> List[Dict[str, Any]]:
        out = []
        for slug in paths.list_projects():
            doc = _script(slug)
            st = stages.state(slug)
            out.append({"slug": slug, "title": doc.get("title") or slug,
                        "cuts": len(doc.get("scenes") or []),
                        "total_sec": doc.get("total_sec"),
                        "done": sum(1 for v in st.values() if v == "done"),
                        "steps": len(st),
                        "built": bool(paths.latest_build(slug))})
        return out

    @app.post("/api/projects")
    async def new_project(file: UploadFile = File(...),
                          title: str = Form(""),
                          fmt: str = Form(""),
                          mbti: str = Form("")) -> Dict[str, Any]:
        """새 프로젝트. **씬 수를 받지 않는다** — 형식만 받고 나머지는 파생값이다.

        예전에는 여기서 `cuts` 를 받아 프롬프트에 「씬 수는 N개다」로 박았고,
        그러면 원문이 18쪽이든 2쪽이든 대본이 N 으로 맞춰 나왔다.
        """
        name = Path(file.filename or "원본").name
        t = (title or Path(name).stem).strip()
        slug = paths.slugify(t)
        paths.ensure(slug)
        dst = paths.plan_dir(slug) / name
        dst.write_bytes(await file.read())
        atomic_write_json(str(paths.source_json(slug)), {
            "file": name, "title": t,
            "format": (fmt or config.get("shorts.format", "narrative")).strip(),
            "voice": config.get("narration.voice", "F2"),
            "speed": config.get("narration.speed", 1.2),
            # 무드를 **만들 때** 받는다. 대본을 뽑고 나서 고르면 그 대본이 무드
            # 없이 나온 것이라 다시 뽑아야 하고, 대본은 크레딧을 쓰는 단계다.
            "mbti": persona.normalize(mbti),
            "mood": persona.mood(mbti),
        }, indent=2)
        return {"slug": slug, "file": name}

    @app.get("/api/projects/{slug}")
    def get_project(slug: str) -> Dict[str, Any]:
        _need(slug)
        doc = _script(slug)
        meta = paths.source_json(slug)
        build = paths.latest_build(slug)
        job = REG.latest(_pid(slug))
        # ★ 표는 **평평하게** 준다. 예전에 `{groups, stages}` 를 그대로 `stages`
        #   키에 넣었더니 화면에서 `stages.find` 가 함수가 아니라고 터졌다 —
        #   같은 이름이 한쪽에서는 배열, 한쪽에서는 객체였다.
        table = stages.as_json(slug)
        return {
            "slug": slug,
            "groups": table["groups"],
            "screens": table["screens"],
            "meta": json.loads(meta.read_text(encoding="utf-8")) if meta.exists() else {},
            "script": doc,
            "stages": table["stages"],
            "source_chars": (paths.source_md(slug).stat().st_size
                             if paths.source_md(slug).exists() else 0),
            # 「재료」 화면의 원고·구조 탭이 쓰는 요약. 본문은 각자 라우트로 받는다 —
            # 원고 HTML 은 십만 자가 넘을 수 있어 이 응답에 담지 않는다.
            "draft": (json.loads((paths.plan_dir(slug) / "원고.json")
                                 .read_text(encoding="utf-8"))
                      if (paths.plan_dir(slug) / "원고.json").exists() else None),
            "art": runner.s6_art.present(slug),
            "build": ({"name": build.name,
                       "youtube": (build / "유튜브.txt").read_text(encoding="utf-8")
                       if (build / "유튜브.txt").exists() else "",
                       "info": json.loads((build / "정보.json").read_text(encoding="utf-8"))
                       if (build / "정보.json").exists() else {}}
                      if build else None),
            "job": job.to_dict() if job else None,
        }

    @app.delete("/api/projects/{slug}")
    def delete_project(slug: str) -> Dict[str, Any]:
        _need(slug)
        import shutil
        shutil.rmtree(paths.project(slug))
        return {"deleted": slug}

    # ── 단계 실행 ─────────────────────────────────────────────────────────
    @app.post("/api/projects/{slug}/stages/{key}/run")
    def run_one(slug: str, key: str, body: Optional[Dict[str, Any]] = None
                ) -> Dict[str, Any]:
        _need(slug)
        if key not in runner.FUNCS:
            raise HTTPException(400, f"모르는 단계입니다: {key}")
        opts = dict(body or {})
        st = stages.BY_KEY[key]

        def work(job) -> Any:
            return runner.run_stage(slug, key, job.add_log, **opts)

        try:
            job = REG.start(project_id=_pid(slug), stage=key,
                            label=f"{slug} · {st.name}", work=work)
        except RuntimeError as e:
            raise HTTPException(409, str(e))
        return job.to_dict()

    @app.post("/api/projects/{slug}/groups/{group}/run")
    def run_group(slug: str, group: str, body: Optional[Dict[str, Any]] = None
                  ) -> Dict[str, Any]:
        """묶음 하나(대본 만들기 · 영상 만들기 · 전체 빌드).

        전체를 한 단추로 흘려보내는 길은 **화면에 두지 않는다** — 대본과 장면은
        보고 고쳐야 하는 자리이고, 묶어서 지나가면 고칠 순간을 놓친다.
        (스크립트로 밤에 돌릴 때는 `scripts/make.py all` 이 있다.)
        """
        _need(slug)
        g = stages.BY_GROUP.get(group)
        if g is None:
            raise HTTPException(400, f"모르는 묶음입니다: {group}")
        opts = dict(body or {})

        def work(job) -> Any:
            return runner.run_group(slug, group, job.add_log,
                                    on_stage=job.progress, **opts)

        try:
            job = REG.start(project_id=_pid(slug), stage=f"group:{group}",
                            label=f"{slug} · {g.label}", work=work,
                            total=len(g.stages))
        except RuntimeError as e:
            raise HTTPException(409, str(e))
        return job.to_dict()

    @app.get("/api/jobs/{job_id}")
    def get_job(job_id: str) -> Dict[str, Any]:
        job = REG.get(job_id)
        if not job:
            raise HTTPException(404, "그런 작업이 없습니다.")
        return job.to_dict()

    @app.post("/api/jobs/{job_id}/cancel")
    def cancel_job(job_id: str) -> Dict[str, Any]:
        job = REG.get(job_id)
        if not job:
            raise HTTPException(404, "그런 작업이 없습니다.")
        job.cancel()
        return job.to_dict()

    # ── 사람이 고치는 자리 ────────────────────────────────────────────────
    @app.get("/api/projects/{slug}/markdown", response_class=PlainTextResponse)
    def get_md(slug: str) -> str:
        _need(slug)
        p = paths.source_md(slug)
        return p.read_text(encoding="utf-8") if p.exists() else ""

    @app.put("/api/projects/{slug}/markdown")
    async def put_md(slug: str, request: Request) -> Dict[str, Any]:
        _need(slug)
        text = (await request.body()).decode("utf-8")
        atomic_write_text(str(paths.source_md(slug)), text)
        return {"chars": len(text)}

    @app.get("/api/projects/{slug}/draft", response_class=PlainTextResponse)
    def get_draft(slug: str) -> str:
        """원고 HTML. 소제목이 잘못 붙었으면 사람이 여기서 고친다."""
        _need(slug)
        p = paths.draft_html(slug)
        return p.read_text(encoding="utf-8") if p.exists() else ""

    @app.put("/api/projects/{slug}/draft")
    async def put_draft(slug: str, request: Request) -> Dict[str, Any]:
        """고친 원고를 저장한다. **「구조」를 다시 돌려야** 사실 표가 갱신된다 —
        `stages.stale()` 이 mtime 을 보고 화면에 그렇게 알려 준다."""
        _need(slug)
        text = (await request.body()).decode("utf-8")
        atomic_write_text(str(paths.draft_html(slug)), text)
        return {"chars": len(text)}

    @app.get("/api/projects/{slug}/structure")
    def get_structure(slug: str) -> Dict[str, Any]:
        """구조. 「재료 → 구조」 탭이 사실 표를 보여 준다."""
        _need(slug)
        p = paths.structure_json(slug)
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}

    @app.put("/api/projects/{slug}/scenes")
    async def put_scenes(slug: str, request: Request) -> Dict[str, Any]:
        """자막·후크·발음을 고친다. **사람 손이 이긴다.**

        `srt_text` 를 고치면 큐를 다시 나눠야 하고, `narration_text` 를 고치면
        그 씬 음성이 낡는다 — 두 가지를 여기서 같이 처리한다. 화면이 기억하게
        두면 고쳐 놓고 다시 굽는 것을 잊는다.
        """
        _need(slug)
        body = await request.json()
        edits = {int(k): v for k, v in (body.get("scenes") or {}).items()}
        doc = _script(slug)
        touched: List[int] = []
        for s in doc.get("scenes") or []:
            e = edits.get(int(s.get("no") or 0))
            if not e:
                continue
            for f in ("hook_line1", "hook_line2", "srt_text", "narration_text"):
                if f in e and str(e[f]) != s.get(f):
                    s[f] = str(e[f]).strip()
                    touched.append(int(s["no"]))
            if "narration_text" in e:
                s["narration_from"] = "손"
        atomic_write_json(str(paths.script_json(slug)), doc, indent=2)

        # 고친 씬은 음성 스탬프가 어긋나므로 다음 「음성」에서 그 씬만 다시 굽는다
        out: Dict[str, Any] = {"touched": sorted(set(touched))}
        if touched:
            out["subs"] = s4_subs.run(slug)
        return out

    @app.get("/api/projects/{slug}/pron", response_class=PlainTextResponse)
    def get_pron(slug: str) -> str:
        _need(slug)
        s2_speech.ensure_table(slug)
        return paths.pron_table(slug).read_text(encoding="utf-8")

    @app.put("/api/projects/{slug}/pron")
    async def put_pron(slug: str, request: Request) -> Dict[str, Any]:
        _need(slug)
        atomic_write_text(str(paths.pron_table(slug)),
                          (await request.body()).decode("utf-8"))
        return s2_speech.run(slug)

    # ── 미리 듣고 보기 ────────────────────────────────────────────────────
    @app.get("/api/projects/{slug}/audio/{no}")
    def get_audio(slug: str, no: int) -> FileResponse:
        _need(slug)
        p = paths.wav(slug, int(no))
        if not p.exists():
            raise HTTPException(404, "그 씬 음성이 아직 없습니다.")
        return FileResponse(p, media_type="audio/wav")

    @app.get("/api/projects/{slug}/art/{no}")
    def get_art(slug: str, no: int) -> FileResponse:
        """씬 장면 하나. `.svg` 면 브라우저가 그대로 움직여 준다."""
        _need(slug)
        name = runner.s6_art.present(slug).get(int(no))
        if not name:
            raise HTTPException(404, "그 씬 장면이 아직 없습니다.")
        p = paths.art_dir(slug) / name
        media = "image/svg+xml" if p.suffix.lower() == ".svg" else None
        return FileResponse(p, media_type=media) if media else FileResponse(p)

    @app.get("/api/projects/{slug}/preview/{path:path}")
    def preview(slug: str, path: str = "index.html") -> FileResponse:
        """컴포지션 폴더를 그대로 서브 — `<hyperframes-player>` 가 이걸 읽는다.

        ★ **굽기 전에 보는 화면이다.** 렌더는 한 편에 1분 걸리고, 아스트라로
          장면을 짜면 호출값까지 든다. 그 앞에 눈으로 확인하는 자리를 두면
          잘못된 채로 굽는 일이 없어진다.

        ★ 경로를 `resolve()` 해서 컴포지션 폴더 밖으로 못 나가게 막는다 —
          `..` 로 레포 전체가 열리면 LAN 공유에서 사고다.
        """
        _need(slug)
        base = paths.comp_dir(slug).resolve()
        f = (base / (path or "index.html")).resolve()
        if not str(f).startswith(str(base)) or not f.is_file():
            raise HTTPException(404, "컴포지션에 그런 파일이 없습니다. 「컴포지션」을 먼저 돌리세요.")
        return FileResponse(f)

    @app.get("/api/projects/{slug}/video")
    def get_video(slug: str) -> FileResponse:
        _need(slug)
        build = paths.latest_build(slug)
        mp4 = (build / f"{slug}.mp4") if build else None
        if not mp4 or not mp4.exists():
            raise HTTPException(404, "아직 빌드가 없습니다.")
        return FileResponse(mp4, media_type="video/mp4")

    @app.get("/api/projects/{slug}/artspec")
    def get_artspec(slug: str) -> Dict[str, Any]:
        """장면 지시. 화면의 「장면 지시」 탭이 이걸 읽어 사람이 읽을 꼴로 보여 준다."""
        _need(slug)
        p = paths.art_spec(slug)
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}

    @app.get("/api/projects/{slug}/srt", response_class=PlainTextResponse)
    def get_srt(slug: str) -> str:
        _need(slug)
        p = paths.srt(slug)
        return p.read_text(encoding="utf-8-sig") if p.exists() else ""

    # ── 대본 다듬기 — 검증 · 후크 다시 · 자막 다시 ──────────────────────
    # ★ 이 넷은 **단계가 아니다.** 레일에 줄을 늘리지 않고 「대본」 화면 안에
    #   머문다. 대본을 확정하는 일은 오가며 고치는 일이라, 단계로 만들면
    #   앞뒤 단계를 낡게 만들어(invalidates) 음성·자막이 매번 다시 굽는다.
    #   자막을 실제로 바꾸는 둘(자막 다시 · 대안 적용)만 그 씬의 발음을 버린다.

    @app.post("/api/projects/{slug}/verify")
    async def run_verify(slug: str, request: Request) -> Dict[str, Any]:
        """사실검증. `{"only": [3]}` 을 주면 그 씬만 — 씬별 「검토」가 이 길이다.

        ★ **고치지 않는다.** 판단과 대안만 돌려주고, 무엇을 쓸지는 사람이 고른다.
        """
        _need(slug)
        body = await _json_body(request)
        only = body.get("only") or None
        return s1b_revise.verify(slug, only=[int(n) for n in only] if only else None)

    @app.post("/api/projects/{slug}/verify/apply")
    async def apply_verify_alt(slug: str, request: Request) -> Dict[str, Any]:
        """사람이 고른 대안을 그 씬에 넣는다. 방어망의 마지막 관문이다."""
        _need(slug)
        body = await _json_body(request)
        try:
            out = s1b_revise.apply_alt(slug, int(body.get("no") or 0),
                                       str(body.get("text") or ""))
        except ValueError as e:
            raise HTTPException(400, str(e))
        out["subs"] = s4_subs.run(slug)      # 자막이 바뀌면 큐를 다시 나눈다
        return out

    @app.post("/api/projects/{slug}/hooks/regen")
    def regen_hooks(slug: str) -> Dict[str, Any]:
        _need(slug)
        return s1b_revise.regen_hooks(slug)

    @app.post("/api/projects/{slug}/captions/regen")
    async def regen_captions(slug: str, request: Request) -> Dict[str, Any]:
        _need(slug)
        body = await _json_body(request)
        only = body.get("only") or None
        out = s1b_revise.regen_captions(
            slug, only=[int(n) for n in only] if only else None)
        if out.get("touched"):
            out["subs"] = s4_subs.run(slug)
        return out

    @app.put("/api/projects/{slug}/persona")
    async def put_persona(slug: str, request: Request) -> Dict[str, Any]:
        """이 프로젝트의 무드(MBTI). `00_기획/source.json` 에 적는다.

        ★ 무드를 씬에 저장하지 않는다. 같은 장(章)을 열여섯 유형으로 내보내는 것이
          캠페인 방식이라, 원고는 장별로만 있고 무드는 **생성 시점에** 입힌다.
        """
        _need(slug)
        body = await _json_body(request)
        who = persona.normalize(body.get("mbti"))

        # ★ 무드를 바꾸는 것은 **유형 폴더를 갈아타는 것**이다. 옛 유형의 대본·음성은
        #   제 폴더에 그대로 남는다 — 덮어쓰지 않으므로 되돌아올 수 있다.
        paths.set_variant(slug, paths.variant_tag(who))

        p = paths.source_json(slug)
        meta = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
        meta["mbti"] = who
        meta["mood"] = str(body.get("mood") or "").strip() or persona.mood(who)
        atomic_write_json(str(p), meta, indent=2)
        return {"mbti": who, "mood": meta["mood"], "variant": paths.variant(slug),
                "variants": paths.variants(slug),
                "tone": persona.tone_block(who, meta["mood"])}

    @app.get("/api/persona")
    def list_persona() -> Dict[str, Any]:
        """16유형과 무드 한 줄. 화면의 고르개가 이것으로 그려진다."""
        return {"order": persona.ROUND_ORDER, "moods": persona.MOODS}

    @app.post("/api/projects/{slug}/fork")
    async def fork_project(slug: str, request: Request) -> Dict[str, Any]:
        """같은 장(章)에서 **다른 유형을 연다.**

        ★ 폴더를 복사하지 않는다. 한 장이 한 폴더이고 `00_기획`(원고·구조)은 공용이라,
          유형을 하나 더 내는 일은 `01_대본/04ESTP/` 같은 빈 칸을 여는 것뿐이다.
          원고 오타를 고치면 열여섯 유형이 같이 고쳐진다 — 복사본이 없기 때문이다.

        ★ 무드를 타는 것은 대본부터다. 그래서 크레딧은 「대본」에서 처음 든다.
        """
        _need(slug)
        body = await _json_body(request)
        who = persona.normalize(body.get("mbti"))
        if not who:
            raise HTTPException(400, "MBTI 16유형 중 하나를 주세요.")
        tag = paths.variant_tag(who)

        p = paths.source_json(slug)
        meta = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
        paths.set_variant(slug, tag)          # 폴더를 만들고 그리로 갈아탄다
        meta["mbti"] = who
        meta["mood"] = persona.mood(who)
        atomic_write_json(str(p), meta, indent=2)
        return {"slug": slug, "mbti": who, "variant": tag,
                "variants": paths.variants(slug)}

    # ── 현황판 — 장 × MBTI ────────────────────────────────────────────
    # ★ 쇼츠공방 I 의 캠페인 목록을 이 레포가 아는 것만으로 다시 세운다. 그쪽
    #   SQLite 를 읽지 않는다 — 두 앱이 한 파일을 물면 잠금과 스키마가 얽힌다.
    #   여기서는 **작업물 폴더가 곧 진실**이다. 폴더를 옮기면 현황도 같이 간다.
    #
    # ★ 전 MBTI 를 한 판에 세우지 않는다. 프로젝트가 장별로 갈려 있어서 한 칸이
    #   한 폴더다 — 없는 칸은 「아직」이고, 그것을 만드는 것은 사람이 정한다.

    @app.get("/api/board")
    def board() -> Dict[str, Any]:
        rows: List[Dict[str, Any]] = []
        for slug in paths.list_projects():
            meta_p = paths.source_json(slug)
            meta = {}
            if meta_p.exists():
                try:
                    meta = json.loads(meta_p.read_text(encoding="utf-8"))
                except Exception:  # noqa: BLE001
                    meta = {}
            try:
                ch = int(meta.get("chapter"))
            except (TypeError, ValueError):
                continue

            # ★ 진실은 **폴더**다. `01_대본` 밑에 있는 유형 폴더가 곧 「만든 것」이고,
            #   없는 유형은 아직 안 만든 것이다. 별도 장부를 두지 않는다.
            cells: Dict[str, Any] = {}
            for tag in paths.variants(slug):
                who = tag[2:] if len(tag) > 2 else tag       # `03ENFP` → `ENFP`
                who = persona.normalize(who)
                if not who:
                    continue
                d = paths.project(slug)
                sc = d / paths.SCRIPT / tag / "script.json"
                n = 0
                if sc.exists():
                    try:
                        n = len(json.loads(sc.read_text(encoding="utf-8")).get("scenes") or [])
                    except Exception:  # noqa: BLE001
                        n = 0
                done = d / paths.DONE / tag
                builds = sorted((x for x in done.glob("v*") if x.is_dir()),
                                key=lambda x: x.name) if done.is_dir() else []
                cells[who] = {
                    "slug": slug, "tag": tag, "scenes": n,
                    "state": "built" if builds else ("script" if n else "empty"),
                    "builds": len(builds),
                    "build": builds[-1].name if builds else "",
                }

            rows.append({
                "chapter": ch, "slug": slug,
                "title": str(meta.get("title") or f"{ch}장"),
                # 원고가 어디까지 왔는지 — 유형과 무관한 공용 단계다
                "material": ("structure" if paths.structure_json(slug).exists()
                             else "draft" if paths.draft_html(slug).exists()
                             else "source" if paths.source_md(slug).exists() else "empty"),
                "current": paths.variant(slug),
                "cells": cells,
            })
        rows.sort(key=lambda r: r["chapter"])
        return {"order": persona.ROUND_ORDER, "moods": persona.MOODS, "chapters": rows}

    # ── 편의 ──────────────────────────────────────────────────────────────
    @app.post("/api/projects/{slug}/open")
    def open_folder(slug: str) -> Dict[str, Any]:
        """산출물 폴더를 띄운다. **서버가 도는 PC 에서** 열린다 — 로컬 전용이다."""
        _need(slug)
        target = paths.latest_build(slug) or paths.project(slug)
        if sys.platform == "win32":
            os.startfile(str(target))               # noqa: S606
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(target)])
        else:
            subprocess.Popen(["xdg-open", str(target)])
        return {"opened": str(target)}

    @app.post("/api/projects/{slug}/placeholder")
    def make_placeholder(slug: str) -> Dict[str, Any]:
        """장면값을 안 쓰고 나머지를 시험한다 — `tools/placeholder_art.py`."""
        _need(slug)
        r = subprocess.run([sys.executable, str(ROOT / "tools" / "placeholder_art.py"),
                            slug, "--force"],
                           cwd=str(ROOT), capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=300)
        return {"ok": r.returncode == 0, "log": (r.stdout or "") + (r.stderr or "")}

    return app


app = create_app()


if __name__ == "__main__":
    import uvicorn

    port = int(config.get("port", 8899))
    host = access.host()
    print(f"쇼츠공방 II — http://127.0.0.1:{port}")
    if access.lan_enabled():
        print("  LAN 공유 켜짐 — 다른 PC 에서는 **보기만** 됩니다.")
    uvicorn.run(app, host=host, port=port, log_level="warning")
