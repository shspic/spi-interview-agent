import { useCallback, useEffect, useMemo, useState } from "react";

import apiClient from "../api/client";
import {
  answerInterviewQuestion,
  cancelInterviewSession,
  createInterviewSession,
  createRetrySession,
  deleteInterviewSession,
  getInterviewComparison,
  getInterviewSession,
  getInterviewSessions,
  retryImprovementGeneration,
  startInterviewSession,
  updateImprovementTask,
} from "../api/interviewTraining";
import {
  deleteResumeDescription,
  generateResumeDescription,
  getResumeDescription,
  getResumeDescriptions,
} from "../api/resumeDescriptions";
import ComparisonPanel from "../components/interview/ComparisonPanel";
import EvaluationPanel from "../components/interview/EvaluationPanel";
import ImprovementTaskList from "../components/interview/ImprovementTaskList";
import InterviewSetup from "../components/interview/InterviewSetup";
import InterviewWorkspace from "../components/interview/InterviewWorkspace";
import ResumeDescriptionPanel from "../components/interview/ResumeDescriptionPanel";
import { getFriendlyErrorMessage } from "../utils/errorMessage";

const ACTIVE_SESSION_KEY = "spi_interview_active_session";

const sectionTabs = [
  ["setup", "准备面试"],
  ["interview", "正在面试"],
  ["result", "面试结果"],
  ["tasks", "改进任务"],
  ["retry", "再次练习"],
  ["resume", "简历描述"],
];

const statusLabels = {
  draft: "草稿",
  in_progress: "进行中",
  completed: "已完成",
  cancelled: "已取消",
};

const modeLabels = {
  quick: "快速练习",
  standard: "标准面试",
  deep_dive: "专项深挖",
};

function formatDate(value) {
  if (!value) {
    return "-";
  }
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString("zh-CN");
}

function getProfileComplete(profile) {
  return Boolean(
    profile?.display_name?.trim() &&
      profile?.target_direction?.trim() &&
      profile?.self_introduction?.trim() &&
      profile?.technical_skills?.length,
  );
}

