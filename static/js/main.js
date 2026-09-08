/* 쇼츠공방 II — 콘솔.
 *
 * ★ **단계 표를 여기 적지 않는다.** `/api/stages` 가 유일한 출처다
 *   (pipeline/stages.py). 표를 두 벌 두면 화면과 실제가 갈리고, 그때 화면이
 *   거짓말을 한다.
 *
 * ★ 진행은 **폴링**이다. 스트리밍을 쓰지 않는 이유는 브라우저를 새로 고쳐도
 *   로그가 이어져야 하기 때문이다 — 잡은 서버 메모리에 산다.
 *
 * ★ 지면 층과 떠 있는 층을 섞지 않는다. 저장 안 된 글이 있는 화면(자막·발음)은
 *   지면 층이고, 진행 기록은 도크다. 화면을 옮겨도 도크는 살아 있다.
 */
"use strict";

const $ = (s) => document.querySelector(s);
const el = (t, c, x) => { const n = document.createElement(t); if (c) n.className = c; if (x !== undefined) n.textContent = x; return n; };
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

const S = {
  table: null,       // /api/stages 가 준 {groups, stages}
  slug: null,        // 지금 보고 있는 프로젝트
  page: "home",      // 지금 보고 있는 화면(= 단계 키 또는 "home")
  proj: null,        // /api/projects/{slug} 응답
  job: null,         // 도는 잡
  poll: null,        // setInterval 핸들
  cfg: null,
};

async function api(path, opts) {
  const r = await fetch(path, opts);
  if (!r.ok) {
    let msg = `HTTP ${r.status}`;
    try { const j = await r.json(); msg = j.detail || j.error || msg; } catch (_) { /* 본문이 JSON 이 아니면 그대로 */ }
    throw new Error(msg);
  }
  const ct = r.headers.get("content-type") || "";
  return ct.includes("json") ? r.json() : r.text();
}
const post = (p, body) => api(p, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(body || {}) });
const put = (p, body, raw) => api(p, { method: "PUT", headers: { "content-type": raw ? "text/plain" : "application/json" }, body: raw ? body : JSON.stringify(body) });

/* ── 레일 ─────────────────────────────────────────────────────────────── */
function stageRows() { return (S.proj?.stages) || S.table?.stages || []; }
function groupRows() { return (S.proj?.groups) || S.table?.groups || []; }
function screenRows() { return (S.proj?.screens) || S.table?.screens || []; }
function stageOf(key) { return stageRows().find((x) => x.key === key); }
function screenOf(key) { return screenRows().find((x) => x.key === key); }

/* ★ 레일에 뜨는 줄은 **화면**이다. 단계가 아니다.
 *   단계 열 개를 그대로 늘어놓으면 무엇이 한 덩어리인지 안 보인다.
 *   「대본」 한 줄이 탭 다섯(대본·발음·음성·자막·장면지시)을 담는다. */
function drawRail() {
  const box = $("#steps");
  box.innerHTML = "";
  const screens = screenRows();
  const groups = groupRows();
  const ro = !!S.cfg?.readonly;
  const busyJob = S.job && S.job.status === "running";
  let n = 0;

  groups.forEach((g, gi) => {
    if (gi > 0) box.appendChild(el("div", "rail-sep"));

    const gb = el("button", "grp" + (g.primary ? " primary" : ""));
    gb.type = "button";
    gb.disabled = ro || !S.slug || busyJob;
    gb.title = ro ? "보기 전용입니다" : g.hint;
    gb.appendChild(el("span", "grp-label", g.label));
    if (g.costs) gb.appendChild(Object.assign(el("span", "cost", "$"),
      { title: "이 묶음에 크레딧 쓰는 단계가 있습니다" }));
    gb.onclick = () => runGroup(g);
    box.appendChild(gb);

    (g.screens || []).forEach((k) => {
      const sc = screenOf(k);
      if (sc) box.appendChild(screenRow(sc, ++n, busyJob));
    });
  });

  // 묶음에 안 든 화면(결과) — 「넘기는 것」 뒤에 붙는다
  const inGroups = new Set(groups.flatMap((g) => g.screens || []));
  const rest = screens.filter((sc) => !inGroups.has(sc.key));
  if (rest.length) {
    box.appendChild(Object.assign(el("div", "step-rule"),
      { innerHTML: "<span>넘기는 것</span>" }));
    rest.forEach((sc) => box.appendChild(screenRow(sc, ++n, busyJob)));
  }
}

function screenRow(sc, n, busyJob) {
  const b = el("button", "step" + (S.page === sc.key ? " on" : "")
    + (sc.stale ? " stale" : ""));
  b.type = "button";
  b.dataset.key = sc.key;
  b.disabled = !S.slug;
  b.title = sc.stale ? "산출물이 입력보다 낡았습니다 — 다시 돌리세요" : sc.hint;
  b.appendChild(el("span", "step-no", String(n)));
  b.appendChild(el("span", "step-name", sc.name));
  // 이 면 안에 단계가 몇 개인지 — 탭이 아니라 세로로 늘어선 구간 수다
  if (sc.stages.length > 1) {
    b.appendChild(Object.assign(el("span", "tabn", String(sc.stages.length)),
      { title: `이 면에 ${sc.stages.length}개 단계가 순서대로 있습니다` }));
  }
  if (sc.costs) b.appendChild(Object.assign(el("span", "cost", "$"),
    { title: "크레딧을 씁니다" }));
  const busy = busyJob && (sc.stages.includes(S.job.stage)
    || (S.job.stage || "").startsWith("group:"));
  b.appendChild(el("span", "step-dot " + (busy ? "busy" : sc.state)));
  b.onclick = () => go(sc.key);
  return b;
}

