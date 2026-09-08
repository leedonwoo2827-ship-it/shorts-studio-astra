/**
 * 두루마리 검사 — 칸 경계를 넘는 요소를 찾는다.
 *
 *   node tools/check_scroll.mjs <in.svg> <칸높이> [--slack 40]
 *
 * 결과는 stdout 에 JSON 한 줄. `{"ok":true}` 또는
 * `{"ok":false,"bad":[{"tag":"path","y0":300,"y1":4100,"cells":[1,2,3]}],...}`
 *
 * ★ **왜 브라우저에게 물어보나.** `d` 속성을 정규식으로 재려 하면 상대 명령
 *   (c·l·v)이 섞여 곧 틀린다. `getBBox()` 는 브라우저가 실제로 그린 상자를
 *   돌려주므로 어긋날 여지가 없다. `tools/shot_svg.mjs` 가 이미 puppeteer 를
 *   쓰고 있어 새 의존도 안 생긴다.
 *
 * ★ **왜 이 검사가 필요한가.** 실측(2026-09-08): 아스트라가 세 칸을 잇겠다고
 *   위에서 아래로 얇은 「우편로」 선을 하나 그었다. 프롬프트에 「칸 경계에
 *   걸치는 것을 두지 마라」고 적어 두었는데도 그랬다.
 *   카메라는 한 번에 **한 칸만** 잡으므로 그 선은 「이음」으로 안 읽히고
 *   화면을 관통하는 정체불명의 획으로 보인다. 칸을 잇는 것은 카메라의 일이다.
 */
import puppeteer from "puppeteer";
import { readFileSync } from "node:fs";

const argv = process.argv.slice(2);
const flag = (n, d) => {
  const i = argv.indexOf(`--${n}`);
  return i >= 0 && i + 1 < argv.length ? argv[i + 1] : d;
};
const pos = argv.filter((a, i) => !a.startsWith("--") && !(argv[i - 1] || "").startsWith("--"));
const [inp, cellHRaw] = pos;
const cellH = Number(cellHRaw || 1920);
// 경계에 살짝 닿는 것은 봐준다 — 그림자·선 굵기가 몇 px 넘는 것은 안 보인다.
const slack = Number(flag("slack", 40));

if (!inp || !(cellH > 0)) {
  console.log(JSON.stringify({ ok: false, error: "usage: check_scroll.mjs <in.svg> <칸높이>" }));
  process.exit(2);
}

const svg = readFileSync(inp, "utf8");
const browser = await puppeteer.launch({ headless: "shell" });
try {
  const page = await browser.newPage();
  await page.setContent(
    `<!doctype html><meta charset="utf-8">` +
    `<body style="margin:0">${svg}</body>`,
    { waitUntil: "load" });

  const out = await page.evaluate((cellH, slack) => {
    const root = document.querySelector("svg");
    if (!root) return { ok: false, error: "svg 를 못 찾았습니다" };
    const vb = (root.getAttribute("viewBox") || "").split(/[\s,]+/).map(Number);
    if (vb.length !== 4) return { ok: false, error: "viewBox 를 못 읽었습니다" };
    const [, vy, , vh] = vb;
    const cells = Math.max(1, Math.round(vh / cellH));
    if (cells < 2) return { ok: true, cells, bad: [] };

    // 잎사귀 요소만 본다. <g> 는 자식을 감싸므로 당연히 경계를 넘는다.
    const LEAF = "path,rect,circle,ellipse,line,polyline,polygon,image,use";
    const bad = [];
    for (const el of root.querySelectorAll(LEAF)) {
      let b;
      try { b = el.getBBox(); } catch (_) { continue; }
      if (!b || b.height <= 0) continue;
      // 화면 전체를 채우는 바탕 <rect> 는 예외다 — 그건 있어야 한다.
      if (b.height >= vh - 2 && b.width >= (vb[2] - 2)) continue;

      // ★ 캔버스 밖은 잘라 낸 뒤에 센다. 실측(2026-09-08): 화면 위로 살짝
      //   삐져나간 장식이 y=-121 로 잡혀 「칸 0 과 칸 1 을 넘는다」는 오탐이
      //   됐고, 멀쩡한 두루마리가 되돌려보내졌다. SVG 는 viewBox 밖을 어차피
      //   잘라 그리므로, 보이는 범위로 자른 뒤에 판단하는 것이 맞다.
      const y0 = Math.max(0, Math.min(vh, b.y - vy));
      const y1 = Math.max(0, Math.min(vh, b.y + b.height - vy));
      if (y1 - y0 <= slack) continue;          // 보이는 부분이 거의 없다
      const c0 = Math.floor((y0 + slack) / cellH);
      const c1 = Math.floor((Math.min(y1, vh - 1) - slack) / cellH);
      if (c1 > c0) {
        const span = [];
        for (let k = c0; k <= c1; k++) span.push(k + 1);
        bad.push({
          tag: el.tagName, y0: Math.round(y0), y1: Math.round(y1),
          h: Math.round(b.height), cells: span,
          id: el.getAttribute("id") || "",
        });
      }
    }
    // 가장 크게 넘는 것부터 — 사람이 볼 때 그게 원인이다.
    bad.sort((a, b2) => b2.h - a.h);
    return { ok: bad.length === 0, cells, bad: bad.slice(0, 8), total: bad.length };
  }, cellH, slack);

  console.log(JSON.stringify(out));
  process.exit(out.ok ? 0 : 1);
} catch (e) {
  console.log(JSON.stringify({ ok: false, error: String(e && e.message || e) }));
  process.exit(2);
} finally {
  await browser.close();
}
