import { useCallback, useEffect, useState } from "react";

import apiClient from "../api/client";
import {
  getInterviewSession,
  getInterviewSessions,
} from "../api/interviewTraining";
import { getFriendlyErrorMessage } from "../utils/errorMessage";

const tabs = [
  {
    key: "training",
    label: "面试训练记录",
  },
  {
    key: "chat",
    label: "自由问答",
  },
  {
    key: "job_analysis",
    label: "岗位分析",
  },
  {
    key: "agent",
    label: "LangGraph Agent",
  },
  {
    key: "interview",
    label: "模拟面试",
  },
];

function getShortText(text, maxLength = 80) {
  if (!text) {
    return "";
  }

  if (text.length <= maxLength) {
    return text;
  }

  return `${text.slice(0, maxLength)}...`;
}

function History({ onOpenTrainingSession }) {
  const [activeTab, setActiveTab] = useState("training");
  const [historyRecords, setHistoryRecords] = useState([]);
  const [interviewRecords, setInterviewRecords] = useState([]);
  const [trainingSessions, setTrainingSessions] = useState([]);
  const [selectedHistoryRecord, setSelectedHistoryRecord] = useState(null);
  const [selectedInterviewRecord, setSelectedInterviewRecord] = useState(null);
  const [selectedTrainingSession, setSelectedTrainingSession] = useState(null);
  const [loading, setLoading] = useState(false);
  const [message, setMessage] = useState("");

  const fetchRecords = useCallback(async (tabKey) => {
    try {
      setLoading(true);
      setMessage("正在加载历史记录...");
      setSelectedHistoryRecord(null);
      setSelectedInterviewRecord(null);
      setSelectedTrainingSession(null);

      if (tabKey === "training") {
        setTrainingSessions(await getInterviewSessions());
      } else if (tabKey === "interview") {
        const response = await apiClient.get("/api/interview-records");
        setInterviewRecords(response.data.records || []);
      } else {
        const response = await apiClient.get("/api/history", {
          params: {
            mode: tabKey,
          },
        });
        setHistoryRecords(response.data.records || []);
      }

      setMessage("历史记录加载成功。");
    } catch (error) {
      console.error("fetch records error:", error);

      const detail = error.response?.data?.detail;
      setMessage(detail || "获取历史记录失败，请检查后端是否启动。");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    const timerId = window.setTimeout(() => fetchRecords(activeTab), 0);

    return () => window.clearTimeout(timerId);
  }, [activeTab, fetchRecords]);

  const handleTabChange = (tabKey) => {
    setActiveTab(tabKey);
    setMessage("");
  };

  const handleViewHistoryDetail = async (recordId) => {
    try {
      setLoading(true);
      setMessage("正在加载历史详情...");
      setSelectedInterviewRecord(null);

      const response = await apiClient.get(`/api/history/${recordId}`);

      setSelectedHistoryRecord(response.data);
      setMessage("历史详情加载成功。");
    } catch (error) {
      console.error("fetch history detail error:", error);

      const detail = error.response?.data?.detail;
      setMessage(detail || "获取历史详情失败。");
    } finally {
      setLoading(false);
    }
  };

  const handleDeleteHistory = async (recordId) => {
    const confirmed = window.confirm("确认删除这条历史记录吗？");

    if (!confirmed) {
      return;
    }

    try {
      setLoading(true);
      setMessage("正在删除历史记录...");

      await apiClient.delete(`/api/history/${recordId}`);

      setHistoryRecords((prevRecords) =>
        prevRecords.filter((record) => record.record_id !== recordId)
      );

      if (selectedHistoryRecord?.record_id === recordId) {
        setSelectedHistoryRecord(null);
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

  const handleViewInterviewDetail = async (sessionId) => {
    try {
      setLoading(true);
      setMessage("正在加载模拟面试记录详情...");
      setSelectedHistoryRecord(null);

      const response = await apiClient.get(`/api/interview-records/${sessionId}`);

      setSelectedInterviewRecord(response.data);
      setMessage("模拟面试记录详情加载成功。");
    } catch (error) {
      console.error("fetch interview detail error:", error);

      const detail = error.response?.data?.detail;
      setMessage(detail || "获取模拟面试记录详情失败。");
    } finally {
      setLoading(false);
    }
  };

  const handleViewTrainingDetail = async (sessionId) => {
    try {
      setLoading(true);
      setMessage("正在加载面试训练详情...");
      setSelectedTrainingSession(await getInterviewSession(sessionId));
      setMessage("面试训练详情加载成功。");
    } catch (error) {
      setMessage(getFriendlyErrorMessage(error, "获取面试训练详情失败。"));
    } finally {
      setLoading(false);
    }
  };

  const handleDeleteInterview = async (sessionId) => {
    const confirmed = window.confirm("确认删除这条模拟面试记录吗？");

    if (!confirmed) {
      return;
    }

    try {
      setLoading(true);
      setMessage("正在删除模拟面试记录...");

      await apiClient.delete(`/api/interview-records/${sessionId}`);

      setInterviewRecords((prevRecords) =>
        prevRecords.filter((record) => record.session_id !== sessionId)
      );

      if (selectedInterviewRecord?.session_id === sessionId) {
        setSelectedInterviewRecord(null);
      }

      setMessage("模拟面试记录删除成功。");
    } catch (error) {
      console.error("delete interview record error:", error);

      const detail = error.response?.data?.detail;
      setMessage(detail || "删除模拟面试记录失败。");
    } finally {
      setLoading(false);
    }
  };

  const renderSourcesTable = (sources) => {
    if (!sources || sources.length === 0) {
      return <p className="empty-text">暂无引用来源。</p>;
    }

    return (
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
    );
  };

  const renderWebSourcesTable = (webSources) => {
    if (!webSources || webSources.length === 0) {
      return <p className="empty-text">暂无联网搜索来源。</p>;
    }

    return (
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
    );
  };

  const renderHistoryTable = () => {
    if (historyRecords.length === 0) {
      return <p className="empty-text">暂无历史记录。</p>;
    }

    return (
      <table className="file-table">
        <thead>
          <tr>
            <th>输入内容</th>
            <th>类型</th>
            <th>联网搜索</th>
            <th>创建时间</th>
            <th>操作</th>
          </tr>
        </thead>

        <tbody>
          {historyRecords.map((record) => (
            <tr key={record.record_id}>
              <td className="long-cell">{getShortText(record.user_input)}</td>
              <td>{record.mode}</td>
              <td>{record.used_web_search ? "是" : "否"}</td>
              <td>{record.created_at}</td>
              <td>
                <div className="table-actions">
                  <button
                    type="button"
                    onClick={() => handleViewHistoryDetail(record.record_id)}
                    disabled={loading}
                  >
                    查看
                  </button>

                  <button
                    type="button"
                    className="danger-button"
                    onClick={() => handleDeleteHistory(record.record_id)}
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
    );
  };

  const renderInterviewTable = () => {
    if (interviewRecords.length === 0) {
      return <p className="empty-text">暂无模拟面试记录。</p>;
    }

    return (
      <table className="file-table">
        <thead>
          <tr>
            <th>面试题</th>
            <th>类型</th>
            <th>题号</th>
            <th>总分</th>
            <th>创建时间</th>
            <th>操作</th>
          </tr>
        </thead>

        <tbody>
          {interviewRecords.map((record) => (
            <tr key={record.session_id}>
              <td className="long-cell">{getShortText(record.question)}</td>
              <td>{record.interview_type}</td>
              <td>{record.question_index}</td>
              <td>{record.score_total}</td>
              <td>{record.created_at}</td>
              <td>
                <div className="table-actions">
                  <button
                    type="button"
                    onClick={() => handleViewInterviewDetail(record.session_id)}
                    disabled={loading}
                  >
                    查看
                  </button>

                  <button
                    type="button"
                    className="danger-button"
                    onClick={() => handleDeleteInterview(record.session_id)}
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
    );
  };

  const renderSelectedHistoryDetail = () => {
    if (!selectedHistoryRecord) {
      return null;
    }

    const isJobAnalysis = selectedHistoryRecord.mode === "job_analysis";
    const isAgent = selectedHistoryRecord.mode === "agent";

    return (
      <div className="history-detail-card">
        <h2>
  {isJobAnalysis
    ? "岗位分析详情"
    : isAgent
    ? "LangGraph Agent 详情"
    : "自由问答详情"}
</h2>

        <div className="detail-block">
          <h3>{isJobAnalysis ? "岗位 JD" : "用户问题"}</h3>
          <div className="answer-content">{selectedHistoryRecord.user_input}</div>
        </div>

        <div className="detail-block">
          <h3>
  {isJobAnalysis
    ? "岗位分析结果"
    : isAgent
    ? "Agent 回答"
    : "AI 回答"}
</h3>
          <div className="answer-content">{selectedHistoryRecord.ai_output}</div>
        </div>

        <div className="detail-block">
          <h3>本地知识库引用来源</h3>
          {renderSourcesTable(selectedHistoryRecord.sources)}
        </div>

        {isAgent && (
  <div className="detail-block">
    <h3>Agent 路由原因</h3>
    <p>{selectedHistoryRecord.route_reason || "暂无路由原因。"}</p>
  </div>
)}

{isAgent && selectedHistoryRecord.execution_steps?.length > 0 && (
  <div className="detail-block">
    <h3>Agent 执行轨迹</h3>
    <ol>
      {selectedHistoryRecord.execution_steps.map((step, index) => (
        <li key={`${step}-${index}`}>{step}</li>
      ))}
    </ol>
  </div>
)}

        {(isJobAnalysis || isAgent) && (
  <div className="detail-block">
    <h3>联网搜索使用情况</h3>
    <p>
      {selectedHistoryRecord.used_web_search
        ? isAgent
          ? "本次 Agent 问答使用了 Tavily 联网搜索。"
          : "本次岗位分析使用了 Tavily 联网搜索。"
        : isAgent
        ? "本次 Agent 问答未使用联网搜索。"
        : "本次岗位分析未使用联网搜索。"}
    </p>
  </div>
)}

{(isJobAnalysis || isAgent) && selectedHistoryRecord.used_web_search && (
  <div className="detail-block">
    <h3>联网搜索来源</h3>
    {renderWebSourcesTable(selectedHistoryRecord.web_sources)}
  </div>
)}
          

      </div>
    );
  };

  const renderSelectedInterviewDetail = () => {
    if (!selectedInterviewRecord) {
      return null;
    }

    return (
      <div className="history-detail-card">
        <h2>模拟面试记录详情</h2>

        <div className="detail-grid">
          <p>
            面试类型：<strong>{selectedInterviewRecord.interview_type}</strong>
          </p>
          <p>
            题号：<strong>{selectedInterviewRecord.question_index}</strong>
          </p>
          <p>
            总分：<strong>{selectedInterviewRecord.score_total}</strong>
          </p>
          <p>
            创建时间：<strong>{selectedInterviewRecord.created_at}</strong>
          </p>
        </div>

        <div className="score-grid">
          <div>
            <span>内容相关性</span>
            <strong>{selectedInterviewRecord.content_relevance ?? 0}</strong>
          </div>

          <div>
            <span>个人经历匹配度</span>
            <strong>{selectedInterviewRecord.personal_match ?? 0}</strong>
          </div>

          <div>
            <span>技术准确性</span>
            <strong>{selectedInterviewRecord.technical_accuracy ?? 0}</strong>
          </div>

          <div>
            <span>表达结构</span>
            <strong>{selectedInterviewRecord.structure_score ?? 0}</strong>
          </div>

          <div>
            <span>风险控制</span>
            <strong>{selectedInterviewRecord.risk_control ?? 0}</strong>
          </div>
        </div>

        <div className="detail-block">
          <h3>岗位 JD</h3>
          <div className="answer-content">
            {selectedInterviewRecord.job_description}
          </div>
        </div>

        <div className="detail-block">
          <h3>面试问题</h3>
          <div className="answer-content">{selectedInterviewRecord.question}</div>
        </div>

        <div className="detail-block">
          <h3>你的回答</h3>
          <div className="answer-content">{selectedInterviewRecord.user_answer}</div>
        </div>

        <div className="detail-block">
          <h3>主要问题</h3>
          <p>{selectedInterviewRecord.main_problems || "暂无"}</p>
        </div>

        <div className="detail-block">
          <h3>改进建议</h3>
          <p>{selectedInterviewRecord.suggestions || "暂无"}</p>
        </div>

        <div className="detail-block">
          <h3>参考回答</h3>
          <div className="answer-content">
            {selectedInterviewRecord.reference_answer || "暂无"}
          </div>
        </div>
      </div>
    );
  };

  const renderTrainingTable = () => {
    if (trainingSessions.length === 0) {
      return <p className="empty-text">暂无面试训练记录。</p>;
    }

    return (
      <table className="file-table training-history-table">
        <thead><tr><th>标题</th><th>模式</th><th>状态</th><th>总分</th><th>创建时间</th><th>完成时间</th><th>操作</th></tr></thead>
        <tbody>
          {trainingSessions.map((item) => (
            <tr key={item.id}>
              <td>{item.title}</td>
              <td>{{ quick: "快速练习", standard: "标准面试", deep_dive: "专项深挖" }[item.mode] || item.mode}</td>
              <td>{{ draft: "草稿", in_progress: "进行中", completed: "已完成", cancelled: "已取消" }[item.status] || item.status}</td>
              <td>{item.overall_score ?? "-"}</td>
              <td>{item.created_at ? new Date(item.created_at).toLocaleString("zh-CN") : "-"}</td>
              <td>{item.completed_at ? new Date(item.completed_at).toLocaleString("zh-CN") : "-"}</td>
              <td className="action-cell">
                <button type="button" onClick={() => handleViewTrainingDetail(item.id)} disabled={loading}>查看详情</button>
                <button type="button" className="secondary-button" onClick={() => onOpenTrainingSession?.(item.id)}>进入工作台</button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    );
  };

  const renderSelectedTrainingDetail = () => {
    if (!selectedTrainingSession) {
      return null;
    }
    return (
      <div className="history-detail-card">
        <div className="inline-heading"><div><h2>{selectedTrainingSession.title}</h2><p>{selectedTrainingSession.summary || "暂无整场总结。"}</p></div><button type="button" onClick={() => onOpenTrainingSession?.(selectedTrainingSession.id)}>进入面试 Agent</button></div>
        <div className="detail-grid">
          <p>状态：<strong>{selectedTrainingSession.status}</strong></p>
          <p>主问题：<strong>{selectedTrainingSession.planned_main_questions}</strong></p>
          <p>总分：<strong>{selectedTrainingSession.overall_score ?? "-"}</strong></p>
          <p>完成时间：<strong>{selectedTrainingSession.completed_at || "-"}</strong></p>
        </div>
        <div className="detail-block"><h3>题目记录</h3>{selectedTrainingSession.turns?.length ? <ol>{selectedTrainingSession.turns.map((turn) => <li key={turn.id}><strong>{turn.question}</strong><p>{turn.user_answer || "尚未回答"}</p><span>{turn.total_score == null ? "待评价" : `${turn.total_score} 分`}</span></li>)}</ol> : <p className="empty-text">暂无题目。</p>}</div>
      </div>
    );
  };

  return (
    <section>
      <h1>历史记录</h1>
      <p>查看面试训练，以及原有自由问答、岗位分析和模拟面试记录。</p>

      <div className="history-tabs">
        {tabs.map((tab) => (
          <button
            key={tab.key}
            type="button"
            className={activeTab === tab.key ? "active-tab" : ""}
            onClick={() => handleTabChange(tab.key)}
            disabled={loading}
          >
            {tab.label}
          </button>
        ))}
      </div>

      <div className="table-header">
        <h2>{tabs.find((tab) => tab.key === activeTab)?.label}</h2>

        <button
          type="button"
          onClick={() => fetchRecords(activeTab)}
          disabled={loading}
        >
          {loading ? "处理中..." : "刷新列表"}
        </button>
      </div>

      {message && <p className="message-text">{message}</p>}

      {activeTab === "training"
        ? renderTrainingTable()
        : activeTab === "interview"
          ? renderInterviewTable()
          : renderHistoryTable()}

      {renderSelectedHistoryDetail()}
      {renderSelectedInterviewDetail()}
      {renderSelectedTrainingDetail()}
    </section>
  );
}

export default History;
