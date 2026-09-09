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
 *
 * ★ **카드 배치는 조각마다 찍는다** (`장면시각.json` 의 `scenes[].shots`).
 *   씬 한가운데 한 장만 찍으면, 그림이 세 장 갈리는 씬에서 **가운데 것 하나만**
 *   찍히고 나머지는 사람이 못 본다 — 몇 장이 비었는지 볼 수 없다는 뜻이다.
 *      frames/002.png      씬 2 한가운데 (두루마리 · 그리고 카드의 대표 한 장)
 *      frames/002-1.png    씬 2 조각 1
 *      frames/002-3.png    씬 2 조각 3
 *   ★ **플립북은 프레임마다 찍지 않는다.** 조각당 한 장(넘김이 끝나 멈춘 자리)만
 *     찍는다. 12프레임을 12장 찍으면 스토리보드 띠가 터진다.
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

const seek = async (t) => {
  await page.evaluate((tt) => {
    const tl = window.__timelines && window.__timelines.main;
    if (tl) { tl.pause(); tl.time(tt); }
  }, t);
  await new Promise((r) => setTimeout(r, 260));
};
const nn = (n) => String(n).padStart(3, "0");

for (const s of shots) {
  // 씬 **한가운데** — 두루마리에서는 이것이 그 씬의 화면이고, 카드에서도
  // 스토리보드가 접혀 있을 때 보여 줄 대표 한 장이다.
  const mid = Number(s.start) + Number(s.dur) / 2;
  await seek(mid);
  await page.screenshot({ path: join(resolve(out), nn(s.no) + ".png") });
  console.log(`[frame] ${s.no} ${mid.toFixed(2)}s`);

  // 조각마다 한 장. `hold` 는 플립북이 마지막 프레임에서 멈추는 시각이다 —
  // 넘김이 끝난 뒤를 찍어야 「무엇으로 멈췄는지」가 보인다.
  for (const sh of s.shots || []) {
    const t = Math.min(Number(sh.hold ?? sh.at) + 0.35,
                       Number(s.start) + Number(s.dur) - 0.05);
    await seek(t);
    await page.screenshot({ path: join(resolve(out), `${nn(s.no)}-${sh.m}.png`) });
    console.log(`[frame] ${s.no}-${sh.m} ${t.toFixed(2)}s (프레임 ${sh.frames}장)`);
  }
}

await browser.close();
console.log("[done] " + resolve(out));
