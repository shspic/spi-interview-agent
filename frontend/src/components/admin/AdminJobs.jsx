import { useCallback, useEffect, useState } from "react";

import { getAdminBackgroundJobs, getAdminWorkers } from "../../api/admin";
import { getFriendlyErrorMessage } from "../../utils/errorMessage";
import { formatDateTime, formatShortId } from "../../utils/format";

const statusLabels = {
  queued: "等待执行",
  running: "执行中",
  retry_wait: "等待重试",
  cancel_requested: "正在取消",
  succeeded: "已完成",
  failed: "失败",
  cancelled: "已取消",
  timed_out: "已超时",
};

function AdminJobs({ refreshKey, onForbidden }) {
  const [filters, setFilters] = useState({ user_id: "", task_type: "", status: "" });
  const [applied, setApplied] = useState(filters);
  const [page, setPage] = useState(1);
  const [jobs, setJobs] = useState({ items: [], total: 0, page_size: 20 });
  const [workers, setWorkers] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const [jobData, workerData] = await Promise.all([
        getAdminBackgroundJobs({ ...applied, page, page_size: 20 }),
        getAdminWorkers(),
      ]);
      setJobs(jobData);
      setWorkers(workerData);
    } catch (requestError) {
      if (requestError.response?.status === 403) onForbidden?.();
      setError(getFriendlyErrorMessage(requestError, "任务与 Worker 状态读取失败。"));
    } finally {
      setLoading(false);
    }
  }, [applied, onForbidden, page]);

  useEffect(() => {
    const timer = window.setTimeout(load, 0);
    return () => window.clearTimeout(timer);
  }, [load, refreshKey]);

  const pageCount = Math.max(1, Math.ceil(jobs.total / jobs.page_size));
  const apply = (event) => {
    event.preventDefault();
    setPage(1);
    setApplied(filters);
  };

  return <div className="admin-panel admin-jobs-panel">
    <section className="admin-worker-summary" aria-labelledby="worker-heading">
      <div className="section-heading"><h2 id="worker-heading">Worker 状态</h2><span>不展示内部标识和租约信息</span></div>
      {workers && <>
        <div className="admin-metric-grid compact">
          <article><span>在线</span><strong>{workers.online_count}</strong></article>
          <article><span>离线</span><strong>{workers.offline_count}</strong></article>
          <article><span>已停止</span><strong>{workers.stopped_count}</strong></article>
        </div>
        <div className="worker-card-grid">
          {workers.workers.map((worker) => <article key={`${worker.label}-${worker.started_at}`} className="worker-card">
            <div><strong>{worker.label}</strong><span className={`status-badge ${worker.state}`}>{worker.state === "online" ? "在线" : worker.state === "offline" ? "离线" : "已停止"}</span></div>
            <p>{worker.database_type} · 最近心跳 {formatDateTime(worker.last_seen_at)}</p>
          </article>)}
          {!workers.workers.length && <p className="empty-text">尚未记录 Worker 心跳。</p>}
        </div>
      </>}
    </section>

    <section aria-labelledby="jobs-heading">
      <div className="section-heading"><h2 id="jobs-heading">后台任务</h2><span>可筛选、分页，仅展示运行摘要</span></div>
      <form className="filter-toolbar" onSubmit={apply}>
        <label>用户 ID<input type="number" min="1" value={filters.user_id} onChange={(event) => setFilters((value) => ({ ...value, user_id: event.target.value }))} /></label>
        <label>任务类型<input value={filters.task_type} onChange={(event) => setFilters((value) => ({ ...value, task_type: event.target.value }))} placeholder="interview_start" /></label>
        <label>状态<select value={filters.status} onChange={(event) => setFilters((value) => ({ ...value, status: event.target.value }))}><option value="">全部</option>{Object.entries(statusLabels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
        <button type="submit">筛选</button>
        <button type="button" className="secondary-button" onClick={() => { const empty = { user_id: "", task_type: "", status: "" }; setFilters(empty); setApplied(empty); setPage(1); }}>清空</button>
      </form>
      {error && <p className="inline-error" role="alert">{error}</p>}
      <div className="admin-table-scroll"><table className="admin-table"><thead><tr><th>任务</th><th>用户</th><th>类型</th><th>状态</th><th>进度</th><th>尝试</th><th>时间</th></tr></thead><tbody>
        {jobs.items.map((job) => <tr key={job.id}><td title={job.id}>{formatShortId(job.id)}</td><td>{job.user_id}</td><td>{job.task_type}</td><td><span className={`status-badge ${job.status}`}>{statusLabels[job.status] || job.status}</span></td><td>{job.progress_percent}%</td><td>{job.attempt_count} / {job.max_attempts}</td><td>{formatDateTime(job.created_at)}{job.error_summary && <small className="table-error-summary">{job.error_summary}</small>}</td></tr>)}
      </tbody></table></div>
      {loading && <p className="loading-line">正在读取运行状态…</p>}
      {!loading && !jobs.items.length && <p className="empty-text">没有符合条件的后台任务。</p>}
      <div className="pagination"><button type="button" disabled={page <= 1 || loading} onClick={() => setPage((value) => value - 1)}>上一页</button><span>第 {page} / {pageCount} 页，共 {jobs.total} 条</span><button type="button" disabled={page >= pageCount || loading} onClick={() => setPage((value) => value + 1)}>下一页</button></div>
    </section>
  </div>;
}

export default AdminJobs;
