/** Pelica Console 开发模式 UI 全量走查（puppeteer-core + 系统 Edge 无头）。
 *
 * 覆盖：向导 8 步（含风险勾选、沙箱真回复）、各页面路由、控制台零错误（B11）、截图产出。
 * 用法：node e2e/walkthrough.mjs  （需网关 :8765 与 vite :5179 已启动）
 */

import puppeteer from "puppeteer-core";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const SHOTS = path.join(HERE, "..", "..", "docs", "screenshots");
fs.mkdirSync(SHOTS, { recursive: true });

const BASE = process.env.CONSOLE_URL || "http://localhost:5179";
const CHROME = "C:/Program Files/Google/Chrome/Application/chrome.exe";
const EDGE = "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe";
const BROWSER_BIN = fs.existsSync(CHROME) ? CHROME : EDGE;

const consoleIssues = [];
const failures = [];

function ok(name, cond, detail = "") {
  const mark = cond ? "PASS" : "FAIL";
  if (!cond) failures.push(`${name} ${detail}`);
  console.log(`[${mark}] ${name}${detail ? " — " + detail : ""}`);
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

const text = (page) => page.evaluate(() => document.body.innerText);

async function waitHeading(page, heading, timeout = 10000) {
  await page.waitForFunction(
    (h) => document.querySelector("h1")?.textContent === h,
    { timeout },
    heading,
  );
}

async function waitText(page, keyword, timeout = 10000) {
  await page.waitForFunction(
    (k) => document.body.innerText.includes(k),
    { timeout },
    keyword,
  );
}

async function clickByText(page, tag, label, exact = false) {
  const clicked = await page.evaluate(
    ({ tag, label, exact }) => {
      const els = [...document.querySelectorAll(tag)];
      const el = els.find((e) =>
        exact ? e.textContent.trim() === label : e.textContent.includes(label),
      );
      if (el) {
        el.click();
        return true;
      }
      return false;
    },
    { tag, label, exact },
  );
  if (!clicked) throw new Error(`未找到可点击元素 <${tag}> "${label}"`);
}

async function shot(page, name) {
  await page.screenshot({ path: path.join(SHOTS, name + ".png") });
}

const browser = await puppeteer.launch({
  executablePath: BROWSER_BIN,
  headless: true,
  args: [
    "--no-sandbox",
    "--disable-gpu",
    "--window-size=1280,860",
    `--user-data-dir=${process.env.TEMP}\\pelica-e2e-profile-${Date.now()}`,
  ],
});
const page = await browser.newPage();
await page.setViewport({ width: 1280, height: 860 });
page.on("console", (msg) => {
  if (msg.type() === "error" || msg.type() === "warning") {
    consoleIssues.push(`[${msg.type()}] ${msg.text()}`);
  }
});
page.on("pageerror", (err) => consoleIssues.push(`[pageerror] ${err.message}`));

try {
  await page.goto(BASE, { waitUntil: "domcontentloaded", timeout: 20000 });
  await waitHeading(page, "欢迎");
  ok("向导·第1步 欢迎", true);
  await shot(page, "wizard-1-welcome");
  await clickByText(page, "button", "下一步");
  await waitHeading(page, "风险告知");

  let body = await text(page);
  ok(
    "向导·第2步 风险文案一字不改",
    body.includes("本程序的微信接入方式（WeChat-Hook）通过 DLL 注入修改微信客户端行为，不属于微信官方支持的接口") &&
      body.includes("强烈建议：仅使用小号运行本程序；不要在承载重要账号的电脑上同时使用 hook"),
  );
  await clickByText(page, "button", "下一步"); // 未勾选 → 应被拦截
  await sleep(500);
  body = await text(page);
  ok("向导·第2步 未勾选被拦截", body.includes("风险告知"));
  await page.click('input[type="checkbox"]');
  await shot(page, "wizard-2-risk");
  await clickByText(page, "button", "下一步");
  await waitHeading(page, "连接微信");
  await shot(page, "wizard-3-bridge");
  await clickByText(page, "button", "下一步");
  await waitHeading(page, "选择方案");
  body = await text(page);
  ok("向导·第4步 三角色", body.includes("佩丽卡") && body.includes("凯尔希") && body.includes("派蒙"));
  await shot(page, "wizard-4-profile");
  await clickByText(page, "button", "下一步");
  await waitHeading(page, "模型密钥");
  ok("向导·第5步 密钥页", true);
  await clickByText(page, "button", "下一步");
  await waitHeading(page, "沙箱试聊");

  await clickByText(page, "button", "发送", true);
  let reply = "";
  for (let i = 0; i < 45; i++) {
    await sleep(1000);
    const bubbles = await page.$$eval("p", (els) =>
      els.map((e) => e.textContent.trim()),
    );
    const hit = bubbles.filter(
      (t) => t && !t.startsWith("给佩丽卡") && !t.startsWith("思考中") && t.length >= 4 &&
        !t.includes("管理员对你说") && t !== "还没发送。此步失败不阻断——可直接点「仍然完成」。",
    );
    if (hit.length) {
      reply = hit[hit.length - 1];
      break;
    }
  }
  ok("向导·第6步 沙箱角色化回复", reply.length > 0, reply.slice(0, 50));
  await shot(page, "wizard-6-sandbox");
  await clickByText(page, "button", "下一步");
  await waitHeading(page, "启用群聊");
  const groupValues = await page.$$eval("input", (els) =>
    els.map((e) => e.value),
  );
  ok("向导·第7步 示例群默认启用", groupValues.some((v) => v.includes("示例群")));
  await clickByText(page, "button", "下一步");
  await waitHeading(page, "完成");
  ok("向导·第8步 完成页", true);
  await shot(page, "wizard-8-done");
  await clickByText(page, "button", "进入控制台");
  await waitText(page, "数据一览", 20000);
  body = await text(page);
  ok("仪表盘加载", body.includes("数据一览") && body.includes("当前角色"));
  await shot(page, "app-dashboard");

  const cases = [
    ["#/profiles", ["佩丽卡 × PRTS", "已应用"]],
    ["#/personas", ["角色包"]],
    ["#/corpora", ["检索测试台"]],
    ["#/sessions", ["群聊白名单"]],
    ["#/providers", ["密钥与接口"]],
    ["#/flags", ["标准"]],
    ["#/sandbox", ["模拟器"]],
    ["#/logs", ["实时日志"]],
    ["#/system", ["环境体检"]],
    ["#/settings", ["数据目录"]],
  ];
  for (const [hash, kws] of cases) {
    await page.evaluate((h) => {
      location.hash = h;
    }, hash);
    await waitText(page, kws[0], 12000).catch(() => {});
    body = await text(page);
    ok(`页面 ${hash}`, kws.every((k) => body.includes(k)));
  }
  await page.evaluate(() => (location.hash = "#/profiles"));
  await sleep(1200);
  await shot(page, "app-profiles");
  await page.evaluate(() => (location.hash = "#/sandbox"));
  await sleep(1200);
  await shot(page, "app-sandbox");

  // Ctrl+K 命令面板
  await page.keyboard.down("Control");
  await page.keyboard.press("KeyK");
  await page.keyboard.up("Control");
  await page
    .waitForSelector('[role="dialog"][aria-label="命令面板"]', { timeout: 5000 })
    .then(() => ok("Ctrl+K 命令面板", true))
    .catch(() => ok("Ctrl+K 命令面板", false));
  await page.keyboard.press("Escape");
  await shot(page, "app-command-palette");
} finally {
  await browser.close();
}

console.log("\n==== 汇总 ====");
console.log("console 错误/警告数:", consoleIssues.length);
for (const line of consoleIssues.slice(0, 12)) console.log("  ", line);
console.log("失败项:", failures.length, JSON.stringify(failures));
process.exit(failures.length || consoleIssues.length ? 1 : 0);
