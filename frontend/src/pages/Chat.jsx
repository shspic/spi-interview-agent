import { useState } from "react";

import apiClient from "../api/client";

function Chat() {
  const [question, setQuestion] = useState("");
  const [answer, setAnswer] = useState("");
  const [sources, setSources] = useState([]);
  const [usedLocalKnowledge, setUsedLocalKnowledge] = useState(false);
  const [usedWebSearch, setUsedWebSearch] = useState(false);
  const [historyRecordId, setHistoryRecordId] = useState("");
  const [loading, setLoading] = useState(false);
  const [message, setMessage] = useState("");

  const handleAsk = async () => {
    const trimmedQuestion = question.trim();

    if (!trimmedQuestion) {
      setMessage("请输入问题。");
      return;
    }

    try {
      setLoading(true);
      setMessage("正在基于本地知识库生成回答...");
      setAnswer("");
      setSources([]);
      setUsedLocalKnowledge(false);
      setUsedWebSearch(false);
      setHistoryRecordId("");

      const response = await apiClient.post("/api/chat/ask", {
        question: trimmedQuestion,
      });

      setAnswer(response.data.answer || "");
      setSources(response.data.sources || []);
      setUsedLocalKnowledge(Boolean(response.data.used_local_knowledge));
      setUsedWebSearch(Boolean(response.data.used_web_search));
      setHistoryRecordId(response.data.history_record_id || "");
      setMessage("回答生成成功。");
    } catch (error) {
      console.error("chat ask error:", error);

      const status = error.response?.status;
      const detail = error.response?.data?.detail;
      const code = error.code;
      const errorMessage = error.message;

      setMessage(
        detail ||
          `问答请求失败。status=${status || "无"}，code=${
            code || "无"
          }，message=${errorMessage || "无"}`
      );
    } finally {
      setLoading(false);
    }
  };

  const handleClear = () => {
    setQuestion("");
    setAnswer("");
    setSources([]);
    setUsedLocalKnowledge(false);
    setUsedWebSearch(false);
    setHistoryRecordId("");
    setMessage("");
  };

  return (
    <section>
      <h1>自由问答</h1>
      <p>
        基于本地知识库进行面试问答。请先在知识库管理页面上传资料，并重建知识库索引。
      </p>

      <div className="chat-input-panel">
        <textarea
          value={question}
          onChange={(event) => setQuestion(event.target.value)}
          placeholder="例如：RAG 是什么？这个项目里是怎么使用 RAG 的？"
          rows={5}
        />

        <div className="chat-actions">
          <button type="button" onClick={handleAsk} disabled={loading}>
            {loading ? "生成中..." : "提交问题"}
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
          <h2>回答结果</h2>
          <div className="answer-content">{answer}</div>
        </div>
      )}

      {answer && (
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
          <h2>引用来源</h2>

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
    </section>
  );
}

export default Chat;