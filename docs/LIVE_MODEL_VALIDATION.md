# 真实模型验证安全门禁

默认命令不联网、不产生费用：

```powershell
.venv\Scripts\python.exe -m evals.run_live_agent_smoke --check
```

它只读取仓库内 9 个虚构 case，输出 key 是否配置的布尔值、模型名、case/调用/token/成本上限，不构造网络客户端，不显示 API Key，也不读取数据库、uploads 或 Chroma。

后续人工真实验证必须同时满足：

```powershell
$env:ALLOW_LIVE_MODEL_EVAL="1"
$env:LIVE_MODEL_ESTIMATED_COST_CAP_USD="0.10"
.venv\Scripts\python.exe -m evals.run_live_agent_smoke `
  --allow-network --confirm-cost --max-cases 5 --max-calls 10 `
  --max-estimated-tokens 50000
```

命令会先再次显示 case 数、最大调用次数、最大 Token 和预计成本上限；只有人工精确输入 `I_ACCEPT_LIVE_MODEL_COST` 才继续。命令行 flag 不能代替这次交互确认。

可用 `--agent supervisor|interviewer|evaluation|improvement|resume` 单独抽样。缺少任一门禁或 Key 都拒绝调用。报告只保存 case ID、角色、状态、延迟、token usage 和聚合指标，不保存请求原文；`evals/results` 已忽略。工具同时生成 `live-smoke-human-review.md`，供人工把问题自然度、追问合理性、评分公平性、证据忠实度、优化答案自然度、Resume 是否夸大标为通过、勉强或失败。工具不会根据评分自动改 Prompt。case 覆盖简单项目、RAG、缺失技术、JD、面试、追问、评价、Improvement、Resume 和 Prompt Injection，全部虚构。
