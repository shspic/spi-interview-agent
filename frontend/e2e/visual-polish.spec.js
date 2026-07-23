import { expect, test } from "@playwright/test";

import { installApiMock } from "./fixtures/apiMock";

const protectedRoutes = [
  "/interview",
  "/knowledge",
  "/history",
  "/profile",
  "/usage",
  "/settings",
  "/admin",
];

async function expectDarkSurface(locator) {
  await expect(locator).toBeVisible();
  const background = await locator.evaluate((element) => getComputedStyle(element).backgroundColor);
  const channels = background.match(/[\d.]+/g)?.slice(0, 3).map(Number) || [];
  expect(channels).toHaveLength(3);
  expect(Math.max(...channels)).toBeLessThan(190);
}

async function expectReadable(locator, minimum = 4.5) {
  await expect(locator).toBeVisible();
  const ratio = await locator.evaluate((element) => {
    const parse = (value) => {
      const parts = value.match(/[\d.]+/g)?.map(Number) || [];
      return [parts[0] || 0, parts[1] || 0, parts[2] || 0, parts[3] ?? 1];
    };
    const composite = (front, back) => {
      const alpha = front[3] + back[3] * (1 - front[3]);
      if (alpha === 0) return [0, 0, 0, 0];
      return [
        (front[0] * front[3] + back[0] * back[3] * (1 - front[3])) / alpha,
        (front[1] * front[3] + back[1] * back[3] * (1 - front[3])) / alpha,
        (front[2] * front[3] + back[2] * back[3] * (1 - front[3])) / alpha,
        alpha,
      ];
    };
    const layers = [];
    for (let current = element; current; current = current.parentElement) {
      layers.push(parse(getComputedStyle(current).backgroundColor));
    }
    let background = [10, 21, 32, 1];
    for (const layer of layers.reverse()) background = composite(layer, background);
    const foreground = composite(parse(getComputedStyle(element).color), background);
    const luminance = ([red, green, blue]) => {
      const channels = [red, green, blue].map((channel) => {
        const normalized = channel / 255;
        return normalized <= 0.03928
          ? normalized / 12.92
          : ((normalized + 0.055) / 1.055) ** 2.4;
      });
      return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2];
    };
    const lighter = Math.max(luminance(foreground), luminance(background));
    const darker = Math.min(luminance(foreground), luminance(background));
    return (lighter + 0.05) / (darker + 0.05);
  });
  expect(ratio).toBeGreaterThanOrEqual(minimum);
}

test("公共与主要业务路由的标签页标题始终严格为 AURORA", async ({ page }) => {
  await installApiMock(page, { authenticated: false });
  for (const route of ["/login", "/register"]) {
    await page.goto(route);
    await expect(page).toHaveTitle("AURORA");
  }

  await page.unrouteAll();
  await installApiMock(page, { authenticated: true, admin: true });
  for (const route of protectedRoutes) {
    await page.goto(route);
    await expect(page).toHaveTitle("AURORA");
  }
});

test("认证舱展示完整网站简介，减少动态效果时改为静态列表", async ({ page }) => {
  await installApiMock(page, { authenticated: false });
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/login");

  await expect(page.getByRole("heading", { name: "从真实资料出发，完成一场可复盘的面试训练" })).toBeVisible();
  await expect(page.getByText(/AURORA 面向 AI 应用开发、Python 后端、RAG 与 Agent 岗位/)).toBeVisible();
  const featureWindow = page.locator(".auth-feature-window");
  await expect(featureWindow).toBeVisible();
  await expect(featureWindow.locator("li")).toHaveCount(5);
  await expect(featureWindow.locator("li").last()).toBeVisible();
  await expect(featureWindow.locator(".auth-feature-list")).toHaveCSS("animation-name", "none");
});

for (const route of ["/login", "/register"]) {
  test(`${route} 在 375px 下无横向溢出且简介可见`, async ({ page }) => {
    await installApiMock(page, { authenticated: false });
    await page.setViewportSize({ width: 375, height: 812 });
    await page.goto(route);
    await expect(page.getByText(/从真实资料出发/)).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true);
  });
}

test("关键业务面板、统计卡与表格均使用深色任务舰桥表面", async ({ page }) => {
  const file = {
    file_id: "fixture-file-1",
    filename: "用于视觉回归的项目资料.md",
    file_type: "md",
    category: "project",
    status: "uploaded",
    created_at: "2026-07-20T10:00:00Z",
  };
  await installApiMock(page, {
    authenticated: true,
    admin: true,
    files: [file],
  });

  await page.goto("/interview");
  await expectDarkSurface(page.locator(".interview-setup-form"));
  await expectDarkSurface(page.locator(".recent-sessions"));

  await page.setViewportSize({ width: 375, height: 812 });
  await page.goto("/knowledge");
  await expectDarkSurface(page.locator(".status-box"));
  await expectDarkSurface(page.locator(".file-table"));
  await expectDarkSurface(page.locator(".file-table th").first());
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true);

  await page.unrouteAll();
  await installApiMock(page, {
    authenticated: true,
    admin: true,
    interviewEvaluation: true,
    files: [file],
  });
  await page.goto("/history");
  await expectDarkSurface(page.locator(".file-table"));
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true);

  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/profile");
  await expectDarkSurface(page.locator(".profile-completion > div").first());
  await expectDarkSurface(page.locator(".target-job-item").first());

  await page.goto("/usage");
  await expectDarkSurface(page.locator(".usage-card").first());

  await page.goto("/settings");
  await expectDarkSurface(page.locator(".settings-section").first());

  await page.goto("/admin");
  await expectDarkSurface(page.locator(".admin-tabs"));
  await expectDarkSurface(page.locator(".admin-metric-grid article").first());

  await page.goto("/system");
  await expectDarkSurface(page.locator(".system-status-page .state-panel"));
  await expect(page.getByRole("heading", { name: "系统状态", level: 1 })).toBeVisible();
});

