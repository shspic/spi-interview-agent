import { useCallback, useEffect, useState } from "react";

import apiClient from "../api/client";

function SystemStatus() {
  const [status, setStatus] = useState(null);
  const [message, setMessage] = useState("");

  const fetchStatus = useCallback(async () => {
    try {
      setMessage("正在检查系统状态...");
      const response = await apiClient.get("/api/system/status");
      setStatus(response.data);
      setMessage("系统状态检查完成。");
    } catch (error) {
      console.error("system status error:", error);
      const detail = error.response?.data?.detail;
      setMessage(detail || "系统状态检查失败，请确认后端是否启动。");
    }
  }, []);

  useEffect(() => {
    const timerId = window.setTimeout(fetchStatus, 0);

    return () => window.clearTimeout(timerId);
  }, [fetchStatus]);

  return (
    <section>
      <h1>系统状态</h1>
      <p>检查后端、API Key、数据库、知识库索引等状态。</p>

      <div className="chat-actions">
        <button type="button" onClick={fetchStatus}>
          刷新状态
        </button>
      </div>

      {message && <p className="message-text">{message}</p>}

      {status && (
        <div className="status-grid">
          <div className="status-box">
            <h2>后端</h2>
            <p>状态：{status.backend?.status}</p>
            <p>应用名：{status.backend?.app_name}</p>
          </div>

          <div className="status-box">
            <h2>API Key</h2>
            <p>DeepSeek：{status.keys?.deepseek_configured ? "已配置" : "未配置"}</p>
            <p>Tavily：{status.keys?.tavily_configured ? "已配置" : "未配置"}</p>
          </div>

          <div className="status-box">
            <h2>数据库</h2>
            <p>文件记录：{status.database?.file_count}</p>
            <p>历史记录：{status.database?.history_count}</p>
            <p>面试记录：{status.database?.interview_count}</p>
          </div>

          <div className="status-box">
            <h2>知识库</h2>
            <p>文件总数：{status.knowledge_base?.total_files}</p>
            <p>已索引文件：{status.knowledge_base?.indexed_files}</p>
            <p>失败文件：{status.knowledge_base?.failed_files}</p>
            <p>向量片段数：{status.knowledge_base?.total_chunks}</p>
            <p>状态：{status.knowledge_base?.status}</p>
          </div>
        </div>
      )}
    </section>
  );
}

export default SystemStatus;
