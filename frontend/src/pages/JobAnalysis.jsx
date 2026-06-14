import { useState } from "react";

import apiClient from "../api/client";

function JobAnalysis() {
  const [jobDescription, setJobDescription] = useState("");
  const [useWebSearch, setUseWebSearch] = useState(false);
  const [analysis, setAnalysis] = useState("");
  const [sources, setSources] = useState([]);
  const [webSources, setWebSources] = useState([]);
  const [usedLocalKnowledge, setUsedLocalKnowledge] = useState(false);
  const [usedWebSearch, setUsedWebSearch] = useState(false);
  const [historyRecordId, setHistoryRecordId] = useState("");
  const [loading, setLoading] = useState(false);
  const [message, setMessage] = useState("");

  const handleAnalyze = async () => {
    const trimmedJobDescription = jobDescription.trim();

    if (!trimmedJobDescription) {
      setMessage("请先粘贴岗位 JD。");
      return;
    }

    try {
      setLoading(true);
      setMessage(
        useWebSearch
          ? "正在结合本地知识库和联网搜索分析岗位，请稍等..."
          : "正在基于本地知识库分析岗位，请稍等..."
      );

      setAnalysis("");
      setSources([]);
      setWebSources([]);
      setUsedLocalKnowledge(false);
      setUsedWebSearch(false);
      setHistoryRecordId("");

      const response = await apiClient.post("/api/jobs/analyze", {
        job_description: trimmedJobDescription,
        use_web_search: useWebSearch,
      });

      setAnalysis(response.data.analysis || "");
      setSources(response.data.sources || []);
      setWebSources(response.data.web_sources || []);
      setUsedLocalKnowledge(Boolean(response.data.used_local_knowledge));
      setUsedWebSearch(Boolean(response.data.used_web_search));
      setHistoryRecordId(response.data.history_record_id || "");
      setMessage("岗位分析完成。");
    } catch (error) {
      console.error("job analysis error:", error);

      const status = error.response?.status;
      const detail = error.response?.data?.detail;
      const code = error.code;
      const errorMessage = error.message;

      setMessage(
        detail ||
          `岗位分析失败。status=${status || "无"}，code=${
            code || "无"
          }，message=${errorMessage || "无"}`
      );
    } finally {
      setLoading(false);
    }
  };

  const handleClear = () => {
    setJobDescription("");
    setUseWebSearch(false);
    setAnalysis("");
    setSources([]);
    setWebSources([]);
    setUsedLocalKnowledge(false);
    setUsedWebSearch(false);
    setHistoryRecordId("");
    setMessage("");
  };

  return (
    <section>
      <h1>岗位分析</h1>

      <p>
        粘贴 AI 实习、后端开发、大模型应用开发等岗位 JD，系统会结合本地知识库分析岗位匹配点、短板、简历优化方向和可能面试问题。
      </p>

      <div className="job-analysis-panel">
        <label htmlFor="job-description">岗位 JD</label>

        <textarea
          id="job-description"
          value={jobDescription}
          onChange={(event) => setJobDescription(event.target.value)}
          placeholder="请粘贴岗位职责、任职要求、加分项等完整 JD..."
          rows={12}
        />

        <label className="web-search-option">
          <input
            type="checkbox"
            checked={useWebSearch}
            onChange={(event) => setUseWebSearch(event.target.checked)}
            disabled={loading}
          />
          <span>启用 Tavily 联网搜索，补充当前岗位市场信息</span>
        </label>

        <p className="helper-text">
          不勾选时只基于本地知识库分析；勾选后会额外调用 Tavily 搜索岗位相关信息。
        </p>

        <div className="chat-actions">
          <button type="button" onClick={handleAnalyze} disabled={loading}>
            {loading ? "分析中..." : "开始分析"}
          </button>

          <button
            type="button"
            className="secondary-button"
            onClick={handleClear}
            disabled={loading}
          >
            清空
          </button>
        </div>
      </div>

      {message && <p className="message-text">{message}</p>}

      {analysis && (
        <div className="answer-card">
          <h2>岗位分析结果</h2>
          <div className="answer-content">{analysis}</div>
        </div>
      )}

      {analysis && (
        <div className="source-summary">
          <p>
            本地知识库：
            <strong>{usedLocalKnowledge ? "已使用" : "未使用"}</strong>
          </p>

          <p>
            联网搜索：
            <strong>{usedWebSearch ? "已使用" : "未使用"}</strong>
          </p>

          {historyRecordId && (
            <p>
              历史记录 ID：<code>{historyRecordId}</code>
            </p>
          )}
        </div>
      )}

      {sources.length > 0 && (
        <div className="sources-panel">
          <h2>本地知识库引用来源</h2>

          <table className="file-table">
            <thead>
              <tr>
                <th>文件名</th>
                <th>类型</th>
                <th>Chunk</th>
                <th>距离</th>
              </tr>
            </thead>

            <tbody>
              {sources.map((source, index) => (
                <tr key={`${source.file_id}-${source.chunk_index}-${index}`}>
                  <td>{source.filename || "未知文件"}</td>
                  <td>{source.file_type || "-"}</td>
                  <td>{source.chunk_index ?? "-"}</td>
                  <td>
                    {source.distance === null || source.distance === undefined
                      ? "-"
                      : Number(source.distance).toFixed(4)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {webSources.length > 0 && (
        <div className="web-sources-panel">
          <h2>联网搜索来源</h2>

          <table className="file-table">
            <thead>
              <tr>
                <th>标题</th>
                <th>内容摘要</th>
                <th>相关度</th>
                <th>发布日期</th>
                <th>链接</th>
              </tr>
            </thead>

            <tbody>
              {webSources.map((source, index) => (
                <tr key={`${source.url}-${index}`}>
                  <td>{source.title || "未知标题"}</td>
                  <td className="long-cell">{source.content || "-"}</td>
                  <td>
                    {source.score === null || source.score === undefined
                      ? "-"
                      : Number(source.score).toFixed(4)}
                  </td>
                  <td>{source.published_date || "-"}</td>
                  <td>
                    {source.url ? (
                      <a
                        href={source.url}
                        target="_blank"
                        rel="noreferrer"
                      >
                        打开
                      </a>
                    ) : (
                      "-"
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

export default JobAnalysis;