/* ── 도크 ─────────────────────────────────────────────────────────────── */
function drawDock() {
  const dock = $("#dock");
  if (!S.job) { dock.hidden = true; return; }
  dock.hidden = false;
  dock.classList.toggle("done", S.job.status === "done");
  dock.classList.toggle("err", S.job.status === "error" || S.job.status === "canceled");
  $("#dock-now").textContent = S.job.step || S.job.label || "";
  // ★ 서버 잡에는 `percent` 가 없다 — `completed` / `total` 뿐이다.
  //   전에 여기서 없는 필드를 읽어서 막대가 0 아니면 100 밖에 안 움직였다.
  const pct = S.job.status === "done" ? 100
    : (S.job.total > 0 ? Math.round((S.job.completed / S.job.total) * 100) : 0);
  $("#dock-bar").style.width = pct + "%";
  $("#dock-stop").hidden = S.job.status !== "running";

  const log = $("#log");
  const atBottom = log.scrollTop + log.clientHeight >= log.scrollHeight - 24;
  log.innerHTML = (S.job.log || []).map((l) => {
    const cls = /실패|✗|Error|Traceback/.test(l) ? "bad"
      : /⚠/.test(l) ? "warn"
        : /^\[/.test(l) ? "head" : "";
    return cls ? `<span class="${cls}">${esc(l)}</span>` : esc(l);
  }).join("\n");
  if (atBottom) log.scrollTop = log.scrollHeight;

  const started = S.job.started_at ? new Date(S.job.started_at) : null;
  if (started) {
    const endRef = S.job.finished_at ? new Date(S.job.finished_at) : new Date();
    const sec = Math.max(0, Math.round((endRef - started) / 1000));
    $("#dock-time").textContent = `${String((sec / 60) | 0).padStart(2, "0")}:${String(sec % 60).padStart(2, "0")}`;
  }
}

function startPoll() {
  if (S.poll) clearInterval(S.poll);
  S.poll = setInterval(async () => {
    if (!S.job) return;
    try {
      S.job = await api(`/api/jobs/${S.job.job_id}`);
      drawDock(); drawRail();
      if (S.job.status !== "running" && S.job.status !== "queued") {
        clearInterval(S.poll); S.poll = null;
        await loadProject(S.slug);       // 끝났으면 상태를 다시 읽는다
      }
    } catch (e) { clearInterval(S.poll); S.poll = null; }
  }, 900);
}

async function runStage(key, opts) {
  try {
    S.job = await post(`/api/projects/${encodeURIComponent(S.slug)}/stages/${key}/run`, opts);
    document.body.classList.add("dock-on");
    document.body.classList.remove("dock-min");
    drawDock(); drawRail(); startPoll();
  } catch (e) { alert(e.message); }
}

async function runGroup(g) {
  // 줄바꿈은 배열로 잇는다 — 이 파일을 스크립트로 고칠 때 escape 가 벗겨져
  // 문자열이 통째로 깨진 적이 있다. 배열이면 그런 일이 없다.
  const ask = [`「${g.label}」 를 돌립니다.`, g.hint];
  if (g.costs) ask.push("", "이 묶음은 크레딧을 씁니다.");
  if (!confirm(ask.join("\n"))) return;
  try {
    S.job = await post(`/api/projects/${encodeURIComponent(S.slug)}/groups/${g.key}/run`, {});
    document.body.classList.add("dock-on");
    document.body.classList.remove("dock-min");
    drawDock(); drawRail(); startPoll();
  } catch (e) { alert(e.message); }
}

/* ── 화면 ─────────────────────────────────────────────────────────────── */
function go(page) { S.page = page; drawRail(); render(); }

async function loadProject(slug) {
  if (!slug) { S.proj = null; return; }
  S.proj = await api(`/api/projects/${encodeURIComponent(slug)}`);
  if (!S.job && S.proj.job) S.job = S.proj.job;
  drawRail(); drawDock(); render();
}

function head(title, sub) {
  const f = document.createDocumentFragment();
  const h = el("div", "page-head"); h.appendChild(el("h1", null, title)); f.appendChild(h);
  if (sub) f.appendChild(el("div", "page-sub", sub));
  return f;
}

/** 가로 한 줄. ★ `el.append(...)` 는 **undefined 를 돌려준다** — 체이닝하면
 *  `Cannot read properties of undefined` 로 터진다(실제로 두 화면이 그랬다).
 *  그래서 줄을 만들어 돌려주는 함수를 따로 둔다. */
function row(...kids) {
  const r = el("div", "row");
  kids.filter(Boolean).forEach((k) => r.appendChild(k));
  return r;
}

function card(title, hint) {
  const c = el("div", "card");
  if (title) c.appendChild(el("h2", null, title));
  if (hint) c.appendChild(el("div", "hint", hint));
  return c;
}

function runBtn(key, label, opts) {
  const s = stageOf(key);
  const b = el("button", "btn primary" + (s && s.costs ? " money" : ""), label);
  b.type = "button";
  // ★ 손님은 **누를 수 없다는 것을 미리** 본다. 눌러 보고 403 을 받으면 고장인 줄 안다.
  if (S.cfg?.readonly) {
    b.disabled = true;
    b.title = "보기 전용입니다 — 만드는 단계는 이 도구를 띄운 PC 에서만 됩니다.";
    return b;
  }
  b.disabled = S.job && S.job.status === "running";
  b.onclick = () => runStage(key, opts);
  return b;
}

const PAGES = {};

/* 홈 — 프로젝트 목록 + 새로 만들기 */
PAGES.home = async (m) => {
  m.appendChild(head("쇼츠공방 II", "단행본 한 장(章)을 넣으면 9:16 30초 모션 쇼츠가 나옵니다."));

  const nc = card("새로 만들기",
    "장(章) 파일 하나를 넣으세요 — PDF · DOCX · MD · TXT · HTML 다 됩니다. 이미 소제목이 잡힌 마크다운이면 「원고」 단계가 할 일이 줄어듭니다.");
  const r1 = el("div", "row");
  const file = Object.assign(document.createElement("input"), { type: "file", accept: ".pdf,.docx,.md,.markdown,.txt,.html,.htm" });
  const title = Object.assign(document.createElement("input"), { type: "text", placeholder: "제목 (비우면 파일 이름)" });
  title.className = "grow";
  /* ★ 씬 수를 묻지 않는다. 예전에 여기 「컷」 숫자칸이 있었고, 그 값이
   *   프롬프트에 「씬 수는 N개다」로 박혀 원문이 18쪽이든 2쪽이든 대본이
   *   N 으로 맞춰 나왔다. 이제 재료가 정한다. 사람이 고르는 것은 형식뿐이다. */
  const fmt = document.createElement("select");
  [["narrative", "서사형"], ["listicle", "목록형"]].forEach(([v, t]) => {
    const o = document.createElement("option"); o.value = v; o.textContent = t; fmt.appendChild(o);
  });
  fmt.value = S.cfg?.shorts?.format ?? "narrative";

  /* ★ 무드를 **여기서** 받는다. 대본을 뽑은 뒤에 고르면 그 대본이 무드 없이
   *   나온 것이라 다시 뽑아야 하고, 대본은 크레딧을 쓰는 단계다.
   *   나중에 「대본」 화면에서 바꿀 수도 있다. */
  const mb = document.createElement("select");
  const mbNone = document.createElement("option");
  mbNone.value = ""; mbNone.textContent = "무드 없음";
  mb.appendChild(mbNone);
  api("/api/persona").then(({ order, moods }) => {
    order.forEach((k) => {
      const o = document.createElement("option");
      o.value = k; o.textContent = `${k} · ${moods[k]}`;
      mb.appendChild(o);
    });
  }).catch(() => { /* 목록을 못 받아도 「무드 없음」으로 만들 수 있다 */ });

  const mk = el("button", "btn primary", "만들기");
  mk.type = "button";
  mk.onclick = async () => {
    if (!file.files[0]) { alert("파일을 고르세요."); return; }
    const fd = new FormData();
    fd.append("file", file.files[0]);
    fd.append("title", title.value);
    fd.append("fmt", fmt.value);
    fd.append("mbti", mb.value);
    mk.disabled = true;
    try {
      const r = await api("/api/projects", { method: "POST", body: fd });
      S.slug = r.slug; await loadProject(r.slug); go("plan");
    } catch (e) { alert(e.message); } finally { mk.disabled = false; }
  };
  r1.append(file, title, el("span", null, "형식"), fmt,
            el("span", null, "무드"), mb, mk);
  nc.appendChild(r1);
  const sh = S.cfg?.shorts || {};
  nc.appendChild(el("div", "hint", `씬 수는 재료가 정합니다 — 사실 하나에 씬 하나이고, 상한은 ${sh.cuts_max ?? 8}개입니다. 지금 예산은 ${S.cfg?.budget_chars ?? "?"}자 (${sh.seconds_min ?? 20}~${sh.seconds_max ?? 30}초 · ${S.cfg?.narration?.speed ?? 1.2}배속).`));
  m.appendChild(nc);

  const lc = card("만들던 것");
  const list = el("div", "plist");
  const rows = await api("/api/projects");
  if (!rows.length) list.appendChild(el("div", "hint", "아직 없습니다."));
  rows.forEach((p) => {
    const b = el("button", "pcard" + (p.slug === S.slug ? " on" : ""));
    b.type = "button";
    const t = el("div", "t");
    t.appendChild(el("b", null, p.title));
    t.appendChild(el("span", null, `${p.slug} · ${p.cuts || 0}컷${p.total_sec ? ` · ${p.total_sec.toFixed(1)}초` : ""}`));
    b.appendChild(t);
    b.appendChild(el("span", "pill" + (p.built ? " ok" : ""), `${p.done}/${p.steps}`));
    b.onclick = async () => { S.slug = p.slug; await loadProject(p.slug); go("plan"); };
    list.appendChild(b);
  });
  lc.appendChild(list);
  m.appendChild(lc);
};

/* 재료 — 원본 → source.md, 사람이 고칠 수 있다 */
function saveBtn(url, ta) {
  const save = el("button", "btn", "저장");
  save.type = "button";
  save.onclick = async () => {
    save.disabled = true;
    try {
      const r = await put(url, ta.value, true);
      save.textContent = `저장됨 (${(r.chars || 0).toLocaleString()}자)`;
    } catch (e) { alert(e.message); }
    finally { setTimeout(() => { save.textContent = "저장"; save.disabled = false; }, 1400); }
  };
  return save;
}

/* 씬 편집 — 발음 탭과 자막 탭이 같은 부품을 쓴다. **사람 손이 이긴다.**
 * ★ 고친 값은 `overrides` 가 아니라 script.json 에 바로 들어가고, 서버가 자막
 *   큐를 다시 나눈다. 그리고 발음을 고친 씬은 음성 스탬프가 어긋나 다음
 *   「음성」에서 **그 씬만** 다시 굽는다 — 전부 다시 굽지 않는다. */
/* ── 사실검증 ─────────────────────────────────────────────────────────
   ★ **AI 는 고치지 않는다.** 판정과 대안만 그리고, 적용은 사람이 누른다.
     자동으로 갈아 끼우면 손으로 다듬어 놓은 문장까지 덮어쓴다 — 쇼츠공방 I 이
     「전체 재작성」을 만들어 놓고 화면에서 뺀 이유가 그것이다. */
function verifyBox(no, v) {
  const box = el("div", "verify " + (v.ok ? "ok" : "ng"));
  box.appendChild(row(
    el("span", "vtag", v.ok ? "OK" : "NG"),
    el("span", "vreason", v.reason || (v.ok ? "근거와 맞습니다" : "")),
  ));
  if ((v.alts || []).length) {
    const alts = el("div", "alts");
    alts.appendChild(el("div", "hint", "대안을 누르면 그 문장으로 바뀝니다."));
    v.alts.forEach((t) => {
      const a = el("button", "alt", t);
      a.type = "button";
      a.disabled = !!S.cfg?.readonly;
      a.onclick = async () => {
        a.disabled = true;
        try {
          await post(`/api/projects/${encodeURIComponent(S.slug)}/verify/apply`,
            { no, text: t });
          await loadProject(S.slug);
          render();
        } catch (e) { alert(e.message); a.disabled = false; }
      };
      alts.appendChild(a);
    });
    box.appendChild(alts);
  }
  return box;
}

function sceneEditor(d, { showSource, showNarration, showVerify } = {}) {
  const ro = !!S.cfg?.readonly;
  const c = card("씬",
    "고치면 「저장」을 누르세요. 발음을 고친 씬은 다음 「음성」에서 그 씬만 다시 굽습니다.");
  const edits = {};

  (d.scenes || []).forEach((s) => {
    const box = el("div", "scene");
    const h = el("div", "scene-head");
    h.appendChild(el("span", "no", String(s.no)));
    h.appendChild(el("span", "role", s.role || "body"));
    h.appendChild(el("span", "pill",
      s.audio_sec ? `${s.audio_sec.toFixed(1)}초` : "소리 없음"));
    h.appendChild(el("span", "grow"));
    if (s.audio_sec) {
      const play = el("button", "btn sm", "▶ 듣기");
      play.type = "button";
      play.onclick = () =>
        new Audio(`/api/projects/${encodeURIComponent(S.slug)}/audio/${s.no}`).play();
      h.appendChild(play);
    }
    if (showVerify) {
      // 씬 하나만 담아 부른다 — 같은 함수, 같은 프롬프트다. 전체 검증이 놓친 것을
      // 사람이 의심할 때 쓰는 4단계다.
      const vb = el("button", "btn sm", "\u{1F50E} 검토");
      vb.type = "button";
      vb.disabled = ro;
      vb.onclick = async () => {
        vb.disabled = true; vb.textContent = "검토 중\u2026";
        try {
          await post(`/api/projects/${encodeURIComponent(S.slug)}/verify`, { only: [s.no] });
          await loadProject(S.slug);
          render();
        } catch (e) {
          alert(e.message); vb.disabled = false; vb.textContent = "\u{1F50E} 검토";
        }
      };
      h.appendChild(vb);
    }
    box.appendChild(h);

    const g = el("div", "scene-grid");
    const field = (label, key, value, rows) => {
      g.appendChild(el("label", null, label));
      const t = document.createElement("textarea");
      t.rows = rows || 2;
      t.value = value || "";
      t.disabled = ro;
      t.oninput = () => { (edits[s.no] = edits[s.no] || {})[key] = t.value; };
      g.appendChild(t);
    };

    g.appendChild(el("label", null, "후크 (2줄)"));
    const hp = el("div", "hookpair");
    [["hook_line1", s.hook_line1], ["hook_line2", s.hook_line2]].forEach(([k, v]) => {
      const i = Object.assign(document.createElement("input"),
        { type: "text", value: v || "", maxLength: 12 });
      i.disabled = ro;
      i.oninput = () => { (edits[s.no] = edits[s.no] || {})[k] = i.value; };
      hp.appendChild(i);
    });
    g.appendChild(hp);

    field("자막 (= 말)", "srt_text", s.srt_text, 2);
    if (showNarration) {
      field(`발음 (${s.narration_from || "규칙"})`, "narration_text", s.narration_text, 2);
    }
    if (showSource && s.source) {
      g.appendChild(el("label", null, "원문 근거"));
      g.appendChild(el("div", "scene-src", s.source));
    }
    box.appendChild(g);
    const v = (d.verify || {})[String(s.no)];
    if (showVerify && v) box.appendChild(verifyBox(s.no, v));
    c.appendChild(box);
  });

  const save = el("button", "btn primary", "저장");
  save.type = "button";
  save.disabled = ro;
  save.onclick = async () => {
    if (!Object.keys(edits).length) { alert("고친 것이 없습니다."); return; }
    save.disabled = true;
    try {
      const r = await put(`/api/projects/${encodeURIComponent(S.slug)}/scenes`,
        { scenes: edits });
      await loadProject(S.slug);
      alert(`씬 ${r.touched.join(", ")} 저장됨. 「음성」 탭을 다시 돌리면 그 씬만 다시 굽습니다.`);
    } catch (e) { alert(e.message); } finally { save.disabled = false; }
  };
  c.appendChild(row(save));
  return c;
}

/* ══ 대본 만들기 — 한 면 ═══════════════════════════════════════════════
   ★ **탭이 없다.** 재료·원고·구조·대본·발음·음성·자막·장면지시가 세로로 늘어서고
     생성 단추가 순서대로 나온다.

     왜 — 탭은 길이를 감추려고 임시로 두른 것이었는데, 감춘 것이 **눌러야 하는
     단추**였다. 「구조 다시 뽑기」를 안 눌렀는데 「대본 다시 쓰기」를 누르면
     구조.json 이 없다고 죽는다. 순서가 곧 일이라면 순서가 보여야 한다.

   ★ **씬 목록은 하나뿐이다.** 예전에는 대본 탭·발음 탭·음성 탭이 각자 씬 편집기를
     그려서 스물두 씬짜리 목록이 세 벌 떠 있었다. 한 씬의 자막·발음·길이·판정은
     한자리에서 봐야 고칠 수 있다.

   ★ **자막은 대본과 한 몸이다.** `srt_text` 가 화면 자막이면서 음성이 읽는 글이다.
     따로 둔 「자막」은 그것을 큐로 쪼갠 **결과**일 뿐이라 씬 목록 아래로 내렸다. */

/* 이 면 위의 건너뛰기 줄. 세로로 길어진 값을 여기서 치른다. */
function jumpBar(items) {
  const bar = el("div", "jump");
  items.forEach(([id, label, st]) => {
    const a = el("button", "jump-i" + (st ? " " + st : ""), label);
    a.type = "button";
    a.onclick = () => {
      const t = document.getElementById(id);
      if (t) t.scrollIntoView({ behavior: "smooth", block: "start" });
    };
    bar.appendChild(a);
  });
  return bar;
}

/* 단계 한 구간. 번호 · 이름 · 상태 · 생성 단추를 한 줄에 세운다.
   ★ 앞 단계가 안 끝났으면 **누르기 전에** 막는다. 눌러서 스택트레이스를 보는 것은
     고장으로 읽힌다 — 무엇을 먼저 해야 하는지 말해 주는 것이 화면이 할 일이다. */
function stepCard(key, n, hint) {
  const st = stageOf(key) || {};
  const c = el("div", "card step-card");
  c.id = "sec-" + key;

  const h = el("div", "step-head");
  h.appendChild(el("span", "sc-no", String(n)));
  h.appendChild(el("h2", null, st.name || key));
  if (st.costs) h.appendChild(Object.assign(el("span", "cost", "$"),
    { title: "크레딧을 씁니다" }));
  h.appendChild(el("span", "step-dot " + (st.state || "")));
  if (st.stale) h.appendChild(el("span", "pill warn", "낡음"));
  h.appendChild(el("span", "grow"));
  c.appendChild(h);
  if (hint) c.appendChild(el("div", "hint", hint));
  return c;
}

/* 앞 단계가 덜 됐으면 못 누르게 하고 이유를 붙인다. */
function gatedRun(key, label, opts) {
  const b = runBtn(key, label, opts);
  const st = stageOf(key) || {};
  const missing = (st.needs || []).filter((k) => {
    const d = stageOf(k) || {};
    return d.state !== "done";
  });
  if (missing.length && !b.disabled) {
    b.disabled = true;
    const names = missing.map((k) => (stageOf(k) || {}).name || k).join(" · ");
    b.title = `먼저 「${names}」 를 끝내세요.`;
  }
  return { btn: b, missing };
}

function runRow(key, label, opts, extra) {
  const { btn, missing } = gatedRun(key, label, opts);
  const kids = [btn];
  if (extra) kids.push(...(Array.isArray(extra) ? extra : [extra]));
  const r = row(...kids.filter(Boolean));
  if (missing.length) {
    const names = missing.map((k) => (stageOf(k) || {}).name || k).join(" · ");
    r.appendChild(el("span", "hint", `먼저 「${names}」 를 끝내세요.`));
  }
  return r;
}

PAGES.plan = async (m) => {
  const p = S.proj, d = p.script || {};
  const enc = encodeURIComponent(S.slug);
  const stt = (k) => (stageOf(k) || {}).state || "";

  m.appendChild(head("대본 만들기",
    "위에서 아래로 순서대로 누르세요. 재료를 갈아 놓지 않고 대본을 부르면 "
    + "대본이 첫 단락만 잡고 뒷장을 버립니다."));

  m.appendChild(jumpBar([
    ["sec-source", "재료", stt("source")],
    ["sec-draft", "원고", stt("draft")],
    ["sec-structure", "구조", stt("structure")],
    ["sec-script", "대본", stt("script")],
    ["sec-scenes", "씬", stt("script")],
    ["sec-speech", "발음", stt("speech")],
    ["sec-tts", "음성", stt("tts")],
    ["sec-subs", "자막", stt("subs")],
    ["sec-artspec", "장면 지시", stt("artspec")],
  ]));

  /* ── 0 · 이 장(章)이 무엇인가 ───────────────────────────────────────
     ★ 무드를 **여기** 둔다. 어조는 대본을 뽑기 전에 정해져야 하는 값이다 —
       대본 옆에 두면 이미 나온 대본을 보고 고르게 되고, 그러면 크레딧을 쓴
       대본을 버리고 다시 뽑아야 한다. */
  const mc = card("이 장(章)",
    // title 에 이미 「10장 배움」처럼 장 번호가 들어 있다 — 앞에 또 붙이면 겹친다
    `${p.meta.file || "(원본 없음)"} · ${p.meta.title || (p.meta.chapter ? p.meta.chapter + "장" : "")}`);
  const fmt = document.createElement("select");
  [["narrative", "서사형"], ["listicle", "목록형"]].forEach(([v, t]) => {
    const o = document.createElement("option"); o.value = v; o.textContent = t; fmt.appendChild(o);
  });
  fmt.value = d.format || p.meta.format || S.cfg?.shorts?.format || "narrative";
  fmt.disabled = !!S.cfg?.readonly;

  const mb = document.createElement("select");
  const mbNone = document.createElement("option");
  mbNone.value = ""; mbNone.textContent = "— 무드 없음 (하십시오체) —";
  mb.appendChild(mbNone);
  mb.disabled = !!S.cfg?.readonly;
  api("/api/persona").then(({ order, moods }) => {
    order.forEach((k) => {
      const o = document.createElement("option");
      o.value = k; o.textContent = `${k} · ${moods[k]}`;
      mb.appendChild(o);
    });
    mb.value = p.meta.mbti || "";
  }).catch(() => { /* 목록을 못 받아도 「무드 없음」으로 돈다 */ });
  mb.onchange = async () => {
    try {
      await put(`/api/projects/${enc}/persona`, { mbti: mb.value });
      await loadProject(S.slug); render();
    } catch (e) { alert(e.message); }
  };
  /* ★ 무드를 바꾸면 **이 프로젝트가** 그 무드가 된다 — 다른 유형을 하나 더 내려면
   *   폴더가 따로 있어야 한다. 그냥 고르개만 돌리고 대본을 다시 뽑으면 앞 유형의
   *   대본이 사라진다. 그래서 「하나 더」를 무드 바로 옆에 둔다. */
  const mb2 = document.createElement("select");
  const mb2n = document.createElement("option");
  mb2n.value = ""; mb2n.textContent = "— 다른 유형으로 하나 더 —";
  mb2.appendChild(mb2n);
  mb2.disabled = !!S.cfg?.readonly;
  api("/api/persona").then(({ order, moods }) => {
    order.filter((k) => k !== (p.meta.mbti || "")).forEach((k) => {
      const o = document.createElement("option");
      o.value = k; o.textContent = `${k} · ${moods[k]}`;
      mb2.appendChild(o);
    });
  }).catch(() => { /* 목록이 없어도 무드 고르개는 돈다 */ });
  mb2.onchange = async () => {
    if (!mb2.value) return;
    const who = mb2.value;
    mb2.value = "";
    // 줄바꿈은 배열로 잇는다 — 이 파일을 스크립트로 고칠 때 escape 가 벗겨져
    // 문자열이 통째로 깨진 적이 있다(위 runGroup 주석과 같은 이유).
    const ask = [`이 장을 ${who} 로도 만듭니다.`, "",
      "원고와 구조는 이 장에 한 벌뿐이라 그대로 씁니다 —",
      "01_대본 밑에 유형 폴더가 하나 열릴 뿐이고, 크레딧은 대본부터 듭니다."];
    if (!confirm(ask.join(String.fromCharCode(10)))) return;
    try {
      const r = await post(`/api/projects/${enc}/fork`, { mbti: who });
      await loadProject(r.slug); render();      // 같은 장, 유형 폴더만 갈렸다
    } catch (e) { alert(e.message); }
  };

  mc.appendChild(row(el("span", null, "형식"), fmt,
                     el("span", null, "무드"), mb, mb2));
  mc.appendChild(el("div", "hint",
    "무드는 어조만 바꿉니다 — 소재·고유명사·수치는 재료에 있는 것만 씁니다. "
    + "대본·후크·자막·올릴글이 모두 이 톤으로 나오니 「대본」 을 뽑기 전에 정하세요."));
  m.appendChild(mc);

  /* ── 1 · 재료 ─────────────────────────────────────────────────────── */
  {
    const c = stepCard("source", 1,
      "조판된 책 PDF 는 쪽번호·머리글이 본문 한가운데 섞입니다. 걷어낸 뒤 고치세요.");
    c.appendChild(runRow("source", "다시 추출"));
    const ta = document.createElement("textarea");
    ta.rows = 12; ta.value = "불러오는 중…";
    ta.placeholder = "「다시 추출」 을 누르면 원본에서 글자를 뽑아 여기 채웁니다.";
    api(`/api/projects/${enc}/markdown`).then((t) => { ta.value = t || ""; })
      .catch(() => { ta.value = ""; });
    c.appendChild(ta);
    c.appendChild(row(saveBtn(`/api/projects/${enc}/markdown`, ta)));
    m.appendChild(c);
  }

  /* ── 2 · 원고 ─────────────────────────────────────────────────────── */
  {
    const dr = p.draft;
    const c = stepCard("draft", 2,
      "절(h2)을 복원하고, 수치·연표·비교를 표로, 추세·대비를 도해 골격으로 세웁니다.");
    if (dr) {
      c.appendChild(row(
        el("span", "pill", `절 ${dr.sections}개`),
        el("span", "pill" + (dr.tables ? " ok" : " warn"), `표 ${dr.tables}개`),
        el("span", "pill", `골격 ${dr.skeletons}개`),
        el("span", "pill", `${(dr.chars || 0).toLocaleString()}자`),
        dr.cost_usd ? el("span", "pill", `$${dr.cost_usd.toFixed(2)}`) : null,
      ));
      (dr.warnings || []).forEach((w) => c.appendChild(el("div", "note", w)));
    }
    c.appendChild(runRow("draft", "원고 다시 짜기"));
    const ta = document.createElement("textarea");
    ta.rows = 14; ta.spellcheck = false; ta.value = "불러오는 중…";
    api(`/api/projects/${enc}/draft`).then((t) => { ta.value = t || "(아직 없음)"; })
      .catch(() => { ta.value = "(아직 없음)"; });
    c.appendChild(el("div", "hint",
      "소제목이 본문에 붙어 왔으면 여기서 떼세요. 고친 뒤 「구조」를 다시 돌려야 표가 갱신됩니다."));
    c.appendChild(ta);
    c.appendChild(row(saveBtn(`/api/projects/${enc}/draft`, ta)));
    m.appendChild(c);
  }

  /* ── 3 · 구조 (무료) ──────────────────────────────────────────────── */
  {
    const c = stepCard("structure", 3,
      "원고의 태그를 읽어 절·블록·표·골격·사실을 목록으로 만듭니다. "
      + "모델을 부르지 않으니 크레딧이 들지 않습니다 — 몇 번이든 돌려도 됩니다.");
    c.appendChild(runRow("structure", "구조 다시 뽑기"));
    const pre = Object.assign(el("pre", "out"), { textContent: "불러오는 중…" });
    api(`/api/projects/${enc}/structure`).then((j) => {
      const facts = (j && j.facts) || [];
      pre.textContent = facts.length
        ? facts.map((f) => `${f.id}  ${f.claim || f.text || ""}`
          + (f.evidence ? `\n      근거: ${f.evidence}` : "")).join("\n")
        : "(아직 없음)\n\n사실이 하나도 없으면 대본이 근거 없이 씁니다 — 원고에 표가 있는지 보세요.";
    }).catch(() => { pre.textContent = "(아직 없음)"; });
    c.appendChild(el("div", "hint", "사실 — 대본이 여기서 골라 씁니다."));
    c.appendChild(pre);
    m.appendChild(c);
  }

  /* ── 4 · 대본 ─────────────────────────────────────────────────────── */
  {
    const c = stepCard("script", 4,
      "씬 수는 재료가 정합니다 — 사실 하나에 씬 하나입니다. "
      + "씬 하나가 아스트라 2분 30초이므로 상한만 둡니다.");
    const bud = d.budget || {};
    c.appendChild(row(
      el("span", "pill" + (bud.chars > bud.limit ? " warn" : " ok"),
        `${bud.chars ?? 0} / ${bud.limit ?? 0}자`),
      el("span", "pill", `추정 ${bud.est_sec ?? 0}초`),
      el("span", "pill", `${(d.scenes || []).length}씬`),
      d.cost_usd ? el("span", "pill", `$${d.cost_usd.toFixed(2)}`) : null,
    ));
    (d.warnings || []).forEach((w) => c.appendChild(el("div", "note", w)));
    c.appendChild(runRow("script", "대본 다시 쓰기", { fmt: fmt.value }));
    if (d.hook_fixed?.line1) {
      c.appendChild(el("div", "hint",
        `고정 후크 「${d.hook_fixed.line1} / ${d.hook_fixed.line2 || ""}」`
        + (d.hook_fixed.mark ? ` · 강조 「${d.hook_fixed.mark}」` : " · 둘째 줄 전체 강조")));
    }
    m.appendChild(c);
  }

  /* ── 5 · 씬 — 자막·발음·판정을 한자리에서 ────────────────────────── */
  if (d.scenes && d.scenes.length) {
    const rc = card("다듬기",
      "대본을 새로 쓰지 않고 손질만 합니다. 검증은 고치지 않고 대안만 냅니다.");
    rc.id = "sec-scenes";
    const busy = (btn, label, fn) => {
      btn.type = "button";
      btn.disabled = !!S.cfg?.readonly;
      btn.onclick = async () => {
        const t = btn.textContent;
        btn.disabled = true; btn.textContent = label;
        try { await fn(); await loadProject(S.slug); render(); }
        catch (e) { alert(e.message); btn.disabled = false; btn.textContent = t; }
      };
      return btn;
    };
    const u = `/api/projects/${enc}`;
    rc.appendChild(row(
      busy(el("button", "btn primary", "전체 사실검증"), "검증 중…",
        () => post(`${u}/verify`)),
      busy(el("button", "btn", "AI 후크 다시"), "후크 다시…",
        () => post(`${u}/hooks/regen`)),
      busy(el("button", "btn", "AI 자막 다시"), "자막 다시…",
        () => post(`${u}/captions/regen`)),
    ));
    const ng = Object.entries(d.verify || {}).filter(([, v]) => !v.ok);
    const seen = Object.keys(d.verify || {}).length;
    rc.appendChild(el("div", "hint", seen
      ? (ng.length
        ? `검증한 ${seen}씬 중 ${ng.length}씬이 NG 입니다 — 씬 ${ng.map(([k]) => k).join(", ")}.`
        : `검증한 ${seen}씬 모두 근거와 맞습니다.`)
      : "아직 검증하지 않았습니다. 자막을 고친 뒤에는 다시 돌리세요."));
    rc.appendChild(el("div", "hint",
      "「AI 자막 다시」는 씬 전체를 한 번에 다시 씁니다 — 하나씩 고치면 이웃이 "
      + "어색해져 끝나지 않습니다. 바뀐 씬은 음성이 낡으므로 「음성」을 다시 돌리세요."));
    m.appendChild(rc);

    // 씬 목록은 **하나뿐이다.** 자막·발음·근거·판정을 한 씬 카드 안에서 본다.
    m.appendChild(sceneEditor(d, { showSource: true, showNarration: true, showVerify: true }));
  }

  /* ── 6 · 발음 ─────────────────────────────────────────────────────── */
  {
    const c = stepCard("speech", 5,
      "괄호를 걷고, 문장 끝을 다듬고, 숫자와 영문을 소리대로. 크레딧이 들지 않습니다. "
      + "자막은 그대로 두고 읽는 글자만 바꿉니다.");
    c.appendChild(runRow("speech", "규칙 다시 적용"));
    const ta = document.createElement("textarea");
    ta.rows = 8; ta.value = "불러오는 중…";
    api(`/api/projects/${enc}/pron`).then((t) => { ta.value = t; })
      .catch(() => { ta.value = ""; });
    const save = el("button", "btn primary", "저장하고 적용");
    save.type = "button";
    save.disabled = !!S.cfg?.readonly;
    save.onclick = async () => {
      save.disabled = true;
      try {
        await put(`/api/projects/${enc}/pron`, ta.value, true);
        await loadProject(S.slug); render();
      } catch (e) { alert(e.message); } finally { save.disabled = false; }
    };
    c.appendChild(el("div", "hint",
      "발음교정표 — 규칙이 못 잡는 것만 적습니다. 적힌 씬은 규칙을 건너뛰고 적힌 대로 읽습니다."));
    c.appendChild(ta);
    c.appendChild(row(save));
    m.appendChild(c);
  }

  /* ── 7 · 음성 ─────────────────────────────────────────────────────── */
  {
    const c = stepCard("tts", 6,
      `엔진 ${S.cfg?.tts?.engine || "?"} · 목소리 ${d.voice || "F2"} · ${d.speed || 1.2}배속`
      + " — 발음이 그대로인 씬은 다시 굽지 않습니다.");
    const tot = d.audio_total_sec || 0;
    const tgt = d.seconds || 22;
    if (tot) {
      c.appendChild(row(el("span", "pill" + (tot > tgt + 2 ? " warn" : " ok"),
        `합계 ${tot.toFixed(1)}초 / 목표 ${tgt}초`)));
    }
    const f = el("button", "btn", "전부 다시 굽기");
    f.type = "button";
    f.disabled = !!S.cfg?.readonly;
    f.onclick = () => runStage("tts", { force: true });
    c.appendChild(runRow("tts", "음성 만들기", null, f));
    m.appendChild(c);
  }

  /* ── 8 · 자막 — 대본에서 파생된 결과다 ───────────────────────────── */
  {
    const c = stepCard("subs", 7,
      "자막은 따로 쓰는 글이 아닙니다 — 위 씬의 「자막(= 말)」을 읽을 수 있는 조각으로 "
      + "쪼개고, 실측 음성 길이를 글자 수 비율로 나눈 결과입니다 — 조각 하나가 한 컷입니다.");
    c.appendChild(runRow("subs", "자막 다시 나누기"));
    const pre = Object.assign(el("pre", "out"), { textContent: "불러오는 중…" });
    api(`/api/projects/${enc}/srt`)
      .then((t) => { pre.textContent = t || "(아직 없음)"; })
      .catch(() => { pre.textContent = "(아직 없음)"; });
    c.appendChild(pre);
    m.appendChild(c);
  }

  /* ── 9 · 장면 지시 ────────────────────────────────────────────────── */
  {
    const c = stepCard("artspec", 8,
      "장면 안에 글자를 넣지 않습니다. 위아래 띠는 비워 둡니다. "
      + "동작은 한 방향으로 한 번만 — 되풀이하면 화면이 안절부절못합니다.");
    c.appendChild(runRow("artspec", "지시 만들기"));
    const pre = Object.assign(el("pre", "out"), { textContent: "불러오는 중…" });
    api(`/api/projects/${enc}/artspec`)
      .then((j) => {
        if (!j || !j.scenes || !j.scenes.length) { pre.textContent = "(아직 없음)"; return; }
        pre.textContent = j.scenes.map((r) => [
          `씬 ${r.no} (${r.role || "body"}) · 화면 ${r.scene_sec ?? r.sec}초 · 동작은 ${r.sec}초 안에`
            + (r.canvas_h ? ` · 두루마리 ${r.canvas_h}px (${(r.cells || []).length}칸)` : ""),
          `  주장 : ${r.claim || "(없음)"}`,
          r.fact ? `  사실 : ${r.fact}` : "",
          `  장면 : ${r.stage}`,
          `  배치 : ${r.layout}`,
          `  변동 : ${r.change || ""}`,
          ...(r.cells || []).map((x) => `  칸${x.no} [${x.fill || ""}] ${x.what || ""}`),
          ...(r.beats || []).map((x) => `  박자 ${x.at}~${x.until}초 : ${x.what}`),
          (r.camera || []).length
            ? "  카메라 : " + r.camera.map((x) => `${x.at}초 칸${x.cell}(${x.move})`).join(" → ")
            : "",
          r.support ? `  거듦 : ${r.support}` : "",
          r.palette_note ? `  색   : ${r.palette_note}` : "",
        ].filter(Boolean).join("\n")).join("\n\n");
        (j.warnings || []).forEach((w) => c.appendChild(el("div", "note", w)));
      })
      .catch(() => { pre.textContent = "(아직 없음)"; });
    c.appendChild(pre);
    m.appendChild(c);
  }
};

/* 장면 제작 — 아스트라 */
PAGES.art = (m) => {
  const p = S.proj;
  m.appendChild(head("장면 제작",
    "아스트라가 씬마다 움직이는 장면을 코드로 씁니다. 씬당 약 2분 30초, 가장 비싼 자리입니다."));

  const c = card("장면",
    "지시가 바뀐 씬만 다시 받습니다. 여기서 아끼는 것이 아스트라 한도를 아끼는 것입니다.");
  const f = el("button", "btn money", "전부 다시 받기");
  f.type = "button";
  f.disabled = !!S.cfg?.readonly;
  f.onclick = () => runStage("art", { force: true });
  const ph = el("button", "btn", "자리표시로 채우기 (무료)");
  ph.type = "button";
  ph.disabled = !!S.cfg?.readonly;
  ph.title = "장면값을 쓰지 않고 컴포지션·빌드를 시험합니다";
  ph.onclick = async () => {
    ph.disabled = true;
    try {
      await post(`/api/projects/${encodeURIComponent(S.slug)}/placeholder`);
      await loadProject(S.slug);
    } catch (e) { alert(e.message); } finally { ph.disabled = false; }
  };
  c.appendChild(row(runBtn("art", "장면 받기"), f, ph));

  const art = p.art || {};
  const strip = el("div", "row");
  (p.script?.scenes || []).forEach((s) => {
    const name = art[s.no];
    const cell = el("div", "artcell");
    const t = el("div", "thumb");
    if (name) {
      t.style.backgroundImage =
        `url('/api/projects/${encodeURIComponent(S.slug)}/art/${s.no}?t=${Date.now()}')`;
    }
    cell.appendChild(t);
    cell.appendChild(el("div", "artlabel",
      name ? (/\.svg$/i.test(name) ? `씬 ${s.no} · 움직임` : `씬 ${s.no} · 정지`)
        : `씬 ${s.no} · 없음`));
    const one = el("button", "btn sm money", "이 씬만");
    one.type = "button";
    one.disabled = !!S.cfg?.readonly;
    one.onclick = () => runStage("art", { only: [s.no], force: true });
    cell.appendChild(one);
    strip.appendChild(cell);
  });
  c.appendChild(strip);
  m.appendChild(c);
};

/* 컴포지션 — **굽기 전에 화면을 보고 승인하는 자리** */
PAGES.compose = (m) => {
  const p = S.proj;
  m.appendChild(head("컴포지션 · 미리보기",
    "굽기 전에 여기서 그대로 재생해 보세요. 렌더는 한 편에 1분 걸립니다."));

  const c = card("굽기", "타이밍을 계산해 렌더할 HTML 을 만듭니다. 크레딧을 쓰지 않습니다.");
  c.appendChild(row(runBtn("compose", "컴포지션 굽기")));
  m.appendChild(c);

  const st = stageOf("compose");
  if (!st || st.state !== "done") {
    m.appendChild(el("div", "note", "아직 컴포지션이 없습니다. 위 단추를 먼저 누르세요."));
    return;
  }

  // ★ 플레이어는 컴포지션 폴더를 **그대로** 읽는다. mp4 가 아니라 HTML 이라
  //   렌더를 기다리지 않고 바로 볼 수 있다 — 이것이 승인 게이트의 값이다.
  const pv = card("이 화면이 그대로 구워집니다",
    "재생해서 확인한 뒤 아래 「이 화면으로 빌드」를 누르세요. 마음에 안 들면 "
    + "「대본」이나 「장면 제작」으로 돌아가면 됩니다.");
  const wrap = el("div", "vwrap");
  const box = el("div", "player");
  if (window.customElements && customElements.get("hyperframes-player")) {
    const pl = document.createElement("hyperframes-player");
    pl.setAttribute("src", `/api/projects/${encodeURIComponent(S.slug)}/preview/index.html`);
    pl.setAttribute("controls", "");
    box.appendChild(pl);
  } else {
    // 플레이어가 없으면 iframe 으로라도 보여 준다 — 못 보는 것보다 낫다
    const f = document.createElement("iframe");
    f.src = `/api/projects/${encodeURIComponent(S.slug)}/preview/index.html`;
    f.title = "컴포지션 미리보기";
    box.appendChild(f);
    pv.appendChild(el("div", "note",
      "플레이어를 못 불러와 정지 화면으로 보여 줍니다. setup.bat 을 다시 돌려 보세요."));
  }
  wrap.appendChild(box);

  const side = el("div", "grow");
  const info = p.script || {};
  // 움직이는 장면 수는 **파일 확장자로 센다** — 별도 상태를 안 들고 있으면
  // 화면이 거짓말을 할 일이 없다(전에 없는 필드를 읽어 늘 0 으로 떴다).
  const art = p.art || {};
  const live = Object.values(art).filter((n) => /\.svg$/i.test(n)).length;
  const nScenes = (info.scenes || []).length;
  side.appendChild(row(
    el("span", "pill", `${nScenes}씬`),
    el("span", "pill", `${(info.total_sec || 0).toFixed(1)}초`),
    el("span", "pill" + (live === nScenes && live > 0 ? " ok" : live ? " warn" : " bad"),
      `움직이는 장면 ${live}/${nScenes}`),
  ));
  const go = runBtn("build", "이 화면으로 빌드");
  side.appendChild(row(go));
  side.appendChild(el("div", "hint",
    "빌드는 쌓입니다 — 덮어쓰지 않으니 여러 판본을 비교할 수 있습니다."));
  wrap.appendChild(side);
  pv.appendChild(wrap);
  m.appendChild(pv);
};

/* 빌드 */
PAGES.build = (m) => {
  const p = S.proj;
  m.appendChild(head("빌드", "헤드리스 Chrome 이 프레임을 한 칸씩 캡처합니다. 같은 입력이면 같은 영상이 나옵니다."));
  const c = card("렌더", "린트를 먼저 통과시킵니다. 빌드는 쌓이고 덮어쓰지 않습니다.");
  c.appendChild(row(runBtn("build", "영상 만들기")));
  m.appendChild(c);

  if (p.build) {
    const c2 = card(p.build.name, `${p.build.info?.size_mb ?? "?"} MB · ${(p.build.info?.total_sec ?? 0).toFixed(1)}초`);
    const w = el("div", "vwrap");
    const v = document.createElement("video");
    v.controls = true; v.preload = "metadata"; v.src = `/api/projects/${encodeURIComponent(S.slug)}/video?t=${Date.now()}`;
    w.appendChild(v);
    const open = el("button", "btn", "폴더 열기");
    open.type = "button";
    open.onclick = () => post(`/api/projects/${encodeURIComponent(S.slug)}/open`).catch((e) => alert(e.message));
    const side = el("div"); side.appendChild(open);
    w.appendChild(side);
    c2.appendChild(w);
    m.appendChild(c2);
  }
};

/* 결과 */
PAGES.result = (m) => {
  const p = S.proj;
  m.appendChild(head("결과", "올릴 글까지 만들고 멈춥니다. 올리는 것은 사람이 합니다."));
  const c = card("유튜브 쇼츠 메타",
    "제목·설명·태그·고정댓글. 설명의 {원본링크} 를 롱폼 주소로 바꿔 넣으세요.");
  const gen = runBtn("result", "메타 생성");

  /* 복사가 없으면 사람이 pre 를 드래그해서 긁는다 — 그러다 줄이 빠진다. */
  const copy = el("button", "btn", "복사");
  copy.type = "button";
  copy.disabled = !p.build?.youtube;
  copy.onclick = async () => {
    try {
      await navigator.clipboard.writeText(p.build.youtube);
      copy.textContent = "복사됨";
      setTimeout(() => { copy.textContent = "복사"; }, 1500);
    } catch (_) { alert("복사하지 못했습니다. 아래 글을 직접 긁어 주세요."); }
  };
  c.appendChild(row(gen, copy));

  if (p.build?.youtube) {
    c.appendChild(Object.assign(el("pre", "out"), { textContent: p.build.youtube }));
  } else {
    c.appendChild(el("div", "hint",
      "빌드가 끝난 뒤에 누르세요 — 올릴 글은 완성 폴더 안에 같이 놓입니다."));
  }
  m.appendChild(c);

  /* ── 현황판 — 장 × MBTI ────────────────────────────────────────────
     ★ 진실은 **작업물 폴더**다. 따로 장부를 두지 않는다 — 장부와 실제가 갈리면
       실제가 옳고 장부가 거짓말인데, 그때 사람은 장부를 믿는다.
     ★ 「했다/안 했다」 두 값으로 두지 않는다. 한 칸을 다시 만들 수 있고 빌드는
       v01·v02 로 쌓이므로, 회차가 보여야 어느 판을 올렸는지 안다. */
  const bc = card("장 × MBTI",
    "같은 장을 유형마다 한 편씩 냅니다. 칸을 누르면 그 작업으로 갑니다.");
  const wrap = el("div", "boardwrap");
  wrap.appendChild(el("div", "hint", "불러오는 중…"));
  bc.appendChild(wrap);
  m.appendChild(bc);

  api("/api/board").then(({ order, moods, chapters }) => {
    if (!chapters.length) {
      wrap.replaceChildren(el("div", "hint",
        "아직 무드를 정한 장이 없습니다. 「대본 만들기」의 무드를 고르면 여기 올라옵니다."));
      return;
    }
    /* ★ **열여섯 유형을 다 세운다.** 전에는 이미 만든 유형의 열만 그렸는데,
     *   이 판에서 알아야 하는 것은 「무엇을 했나」가 아니라 **「무엇이 남았나」**다.
     *   한 것만 보이면 남은 것을 세려고 사람이 머릿속에서 열여섯을 빼야 한다. */
    const t = el("table", "board");
    const thead = el("thead");
    const hr = el("tr");
    hr.appendChild(el("th", "ch", "장"));
    order.forEach((k, ix) => {
      const th = el("th");
      th.appendChild(el("span", "ord", String(ix + 1).padStart(2, "0")));
      th.appendChild(el("span", null, k));
      th.title = `${ix + 1}리스트 · ${moods[k] || ""}`;   // 쇼츠공방 I 의 「N리스트」
      hr.appendChild(th);
    });
    thead.appendChild(hr); t.appendChild(thead);

    const tb = el("tbody");
    chapters.forEach((c) => {
      const done = order.filter((k) => c.cells[k] && c.cells[k].state === "built").length;
      const tr = el("tr");
      const th = el("th", "ch");
      th.appendChild(el("span", "chname", c.title || `${c.chapter}장`));
      th.appendChild(el("span", "chdone" + (done === 16 ? " full" : ""), `${done}/16`));
      const matName = { structure: "구조", draft: "원고", source: "재료", empty: "—" }[c.material];
      th.appendChild(el("span", "chmat", matName));
      tr.appendChild(th);

      // 한 장이 한 폴더다 — 빈 칸을 여는 것은 그 장 안에 유형 폴더를 만드는 일이다.

      order.forEach((k) => {
        const cell = c.cells[k];
        const td = el("td");
        if (!cell) {
          const b = el("button", "cellbox none", "+");
          b.type = "button";
          b.title = `${c.title} · ${k} 로 하나 더 만들기 — 원고·구조를 물려받아 크레딧이 들지 않습니다`;
          b.disabled = !!S.cfg?.readonly;
          b.onclick = async () => {
            if (!confirm(`${c.title} 을 ${k} 로 만듭니다. 크레딧이 들지 않습니다.`)) return;
            b.disabled = true;
            try {
              const r = await post(
                `/api/projects/${encodeURIComponent(c.slug)}/fork`, { mbti: k });
              S.slug = r.slug; await loadProject(r.slug); go("plan");
            } catch (e) { alert(e.message); b.disabled = false; }
          };
          td.appendChild(b);
          tr.appendChild(td);
          return;
        }
        const label = cell.state === "built"
          ? (cell.builds > 1 ? `✓${cell.builds}` : "✓")
          : cell.state === "script" ? `${cell.scenes}씬`
          : cell.state === "structure" ? "구조"
          : cell.state === "draft" ? "원고"
          : cell.state === "source" ? "재료" : "빈";
        const b = el("button", "cellbox " + cell.state, label);
        b.type = "button";
        b.title = `${cell.slug} / ${cell.tag}${cell.build ? " · " + cell.build : ""}`;
        b.onclick = async () => {
          S.slug = cell.slug;
          // 다른 유형을 보고 있을 수 있다 — 폴더를 그 유형으로 갈아탄 뒤 연다
          try { await put(`/api/projects/${encodeURIComponent(cell.slug)}/persona`, { mbti: k }); }
          catch (e) { /* 갈아타기가 막혀도 장은 열어 준다 */ }
          await loadProject(cell.slug); go("plan");
        };
        td.appendChild(b);
        tr.appendChild(td);
      });
      tb.appendChild(tr);
    });
    t.appendChild(tb);
    wrap.replaceChildren(t);
  }).catch((e) => {
    wrap.replaceChildren(el("div", "note bad", e.message));
  });
};

/* ★ 화면 함수는 async 다 — 안에서 fetch 를 기다린다. 그 사이에 다른 render 가
 *   들어오면 **두 화면이 한 지면에 겹쳐 쌓인다**(실제로 홈의 목록과 재료의 카드가
 *   같이 떴다). 그래서 세대 번호를 두고, 기다리는 동안 세대가 바뀌면 버린다.
 *   그리고 지면에 바로 붙이지 않고 조각에 그린 뒤 **한 번에 갈아 끼운다.** */
let RENDER_GEN = 0;

async function render() {
  const gen = ++RENDER_GEN;
  if (S.page !== "home" && !S.proj) S.page = "home";
  const frag = document.createElement("div");
  try {
    await (PAGES[S.page] || PAGES.home)(frag);
  } catch (e) {
    frag.appendChild(el("div", "note bad", e.message));
  }
  if (gen !== RENDER_GEN) return;          // 늦게 끝난 화면은 버린다
  const m = $("#main");
  m.replaceChildren(...frag.childNodes);
  if (S.cfg?.readonly) {
    const b = el("div", "note");
    b.textContent = "보기 전용 — 만드는 단계는 이 도구를 띄운 PC 주인의 구독으로 돕니다. "
      + "직접 만들려면 이 저장소를 받아 setup.bat 을 실행하세요.";
    m.insertBefore(b, m.firstChild);
  }
}

/* ── 연결 상태 칩 ─────────────────────────────────────────────────────── */
async function chips() {
  const set = (sel, ok, text, title) => {
    const b = $(sel);
    b.classList.toggle("ok", !!ok);
    b.classList.toggle("bad", !ok);
    b.querySelector(".conn-text").textContent = text;
    b.title = title || text;
  };
  try {
    const s = await api("/api/llm/status");
    const ok = s.installed && s.credentials;
    set("#conn-llm", ok, ok ? "Claude 로그인됨" : "Claude 로그인 필요",
      ok ? s.path : "터미널에서 claude 를 한 번 실행해 로그인하세요.");
  } catch (_) { set("#conn-llm", false, "Claude 확인 실패"); }
  try {
    const s = await api("/api/imagegen/status");
    set("#conn-img", s.ok, s.ok ? "ChatGPT 로그인됨" : "ChatGPT 로그인 필요",
      `${s.message}\n${s.how}`);
    $("#conn-img").onclick = () => alert(`${s.message}\n\n${s.how}`);
  } catch (_) { set("#conn-img", false, "ChatGPT 확인 실패"); }
}

/* ── 시작 ─────────────────────────────────────────────────────────────── */
$("#rail-toggle").onclick = () => railToggle();

/* 레일 접기/펴기. 단추 설명도 같이 바꾼다 — 접힌 채로 「접기」라고 적혀 있으면
   무엇을 누르는지 알 수 없다. */
function railToggle() {
  const off = document.body.classList.toggle("rail-off");
  const b = $("#rail-toggle");
  if (b) b.title = off ? "레일 펴기 (Ctrl+B)" : "레일 접기 (Ctrl+B)";
}

/* 글을 쓰는 칸에서는 Ctrl+B 를 가로채지 않는다. 원고·자막 textarea 에서
   굵게 하려고 누른 것이 레일을 접어 버렸다 — 그게 「가끔 안 펴진다」의 정체다. */
function typing(t) {
  const n = (t && t.tagName || "").toLowerCase();
  return n === "textarea" || n === "input" || n === "select" || (t && t.isContentEditable);
}
$("#dock-toggle").onclick = (e) => {
  if (e.target.id === "dock-stop") return;
  document.body.classList.toggle("dock-min");
};
$("#dock-stop").onclick = async (e) => {
  e.stopPropagation();
  if (S.job) { try { await post(`/api/jobs/${S.job.job_id}/cancel`); } catch (_) { /* 이미 끝났으면 무시 */ } }
};
document.addEventListener("keydown", (e) => {
  if (e.ctrlKey && e.key.toLowerCase() === "b" && !typing(e.target)) { e.preventDefault(); railToggle(); }
  if (e.ctrlKey && e.key.toLowerCase() === "j" && !typing(e.target)) { e.preventDefault(); document.body.classList.toggle("dock-min"); }
});

(async function boot() {
  try {
    S.cfg = await api("/api/config");
    S.table = await api("/api/stages");
  } catch (e) { $("#main").innerHTML = `<div class="note bad">서버에 붙지 못했습니다: ${esc(e.message)}</div>`; return; }
  drawRail();
  chips();
  const rows = await api("/api/projects").catch(() => []);
  if (rows.length === 1) {
    // 프로젝트가 하나면 바로 그것을 연다. **page 를 먼저 정하고** 한 번만 그린다 —
    // render() 다음에 go() 를 부르면 두 번 그려지고 위 세대 규칙에 걸린다.
    S.slug = rows[0].slug;
    S.page = "plan";
    await loadProject(S.slug);
  } else {
    render();
  }
})();
