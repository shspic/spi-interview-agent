import { expect, test } from "@playwright/test";

import { installApiMock } from "./fixtures/apiMock";

const pendingRequest = {
  id: 42,
  user_id: 2,
  username: "synthetic_user",
  status: "pending",
  request_note: "通过可信渠道联系",
  admin_note: "",
  requested_at: "2026-07-23T08:00:00Z",
  processed_at: null,
  processed_by_user_id: null,
  created_at: "2026-07-23T08:00:00Z",
  updated_at: "2026-07-23T08:00:00Z",
};

test("AURORA 品牌与登录、注册的密码重置入口一致", async ({ page }) => {
  await installApiMock(page, { authenticated: false });
  await page.goto("/login");
  await expect(page).toHaveTitle(/AURORA/);
  await expect(page.getByText("AI Interview Intelligence").first()).toBeVisible();
  await expect(page.getByText("让潜力被看见，让成长有迹可循")).toBeVisible();
  await expect(page.getByRole("img", { name: "AURORA 环轨标志" }).first()).toBeVisible();
  await expect(page.getByRole("button", { name: "忘记密码？申请重置" })).toBeVisible();
  await page.getByRole("button", { name: /注册/ }).click();
  await expect(page.getByRole("button", { name: "忘记密码？申请重置" })).toBeVisible();
});

test("存在、不存在与重复申请显示同一匿名提示", async ({ page }) => {
  await installApiMock(page, { authenticated: false });
  await page.goto("/password-reset");
  for (const username of ["synthetic_user", "missing_user", "synthetic_user"]) {
    await page.getByLabel("用户名").fill(username);
    await page.getByRole("button", { name: "提交重置申请" }).click();
    await expect(page.getByText("如果账号存在且申请信息有效，管理员会处理你的申请。")).toBeVisible();
  }
});

test("普通用户不可见审批，管理员批准后密码只在 Modal 显示一次", async ({ page }) => {
  await installApiMock(page, { authenticated: true, admin: false, resetRequests: [pendingRequest] });
  await page.goto("/admin");
  await expect(page.getByText("无权访问管理后台")).toBeVisible();
  await expect(page.getByRole("button", { name: "密码重置申请" })).toHaveCount(0);

  await page.unrouteAll();
  await installApiMock(page, { authenticated: true, admin: true, resetRequests: [pendingRequest] });
  await page.goto("/admin");
  await page.getByRole("button", { name: "密码重置申请" }).click();
  await expect(page.getByText("synthetic_user")).toBeVisible();
  await page.getByRole("button", { name: "处理申请" }).click();
  await page.getByLabel("管理员备注").fill("已完成合成身份核验");
  await page.getByRole("button", { name: "批准并生成临时密码" }).click();
  const secret = page.getByLabel("一次性临时密码");
  await expect(secret).toHaveText("Synthetic-Temp-4821!");
  await page.getByRole("button", { name: "复制临时密码" }).click();
  await expect(page.getByText("临时密码已复制。")).toBeVisible();
  await page.getByRole("button", { name: "关闭并清除" }).click();
  await expect(secret).toHaveCount(0);
  await expect(page.getByText("Synthetic-Temp-4821!")).toHaveCount(0);
});

test("临时密码状态强制跳转且不能绕过进入业务或管理页", async ({ page }) => {
  await installApiMock(page, { authenticated: true, admin: true, mustChangePassword: true });
  await page.goto("/interview");
  await expect(page).toHaveURL(/\/change-temporary-password$/);
  await expect(page.getByRole("heading", { name: "需要更新密码" })).toBeVisible();
  await page.goto("/admin");
  await expect(page).toHaveURL(/\/change-temporary-password$/);
  await page.getByLabel("新密码", { exact: true }).fill("Synthetic-New-4821!");
  await page.getByLabel("确认新密码").fill("Synthetic-New-4821!");
  await page.getByRole("button", { name: "更新密码并重新登录" }).click();
  await expect(page).toHaveURL(/\/login$/);
  await page.getByLabel("用户名").fill("synthetic_user");
  await page.getByLabel("密码", { exact: true }).fill("Synthetic-New-4821!");
  await page.getByRole("button", { name: "登录 AURORA" }).click();
  await expect(page).toHaveURL(/\/admin$/);
  await expect(page.getByRole("heading", { name: "管理后台", level: 1 })).toBeVisible();
});

for (const viewport of [
  { width: 375, height: 812 },
  { width: 768, height: 1024 },
  { width: 1024, height: 768 },
  { width: 1440, height: 900 },
]) {
  test(`AURORA 主界面在 ${viewport.width}px 无横向溢出`, async ({ page }) => {
    await installApiMock(page);
    await page.setViewportSize(viewport);
    await page.goto("/interview");
    await expect(page.getByRole("heading", { name: "模拟面试" })).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true);
  });
}
