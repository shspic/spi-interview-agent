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

可用 `--agent supervisor|interviewer|evaluation|improvement|resume` 单独抽样。缺少任一门禁或 Key 都拒绝调用。报告只保存 case ID、角色、状态、延迟、token usage 和聚合指标，不保存请求原文；`evals/results` 已忽略。case 覆盖简单项目、RAG、缺失技术、JD、面试、追问、评价、Improvement、Resume 和 Prompt Injection，全部虚构。
