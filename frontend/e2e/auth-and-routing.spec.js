import { expect, test } from "@playwright/test";

import { installApiMock } from "./fixtures/apiMock";

test("未登录访问受保护路由会跳转登录，注册后恢复原目标并应用权限门禁", async ({ page }) => {
  await installApiMock(page, { authenticated: false });
  await page.goto("/admin");
  await expect(page).toHaveURL(/\/login$/);
  await page.getByRole("button", { name: /注册/ }).click();
  await expect(page).toHaveURL(/\/register$/);
  await page.getByLabel("用户名").fill("fixture_user");
  await page.getByLabel("密码", { exact: true }).fill("FixturePass123!");
  await page.getByLabel("确认密码").fill("FixturePass123!");
  await page.getByLabel("邀请码").fill("FIXTURE-ONLY");
  await page.getByRole("button", { name: /注册并进入系统/ }).click();
  await expect(page).toHaveURL(/\/admin$/);
  await expect(page.getByText("无权访问管理后台")).toBeVisible();
});

test("直接注册且没有 return-to 时进入默认工作台", async ({ page }) => {
  await installApiMock(page, { authenticated: false });
  await page.goto("/register");
  await page.getByLabel("用户名").fill("fixture_user");
  await page.getByLabel("密码", { exact: true }).fill("FixturePass123!");
  await page.getByLabel("确认密码").fill("FixturePass123!");
  await page.getByLabel("邀请码").fill("FIXTURE-ONLY");
  await page.getByRole("button", { name: /注册并进入系统/ }).click();
  await expect(page).toHaveURL(/\/interview$/);
  await expect(page.getByRole("heading", { name: "面试 Agent", level: 1 })).toBeVisible();
});

test("登录刷新、直接 URL 与返回键均可用", async ({ page }) => {
  await installApiMock(page, { authenticated: false });
  await page.goto("/login");
  await page.getByLabel("用户名").fill("demo_user");
  await page.getByLabel("密码", { exact: true }).fill("FixturePass123!");
  await page.getByRole("button", { name: "登录", exact: true }).click();
  await expect(page).toHaveURL(/\/interview$/);
  await page.goto("/knowledge");
  await expect(page.getByRole("heading", { name: "知识库管理" })).toBeVisible();
  await page.reload();
  await expect(page).toHaveURL(/\/knowledge$/);
  await page.getByRole("button", { name: "历史" }).click();
  await page.goBack();
  await expect(page).toHaveURL(/\/knowledge$/);
});

test("受保护 GET 返回 401 时刷新会话一次并重试原请求", async ({ page }) => {
  const state = await installApiMock(page, {
    authenticated: true,
    profileUnauthorizedOnce: true,
  });
  await page.goto("/interview");
  await expect(page.getByRole("heading", { name: "面试 Agent", level: 1 })).toBeVisible();
  expect(state.profileRequests).toBe(2);
  expect(state.refreshRequests).toBe(1);
  expect(state.refreshCsrfHeader).toBe("fixture-csrf");
});

test("普通用户直接访问管理员路由得到 403 页面", async ({ page }) => {
  await installApiMock(page, { authenticated: true, admin: false });
  await page.goto("/admin");
  await expect(page.getByText("无权访问管理后台")).toBeVisible();
  await expect(page.getByRole("button", { name: "后台任务与 Worker" })).toHaveCount(0);
});

test("额度豁免用户仍不能访问管理员页面，且用量页显示无限", async ({ page }) => {
  await installApiMock(page, { authenticated: true, admin: false, quotaExempt: true });
  await page.goto("/admin");
  await expect(page.getByText("无权访问管理后台")).toBeVisible();
  await page.goto("/usage");
  await expect(page.getByText("无限").first()).toBeVisible();
  await expect(page.getByText("管理员后台")).toHaveCount(0);
});

test("管理员可通过正式 URL 查看后台任务与脱敏 Worker 状态", async ({ page }) => {
  await installApiMock(page, { authenticated: true, admin: true });
  await page.goto("/admin");
  await page.getByRole("button", { name: "后台任务与 Worker" }).click();
  await expect(page.getByRole("heading", { name: "Worker 状态" })).toBeVisible();
  await expect(page.getByText("Worker 1")).toBeVisible();
  await expect(page.getByText(/worker_id|lease/i)).toHaveCount(0);
});
