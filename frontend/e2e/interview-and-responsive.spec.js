import { expect, test } from "@playwright/test";

import { installApiMock } from "./fixtures/apiMock";

test("创建面试后通过 BackgroundJob 进入首题", async ({ page }) => {
  await installApiMock(page);
  await page.goto("/interview");
  await page.getByLabel("会话标题（可选）").fill("端到端虚构面试");
  await page.getByRole("button", { name: "创建并开始" }).click();
  await expect(page.getByText("请介绍一次你处理后台任务可靠性的经历。")).toBeVisible();
  await expect(page.getByText("面试会话已启动。")).toBeVisible();
});

test("readiness 降级在系统页可解释且不白屏", async ({ page }) => {
  await installApiMock(page, { degraded: true });
  await page.goto("/system");
  await expect(page.getByText("服务处于降级状态")).toBeVisible();
  await expect(page.getByText("数据库")).toBeVisible();
});

test("桌面与 390px 主页面无整页横向溢出并保留可用导航", async ({ page }, testInfo) => {
  await installApiMock(page);
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/interview");
  await expect(page.getByRole("heading", { name: "面试 Agent" })).toBeVisible();
  await page.screenshot({ path: testInfo.outputPath("interview-desktop.png"), fullPage: true });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true);

  await page.setViewportSize({ width: 390, height: 844 });
  await page.reload();
  await page.getByRole("button", { name: "导航" }).click();
  await expect(page.getByRole("button", { name: "知识库" })).toBeVisible();
  await page.screenshot({ path: testInfo.outputPath("interview-mobile.png"), fullPage: true });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true);
});
