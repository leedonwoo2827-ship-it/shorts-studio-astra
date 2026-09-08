/**
 * 화면 사진 — 콘솔을 눈으로 확인하는 용도. 개발용이고 앱은 이것에 기대지 않는다.
 *
 *   node tools/shot.mjs <url> <out.png> [--w 1440] [--h 900] [--wait 1200] [--full]
 *
 * ★ Chrome 은 HyperFrames 가 이미 끌고 온 puppeteer 것을 쓴다 — 따로 깔지 않는다.
 */
import puppeteer from "puppeteer";
import { mkdirSync } from "node:fs";
import { dirname } from "node:path";

const argv = process.argv.slice(2);
const flag = (n, d) => {
  const i = argv.indexOf(`--${n}`);
  return i >= 0 && i + 1 < argv.length ? argv[i + 1] : d;
};
const [url, out] = argv.filter((a) => !a.startsWith("--") &&
  !(argv[argv.indexOf(a) - 1] || "").startsWith("--"));

if (!url || !out) {
  console.error("usage: node tools/shot.mjs <url> <out.png> [--w 1440] [--h 900] [--wait 1200] [--full]");
  process.exit(2);
}

const browser = await puppeteer.launch({ headless: "shell" });
try {
  const page = await browser.newPage();
  await page.setViewport({
    width: Number(flag("w", 1440)),
    height: Number(flag("h", 900)),
    deviceScaleFactor: 1,
  });

  // 콘솔 오류를 그대로 흘린다 — 조용히 깨진 화면을 사진만 보고 판단하면 놓친다
  const problems = [];
  page.on("pageerror", (e) => problems.push(`pageerror: ${e.message}`));
  page.on("requestfailed", (r) => problems.push(`requestfailed: ${r.url()} ${r.failure()?.errorText}`));
  page.on("console", (m) => {
    if (m.type() === "error" || m.type() === "warning") problems.push(`console.${m.type()}: ${m.text()}`);
  });

  await page.goto(url, { waitUntil: "networkidle2", timeout: 30000 });
  await new Promise((r) => setTimeout(r, Number(flag("wait", 1200))));

  // --step <키> : 좌측 레일의 그 단계를 눌러 화면을 옮긴다.
  // 이 콘솔은 URL 라우팅이 없어서(한 페이지 앱) 사진을 찍으려면 눌러야 한다.
  const step = flag("step", null);
  if (step) {
    const hit = await page.evaluate((k) => {
      const b = document.querySelector(`.step[data-key="${k}"]`);
      if (!b) return false;
      b.click();
      return true;
    }, step);
    if (!hit) console.log(`[warn] 그런 단계 버튼이 없습니다: ${step}`);
    await new Promise((r) => setTimeout(r, Number(flag("wait", 1200))));
  }

  mkdirSync(dirname(out), { recursive: true });
  await page.screenshot({ path: out, fullPage: argv.includes("--full") });

  if (problems.length) {
    console.log("[problems]");
    for (const p of [...new Set(problems)]) console.log("  " + p);
  } else {
    console.log("[problems] none");
  }
  console.log(`[done] ${out}`);
} finally {
  await browser.close();
}
