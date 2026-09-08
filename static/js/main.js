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
  tab: {},           // 화면별로 마지막에 보던 탭
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
  // 탭이 여럿인 화면은 개수를 알려 준다 — 안에 더 있다는 표시
  if (sc.stages.length > 1) {
    b.appendChild(Object.assign(el("span", "tabn", String(sc.stages.length)),
      { title: `${sc.stages.length}개 탭` }));
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

  const nc = card("새로 만들기", "장(章) 파일 하나를 넣으세요. PDF · DOCX · MD · TXT · HTML.");
  const r1 = el("div", "row");
  const file = Object.assign(document.createElement("input"), { type: "file", accept: ".pdf,.docx,.md,.txt,.html,.htm" });
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
  const mk = el("button", "btn primary", "만들기");
  mk.type = "button";
  mk.onclick = async () => {
    if (!file.files[0]) { alert("파일을 고르세요."); return; }
    const fd = new FormData();
    fd.append("file", file.files[0]);
    fd.append("title", title.value);
    fd.append("fmt", fmt.value);
    mk.disabled = true;
    try {
      const r = await api("/api/projects", { method: "POST", body: fd });
      S.slug = r.slug; await loadProject(r.slug); go("source");
    } catch (e) { alert(e.message); } finally { mk.disabled = false; }
  };
  r1.append(file, title, el("span", null, "형식"), fmt, mk);
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
    b.onclick = async () => { S.slug = p.slug; await loadProject(p.slug); go("source"); };
    list.appendChild(b);
  });
  lc.appendChild(list);
  m.appendChild(lc);
};

