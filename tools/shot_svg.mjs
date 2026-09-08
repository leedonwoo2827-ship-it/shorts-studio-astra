/**
 * SVG 한 장을 시각별로 그려 본다 — 장면이 비어 보일 때 원인을 가른다.
 *
 *   node tools/shot_svg.mjs <in.svg> <out.png> [--t 3.2] [--w 540]
 *
 * ★ `--t` 는 **SVG 안의 시각**이다. `svg.setCurrentTime()` 으로 SMIL 을 그 지점에
 *   세운 뒤 찍는다. HyperFrames 도 프레임마다 이렇게 시각을 세워 캡처한다 —
 *   그래서 여기서 비면 렌더에서도 빈다.
 */
import puppeteer from "puppeteer";
import { readFileSync, mkdirSync } from "node:fs";
import { dirname } from "node:path";

const argv = process.argv.slice(2);
const flag = (n, d) => {
  const i = argv.indexOf(`--${n}`);
  return i >= 0 && i + 1 < argv.length ? argv[i + 1] : d;
};
const pos = argv.filter((a, i) => !a.startsWith("--") && !(argv[i - 1] || "").startsWith("--"));
const [inp, out] = pos;
if (!inp || !out) {
  console.error("usage: node tools/shot_svg.mjs <in.svg> <out.png> [--t 3.2] [--w 540]");
  process.exit(2);
}

const svg = readFileSync(inp, "utf8");
const t = Number(flag("t", 0));
const w = Number(flag("w", 540));

const browser = await puppeteer.launch({ headless: "shell" });
try {
  const page = await browser.newPage();
  await page.setViewport({ width: w, height: Math.round(w * 16 / 9) });
  const problems = [];
  page.on("pageerror", (e) => problems.push(`pageerror: ${e.message}`));

  await page.setContent(
    `<style>html,body{margin:0;background:#fff}svg{display:block;width:100vw;height:100vh}</style>${svg}`,
    { waitUntil: "load" });

  const info = await page.evaluate((time) => {
    const s = document.querySelector("svg");
    if (!s) return { ok: false, why: "svg 태그가 없다" };
    if (typeof s.pauseAnimations === "function") s.pauseAnimations();
    if (typeof s.setCurrentTime === "function") s.setCurrentTime(time);
    // 실제로 화면에 뭔가 있는지 — 눈에 보이는 도형의 합친 크기를 잰다
    let n = 0, area = 0;
    for (const node of s.querySelectorAll("path,rect,circle,ellipse,polygon,line,use,g")) {
      const st = getComputedStyle(node);
      if (st.display === "none" || st.visibility === "hidden") continue;
      if (parseFloat(st.opacity) === 0) continue;
      let b;
      try { b = node.getBoundingClientRect(); } catch (_) { continue; }
      if (b.width > 1 && b.height > 1) { n++; area = Math.max(area, b.width * b.height); }
    }
    return { ok: true, visible: n, maxArea: Math.round(area), currentTime: s.getCurrentTime?.() };
  }, t);

  mkdirSync(dirname(out), { recursive: true });
  await page.screenshot({ path: out });
  console.log(`[t=${t}s] ${JSON.stringify(info)}`);
  if (problems.length) console.log("[problems] " + problems.join(" | "));
  console.log(`[done] ${out}`);
} finally {
  await browser.close();
}
