import { useEffect, useState } from "react";

import apiClient from "../api/client";

function History() {
  const [records, setRecords] = useState([]);
  const [selectedRecord, setSelectedRecord] = useState(null);
  const [loading, setLoading] = useState(false);
  const [message, setMessage] = useState("");

  const fetchHistory = async () => {
    try {
      setLoading(true);
      setMessage("正在加载历史记录...");

      const response = await apiClient.get("/api/history", {
        params: {
          mode: "chat",
        },
      });

      setRecords(response.data.records || []);
      setMessage("历史记录加载成功。");
    } catch (error) {
      console.error("fetch history error:", error);

      const detail = error.response?.data?.detail;
      setMessage(detail || "获取历史记录失败，请检查后端是否启动。");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchHistory();
  }, []);

  const handleViewDetail = async (recordId) => {
    try {
      setLoading(true);
      setMessage("正在加载历史详情...");

      const response = await apiClient.get(`/api/history/${recordId}`);

      setSelectedRecord(response.data);
      setMessage("历史详情加载成功。");
    } catch (error) {
      console.error("fetch history detail error:", error);

      const detail = error.response?.data?.detail;
      setMessage(detail || "获取历史详情失败。");
    } finally {
      setLoading(false);
    }
  };

  const handleDelete = async (recordId) => {
    const confirmed = window.confirm("确认删除这条历史记录吗？");

    if (!confirmed) {
      return;
    }

    try {
      setLoading(true);
      setMessage("正在删除历史记录...");

      await apiClient.delete(`/api/history/${recordId}`);

      setRecords((prevRecords) =>
        prevRecords.filter((record) => record.record_id !== recordId)
      );

      if (selectedRecord?.record_id === recordId) {
        setSelectedRecord(null);
      }

      setMessage("历史记录删除成功。");
    } catch (error) {
      console.error("delete history error:", error);

      const detail = error.response?.data?.detail;
      setMessage(detail || "删除历史记录失败。");
    } finally {
      setLoading(false);
    }
  };

  return (
    <section>
      <h1>历史记录</h1>
      <p>查看自由问答生成的历史记录，包括用户问题、AI 回答和引用来源。</p>

      <div className="table-header">
        <h2>问答历史</h2>

        <button type="button" onClick={fetchHistory} disabled={loading}>
          {loading ? "处理中..." : "刷新列表"}
        </button>
      </div>

      {message && <p className="message-text">{message}</p>}

      {records.length === 0 ? (
        <p className="empty-text">暂无历史记录。</p>
      ) : (
        <table className="file-table">
          <thead>
            <tr>
              <th>问题</th>
              <th>类型</th>
              <th>联网搜索</th>
              <th>创建时间</th>
              <th>操作</th>
            </tr>
          </thead>

          <tbody>
            {records.map((record) => (
              <tr key={record.record_id}>
                <td>{record.user_input}</td>
                <td>{record.mode}</td>
                <td>{record.used_web_search ? "是" : "否"}</td>
                <td>{record.created_at}</td>
                <td>
                  <div className="table-actions">
                    <button
                      type="button"
                      onClick={() => handleViewDetail(record.record_id)}
                      disabled={loading}
                    >
                      查看
                    </button>

                    <button
                      type="button"
                      className="danger-button"
                      onClick={() => handleDelete(record.record_id)}
                      disabled={loading}
                    >
                      删除
                    </button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {selectedRecord && (
        <div className="history-detail-card">
          <h2>历史详情</h2>

          <div className="detail-block">
            <h3>用户问题</h3>
            <p>{selectedRecord.user_input}</p>
          </div>

          <div className="detail-block">
            <h3>AI 回答</h3>
            <div className="answer-content">{selectedRecord.ai_output}</div>
          </div>

          <div className="detail-block">
            <h3>引用来源</h3>

            {selectedRecord.sources?.length > 0 ? (
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
                  {selectedRecord.sources.map((source, index) => (
                    <tr
                      key={`${source.file_id}-${source.chunk_index}-${index}`}
                    >
                      <td>{source.filename || "未知文件"}</td>
                      <td>{source.file_type || "-"}</td>
                      <td>{source.chunk_index ?? "-"}</td>
                      <td>
                        {source.distance === null ||
                        source.distance === undefined
                          ? "-"
                          : Number(source.distance).toFixed(4)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            ) : (
              <p className="empty-text">暂无引用来源。</p>
            )}
          </div>
        </div>
      )}
    </section>
  );
}

export default History;