function InterviewAgent({ onOpenProfile, onOpenKnowledge, requestedSessionId }) {
  const [profile, setProfile] = useState(null);
  const [targetJobs, setTargetJobs] = useState([]);
  const [files, setFiles] = useState([]);
  const [sessions, setSessions] = useState([]);
  const [session, setSession] = useState(null);
  const [activeSection, setActiveSection] = useState("setup");
  const [latestResult, setLatestResult] = useState(null);
  const [retryInfo, setRetryInfo] = useState(null);
  const [comparison, setComparison] = useState(null);
  const [descriptions, setDescriptions] = useState([]);
  const [selectedDescription, setSelectedDescription] = useState(null);
  const [loading, setLoading] = useState(true);
  const [busyAction, setBusyAction] = useState("");
  const [updatingTaskId, setUpdatingTaskId] = useState(null);
  const [message, setMessage] = useState("");

  const resumeFiles = useMemo(() => files.filter((file) => file.category === "resume"), [files]);
  const projectFiles = useMemo(() => files.filter((file) => file.category === "project"), [files]);
  const activeJob = useMemo(() => targetJobs.find((job) => job.is_active), [targetJobs]);
  const completedSessions = useMemo(() => sessions.filter((item) => item.status === "completed"), [sessions]);
  const preparationItems = useMemo(() => [
    ["基本资料", getProfileComplete(profile)],
    ["简历文件", resumeFiles.length > 0],
    ["项目资料", projectFiles.length > 0],
    ["当前目标岗位", Boolean(activeJob)],
  ], [activeJob, profile, projectFiles.length, resumeFiles.length]);

  const loadSession = useCallback(async (sessionId, preferredSection) => {
    const detail = await getInterviewSession(sessionId);
    setSession(detail);
    setLatestResult(null);
    setComparison(null);
    localStorage.setItem(ACTIVE_SESSION_KEY, String(detail.id));
    if (preferredSection) {
      setActiveSection(preferredSection);
    } else if (detail.status === "in_progress") {
      setActiveSection("interview");
    } else if (detail.status === "completed") {
      setActiveSection("result");
    } else {
      setActiveSection("setup");
    }
    return detail;
  }, []);

  const loadInitialData = useCallback(async () => {
    setLoading(true);
    setMessage("");
    try {
      const [profileResponse, jobsResponse, filesResponse, sessionList, resumeHistory] = await Promise.all([
        apiClient.get("/api/profile"),
        apiClient.get("/api/target-jobs"),
        apiClient.get("/api/files"),
        getInterviewSessions(),
        getResumeDescriptions(),
      ]);
      setProfile(profileResponse.data.profile || null);
      setTargetJobs(jobsResponse.data.jobs || []);
      setFiles(filesResponse.data.files || []);
      setSessions(sessionList);
      setDescriptions(resumeHistory);
      setSelectedDescription((current) => current || resumeHistory[0] || null);

      const storedId = Number(localStorage.getItem(ACTIVE_SESSION_KEY));
      const desiredId = Number(requestedSessionId) || storedId;
      const recoverable = sessionList.find((item) => item.id === desiredId)
        || sessionList.find((item) => item.status === "in_progress");
      if (recoverable) {
        await loadSession(recoverable.id);
      }
    } catch (error) {
      setMessage(getFriendlyErrorMessage(error, "加载面试工作台失败。"));
    } finally {
      setLoading(false);
    }
  }, [loadSession, requestedSessionId]);

  useEffect(() => {
    const timerId = window.setTimeout(loadInitialData, 0);
    return () => window.clearTimeout(timerId);
  }, [loadInitialData]);

  const refreshSessions = useCallback(async () => {
    const nextSessions = await getInterviewSessions();
    setSessions(nextSessions);
    return nextSessions;
  }, []);

  const runStart = async (sessionId) => {
    setBusyAction("start");
    setMessage("");
    try {
      const started = await startInterviewSession(sessionId);
      setSession(started);
      setLatestResult(null);
      setRetryInfo(null);
      setActiveSection("interview");
      localStorage.setItem(ACTIVE_SESSION_KEY, String(started.id));
      await refreshSessions();
    } catch (error) {
      if (error.response?.status === 409) {
        const detail = await loadSession(sessionId);
        setMessage(detail.status === "in_progress" ? "会话已经启动，已恢复当前问题。" : getFriendlyErrorMessage(error, "会话状态冲突。"));
      } else {
        try {
          await loadSession(sessionId, "setup");
        } catch {
          // 保留原始错误信息，避免用二次读取错误覆盖。
        }
        setMessage(getFriendlyErrorMessage(error, "会话已创建，但启动失败。可稍后重新开始。"));
      }
    } finally {
      setBusyAction("");
    }
  };

  const handleCreate = async (payload) => {
    setBusyAction("create");
    setMessage("");
    try {
      const created = await createInterviewSession(payload);
      setSession(created);
      localStorage.setItem(ACTIVE_SESSION_KEY, String(created.id));
      await refreshSessions();
      await runStart(created.id);
    } catch (error) {
      setMessage(getFriendlyErrorMessage(error, "创建面试会话失败。"));
    } finally {
      setBusyAction("");
    }
  };

  const handleAnswer = async (turnId, answer) => {
    setBusyAction("answer");
    setMessage("");
    try {
      const result = await answerInterviewQuestion(session.id, turnId, answer);
      setSession((current) => ({ ...current, ...result }));
      setLatestResult(result);
      await refreshSessions();
    } catch (error) {
      try {
        const detail = await loadSession(session.id, "interview");
        const savedTurn = detail.turns?.find((turn) => turn.id === turnId);
        if (savedTurn?.user_answer) {
          setMessage(savedTurn.total_score == null ? "回答已保存，但评价尚未完成。请使用恢复处理。" : "回答和评价已保存，但下一题尚未生成。请使用恢复处理。");
        } else {
          setMessage(getFriendlyErrorMessage(error, "提交回答失败。"));
        }
      } catch {
        setMessage(getFriendlyErrorMessage(error, "提交回答失败。"));
      }
    } finally {
      setBusyAction("");
    }
  };

  const handleContinue = async () => {
    setBusyAction("refresh");
    try {
      const detail = await loadSession(session.id);
      if (detail.status === "completed") {
        setActiveSection("result");
      }
      await refreshSessions();
    } catch (error) {
      setMessage(getFriendlyErrorMessage(error, "刷新会话失败。"));
    } finally {
      setBusyAction("");
    }
  };

  const handleCancel = async () => {
    if (!window.confirm("确认取消当前面试会话吗？")) {
      return;
    }
    setBusyAction("cancel");
    try {
      await cancelInterviewSession(session.id);
      await loadSession(session.id, "result");
      await refreshSessions();
      setMessage("会话已取消。");
    } catch (error) {
      setMessage(getFriendlyErrorMessage(error, "取消会话失败。"));
    } finally {
      setBusyAction("");
    }
  };

  const handleDelete = async (sessionId) => {
    if (!window.confirm("确认删除这场面试及其题目、评价和改进任务吗？")) {
      return;
    }
    setBusyAction(`delete-${sessionId}`);
    try {
      await deleteInterviewSession(sessionId);
      if (session?.id === sessionId) {
        setSession(null);
        setLatestResult(null);
        setActiveSection("setup");
        localStorage.removeItem(ACTIVE_SESSION_KEY);
      }
      await refreshSessions();
      setMessage("面试会话已删除。");
    } catch (error) {
      setMessage(getFriendlyErrorMessage(error, "删除会话失败。"));
    } finally {
      setBusyAction("");
    }
  };

  const handleImprovementRetry = async () => {
    setBusyAction("improvements");
    try {
      await retryImprovementGeneration(session.id);
      await loadSession(session.id, "tasks");
      await refreshSessions();
      setMessage("改进任务已生成。" );
    } catch (error) {
      await loadSession(session.id, "result");
      setMessage(getFriendlyErrorMessage(error, "改进任务生成仍未成功，可稍后重试。"));
    } finally {
      setBusyAction("");
    }
  };

  const handleTaskToggle = async (task) => {
    const previousStatus = task.status;
    const nextStatus = previousStatus === "completed" ? "pending" : "completed";
    setUpdatingTaskId(task.id);
    setSession((current) => ({ ...current, improvement_tasks: current.improvement_tasks.map((item) => item.id === task.id ? { ...item, status: nextStatus } : item) }));
    try {
      const updated = await updateImprovementTask(task.id, nextStatus);
      setSession((current) => ({ ...current, improvement_tasks: current.improvement_tasks.map((item) => item.id === task.id ? updated : item) }));
    } catch (error) {
      setSession((current) => ({ ...current, improvement_tasks: current.improvement_tasks.map((item) => item.id === task.id ? { ...item, status: previousStatus } : item) }));
      setMessage(getFriendlyErrorMessage(error, "更新改进任务失败，状态已恢复。"));
    } finally {
      setUpdatingTaskId(null);
    }
  };

  const handleRetrySession = async () => {
    setBusyAction("retry");
    try {
      const created = await createRetrySession(session.id);
      setRetryInfo(created);
      setSession(created);
      localStorage.setItem(ACTIVE_SESSION_KEY, String(created.id));
      setActiveSection("retry");
      await refreshSessions();
    } catch (error) {
      setMessage(getFriendlyErrorMessage(error, "创建再次练习失败。"));
    } finally {
      setBusyAction("");
    }
  };

  const handleLoadComparison = async () => {
    setBusyAction("comparison");
    try {
      setComparison(await getInterviewComparison(session.id));
    } catch (error) {
      setMessage(getFriendlyErrorMessage(error, "加载成绩对比失败。"));
    } finally {
      setBusyAction("");
    }
  };

  const handleGenerateResume = async (payload) => {
    setBusyAction("resume");
    try {
      const generated = await generateResumeDescription(payload);
      setDescriptions((current) => [generated, ...current]);
      setSelectedDescription(generated);
      setMessage("简历项目描述已生成并保存为新版本。" );
    } catch (error) {
      setMessage(getFriendlyErrorMessage(error, "生成简历项目描述失败，已有历史版本未受影响。"));
    } finally {
      setBusyAction("");
    }
  };

  const handleSelectDescription = async (descriptionId) => {
    setBusyAction("resume-detail");
    try {
      setSelectedDescription(await getResumeDescription(descriptionId));
    } catch (error) {
      setMessage(getFriendlyErrorMessage(error, "加载简历描述版本失败。"));
    } finally {
      setBusyAction("");
    }
  };

  const handleDeleteDescription = async (descriptionId) => {
    if (!window.confirm("确认删除这个简历项目描述版本吗？该操作不会删除上传的简历文件。")) {
      return;
    }
    setBusyAction("resume-delete");
    try {
      await deleteResumeDescription(descriptionId);
      const nextDescriptions = descriptions.filter((item) => item.id !== descriptionId);
      setDescriptions(nextDescriptions);
      setSelectedDescription(nextDescriptions[0] || null);
      setMessage("简历描述版本已删除。" );
    } catch (error) {
      setMessage(getFriendlyErrorMessage(error, "删除简历描述版本失败。"));
    } finally {
      setBusyAction("");
    }
  };

  const handleCopy = async (text) => {
    try {
      await navigator.clipboard.writeText(text);
      setMessage("内容已复制到剪贴板。" );
    } catch {
      setMessage("复制失败，请手动选择文本复制。" );
    }
  };

  const recoveryTurn = useMemo(() => {
    if (!session || session.status !== "in_progress" || session.current_question || latestResult) {
      return null;
    }
    return [...(session.turns || [])].reverse().find((turn) => turn.user_answer) || null;
  }, [latestResult, session]);

  const renderPreparation = () => (
    <>
      <div className="preparation-status">
        {preparationItems.map(([label, complete]) => (
          <div key={label} className={complete ? "complete" : "pending"}><span>{label}</span><strong>{complete ? "已就绪" : "待完善"}</strong></div>
        ))}
      </div>
      {preparationItems.some(([, complete]) => !complete) && (
        <div className="preparation-guidance">
          <div><strong>资料尚未完全准备好</strong><p>你仍可进行快速或标准面试；缺少的资料会降低个性化证据覆盖。</p></div>
          <div><button type="button" onClick={onOpenProfile}>完善资料</button><button type="button" className="secondary-button" onClick={onOpenKnowledge}>前往知识库</button></div>
        </div>
      )}
      <InterviewSetup targetJobs={targetJobs} projectFiles={projectFiles} activeJob={activeJob} busy={Boolean(busyAction)} draftSession={session?.status === "draft" ? session : null} onCreate={handleCreate} onStartDraft={runStart} />
    </>
  );

  const renderResult = () => {
    if (!session) {
      return <p className="empty-text">请选择一场会话查看结果。</p>;
    }
    if (session.status === "cancelled") {
      return <div className="interview-alert warning"><strong>会话已取消</strong><p>该会话不会继续生成问题，可以在会话列表中删除或新建练习。</p></div>;
    }
    if (session.status !== "completed") {
      return <div className="interview-alert warning"><strong>面试尚未完成</strong><p>完成全部计划问题后会生成整场评分和改进任务。</p></div>;
    }
    const dimensions = session.dimension_scores || {};
    return (
      <div className="session-result">
        <div className="session-score-summary">
          <div className="overall-score"><span>整场总分</span><strong>{session.overall_score ?? "-"}</strong></div>
          <div><h2>{session.title}</h2><p>{session.summary || "暂无会话总结。"}</p><span>完成于 {formatDate(session.completed_at)}</span></div>
        </div>
        <div className="dimension-summary-grid">
          {Object.entries({technical_accuracy_score:"技术准确性",evidence_consistency_score:"资料一致性",answer_depth_score:"回答深度",expression_structure_score:"表达结构",job_match_score:"岗位匹配度"}).map(([key,label]) => <div key={key}><span>{label}</span><strong>{dimensions[key] ?? "-"}</strong></div>)}
        </div>
        <div className="result-actions">
          <button type="button" onClick={() => setActiveSection("tasks")}>查看改进任务</button>
          <button type="button" onClick={handleRetrySession} disabled={Boolean(busyAction)}>再次练习</button>
          <button type="button" onClick={() => setActiveSection("resume")}>生成简历描述</button>
          {session.previous_session && <button type="button" className="secondary-button" onClick={handleLoadComparison}>查看成绩对比</button>}
        </div>
        <div className={`improvement-status ${session.improvement_status}`}>
          <strong>改进任务状态：{session.improvement_status}</strong>
          {session.improvement_summary && <p>{session.improvement_summary}</p>}
          {session.next_round_strategy && <p><strong>下一轮策略：</strong>{session.next_round_strategy}</p>}
          {session.improvement_status === "failed" && <button type="button" onClick={handleImprovementRetry} disabled={Boolean(busyAction)}>重试生成改进任务</button>}
        </div>
        {comparison && <ComparisonPanel comparison={comparison} />}
        <div className="turn-review-list">
          <h3>问题与评价回顾</h3>
          {(session.turns || []).map((turn) => <article key={turn.id} className="turn-review"><div className="question-meta"><span>{turn.follow_up_number ? `追问 ${turn.follow_up_number}` : `主问题 ${turn.main_question_number}`}</span><span>{turn.total_score ?? "待评价"}</span></div><h4>{turn.question}</h4><EvaluationPanel turn={turn} onCopy={handleCopy} compact /></article>)}
        </div>
      </div>
    );
  };

  const renderCurrentSection = () => {
    if (activeSection === "setup") return renderPreparation();
    if (activeSection === "interview") return session?.status === "in_progress" ? <InterviewWorkspace key={`${session.id}-${session.current_question?.id || recoveryTurn?.id || "result"}-${latestResult?.answered_turn?.id || "answer"}`} session={session} latestResult={latestResult} recoveryTurn={recoveryTurn} busy={Boolean(busyAction)} onSubmit={handleAnswer} onContinue={handleContinue} onCopy={handleCopy} onCancel={handleCancel} /> : <div className="interview-alert warning"><strong>没有进行中的会话</strong><p>从“准备面试”创建新会话，或从最近会话恢复草稿。</p></div>;
    if (activeSection === "result") return renderResult();
    if (activeSection === "tasks") return session?.status === "completed" ? <><div className="strategy-panel"><h3>改进诊断</h3><p>{session.improvement_summary || "暂无诊断。"}</p><h4>下一轮训练策略</h4><p>{session.next_round_strategy || "暂无策略。"}</p>{session.improvement_status === "failed" && <button type="button" onClick={handleImprovementRetry}>重试生成</button>}</div><ImprovementTaskList tasks={session.improvement_tasks || []} updatingTaskId={updatingTaskId} onToggle={handleTaskToggle} /></> : <p className="empty-text">完成一场面试后查看改进任务。</p>;
    if (activeSection === "retry") return retryInfo ? <div className="retry-confirmation"><span className="status-badge draft">再次练习草稿</span><h2>{retryInfo.title}</h2><p>上一轮任务共 {retryInfo.previous_task_count} 项，已完成 {retryInfo.completed_task_count} 项，完成率 {retryInfo.task_completion_rate}%。</p><p><strong>训练策略：</strong>{session.previous_session?.next_round_strategy || "启动后将使用上一轮策略和未完成任务作为计划参考，不作为事实证据。"}</p><button type="button" onClick={() => runStart(retryInfo.id)} disabled={Boolean(busyAction)}>确认并开始新一轮</button></div> : session?.previous_session ? <ComparisonPanel comparison={comparison} loading={busyAction === "comparison"} onLoad={handleLoadComparison} /> : <p className="empty-text">完成面试后可创建再次练习。</p>;
    if (activeSection === "resume") return <ResumeDescriptionPanel completedSessions={completedSessions} targetJobs={targetJobs} projectFiles={projectFiles} descriptions={descriptions} selectedDescription={selectedDescription} generating={busyAction === "resume"} onGenerate={handleGenerateResume} onSelect={handleSelectDescription} onDelete={handleDeleteDescription} onCopy={handleCopy} />;
    return null;
  };

  if (loading) {
    return <section className="interview-agent-page"><div className="page-loading" role="status">正在加载面试工作台...</div></section>;
  }

  return (
    <section className="interview-agent-page">
      <div className="interview-agent-heading">
        <div><h1>面试 Agent</h1><p>从真实资料出发，完成训练、评价、改进、复练和简历表达。</p></div>
        <button type="button" className="secondary-button" onClick={loadInitialData} disabled={Boolean(busyAction)}>刷新数据</button>
      </div>
      {message && <div className="workspace-message" role="status">{message}<button type="button" aria-label="关闭提示" onClick={() => setMessage("")}>×</button></div>}

      <div className="interview-section-tabs" role="tablist">
        {sectionTabs.map(([key, label]) => <button key={key} type="button" role="tab" aria-selected={activeSection === key} className={activeSection === key ? "active" : ""} onClick={() => setActiveSection(key)}>{label}</button>)}
      </div>

      <div className="interview-agent-layout">
        <main className="interview-stage">{renderCurrentSection()}</main>
        <aside className="recent-sessions">
          <div className="inline-heading"><h2>最近会话</h2><span>{sessions.length}</span></div>
          {sessions.length === 0 ? <p className="empty-text">暂无面试训练记录。</p> : sessions.slice(0, 10).map((item) => (
            <article key={item.id} className={session?.id === item.id ? "session-list-item active" : "session-list-item"}>
              <button type="button" className="session-select" onClick={() => loadSession(item.id)}>
                <div><strong>{item.title}</strong><span className={`status-badge ${item.status}`}>{statusLabels[item.status]}</span></div>
                <p>{modeLabels[item.mode]} · {formatDate(item.created_at)}</p>
                {item.overall_score != null && <span>总分 {item.overall_score}</span>}
              </button>
              <button type="button" className="session-delete-button" aria-label={`删除 ${item.title}`} onClick={() => handleDelete(item.id)} disabled={Boolean(busyAction)}>删除</button>
            </article>
          ))}
        </aside>
      </div>
    </section>
  );
}

export default InterviewAgent;
