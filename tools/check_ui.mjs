/**
 * 콘솔 화면 점검 — 사진 대신 **DOM 을 직접 본다.**
 *
 *   node tools/check_ui.mjs [http://127.0.0.1:8899/]
 *
 * ★ 사진은 「보기 좋은가」를 알려 주지만 「제대로 붙었는가」는 못 알려 준다.
 *   레일 줄이 몇 개인지, 탭이 다 있는지, 실행 단추가 살아 있는지, 콘솔에
 *   오류가 났는지는 세어 보는 쪽이 정확하다. CI 에서도 그대로 돈다.
 */
import puppeteer from "puppeteer";

const url = process.argv[2] || "http://127.0.0.1:8899/";
const browser = await puppeteer.launch({ headless: "shell" });
let bad = 0;

function ok(label, pass, extra = "") {
  if (!pass) bad++;
  console.log(`  ${pass ? "OK  " : "실패"} ${label}${extra ? "   " + extra : ""}`);
}

try {
  const page = await browser.newPage();
  await page.setViewport({ width: 1280, height: 900 });
  const errs = [];
  page.on("pageerror", (e) => errs.push(e.message));
  page.on("console", (m) => { if (m.type() === "error") errs.push(m.text()); });

  await page.goto(url, { waitUntil: "networkidle2", timeout: 30000 });
  await new Promise((r) => setTimeout(r, 2500));

  // ── 레일 ──
  const rail = await page.evaluate(() => ({
    groups: [...document.querySelectorAll(".grp")].map((b) => b.textContent.trim()),
    steps: [...document.querySelectorAll(".step")].map((b) => ({
      name: b.querySelector(".step-name")?.textContent,
      tabs: b.querySelector(".tabn")?.textContent || null,
      money: !!b.querySelector(".cost"),
      dot: b.querySelector(".step-dot")?.className.replace("step-dot", "").trim(),
    })),
    seps: document.querySelectorAll(".rail-sep").length,
    chips: [...document.querySelectorAll(".conn")].map((c) => c.textContent.trim()),
  }));
  console.log("== 레일 ==");
  ok("묶음 단추 3개", rail.groups.length === 3, rail.groups.join(" / "));
  ok("화면 줄 6개", rail.steps.length === 6,
    rail.steps.map((s) => s.name).join(" / "));
  ok("묶음 사이 금 2개", rail.seps === 2);
  ok("「대본」 줄에 탭 개수 5", rail.steps.some((s) => s.tabs === "5"));
  ok("연결 칩 2개", rail.chips.length === 2);

  // ── 대본 화면의 탭 ──
  await page.evaluate(() => document.querySelector('.step[data-key="script"]')?.click());
  await new Promise((r) => setTimeout(r, 1400));
  const tabs = await page.evaluate(() => ({
    names: [...document.querySelectorAll(".tab")].map((t) => t.firstChild?.textContent),
    on: document.querySelector(".tab.on")?.firstChild?.textContent,
    runBtns: [...document.querySelectorAll(".tabbody .btn.primary")].map((b) => b.textContent),
    scenes: document.querySelectorAll(".tabbody .scene").length,
    h1: document.querySelector("h1")?.textContent,
  }));
  console.log("== 대본 화면 ==");
  ok("제목이 「대본」", tabs.h1 === "대본", tabs.h1);
  ok("탭 5개", tabs.names.length === 5, tabs.names.join(" / "));
  ok("첫 탭이 켜져 있음", tabs.on === "대본", tabs.on);
  ok("탭 안에 실행 단추", tabs.runBtns.length >= 1, tabs.runBtns.join(" / "));
  ok("씬 편집 카드가 있음", tabs.scenes > 0, `${tabs.scenes}개`);

  // 탭을 옮겨도 실행 단추가 살아 있는가 — 클릭 권한이 안 없어지는지
  for (const want of ["발음", "음성", "자막", "장면 지시"]) {
    const got = await page.evaluate((w) => {
      const t = [...document.querySelectorAll(".tab")]
        .find((x) => x.firstChild?.textContent === w);
      if (!t) return null;
      t.click();
      return true;
    }, want);
    if (!got) { ok(`탭 「${want}」 존재`, false); continue; }
    await new Promise((r) => setTimeout(r, 900));
    const btn = await page.evaluate(() =>
      [...document.querySelectorAll(".tabbody .btn")].map((b) => b.textContent));
    ok(`탭 「${want}」 에 단추`, btn.length >= 1, btn.slice(0, 3).join(" / "));
  }

  // ── 장면 제작 · 미리보기 ──
  for (const [key, want] of [["art", "장면 제작"], ["compose", "컴포지션 · 미리보기"]]) {
    await page.evaluate((k) => document.querySelector(`.step[data-key="${k}"]`)?.click(), key);
    await new Promise((r) => setTimeout(r, 1600));
    const h1 = await page.evaluate(() => document.querySelector("h1")?.textContent);
    ok(`「${want}」 화면 열림`, h1 === want, h1);
  }
  const player = await page.evaluate(() =>
    !!document.querySelector(".player hyperframes-player, .player iframe"));
  ok("미리보기 플레이어 붙음", player);

  console.log("== 콘솔 오류 ==");
  ok("오류 없음", errs.length === 0, errs.slice(0, 2).join(" | "));
} finally {
  await browser.close();
}

console.log(bad ? `\n실패 ${bad}건` : "\n전부 통과");
process.exit(bad ? 1 : 0);