/* 재료 — 원본 → source.md, 사람이 고칠 수 있다 */
PAGES.source = async (m) => {
  const p = S.proj;
  const enc = encodeURIComponent(S.slug);
  m.appendChild(head("재료",
    "줄글 한 덩어리를 바로 대본에 넘기면 대본이 첫 단락만 잡고 뒷장을 버립니다. "
    + "여기서 소제목을 복원하고 수치를 표로 세워 둡니다."));

  m.appendChild(tabs("source", ["source", "draft", "structure"], {

    /* 1 추출 — 원본 → source.md */
    source: (b) => {
      const c = card("원본",
        `${p.meta.file || "(없음)"} · 형식 ${p.meta.format === "listicle" ? "목록형" : "서사형"}`
        + ` · 목소리 ${p.meta.voice || "F2"}`);
      c.appendChild(row(runBtn("source", "다시 추출")));
      b.appendChild(c);

      const c2 = card("source.md",
        "조판된 책 PDF 는 쪽번호·머리글이 본문 한가운데 섞입니다. 걷어낸 뒤 고치세요.");
      const ta = document.createElement("textarea");
      ta.rows = 18;
      ta.value = "불러오는 중…";
      api(`/api/projects/${enc}/markdown`).then((t) => { ta.value = t; });
      c2.appendChild(ta);
      c2.appendChild(row(saveBtn(`/api/projects/${enc}/markdown`, ta)));
      b.appendChild(c2);
    },

    /* 2 원고 — 소제목 복원 + 수치를 표로 */
    draft: (b) => {
      const dr = p.draft;
      const c = card("원고 HTML",
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
      c.appendChild(row(runBtn("draft", "원고 다시 짜기")));
      b.appendChild(c);

      const c2 = card("고치는 자리",
        "소제목이 본문에 붙어 왔으면 여기서 떼세요. 고친 뒤 「구조」를 다시 돌려야 표가 갱신됩니다.");
      const ta = document.createElement("textarea");
      ta.rows = 22;
      ta.spellcheck = false;
      ta.value = "불러오는 중…";
      api(`/api/projects/${enc}/draft`).then((t) => { ta.value = t || "(아직 없음)"; });
      c2.appendChild(ta);
      c2.appendChild(row(saveBtn(`/api/projects/${enc}/draft`, ta)));
      b.appendChild(c2);
    },

    /* 3 구조 — 파서. 크레딧 0 */
    structure: (b) => {
      const c = card("구조 뽑기",
        "원고의 태그를 읽어 절·블록·표·골격·사실을 목록으로 만듭니다. "
        + "모델을 부르지 않으니 **크레딧이 들지 않습니다** — 몇 번이든 돌려도 됩니다.");
      c.appendChild(row(runBtn("structure", "구조 다시 뽑기")));
      b.appendChild(c);

      const c2 = card("사실 — 대본이 여기서 골라 씁니다");
      const pre = Object.assign(el("pre", "out"), { textContent: "불러오는 중…" });
      api(`/api/projects/${enc}/structure`)
        .then((j) => {
          if (!j || !(j.facts || []).length) {
            pre.textContent = "(아직 없음)\n\n사실이 하나도 없으면 대본이 근거 없이 씁니다 — "
              + "원고에 표가 있는지 보세요.";
            (j?.warnings || []).forEach((w) => c2.appendChild(el("div", "note", w)));
            return;
          }
          const lines = [];
          lines.push(`절 ${(j.sections || []).length}개 · 블록 ${(j.blocks || []).length}개 · `
            + `표 ${(j.tables || []).length}개 · 골격 ${(j.skeletons || []).length}개 · `
            + `사실 ${(j.facts || []).length}개`);
          lines.push("");
          j.facts.forEach((f) => {
            lines.push(`${f.id.padEnd(5)}[${f.kind}] ${f.label} = ${f.value}${f.unit}`
              + (f.year ? ` (${f.year}년)` : ""));
            if (f.quote) lines.push(`     근거: ${f.quote.slice(0, 80)}`);
          });
          if ((j.tables || []).length) {
            lines.push("", "── 표 ──");
            j.tables.forEach((t) => {
              lines.push(`${t.id}  ${(t.head || []).join(" / ")}`);
              (t.rows || []).forEach((r) => lines.push(`     ${r.join(" · ")}`));
            });
          }
          if ((j.skeletons || []).length) {
            lines.push("", "── 도해 골격 ──");
            j.skeletons.forEach((k) => lines.push(`${k.id}  [${k.kind}] ${k.aria || ""}`));
          }
          pre.textContent = lines.join("\n");
          (j.warnings || []).forEach((w) => c2.appendChild(el("div", "note", w)));
        })
        .catch(() => { pre.textContent = "(아직 없음)"; });
      c2.appendChild(pre);
      b.appendChild(c2);
    },
  }));
};

/* 저장 단추 — 원본·원고 두 탭이 같은 부품을 쓴다 */
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
function sceneEditor(d, { showSource, showNarration } = {}) {
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

/* ══ 탭 부품 ══════════════════════════════════════════════════════════
   ★ **단계마다 화면을 따로 두지 않는다.** 대본·발음·음성·자막·장면지시는
     전부 「대본을 확정하는 일」이고, 오가며 고치는 것이 실제 작업이다.
     레일에 열 줄이 늘어서 있으면 무엇이 한 덩어리인지 안 보인다.
   ★ 탭을 옮겨도 **단계별 실행 단추는 그대로 있다** — 클릭 권한은 안 없어진다. */
function tabs(screenKey, stageKeys, bodies) {
  const cur = S.tab[screenKey] || stageKeys[0];
  const wrap = el("div", "tabwrap");

  const bar = el("div", "tabbar");
  stageKeys.forEach((k) => {
    const st = stageOf(k);
    if (!st) return;
    const b = el("button", "tab" + (k === cur ? " on" : "") + (st.stale ? " stale" : ""));
    b.type = "button";
    b.appendChild(el("span", null, st.name));
    if (st.costs) b.appendChild(Object.assign(el("span", "cost", "$"),
      { title: "크레딧을 씁니다" }));
    b.appendChild(el("span", "step-dot " + (st.state || "")));
    b.onclick = () => { S.tab[screenKey] = k; render(); };
    bar.appendChild(b);
  });
  wrap.appendChild(bar);

  const body = el("div", "tabbody");
  const fn = bodies[cur];
  if (fn) fn(body);
  wrap.appendChild(body);
  return wrap;
}

/* 대본 — 한 화면에 탭 다섯. 대본·발음·음성·자막·장면 지시 */
PAGES.script = (m) => {
  const p = S.proj, d = p.script || {};
  m.appendChild(head("대본",
    "대본을 확정하는 일 전부. 탭을 오가며 고치고, 각 탭에서 그 단계만 돌립니다."));

  m.appendChild(tabs("script", ["script", "speech", "tts", "subs", "artspec"], {

    script: (b) => {
      const c = card(d.title || "(아직 없음)");
      const bud = d.budget || {};
      c.appendChild(row(
        el("span", "pill" + (bud.chars > bud.limit ? " warn" : " ok"),
          `${bud.chars ?? 0} / ${bud.limit ?? 0}자`),
        el("span", "pill", `추정 ${bud.est_sec ?? 0}초`),
        el("span", "pill", `${(d.scenes || []).length}씬`),
        d.cost_usd ? el("span", "pill", `$${d.cost_usd.toFixed(2)}`) : null,
      ));
      (d.warnings || []).forEach((w) => c.appendChild(el("div", "note", w)));
      /* 형식만 고른다. 씬 수는 재료가 정한다. */
      const fmt = document.createElement("select");
      [["narrative", "서사형"], ["listicle", "목록형"]].forEach(([v, t]) => {
        const o = document.createElement("option"); o.value = v; o.textContent = t; fmt.appendChild(o);
      });
      fmt.value = d.format || p.meta.format || S.cfg?.shorts?.format || "narrative";
      const rb = runBtn("script", "대본 다시 쓰기");
      rb.onclick = () => runStage("script", { fmt: fmt.value });
      c.appendChild(row(el("span", null, "형식"), fmt, rb));
      c.appendChild(el("div", "hint",
        "씬 수는 재료가 정합니다 — 사실 하나에 씬 하나입니다. "
        + "씬 하나가 아스트라 2분 30초이므로 상한만 둡니다."));
      if (d.hook_fixed?.line1) {
        c.appendChild(el("div", "hint",
          `고정 후크 「${d.hook_fixed.line1} / ${d.hook_fixed.line2 || ""}」`
          + (d.hook_fixed.mark ? ` · 강조 「${d.hook_fixed.mark}」` : " · 둘째 줄 전체 강조")));
      }
      b.appendChild(c);
      if (d.scenes) b.appendChild(sceneEditor(d, { showSource: true }));
    },

    speech: (b) => {
      const c = card("규칙 다시 적용",
        "괄호를 걷고, 문장 끝을 하십시오체로, 숫자와 영문을 소리대로. 공짜입니다.");
      c.appendChild(row(runBtn("speech", "규칙 다시 적용")));
      b.appendChild(c);

      const c2 = card("발음교정표",
        "규칙이 못 잡는 것만 적습니다. 적힌 씬은 규칙을 건너뛰고 적힌 대로 읽습니다.");
      const ta = document.createElement("textarea");
      ta.rows = 9;
      ta.value = "불러오는 중…";
      api(`/api/projects/${encodeURIComponent(S.slug)}/pron`)
        .then((t) => { ta.value = t; }).catch(() => { ta.value = ""; });
      const save = el("button", "btn primary", "저장하고 적용");
      save.type = "button";
      save.disabled = !!S.cfg?.readonly;
      save.onclick = async () => {
        save.disabled = true;
        try {
          await put(`/api/projects/${encodeURIComponent(S.slug)}/pron`, ta.value, true);
          await loadProject(S.slug);
          alert("적용했습니다. 「음성」 탭에서 다시 굽세요.");
        } catch (e) { alert(e.message); } finally { save.disabled = false; }
      };
      c2.appendChild(ta);
      c2.appendChild(row(save));
      b.appendChild(c2);
      if (d.scenes) b.appendChild(sceneEditor(d, { showNarration: true }));
    },

    tts: (b) => {
      const c = card(
        `엔진 ${S.cfg?.tts?.engine || "?"} · 목소리 ${d.voice || "F2"} · ${d.speed || 1.2}배속`,
        "발음이 그대로인 씬은 다시 굽지 않습니다. 고친 씬만 다시 만듭니다.");
      const tot = d.audio_total_sec || 0;
      const tgt = d.seconds || 22;
      c.appendChild(row(el("span", "pill" + (tot > tgt + 2 ? " warn" : " ok"),
        `합계 ${tot.toFixed(1)}초 / 목표 ${tgt}초`)));
      const f = el("button", "btn", "전부 다시 굽기");
      f.type = "button";
      f.disabled = !!S.cfg?.readonly;
      f.onclick = () => runStage("tts", { force: true });
      c.appendChild(row(runBtn("tts", "음성 만들기"), f));
      b.appendChild(c);
      if (d.scenes) b.appendChild(sceneEditor(d, { showNarration: true }));
    },

    subs: (b) => {
      const c = card("큐", "글자 수 비율로 시간을 나눕니다. 낱말 가운데를 자르지 않습니다.");
      c.appendChild(row(runBtn("subs", "자막 다시 만들기")));
      b.appendChild(c);
      const c2 = card("SRT");
      const pre = Object.assign(el("pre", "out"), { textContent: "불러오는 중…" });
      api(`/api/projects/${encodeURIComponent(S.slug)}/srt`)
        .then((t) => { pre.textContent = t || "(아직 없음)"; })
        .catch(() => { pre.textContent = "(아직 없음)"; });
      c2.appendChild(pre);
      b.appendChild(c2);
    },

    artspec: (b) => {
      const c = card("장면 지시",
        "장면 안에 글자를 넣지 않습니다. 위아래 띠는 비워 둡니다. "
        + "동작은 한 방향으로 한 번만 — 되풀이하면 화면이 안절부절못합니다.");
      c.appendChild(row(runBtn("artspec", "지시 만들기")));
      b.appendChild(c);

      const c2 = card("씬마다 무엇이 어떻게 움직이나");
      const pre = Object.assign(el("pre", "out"), { textContent: "불러오는 중…" });
      api(`/api/projects/${encodeURIComponent(S.slug)}/artspec`)
        .then((j) => {
          if (!j || !j.scenes || !j.scenes.length) { pre.textContent = "(아직 없음)"; return; }
          pre.textContent = j.scenes.map((r) => [
            `씬 ${r.no} (${r.role || "body"}) · 화면 ${r.scene_sec ?? r.sec}초 · 동작은 ${r.sec}초 안에`
              + (r.canvas_h ? ` · 두루마리 ${r.canvas_h}px (${(r.cells || []).length}칸)` : ""),
            /* ★ 주장을 맨 위에 놓는다. 예전 이 자리는 `r.motion` 을 읽었는데
             *   그건 v1 필드였다 — 스키마 v2 는 claim/change/beats 를 쓰므로
             *   화면이 **주장을 통째로 안 보여 주고** 있었다. */
            `  주장 : ${r.claim || "(없음)"}`,
            r.fact ? `  사실 : ${r.fact}` : "",
            `  장면 : ${r.stage}`,
            `  배치 : ${r.layout}`,
            `  변동 : ${r.change || ""}`,
            ...(r.cells || []).map((c) => `  칸${c.no} [${c.fill || ""}] ${c.what || ""}`),
            ...(r.beats || []).map((x) => `  박자 ${x.at}~${x.until}초 : ${x.what}`),
            (r.camera || []).length
              ? "  카메라 : " + r.camera.map((x) => `${x.at}초 칸${x.cell}(${x.move})`).join(" → ")
              : "",
            r.support ? `  거듦 : ${r.support}` : "",
            r.palette_note ? `  색   : ${r.palette_note}` : "",
          ].filter(Boolean).join("\n")).join("\n\n");
          (j.warnings || []).forEach((w) => c2.appendChild(el("div", "note", w)));
        })
        .catch(() => { pre.textContent = "(아직 없음)"; });
      c2.appendChild(pre);
      b.appendChild(c2);
    },
  }));
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
  const c = card("유튜브 글", "제목·설명·태그·고정댓글. 설명의 {원본링크} 를 롱폼 주소로 바꿔 넣으세요.");
  c.appendChild(row(runBtn("result", "올릴 글 만들기")));
  if (p.build?.youtube) c.appendChild(Object.assign(el("pre", "out"), { textContent: p.build.youtube }));
  m.appendChild(c);
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
    S.page = "source";
    await loadProject(S.slug);
  } else {
    render();
  }
})();
