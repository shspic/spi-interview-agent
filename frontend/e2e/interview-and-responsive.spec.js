import { expect, test } from "@playwright/test";

import { installApiMock } from "./fixtures/apiMock";

const evaluationAnswer = "我使用幂等键、lease 和 heartbeat 防止后台任务重复执行。";

async function submitEvaluationAnswer(page) {
  await expect(page.getByText("请介绍一次你处理后台任务可靠性的经历。")).toBeVisible();
  await page.getByLabel("你的回答").fill(evaluationAnswer);
  await page.getByRole("button", { name: "提交回答" }).click();
}

test("创建面试后通过 BackgroundJob 进入首题", async ({ page }) => {
  const state = await installApiMock(page);
  await page.goto("/interview");
  await page.getByLabel("会话标题（可选）").fill("端到端虚构面试");
  await page.getByRole("button", { name: "创建并开始" }).click();
  await expect(page.getByText("请介绍一次你处理后台任务可靠性的经历。")).toBeVisible();
  await expect(page.getByText("面试会话已启动。")).toBeVisible();
  expect(state.sessionDetailRequests).toBe(1);
});

test("评价成功仍只执行一次成功刷新并展示结果", async ({ page }) => {
  const state = await installApiMock(page, {
    interviewEvaluation: true,
    jobStatus: "succeeded",
  });
  await page.goto("/interview");
  await submitEvaluationAnswer(page);

  await expect(page.getByText("回答评价已完成。")).toBeVisible();
  await expect(page.getByText("我通过 lease、heartbeat 和幂等键避免任务重复执行。")).toBeVisible();
  await expect(page.getByText("已完成", { exact: true })).toBeVisible();
  expect(state.evaluationRequests).toBe(1);
  expect(state.evaluationCsrfHeader).toBe("fixture-csrf");
  expect(state.sessionDetailRequests).toBe(2);
});

test("主问题和两次追问按各自 Turn 展示不同内容", async ({ page }) => {
  await page.addInitScript(() => {
    window.localStorage.setItem("spi_interview_active_session", "7");
  });
  await installApiMock(page, { completedQuestionHistory: true });

  await page.goto("/interview");
  await expect(
    page.getByText("请介绍一次你处理后台任务可靠性的经历。"),
  ).toBeVisible();

  const questions = await page.locator("article.turn-review > h4").allTextContents();
  expect(questions).toEqual([
    "请介绍一次你处理后台任务可靠性的经历。",
    "你如何验证任务不会被重复执行？",
    "该方案上线后的结果通过什么证据得到确认？",
  ]);
  expect(new Set(questions).size).toBe(3);
  await expect(page.getByText("追问 1", { exact: true })).toBeVisible();
  await expect(page.getByText("追问 2", { exact: true })).toBeVisible();
});

for (const terminal of [
  { status: "failed", label: "执行失败" },
  { status: "timed_out", label: "已超时" },
  { status: "cancelled", label: "已取消" },
]) {
  test(`评价 ${terminal.status} 后自动刷新一次并锁定已保存回答`, async ({ page }) => {
    const state = await installApiMock(page, {
      interviewEvaluation: true,
      jobStatus: terminal.status,
    });
    await page.goto("/interview");
    await submitEvaluationAnswer(page);

    await expect(page.getByText(terminal.label, { exact: true })).toBeVisible();
    await expect(page.getByText("回答已保存，评价待恢复")).toBeVisible();
    await expect(page.getByLabel("你的回答")).toHaveValue(evaluationAnswer);
    await expect(page.getByLabel("你的回答")).toBeDisabled();
    expect(state.evaluationRequests).toBe(1);
    expect(state.sessionDetailRequests).toBe(2);
  });
}

test("相同失败终态由并发轮询返回时只执行一次刷新", async ({ page }) => {
  await page.addInitScript(() => {
    window.localStorage.setItem("spi.background-job.interview-evaluation", "fixture-task-1");
  });
  const state = await installApiMock(page, {
    interviewEvaluation: true,
    jobStatus: "failed",
    taskPollDelayMs: 1200,
  });
  const restoredPoll = page.waitForRequest((request) => (
    request.method() === "GET"
      && new URL(request.url()).pathname === "/api/tasks/fixture-task-1"
  ));
  await page.goto("/interview");
  await restoredPoll;
  await submitEvaluationAnswer(page);

  await expect(page.getByText("回答已保存，评价待恢复")).toBeVisible();
  expect(state.taskPolls).toBeGreaterThanOrEqual(2);
  expect(state.sessionDetailRequests).toBe(2);
});

test("评价轮询完成前卸载组件不会触发终态刷新", async ({ page }) => {
  await page.addInitScript(() => {
    window.localStorage.setItem("spi.background-job.interview-evaluation", "fixture-task-1");
  });
  const state = await installApiMock(page, {
    interviewEvaluation: true,
    jobStatus: "failed",
    taskPollDelayMs: 1200,
  });
  const restoredPoll = page.waitForRequest((request) => (
    request.method() === "GET"
      && new URL(request.url()).pathname === "/api/tasks/fixture-task-1"
  ));
  await page.goto("/interview");
  await restoredPoll;
  await expect(page.getByText("请介绍一次你处理后台任务可靠性的经历。")).toBeVisible();
  await page.goto("/system");
  await expect(page.getByRole("heading", { name: "系统状态", level: 1 })).toBeVisible();
  await page.waitForTimeout(1400);

  expect(state.taskPolls).toBe(1);
  expect(state.sessionDetailRequests).toBe(1);
});

test("评价失败后的 Session 刷新失败仍保留任务错误", async ({ page }) => {
  const state = await installApiMock(page, {
    interviewEvaluation: true,
    jobStatus: "failed",
    sessionRefreshFailure: true,
  });
  await page.goto("/interview");
  await submitEvaluationAnswer(page);

  await expect(page.getByText("执行失败", { exact: true })).toBeVisible();
  await expect(page.getByText("回答评价任务执行失败")).toBeVisible();
  await expect(page.getByText("服务暂时无法完成请求，请稍后重试。")).toBeVisible();
  expect(state.sessionDetailRequests).toBe(2);
});

test("readiness 降级在系统页可解释且不白屏", async ({ page }) => {
  await installApiMock(page, { degraded: true });
  await page.goto("/system");
  await expect(page.getByText("服务处于降级状态")).toBeVisible();
  await expect(page.getByRole("heading", { name: "数据库", exact: true })).toBeVisible();
});

test("桌面与 390px 主页面无整页横向溢出并保留可用导航", async ({ page }, testInfo) => {
  await installApiMock(page);
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/interview");
  await expect(page.getByRole("heading", { name: "面试 Agent", level: 1 })).toBeVisible();
  await page.screenshot({ path: testInfo.outputPath("interview-desktop.png"), fullPage: true });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true);

  await page.setViewportSize({ width: 390, height: 844 });
  await page.reload();
  await page.getByRole("button", { name: "导航" }).click();
  await expect(page.getByRole("button", { name: "02 知识库", exact: true })).toBeVisible();
  await page.screenshot({ path: testInfo.outputPath("interview-mobile.png"), fullPage: true });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true);
});
