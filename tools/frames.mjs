/**
 * 씬마다 **최종 화면** 한 장 — 스토리보드가 이것을 슬라이드로 쓴다.
 *
 *   node tools/frames.mjs <컴포지션폴더> <나갈폴더> [--w 1080]
 *
 * ★ 왜 필요한가 — 스토리보드의 슬라이드가 씬 SVG 를 그냥 얹은 것이었다. 그런데
 *   최종 화면은 SVG 위에 후크·자막·해시태그·진행 레일이 얹힌 것이라, 슬라이드로는
 *   **글자가 띠를 넘치는지·자막이 그림을 가리는지**를 볼 수 없었다.
 *   컴포지션 HTML 을 씬 한가운데 시각으로 세워 찍으면 그것이 곧 나갈 화면이다.
 *
 * ★ 컴포지션이 있어야 돈다. 없으면 조용히 아무것도 안 만들고 끝낸다 —
 *   슬라이드는 그때 예전처럼 SVG 로 떨어진다.
 */
import puppeteer from "puppeteer";
import { mkdirSync, readFileSync, existsSync } from "node:fs";
import { join, resolve } from "node:path";

const argv = process.argv.slice(2);
const flag = (n, d) => {
  const i = argv.indexOf(`--${n}`);
  return i >= 0 && i + 1 < argv.length ? argv[i + 1] : d;
};
const pos = argv.filter((a, i) => !a.startsWith("--") && !(argv[i - 1] || "").startsWith("--"));
const [dir, out] = pos;
if (!dir || !out) {
  console.log("[error] usage: node tools/frames.mjs <컴포지션폴더> <나갈폴더>");
  process.exit(2);
}

const html = join(resolve(dir), "index.html");
if (!existsSync(html)) {
  console.log("[warn] 컴포지션이 없습니다 — 건너뜁니다.");
  process.exit(0);
}
// 씬 시각은 컴포지션이 이미 계산해 뒀다. 여기서 다시 세지 않는다 —
// 계산이 두 곳에 있으면 언젠가 서로 달라진다.
const infoPath = join(resolve(dir), "장면시각.json");
let shots = [];
if (existsSync(infoPath)) {
  shots = JSON.parse(readFileSync(infoPath, "utf-8")).scenes || [];
}
if (!shots.length) {
  console.log("[warn] 장면시각.json 이 없습니다 — 건너뜁니다.");
  process.exit(0);
}

const W = Number(flag("w", "1080"));
mkdirSync(resolve(out), { recursive: true });

const browser = await puppeteer.launch({ headless: "shell", args: ["--no-sandbox"] });
const page = await browser.newPage();
// 세로 9:16. 배율을 낮춰 파일을 가볍게 — 스토리보드에서 보는 크기면 충분하다.
await page.setViewport({ width: 1080, height: 1920, deviceScaleFactor: W / 1080 });
await page.goto("file:///" + html.replace(/\\/g, "/"), { waitUntil: "networkidle0" });
await new Promise((r) => setTimeout(r, 800));

for (const s of shots) {
  // 씬 **한가운데** 를 찍는다. 시작 순간은 페이드가 덜 끝나 흐리다.
  const t = Number(s.start) + Number(s.dur) / 2;
  await page.evaluate((tt) => {
    const tl = window.__timelines && window.__timelines.main;
    if (tl) { tl.pause(); tl.time(tt); }
  }, t);
  await new Promise((r) => setTimeout(r, 260));
  const file = join(resolve(out), String(s.no).padStart(3, "0") + ".png");
  await page.screenshot({ path: file });
  console.log(`[frame] ${s.no} ${t.toFixed(2)}s`);
}

await browser.close();
console.log("[done] " + resolve(out));
