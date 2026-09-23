/** 定向验证 2026-09-23 验收反馈三项：方案编辑器 / 仪表盘微信卡 / 沙箱跟随角色。 */

import puppeteer from "puppeteer-core";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const SHOTS = path.join(path.dirname(fileURLToPath(import.meta.url)), "..", "..", "docs", "screenshots");
const BASE = "http://localhost:5179";
const CHROME = "C:/Program Files/Google/Chrome/Application/chrome.exe";
const EDGE = "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe";
const failures = [];
const ok = (name, cond, detail = "") => {
  if (!cond) failures.push(name);
  console.log(`[${cond ? "PASS" : "FAIL"}] ${name}${detail ? " — " + detail : ""}`);
};
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const text = (page) => page.evaluate(() => document.body.innerText);
const clickByText = async (page, tag, label, exact = false) => {
  const clicked = await page.evaluate(
    ({ tag, label, exact }) => {
      const el = [...document.querySelectorAll(tag)].find((e) =>
        exact ? e.textContent.trim() === label : e.textContent.includes(label),
      );
      if (el) { el.click(); return true; }
      return false;
    },
    { tag, label, exact },
  );
  if (!clicked) throw new Error(`点击失败 <${tag}> ${label}`);
};

const browser = await puppeteer.launch({
  executablePath: fs.existsSync(CHROME) ? CHROME : EDGE,
  headless: true,
  args: ["--no-sandbox", "--disable-gpu", `--user-data-dir=${process.env.TEMP}\\pelica-feat-${Date.now()}`],
});
const page = await browser.newPage();
await page.setViewport({ width: 1280, height: 860 });
const consoleIssues = [];
page.on("console", (m) => { if (m.type() === "error" || m.type() === "warning") consoleIssues.push(m.text()); });
page.on("pageerror", (e) => consoleIssues.push(e.message));

try {
  // 直接跳过向导（本脚本只验主应用新功能）
  await page.goto(BASE, { waitUntil: "domcontentloaded" });
  await sleep(2500);
  const body0 = await text(page);
  if (body0.includes("首次配置向导")) {
    // 老数据：完成向导（勾选风险→一路下一步）
    await clickByText(page, "button", "下一步");
    await sleep(400);
    await page.click('input[type="checkbox"]');
    for (let i = 0; i < 6; i++) { await clickByText(page, "button", "下一步"); await sleep(400); }
    await clickByText(page, "button", "进入控制台");
    await sleep(2500);
  }

  // 1) 仪表盘：微信连接卡 + 实时状态
  await page.evaluate(() => (location.hash = "#/"));
  await sleep(1800);
  let body = await text(page);
  ok("仪表盘·微信连接卡", body.includes("微信连接") && (body.includes("沙箱模式") || body.includes("已连接") || body.includes("未接入")));
  ok("仪表盘·断开/连接按钮", body.includes("断开连接") || body.includes("连接微信") || body.includes("启动"));
  await page.screenshot({ path: path.join(SHOTS, "feat-dashboard-bridge.png") });

  // 2) 方案编辑器：三区（人设/语料库/模型）
  await page.evaluate(() => (location.hash = "#/profiles"));
  await sleep(1500);
  await clickByText(page, "button", "编辑");
  await sleep(1200);
  body = await text(page);
  ok("方案编辑器·三区齐备", body.includes("① 人设（提示词）") && body.includes("② 语料库") && body.includes("③ 模型与 API"));
  await clickByText(page, "button", "查看 / 编辑提示词");
  await sleep(1200);
  body = await text(page);
  ok("方案编辑器·提示词可查看", body.includes("保存提示词"));
  await page.screenshot({ path: path.join(SHOTS, "feat-profile-editor.png") });

  // 新建方案入口
  await page.keyboard.press("Escape");
  await sleep(500);
  await page.evaluate(() => (location.hash = "#/profiles"));
  await sleep(800);
  ok("方案中心·新建按钮", (await text(page)).includes("新建方案"));

  // 3) 沙箱跟随角色：切到派蒙 → 默认消息变 @派蒙
  await page.evaluate(async () => {
    const token = (window.__TAURI_INTERNALS__ ? null : null);
    void token;
  });
  // 通过 UI：无法直接在简单模式切角色（方案中心应用）——用「编辑」弹窗里保存提示词太重，
  // 直接调 API（页面 fetch 带代理 token 不行）——改走方案应用：派蒙卡点「应用」
  await page.evaluate(() => (location.hash = "#/profiles"));
  await sleep(1000);
  const paimonApplied = await page.evaluate(() => {
    // Card 渲染为 <section>：在 section 级别精确定位派蒙卡
    const cards = [...document.querySelectorAll("section")];
    const card = cards.find((c) => c.textContent.includes("派蒙 × 原神语料"));
    const btn = card ? [...card.querySelectorAll("button")].find((b) => b.textContent.trim() === "应用") : null;
    if (btn) { btn.click(); return true; }
    return false;
  });
  if (paimonApplied) await sleep(1500);
  await page.evaluate(() => (location.hash = "#/sandbox"));
  await sleep(1500);
  const inputs = await page.$$eval("input", (els) => els.map((e) => e.value));
  const msg = inputs.find((v) => v.includes("你好")) ?? "";
  ok("沙箱·默认消息跟随角色（派蒙）", msg.includes("@派蒙"), msg);
  await page.screenshot({ path: path.join(SHOTS, "feat-sandbox-paimon.png") });
} finally {
  await browser.close();
}
console.log("\nconsole 错误/警告:", consoleIssues.length, consoleIssues.slice(0, 5));
console.log("失败项:", failures.length, failures);
process.exit(failures.length || consoleIssues.length ? 1 : 0);
