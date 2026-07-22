import { expect, test } from "@playwright/test";
import { Buffer } from "node:buffer";

import { installApiMock } from "./fixtures/apiMock";

test("TXT 上传、索引进度、近似搜索与删除形成闭环", async ({ page }) => {
  await installApiMock(page);
  await page.goto("/knowledge");
  await page.locator("#file-input").setInputFiles({ name: "demo-project.txt", mimeType: "text/plain", buffer: Buffer.from("fictional project") });
  await page.getByRole("button", { name: "上传文件" }).click();
  await expect(page.getByText("demo-project.txt")).toBeVisible();
  page.once("dialog", (dialog) => dialog.accept());
  await page.getByRole("button", { name: "重建知识库索引" }).click();
  await expect(page.getByText("已完成", { exact: true })).toBeVisible();
  await expect(page.getByLabel("知识库索引进度 100%")).toBeVisible();
  await page.getByLabel("在我的资料中近似搜索").fill("后台任务如何恢复");
  await page.getByRole("button", { name: "搜索", exact: true }).click();
  await expect(page.getByText(/lease 与 heartbeat/)).toBeVisible();
  page.once("dialog", (dialog) => dialog.accept());
  await page.getByRole("button", { name: "删除", exact: true }).click();
  await expect(page.getByText("暂无上传文件。")).toBeVisible();
});

test("后台任务超时显示可恢复操作，终态停止轮询", async ({ page }) => {
  const state = await installApiMock(page, { jobStatus: "timed_out" });
  await page.addInitScript(() => localStorage.setItem("spi.background-job.knowledge-rebuild", "fixture-task-1"));
  await page.goto("/knowledge");
  await expect(page.getByText("任务超过允许时间", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "重新创建" })).toBeVisible();
  const pollsAtTerminal = state.taskPolls;
  await page.waitForTimeout(1500);
  expect(state.taskPolls).toBe(pollsAtTerminal);
});

test("不支持类型和超大文件在请求前给出明确错误", async ({ page }) => {
  await installApiMock(page);
  await page.goto("/knowledge");
  await expect(page.getByText("知识库状态刷新成功。")).toBeVisible();
  await page.locator("#file-input").setInputFiles({ name: "unsafe.csv", mimeType: "text/csv", buffer: Buffer.from("a,b") });
  await expect(page.getByText("仅可上传 PDF、TXT 或 MD")).toBeVisible();
  await page.locator("#file-input").setInputFiles({ name: "oversize.txt", mimeType: "text/plain", buffer: Buffer.alloc(20 * 1024 * 1024 + 1) });
  await expect(page.getByText("超过 20 MB")).toBeVisible();
});
