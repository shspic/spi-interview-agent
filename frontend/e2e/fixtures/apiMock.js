const now = "2026-07-20T10:00:00Z";

function json(route, data, status = 200) {
  return route.fulfill({ status, contentType: "application/json", body: JSON.stringify(data) });
}

export async function installApiMock(page, options = {}) {
  const interviewEvaluation = Boolean(options.interviewEvaluation);
  const initialInterviewSession = {
    id: 7,
    title: "快速练习",
    mode: "quick",
    status: "in_progress",
    planned_main_questions: 3,
    current_main_question: 1,
    selected_project_file_ids: [],
  };
  const state = {
    authenticated: options.authenticated ?? true,
    admin: options.admin ?? false,
    files: options.files ? [...options.files] : [],
    jobStatus: options.jobStatus || "succeeded",
    taskPolls: 0,
    taskPollDelayMs: options.taskPollDelayMs || 0,
    sessionDetailRequests: 0,
    sessionListRequests: 0,
    profileRequests: 0,
    refreshRequests: 0,
    refreshCsrfHeader: null,
    evaluationRequests: 0,
    evaluationCsrfHeader: null,
    answerSubmitted: false,
    submittedAnswer: "",
    sessions: interviewEvaluation ? [initialInterviewSession] : [],
  };
  await page.context().addCookies([{ name: "spi_csrf", value: "fixture-csrf", domain: "127.0.0.1", path: "/" }]);

  const user = () => ({ id: state.admin ? 1 : 2, username: state.admin ? "demo_admin" : "demo_user", is_admin: state.admin, is_active: true, created_at: now, last_login_at: now });
  const profile = { display_name: "演示用户", target_direction: "Python 后端", self_introduction: "专注可靠的 AI 应用工程。", technical_skills: ["Python", "FastAPI", "PostgreSQL"] };
  const targetJobs = [{ id: 10, job_title: "Python 后端工程师", company_name: "虚构科技", jd_text: "负责 API 与异步任务系统。", notes: "", is_active: true }];
  const interviewQuestion = { id: 70, session_id: 7, question: "请介绍一次你处理后台任务可靠性的经历。", sequence_number: 1, main_question_number: 1, follow_up_number: 0, question_type: "main" };
  const followUpQuestion = { id: 71, session_id: 7, question: "你如何验证任务不会被重复执行？", sequence_number: 2, main_question_number: 1, follow_up_number: 1, question_type: "follow_up" };
  const task = (status = state.jobStatus) => ({
    task_id: "fixture-task-1",
    task_type: interviewEvaluation ? "interview_evaluation" : "knowledge_rebuild",
    status,
    progress_percent: status === "succeeded" ? 100 : status === "timed_out" ? 72 : status === "cancelled" ? 35 : 20,
    phase: status === "succeeded" ? "completed" : status === "queued" ? "queued" : "failed",
    created_at: now,
    error_summary: status === "failed" ? "回答评价任务执行失败" : status === "timed_out" ? "任务超过允许时间，可重新创建。" : null,
    result: interviewEvaluation
      ? { session_id: 7, answered_turn_id: 70, is_completed: false, decision: { action: "follow_up", reason: "需要补充验证细节。" } }
      : { total_chunks: 4, session_id: 7 },
  });

  const sessionDetail = () => {
    const successfulEvaluation = state.answerSubmitted && state.jobStatus === "succeeded";
    const answeredTurn = {
      ...interviewQuestion,
      user_answer: state.submittedAnswer,
      technical_accuracy_score: successfulEvaluation ? 80 : null,
      evidence_consistency_score: successfulEvaluation ? 75 : null,
      answer_depth_score: successfulEvaluation ? 70 : null,
      expression_structure_score: successfulEvaluation ? 85 : null,
      job_match_score: successfulEvaluation ? 75 : null,
      total_score: successfulEvaluation ? 77 : null,
      evaluation_summary: successfulEvaluation ? "回答结构清晰，并说明了任务可靠性措施。" : null,
      optimized_answer: successfulEvaluation ? "我通过 lease、heartbeat 和幂等键避免任务重复执行。" : null,
    };
    const turns = state.answerSubmitted
      ? [answeredTurn, ...(successfulEvaluation ? [followUpQuestion] : [])]
      : [];
    return {
      ...initialInterviewSession,
      completed_main_questions: 0,
      current_follow_up_count: successfulEvaluation ? 1 : 0,
      evidence_limited: false,
      target_job: targetJobs[0],
      current_question: state.answerSubmitted
        ? (successfulEvaluation ? followUpQuestion : null)
        : interviewQuestion,
      turns,
      improvement_tasks: [],
    };
  };

  await page.route(/^https?:\/\/[^/]+\/api(?:\/|$)/, async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    const method = request.method();

    if (path === "/api/auth/csrf") return json(route, { csrf_token: "fixture-csrf" });
    if (path === "/api/auth/me") return state.authenticated ? json(route, { user: user() }) : json(route, { detail: "未登录" }, 401);
    if (path === "/api/auth/register") return json(route, { success: true }, 201);
    if (path === "/api/auth/login") { state.authenticated = true; return json(route, { user: user() }); }
    if (path === "/api/auth/refresh") { state.refreshRequests += 1; state.refreshCsrfHeader = request.headers()["x-csrf-token"] || null; return state.authenticated ? json(route, { success: true }) : json(route, { detail: "会话失效" }, 401); }
    if (path === "/api/auth/logout" || path === "/api/auth/logout-all") { state.authenticated = false; return json(route, { success: true }); }
    if (path === "/api/auth/change-password") return json(route, { success: true, message: "密码已修改，请重新登录。" });
    if (path === "/api/health/ready") return json(route, { status: options.degraded ? "not_ready" : "ready", auth_ready: true, database_ready: !options.degraded, database_type: "postgresql", schema_ready: true, storage_ready: true, task_system_ready: true, worker_ready: !options.degraded }, options.degraded ? 503 : 200);
    if (path === "/api/system/status") return json(route, { database: { file_count: state.files.length, interview_count: state.sessions.length }, knowledge_base: { total_chunks: state.files.length * 4 } });
    if (path === "/api/profile" && method === "GET") { state.profileRequests += 1; if (options.profileUnauthorizedOnce && state.profileRequests === 1) return json(route, { detail: "访问凭证已过期" }, 401); return json(route, { profile }); }
    if (path === "/api/profile" && method === "PUT") return json(route, profile);
    if (path === "/api/target-jobs" && method === "GET") return json(route, { jobs: targetJobs });
    if (path === "/api/files" && method === "GET") return json(route, { files: state.files });
    if (path === "/api/files/upload") { state.files.push({ file_id: "fixture-file-1", filename: "demo-project.txt", file_type: "txt", category: "project", status: "uploaded", created_at: now }); return json(route, { success: true }, 201); }
    if (path.startsWith("/api/files/") && method === "DELETE") { state.files = []; return json(route, { success: true }); }
    if (path === "/api/knowledge/status") return json(route, { total_files: state.files.length, indexed_files: state.files.length, failed_files: 0, total_chunks: state.files.length * 4, status: "ready" });
    if (path === "/api/knowledge/search") return json(route, { results: [{ file_id: "fixture-file-1", filename: "demo-project.txt", text: "使用数据库任务表、lease 与 heartbeat 保障任务恢复。" }] });
    if (path === "/api/interview-sessions" && method === "GET") { state.sessionListRequests += 1; return json(route, { sessions: state.sessions }); }
    if (path === "/api/interview-sessions" && method === "POST") { const created = { id: 7, title: "快速练习", mode: "quick", status: "draft", planned_main_questions: 3, selected_project_file_ids: [] }; state.sessions = [created]; return json(route, created, 201); }
    if (path === "/api/interview-sessions/7") {
      state.sessionDetailRequests += 1;
      if (options.sessionRefreshFailure && state.answerSubmitted) {
        return json(route, { detail: "会话刷新暂时不可用" }, 503);
      }
      return json(route, sessionDetail());
    }
    if (path === "/api/resume-project-descriptions") return json(route, { descriptions: [] });
    if (path === "/api/tasks" && method === "GET") return json(route, { items: options.globalJobs || [], total: (options.globalJobs || []).length, page: 1, page_size: 20 });
    if (path.startsWith("/api/tasks/") && method === "GET") { state.taskPolls += 1; if (state.taskPollDelayMs) await new Promise((resolve) => setTimeout(resolve, state.taskPollDelayMs)); return json(route, task()); }
    if (path.startsWith("/api/tasks/") && path.endsWith("/cancel")) return json(route, task("cancelled"));
    if (path === "/api/tasks/interview-evaluation" && method === "POST") { const payload = request.postDataJSON(); state.evaluationRequests += 1; state.evaluationCsrfHeader = request.headers()["x-csrf-token"] || null; state.answerSubmitted = true; state.submittedAnswer = payload.answer; return json(route, task("queued"), 202); }
    if (path.startsWith("/api/tasks/") && method === "POST") return json(route, task("queued"), 202);
    if (path === "/api/usage/me") return json(route, { current_date: "2026-07-20", timezone: "Asia/Shanghai", items: [{ usage_type: "interview_evaluation", display_name: "面试评价", used: 1, reserved: 0, limit: 10, remaining: 9, reset_at: "2026-07-21T00:00:00+08:00" }] });
    if (path === "/api/admin/usage/summary") return json(route, { registered_user_count: 2, active_user_count: 2, agent_run_count: 3, average_latency_ms: 120, business_usage: {}, event_status_counts: {}, daily_trend: [], agent_runs_by_name: {}, recent_failure_types: [] });
    if (path === "/api/admin/background-jobs") return json(route, { items: [], total: 0, page: 1, page_size: 20 });
    if (path === "/api/admin/workers") return json(route, { online_count: 1, offline_count: 0, stopped_count: 0, workers: [{ label: "Worker 1", state: "online", database_type: "postgresql", started_at: now, last_seen_at: now, stopped_at: null }] });
    return json(route, { detail: `fixture 未实现 ${method} ${path}` }, 404);
  });

  return state;
}
