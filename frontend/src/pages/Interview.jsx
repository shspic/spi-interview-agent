import { useState } from "react";

import apiClient from "../api/client";

function Interview() {
  const [interviewType, setInterviewType] = useState("AI 应用开发实习面试");
  const [jobDescription, setJobDescription] = useState("");
  const [questionIndex, setQuestionIndex] = useState(1);
  const [question, setQuestion] = useState("");
  const [questionSources, setQuestionSources] = useState([]);
  const [userAnswer, setUserAnswer] = useState("");
  const [evaluation, setEvaluation] = useState(null);
  const [evaluationSources, setEvaluationSources] = useState([]);
  const [sessionId, setSessionId] = useState("");
  const [message, setMessage] = useState("");
  const [loadingQuestion, setLoadingQuestion] = useState(false);
  const [loadingEvaluation, setLoadingEvaluation] = useState(false);

  const handleGenerateQuestion = async () => {
    const trimmedJobDescription = jobDescription.trim();
    const trimmedInterviewType = interviewType.trim();

    if (!trimmedInterviewType) {
      setMessage("请输入面试类型。");
      return;
    }

    if (!trimmedJobDescription) {
      setMessage("请先粘贴岗位 JD。");
      return;
    }

    try {
      setLoadingQuestion(true);
      setMessage("正在生成模拟面试题...");
      setQuestion("");
      setQuestionSources([]);
      setUserAnswer("");
      setEvaluation(null);
      setEvaluationSources([]);
      setSessionId("");

      const response = await apiClient.post("/api/interview/question", {
        interview_type: trimmedInterviewType,
        job_description: trimmedJobDescription,
        question_index: questionIndex,
      });

      setQuestion(response.data.question || "");
      setQuestionSources(response.data.sources || []);
      setMessage("模拟面试题生成成功。");
    } catch (error) {
      console.error("generate interview question error:", error);

      const status = error.response?.status;
      const detail = error.response?.data?.detail;
      const code = error.code;
      const errorMessage = error.message;

      setMessage(
        detail ||
          `生成面试题失败。status=${status || "无"}，code=${
            code || "无"
          }，message=${errorMessage || "无"}`
      );
    } finally {
      setLoadingQuestion(false);
    }
  };

  const handleEvaluateAnswer = async () => {
    const trimmedJobDescription = jobDescription.trim();
    const trimmedInterviewType = interviewType.trim();
    const trimmedQuestion = question.trim();
    const trimmedUserAnswer = userAnswer.trim();

    if (!trimmedQuestion) {
      setMessage("请先生成面试题。");
      return;
    }

    if (!trimmedUserAnswer) {
      setMessage("请先输入你的回答。");
      return;
    }

    try {
      setLoadingEvaluation(true);
      setMessage("正在评价你的回答...");
      setEvaluation(null);
      setEvaluationSources([]);
      setSessionId("");

      const response = await apiClient.post("/api/interview/evaluate", {
        interview_type: trimmedInterviewType,
        job_description: trimmedJobDescription,
        question_index: questionIndex,
        question: trimmedQuestion,
        user_answer: trimmedUserAnswer,
      });

      setSessionId(response.data.session_id || "");
      setEvaluation(response.data.evaluation || null);
      setEvaluationSources(response.data.sources || []);
      setMessage("回答评价完成。");
    } catch (error) {
      console.error("evaluate interview answer error:", error);

      const status = error.response?.status;
      const detail = error.response?.data?.detail;
      const code = error.code;
      const errorMessage = error.message;

      setMessage(
        detail ||
          `评价回答失败。status=${status || "无"}，code=${
            code || "无"
          }，message=${errorMessage || "无"}`
      );
    } finally {
      setLoadingEvaluation(false);
    }
  };

  const handleNextQuestion = () => {
    setQuestionIndex((prevIndex) => prevIndex + 1);
    setQuestion("");
    setQuestionSources([]);
    setUserAnswer("");
    setEvaluation(null);
    setEvaluationSources([]);
    setSessionId("");
    setMessage("已切换到下一题，请点击生成面试题。");
  };

  const handleClear = () => {
    setInterviewType("AI 应用开发实习面试");
    setJobDescription("");
    setQuestionIndex(1);
    setQuestion("");
    setQuestionSources([]);
    setUserAnswer("");
    setEvaluation(null);
    setEvaluationSources([]);
    setSessionId("");
    setMessage("");
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

  return (
    <section>
      <h1>模拟面试</h1>
      <p>
        根据岗位 JD 和本地知识库生成模拟面试题，并对你的回答进行评分、问题诊断和参考回答生成。
      </p>

      <div className="interview-panel">
        <label htmlFor="interview-type">面试类型</label>
        <input
          id="interview-type"
          value={interviewType}
          onChange={(event) => setInterviewType(event.target.value)}
          placeholder="例如：AI 应用开发实习面试"
        />

        <label htmlFor="question-index">当前题号</label>
        <input
          id="question-index"
          type="number"
          min="1"
          value={questionIndex}
          onChange={(event) =>
            setQuestionIndex(Math.max(1, Number(event.target.value) || 1))
          }
        />

        <label htmlFor="job-description">岗位 JD</label>
        <textarea
          id="job-description"
          value={jobDescription}
          onChange={(event) => setJobDescription(event.target.value)}
          placeholder="请粘贴岗位职责、任职要求、加分项等完整 JD..."
          rows={10}
        />

        <div className="chat-actions">
          <button
            type="button"
            onClick={handleGenerateQuestion}
            disabled={loadingQuestion || loadingEvaluation}
          >
            {loadingQuestion ? "生成中..." : "生成面试题"}
          </button>

          <button
            type="button"
            className="secondary-button"
            onClick={handleNextQuestion}
            disabled={loadingQuestion || loadingEvaluation}
          >
            下一题
          </button>

          <button
            type="button"
            className="secondary-button"
            onClick={handleClear}
            disabled={loadingQuestion || loadingEvaluation}
          >
            清空
          </button>
        </div>
      </div>

      {message && <p className="message-text">{message}</p>}

      {question && (
        <div className="answer-card">
          <h2>模拟面试题</h2>
          <div className="answer-content">{question}</div>
        </div>
      )}

      {questionSources.length > 0 && (
        <div className="sources-panel">
          <h2>出题引用来源</h2>
          {renderSourcesTable(questionSources)}
        </div>
      )}

      {question && (
        <div className="interview-answer-panel">
          <label htmlFor="user-answer">你的回答</label>
          <textarea
            id="user-answer"
            value={userAnswer}
            onChange={(event) => setUserAnswer(event.target.value)}
            placeholder="请像真实面试一样输入你的回答..."
            rows={8}
          />

          <div className="chat-actions">
            <button
              type="button"
              onClick={handleEvaluateAnswer}
              disabled={loadingQuestion || loadingEvaluation}
            >
              {loadingEvaluation ? "评价中..." : "评价回答"}
            </button>
          </div>
        </div>
      )}

      {evaluation && (
        <div className="evaluation-card">
          <h2>回答评价</h2>

          {sessionId && (
            <p>
              面试记录 ID：<code>{sessionId}</code>
            </p>
          )}

          <div className="score-grid">
            <div>
              <span>总分</span>
              <strong>{evaluation.score_total ?? 0}</strong>
            </div>

            <div>
              <span>内容相关性</span>
              <strong>{evaluation.content_relevance ?? 0}</strong>
            </div>

            <div>
              <span>个人经历匹配度</span>
              <strong>{evaluation.personal_match ?? 0}</strong>
            </div>

            <div>
              <span>技术准确性</span>
              <strong>{evaluation.technical_accuracy ?? 0}</strong>
            </div>

            <div>
              <span>表达结构</span>
              <strong>{evaluation.structure_score ?? 0}</strong>
            </div>

            <div>
              <span>风险控制</span>
              <strong>{evaluation.risk_control ?? 0}</strong>
            </div>
          </div>

          <div className="detail-block">
            <h3>主要问题</h3>
            <p>{evaluation.main_problems || "暂无"}</p>
          </div>

          <div className="detail-block">
            <h3>改进建议</h3>
            <p>{evaluation.suggestions || "暂无"}</p>
          </div>

          <div className="detail-block">
            <h3>参考回答</h3>
            <div className="answer-content">
              {evaluation.reference_answer || "暂无"}
            </div>
          </div>
        </div>
      )}

      {evaluationSources.length > 0 && (
        <div className="sources-panel">
          <h2>评价引用来源</h2>
          {renderSourcesTable(evaluationSources)}
        </div>
      )}
    </section>
  );
}

export default Interview;