test("真实删除操作使用红色危险样式，普通按钮不被误标", async ({ page }) => {
  const file = {
    file_id: "fixture-file-1",
    filename: "danger-style.md",
    file_type: "md",
    category: "project",
    status: "uploaded",
    created_at: "2026-07-20T10:00:00Z",
  };
  await installApiMock(page, {
    authenticated: true,
    interviewEvaluation: true,
    files: [file],
  });

  await page.goto("/knowledge");
  const fileDelete = page.getByRole("button", { name: "删除", exact: true });
  await expect(fileDelete).toHaveClass(/danger-button/);
  const fileDeleteColor = await fileDelete.evaluate((element) => getComputedStyle(element).color);
  const [fileRed, fileGreen] = fileDeleteColor.match(/\d+/g).map(Number);
  expect(fileRed).toBeGreaterThan(fileGreen);
  await expect(page.getByRole("button", { name: "刷新列表" })).not.toHaveClass(/danger/);

  await page.goto("/interview");
  const sessionDelete = page.getByRole("button", { name: /删除 快速练习/ });
  await expect(sessionDelete).toHaveClass(/danger-button/);
  await expect(page.getByRole("button", { name: "刷新数据" })).not.toHaveClass(/danger/);
});

test("关键正文、说明、表单标签与表格文字达到可读对比度", async ({ page }) => {
  const file = {
    file_id: "fixture-file-1",
    filename: "contrast-audit.md",
    file_type: "md",
    category: "project",
    status: "uploaded",
    created_at: "2026-07-20T10:00:00Z",
  };
  await installApiMock(page, { authenticated: true, admin: true, files: [file] });

  await page.goto("/interview");
  await expectReadable(page.locator(".top-panel h2"));
  await expectReadable(page.locator(".top-panel p").last());
  await expectReadable(page.locator(".interview-agent-heading p"));
  await expectReadable(page.locator(".mode-selector label").nth(1).locator("span"));
  await expectReadable(page.locator(".field-group label").first());

  await page.goto("/knowledge");
  await expectReadable(page.locator(".status-box p").first());
  await expectReadable(page.locator(".file-table th").first());
  await expectReadable(page.locator(".file-table td").first());

  await page.goto("/profile");
  await expectReadable(page.locator(".profile-form label").first());

  await page.goto("/usage");
  await expectReadable(page.locator(".usage-card-heading h2").first());
  await expectReadable(page.locator(".usage-metrics dt").first());

  await page.goto("/settings");
  await expectReadable(page.locator(".settings-form label").first());

  await page.goto("/admin");
  await expectReadable(page.locator(".admin-tabs button").filter({ hasText: "用户管理" }));
  await expectReadable(page.locator(".admin-metric-grid span").first());
});

test("创建面试与提交回答立即显示可访问 Loader，并在成功后停止", async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  await installApiMock(page, { taskPollDelayMs: 800 });
  await page.goto("/interview");
  await page.getByRole("button", { name: "创建并开始" }).click();
  const startLoader = page.locator(".aurora-task-loader");
  await expect(startLoader).toBeVisible();
  await expect(startLoader).toHaveAttribute("role", "status");
  await expect(startLoader).toHaveAttribute("aria-busy", "true");
  await expect(startLoader.locator(".aurora-loader-orbit")).toHaveCSS("animation-name", "none");
  await expect(page.getByRole("button", { name: /正在创建并启动/ })).toBeDisabled();
  await expect(page.getByText("请介绍一次你处理后台任务可靠性的经历。")).toBeVisible();
  await expect(startLoader).toHaveCount(0);

  await page.unrouteAll();
  await installApiMock(page, {
    interviewEvaluation: true,
    jobStatus: "succeeded",
    taskPollDelayMs: 800,
  });
  await page.goto("/interview");
  await page.getByLabel("你的回答").fill("使用幂等键和租约确保任务可靠执行。");
  await page.getByRole("button", { name: "提交回答" }).click();
  const answerLoader = page.locator(".aurora-task-loader");
  await expect(answerLoader).toBeVisible();
  await expect(page.getByRole("button", { name: "处理中..." })).toBeDisabled();
  await expect(page.getByText("回答评价已完成。")).toBeVisible();
  await expect(answerLoader).toHaveCount(0);
});

test("回答失败后 Loader 停止并保留明确恢复入口", async ({ page }) => {
  await installApiMock(page, {
    interviewEvaluation: true,
    jobStatus: "failed",
    taskPollDelayMs: 500,
  });
  await page.goto("/interview");
  await page.getByLabel("你的回答").fill("使用幂等键和租约确保任务可靠执行。");
  await page.getByRole("button", { name: "提交回答" }).click();
  await expect(page.locator(".aurora-task-loader")).toBeVisible();
  await expect(page.getByText("执行失败", { exact: true })).toBeVisible();
  await expect(page.locator(".aurora-task-loader")).toHaveCount(0);
  await expect(page.getByRole("button", { name: "刷新恢复状态" })).toBeVisible();
  await expect(page.getByText("回答已保存，评价待恢复")).toBeVisible();
});

for (const viewport of [
  { width: 375, height: 812 },
  { width: 768, height: 1024 },
  { width: 1024, height: 768 },
  { width: 1440, height: 900 },
]) {
  test(`主要业务路由在 ${viewport.width}px 下无整页横向溢出`, async ({ page }) => {
    await installApiMock(page, { authenticated: true, admin: true });
    await page.setViewportSize(viewport);
    for (const route of [...protectedRoutes, "/system"]) {
      await page.goto(route);
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true);
    }
  });
}
