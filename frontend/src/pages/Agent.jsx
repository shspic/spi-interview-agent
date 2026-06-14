import { useState } from "react";

import apiClient from "../api/client";

const modeOptions = [
  {
    value: "auto",
    label: "auto：自动选择",
    description: "根据问题自动判断是否需要联网搜索。",
  },
  {
    value: "local",
    label: "local：只用本地知识库",
    description: "适合询问你的项目、资料、经历、技术笔记。",
  },
  {
    value: "web",
    label: "web：只用联网搜索",
    description: "适合查询当前市场、岗位趋势、外部信息。",
  },
  {
    value: "hybrid",
    label: "hybrid：本地知识库 + 联网搜索",
    description: "适合岗位匹配、面试准备、趋势结合个人项目分析。",
  },
];

function Agent() {
  const [question, setQuestion] = useState("");
  const [mode, setMode] = useState("auto");
  const [topK, setTopK] = useState(5);
  const [maxWebResults, setMaxWebResults] = useState(5);

  const [answer, setAnswer] = useState("");
  const [route, setRoute] = useState("");
  const [sources, setSources] = useState([]);
  const [webSources, setWebSources] = useState([]);
  const [usedLocalKnowledge, setUsedLocalKnowledge] = useState(false);
  const [usedWebSearch, setUsedWebSearch] = useState(false);
  const [historyRecordId, setHistoryRecordId] = useState("");

  const [loading, setLoading] = useState(false);
  const [message, setMessage] = useState("");

  const handleAskAgent = async () => {
    const trimmedQuestion = question.trim();

    if (!trimmedQuestion) {
      setMessage("请输入问题。");
      return;
    }

    try {
      setLoading(true);
      setMessage("LangGraph Agent 正在处理问题...");
      setAnswer("");
      setRoute("");
      setSources([]);
      setWebSources([]);
      setUsedLocalKnowledge(false);
      setUsedWebSearch(false);
      setHistoryRecordId("");

      const response = await apiClient.post("/api/agent/ask", {
        question: trimmedQuestion,
        mode,
        top_k: Number(topK),
        max_web_results: Number(maxWebResults),
      });

      setAnswer(response.data.answer || "");
      setRoute(response.data.route || "");
      setSources(response.data.sources || []);
      setWebSources(response.data.web_sources || []);
      setUsedLocalKnowledge(Boolean(response.data.used_local_knowledge));
      setUsedWebSearch(Boolean(response.data.used_web_search));
      setHistoryRecordId(response.data.history_record_id || "");
      setMessage("Agent 回答生成成功。");
    } catch (error) {
      console.error("agent ask error:", error);

      const status = error.response?.status;
      const detail = error.response?.data?.detail;
      const code = error.code;
      const errorMessage = error.message;

      setMessage(
        detail ||
          `Agent 请求失败。status=${status || "无"}，code=${
            code || "无"
          }，message=${errorMessage || "无"}`
      );
    } finally {
      setLoading(false);
    }
  };

  const handleClear = () => {
    setQuestion("");
    setMode("auto");
    setTopK(5);
    setMaxWebResults(5);
    setAnswer("");
    setRoute("");
    setSources([]);
    setWebSources([]);
    setUsedLocalKnowledge(false);
    setUsedWebSearch(false);
    setHistoryRecordId("");
    setMessage("");
  };

  return (
    <section>
      <h1>LangGraph Agent</h1>

      <p>
        基于 LangGraph 的智能问答入口。系统可以在本地知识库、Tavily
        联网搜索、混合检索之间进行路由，用于求职、岗位分析、面试准备和项目问答。
      </p>

      <div className="agent-panel">
        <label htmlFor="agent-question">问题</label>

        <textarea
          id="agent-question"
          value={question}
          onChange={(event) => setQuestion(event.target.value)}
          placeholder="例如：当前 AI 应用开发实习岗位对 RAG 和 FastAPI 有什么要求？结合我的项目说一下。"
          rows={7}
        />

        <label htmlFor="agent-mode">Agent 模式</label>

        <select
          id="agent-mode"
          value={mode}
          onChange={(event) => setMode(event.target.value)}
          disabled={loading}
        >
          {modeOptions.map((option) => (
            <option key={option.value} value={option.value}>
              {option.label}
            </option>
          ))}
        </select>

        <p className="helper-text">
          {modeOptions.find((option) => option.value === mode)?.description}
        </p>

        <div className="agent-config-grid">
          <div>
            <label htmlFor="top-k">本地检索 top_k</label>
            <input
              id="top-k"
              type="number"
              min="1"
              max="10"
              value={topK}
              onChange={(event) =>
                setTopK(Math.min(10, Math.max(1, Number(event.target.value) || 1)))
              }
              disabled={loading}
            />
          </div>

          <div>
            <label htmlFor="max-web-results">联网结果数量</label>
            <input
              id="max-web-results"
              type="number"
              min="1"
              max="10"
              value={maxWebResults}
              onChange={(event) =>
                setMaxWebResults(
                  Math.min(10, Math.max(1, Number(event.target.value) || 1))
                )
              }
              disabled={loading}
            />
          </div>
        </div>

        <div className="chat-actions">
          <button type="button" onClick={handleAskAgent} disabled={loading}>
            {loading ? "处理中..." : "提交给 Agent"}
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

      {answer && (
        <div className="answer-card">
          <h2>Agent 回答</h2>
          <div className="answer-content">{answer}</div>
        </div>
      )}

      {answer && (
        <div className="source-summary">
          <p>
            实际路由：
            <strong>{route || "-"}</strong>
          </p>

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
                      <a href={source.url} target="_blank" rel="noreferrer">
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

export default Agent;