import { useCallback, useEffect, useState } from "react";

import apiClient from "../api/client";
import StatePanel from "../components/StatePanel";

const checks = [
  ["auth_ready", "认证配置", "登录与会话配置可用"],
  ["database_ready", "数据库", "应用可以连接数据库"],
  ["schema_ready", "数据库版本", "迁移版本与应用一致"],
  ["storage_ready", "持久目录", "上传与知识索引目录可用"],
  ["task_system_ready", "后台任务表", "任务数据结构已就绪"],
  ["worker_ready", "Worker", "最近收到 Worker 心跳"],
];

function SystemStatus() {
  const [status, setStatus] = useState(null);
  const [details, setDetails] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const fetchStatus = useCallback(async () => {
    setLoading(true);
    setError("");
    const [readyResult, detailResult] = await Promise.allSettled([
      apiClient.get("/api/health/ready"),
      apiClient.get("/api/system/status"),
    ]);
    const readyData = readyResult.status === "fulfilled" ? readyResult.value.data : readyResult.reason.response?.data;
    setStatus(readyData || null);
    if (detailResult.status === "fulfilled") setDetails(detailResult.value.data);
    if (!readyData) setError("无法连接后端服务，请确认服务已启动后重试。");
    setLoading(false);
  }, []);

  useEffect(() => {
    const timer = window.setTimeout(fetchStatus, 0);
    return () => window.clearTimeout(timer);
  }, [fetchStatus]);

  return (
    <section className="system-status-page">
      <div className="page-heading-row"><div><h1>系统状态</h1><p>这里展示用户可理解的可用性信息，不会显示 Secret、物理路径或连接凭据。</p></div><button type="button" onClick={fetchStatus} disabled={loading}>{loading ? "检查中..." : "重新检查"}</button></div>
      {error && <StatePanel tone="error" title="服务不可达" description={error} actionLabel="重试" onAction={fetchStatus} />}
      {status && <StatePanel tone={status.status === "ready" ? "success" : "warning"} title={status.status === "ready" ? "核心服务已就绪" : "服务处于降级状态"} description={status.status === "ready" ? "可以继续使用面试训练与资料管理。" : "部分能力暂不可用，请查看下方检查项。"} />}
      {status && <div className="health-check-grid">{checks.map(([key, label, description]) => <article key={key} className={status[key] ? "is-ready" : "is-degraded"}><span>{status[key] ? "可用" : "需检查"}</span><h2>{label}</h2><p>{description}</p></article>)}</div>}
      {details && <div className="status-summary-grid"><article><span>数据库类型</span><strong>{status?.database_type === "postgresql" ? "PostgreSQL" : "SQLite（本地）"}</strong></article><article><span>资料文件</span><strong>{details.database?.file_count ?? 0}</strong></article><article><span>面试记录</span><strong>{details.database?.interview_count ?? 0}</strong></article><article><span>知识片段</span><strong>{details.knowledge_base?.total_chunks ?? 0}</strong></article></div>}
    </section>
  );
}

export default SystemStatus;
