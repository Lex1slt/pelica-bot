/** §13.3 十分钟剧本（计时）：真实 Key 导入 → 测试连接绿 → 沙箱角色化回复 → 启用示例群 → 完成。
 *
 * Key 从仓库 .env 文件直接读取（仅填充进密码框，绝不打印/落日志）。
 * 用法：PELICA_ACC_GW_PORT=xxxx PELICA_ACC_GW_TOKEN=xxx node e2e/acceptance.mjs
 */

import puppeteer from "puppeteer-core";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const SHOTS = path.join(
  path.dirname(fileURLToPath(import.meta.url)),
  "..",
  "..",
  "docs",
  "screenshots",
);

const GW_PORT = process.env.PELICA_ACC_GW_PORT;
const GW_TOKEN = process.env.PELICA_ACC_GW_TOKEN;
if (!GW_PORT || !GW_TOKEN) {
  console.error("需要 PELICA_ACC_GW_PORT / PELICA_ACC_GW_TOKEN");
  process.exit(2);
}

// 从 .env 取真实 Key（不回显）
const envText = fs.readFileSync("D:/PRTS robot/.env", "utf-8");
const keyMatch = envText.match(/^DEEPSEEK_API_KEY=(.+)$/m);
const apiKey = keyMatch ? keyMatch[1].trim() : "";
if (!apiKey || apiKey.startsWith("sk-xxx")) {
  console.error("真实 Key 缺失（.env 无有效 DEEPSEEK_API_KEY）");
  process.exit(2);
}

const BASE = "http://localhost:5179";
const EDGE = "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe";
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const failures = [];
const ok = (name, cond, detail = "") => {
  if (!cond) failures.push(name);
  console.log(`[${cond ? "PASS" : "FAIL"}] ${name}${detail ? " — " + detail : ""}`);
};

const t0 = Date.now();
const browser = await puppeteer.launch({
  executablePath: EDGE,
  headless: true,
  args: ["--no-sandbox", "--disable-gpu"],
});
const page = await browser.newPage();
await page.setViewport({ width: 1280, height: 860 });
const consoleIssues = [];
page.on("console", (m) => {
  if (m.type() === "error" || m.type() === "warning")
    consoleIssues.push(m.text());
});
page.on("pageerror", (e) => consoleIssues.push(e.message));

const text = () => page.evaluate(() => document.body.innerText);
const waitHeading = (h, t = 12000) =>
  page.waitForFunction(
    (x) => document.querySelector("h1")?.textContent === x,
    { timeout: t },
    h,
  );
const clickByText = async (tag, label, exact = false) => {
  const clicked = await page.evaluate(
    ({ tag, label, exact }) => {
      const el = [...document.querySelectorAll(tag)].find((e) =>
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
  if (!clicked) throw new Error(`点击失败 <${tag}> ${label}`);
};
const shot = (name) =>
  page.screenshot({ path: path.join(SHOTS, `acc-${name}.png`) });

try {
  await page.goto(BASE, { waitUntil: "domcontentloaded" });
  await waitHeading("欢迎");
  ok("① 欢迎+模式选择", true);
  await clickByText("button", "下一步");

  await waitHeading("风险告知");
  await page.click('input[type="checkbox"]');
  await clickByText("button", "下一步");
  ok("② 风险告知（勾选后通过）", true);

  await waitHeading("连接微信");
  await clickByText("button", "下一步");
  ok("③ 连接微信（mock 跳过）", true);

  await waitHeading("选择方案");
  const body1 = await text();
  ok("④ 选择方案（佩丽卡默认）", body1.includes("佩丽卡"));
  await clickByText("button", "下一步");

  await waitHeading("模型密钥");
  const keyInput = await page.$('input[type="password"]');
  await keyInput.type(apiKey, { delay: 0 }); // 真实 Key，不回显
  await clickByText("button", "测试连接");
  let green = false;
  for (let i = 0; i < 40; i++) {
    await sleep(1000);
    const badge = await page.evaluate(() => {
      const el = [...document.querySelectorAll("span")].find((e) =>
        e.textContent.includes("绿灯"),
      );
      return el ? el.textContent : "";
    });
    if (badge) {
      green = true;
      ok("⑤ 测试连接绿", true, badge);
      break;
    }
  }
  if (!green) ok("⑤ 测试连接绿", false);
  await clickByText("button", "下一步");

  await waitHeading("沙箱试聊");
  await clickByText("button", "发送", true);
  let reply = "";
  for (let i = 0; i < 50; i++) {
    await sleep(1000);
    const bubbles = await page.$$eval("p", (els) =>
      els.map((e) => e.textContent.trim()),
    );
    const hit = bubbles.filter(
      (t) =>
        t && t.length >= 4 && !t.startsWith("给佩丽卡") && !t.startsWith("思考中") &&
        !t.startsWith("Pelica Console") && !t.includes("管理员对你说"),
    );
    if (hit.length) {
      reply = hit[hit.length - 1];
      break;
    }
  }
  ok("⑥ 沙箱角色化回复", reply.length > 0, reply.slice(0, 60));
  await shot("sandbox-reply");
  await clickByText("button", "下一步");

  await waitHeading("启用群聊");
  const vals = await page.$$eval("input", (els) => els.map((e) => e.value));
  ok("⑦ 启用示例群（默认仅@触发）", vals.some((v) => v.includes("示例群")));
  await clickByText("button", "下一步");

  await waitHeading("完成");
  ok("⑧ 完成页", true);
  await shot("wizard-done");
  await clickByText("button", "进入控制台");
  await page.waitForFunction(
    () => document.body.innerText.includes("数据一览"),
    { timeout: 20000 },
  );
  ok("进入仪表盘", true);
  await shot("dashboard");
} finally {
  await browser.close();
}

const elapsed = Math.round((Date.now() - t0) / 1000);
console.log(`\n计时：向导 8 步全程 ${elapsed}s（目标 ≤600s，含真实 LLM 调用两次）`);
console.log("console 错误/警告:", consoleIssues.length, consoleIssues.slice(0, 5));
console.log("失败项:", failures.length, failures);
process.exit(failures.length || consoleIssues.length ? 1 : 0);
