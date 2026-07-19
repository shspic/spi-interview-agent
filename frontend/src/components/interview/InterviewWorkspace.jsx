import { useState } from "react";

import EvaluationPanel from "./EvaluationPanel";

function InterviewWorkspace({ session, latestResult, busy, recoveryTurn, onSubmit, onContinue, onCopy, onCancel }) {
  const [answer, setAnswer] = useState(() => recoveryTurn?.user_answer || "");
  const [validationMessage, setValidationMessage] = useState("");
  const currentQuestion = session.current_question;
  const showingEvaluation = Boolean(latestResult?.answered_turn);
  const turnToAnswer = recoveryTurn || currentQuestion;
  const isRecovery = Boolean(recoveryTurn);

  const submit = (event) => {
    event.preventDefault();
    const normalized = answer.trim();
    if (!normalized) {
      setValidationMessage("回答不能为空。");
      return;
    }
    if (normalized.length > 20000) {
      setValidationMessage("回答不能超过 20000 个字符。");
      return;
    }
    setValidationMessage("");
    onSubmit(turnToAnswer.id, normalized);
  };

  return (
    <div className="interview-workspace">
      <div className="workspace-header">
        <div>
          <span className="status-badge in-progress">进行中</span>
          <h2>{session.title}</h2>
          <p>{session.target_job ? `${session.target_job.job_title}${session.target_job.company_name ? ` · ${session.target_job.company_name}` : ""}` : "未指定目标岗位"}</p>
        </div>
        <button type="button" className="danger-button" onClick={onCancel} disabled={busy}>取消会话</button>
      </div>

      <div className="interview-progress">
        <div><span>主问题进度</span><strong>{session.completed_main_questions}/{session.planned_main_questions}</strong></div>
        <div><span>当前主问题</span><strong>{session.current_main_question || currentQuestion?.main_question_number || 1}</strong></div>
        <div><span>本题追问</span><strong>{session.current_follow_up_count || 0}/2</strong></div>
        <div><span>模式</span><strong>{session.mode === "quick" ? "快速" : session.mode === "standard" ? "标准" : "专项深挖"}</strong></div>
      </div>

      {session.evidence_limited && <div className="interview-alert warning"><strong>证据有限</strong><p>当前问题会采用保守、开放的表达。请只按真实经历回答。</p></div>}

      {showingEvaluation ? (
        <>
          <EvaluationPanel turn={latestResult.answered_turn} decision={latestResult.decision} onCopy={onCopy} />
          {latestResult.is_completed ? (
            <button type="button" className="primary-wide-button" onClick={onContinue}>查看整场结果</button>
          ) : (
            <button type="button" className="primary-wide-button" onClick={onContinue}>继续下一题</button>
          )}
        </>
      ) : turnToAnswer ? (
        <article className="question-card">
          <div className="question-meta">
            <span>{turnToAnswer.follow_up_number > 0 ? `第 ${turnToAnswer.follow_up_number} 次追问` : `主问题 ${turnToAnswer.main_question_number}`}</span>
            <span>题目 {turnToAnswer.sequence_number}</span>
          </div>
          <h3>{turnToAnswer.question}</h3>
          {isRecovery && <div className="interview-alert warning"><strong>{turnToAnswer.total_score == null ? "回答已保存，评价待恢复" : "评价已保存，下一题待恢复"}</strong><p>点击下方按钮将复用后端恢复逻辑，不会重复写入回答或评价。</p></div>}
          <form className="answer-form" onSubmit={submit}>
            <label htmlFor="interview-answer">你的回答</label>
            <textarea id="interview-answer" value={answer} onChange={(event) => setAnswer(event.target.value)} disabled={busy || isRecovery} rows={10} maxLength={20000} placeholder="建议说明背景、你的职责、技术方案、关键取舍和结果。" />
            <div className="answer-form-footer">
              <span>{answer.length}/20000</span>
              <button type="submit" disabled={busy}>{busy ? "处理中..." : isRecovery ? "恢复处理" : "提交回答"}</button>
            </div>
            {validationMessage && <p className="form-error" role="alert">{validationMessage}</p>}
          </form>
        </article>
      ) : (
        <div className="interview-alert warning"><strong>下一题尚未生成</strong><p>刷新会话后仍无待答题目时，请使用恢复入口重试上一题处理。</p></div>
      )}

      {session.agent_execution_summary && (
        <details className="agent-summary">
          <summary>Agent 执行摘要</summary>
          <dl>{Object.entries(session.agent_execution_summary).map(([key, value]) => <div key={key}><dt>{key}</dt><dd>{typeof value === "object" ? JSON.stringify(value) : String(value)}</dd></div>)}</dl>
        </details>
      )}
    </div>
  );
}

export default InterviewWorkspace;
