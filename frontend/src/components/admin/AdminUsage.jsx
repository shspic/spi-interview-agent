import { useCallback, useEffect, useState } from "react";

import { getAdminUsageSummary, getAdminUserUsage } from "../../api/admin";
import { getFriendlyErrorMessage } from "../../utils/errorMessage";
import { formatDateTime } from "../../utils/format";

function AdminUsage({ dateRange, refreshKey, mode, onForbidden }) {
  const [summary, setSummary] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [userId, setUserId] = useState("");
  const [userUsage, setUserUsage] = useState(null);
  const [userError, setUserError] = useState("");
  const [userLoading, setUserLoading] = useState(false);

  const loadSummary = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      setSummary(await getAdminUsageSummary(dateRange));
    } catch (requestError) {
      if (requestError.response?.status === 403) onForbidden?.();
      setError(getFriendlyErrorMessage(requestError, "管理员统计读取失败。"));
    } finally {
      setLoading(false);
    }
  }, [dateRange, onForbidden]);

  useEffect(() => {
    const timer = window.setTimeout(loadSummary, 0);
    return () => window.clearTimeout(timer);
  }, [loadSummary, refreshKey]);

  const loadUserUsage = async (event) => {
    event.preventDefault();
    if (!userId) return;
    setUserLoading(true);
    setUserError("");
    setUserUsage(null);
    try {
      setUserUsage(await getAdminUserUsage(userId, dateRange));
    } catch (requestError) {
      if (requestError.response?.status === 403) onForbidden?.();
      setUserError(getFriendlyErrorMessage(requestError, "用户用量读取失败。"));
    } finally {
      setUserLoading(false);
    }
  };

  if (loading && !summary) return <div className="page-loading">正在读取管理统计...</div>;

  return (
    <div className="admin-panel">
      {error && <div className="notice-box error-notice"><span>{error}</span><button type="button" onClick={loadSummary}>重试</button></div>}
      {summary && (
        <>
          <div className="admin-metric-grid">
            <article><span>注册用户</span><strong>{summary.registered_user_count}</strong></article>
            <article><span>活跃用户</span><strong>{summary.active_user_count}</strong></article>
            <article><span>Agent 调用</span><strong>{summary.agent_run_count}</strong></article>
            <article><span>平均延迟</span><strong>{summary.average_latency_ms ?? "--"}<small> ms</small></strong></article>
          </div>

          <div className="admin-grid-two">
            <div className="admin-subpanel">
              <h3>四项业务使用次数</h3>
              <dl className="summary-list">
                {Object.entries(summary.business_usage || {}).map(([name, count]) => <div key={name}><dt>{name}</dt><dd>{count}</dd></div>)}
              </dl>
            </div>
            <div className="admin-subpanel">
              <h3>事件状态</h3>
              <dl className="summary-list">
                {Object.entries(summary.event_status_counts || {}).map(([name, count]) => <div key={name}><dt>{name}</dt><dd>{count}</dd></div>)}
              </dl>
            </div>
          </div>

          {mode === "overview" ? (
            <div className="admin-grid-two">
              <div className="admin-subpanel">
                <h3>按 Agent 分类</h3>
                {Object.keys(summary.agent_runs_by_name || {}).length ? (
                  <dl className="summary-list">
                    {Object.entries(summary.agent_runs_by_name).map(([name, item]) => <div key={name}><dt>{name}</dt><dd>成功 {item.success || 0} / 失败 {item.error || 0}</dd></div>)}
                  </dl>
                ) : <p className="empty-text">暂无 Agent 运行数据。</p>}
              </div>
              <div className="admin-subpanel">
                <h3>最近失败类型</h3>
                {(summary.recent_failure_types || []).length ? summary.recent_failure_types.map((item, index) => (
                  <p key={`${item.agent_name}-${index}`} className="failure-line"><strong>{item.agent_name}</strong> {item.error_type} <span>{formatDateTime(item.created_at)}</span></p>
                )) : <p className="empty-text">所选范围没有失败记录。</p>}
              </div>
            </div>
          ) : (
            <>
              <div className="admin-subpanel">
                <h3>每日趋势</h3>
                <div className="admin-table-scroll"><table className="admin-table"><thead><tr><th>日期</th><th>chat</th><th>job_analysis</th><th>interview_evaluation</th><th>multi_agent_task</th></tr></thead><tbody>
                  {(summary.daily_trend || []).map((item) => <tr key={item.date}><td>{item.date}</td><td>{item.chat || 0}</td><td>{item.job_analysis || 0}</td><td>{item.interview_evaluation || 0}</td><td>{item.multi_agent_task || 0}</td></tr>)}
                </tbody></table></div>
                {!summary.daily_trend?.length && <p className="empty-text">所选范围暂无趋势数据。</p>}
              </div>
              <div className="admin-subpanel">
                <h3>查询单个用户用量</h3>
                <form className="filter-toolbar" onSubmit={loadUserUsage}>
                  <label>用户 ID<input type="number" min="1" value={userId} onChange={(event) => setUserId(event.target.value)} required /></label>
                  <button type="submit" disabled={userLoading}>{userLoading ? "查询中..." : "查询"}</button>
                </form>
                {userError && <p className="inline-error">{userError}</p>}
                {userUsage && <div className="user-usage-result"><h4>{userUsage.user?.username}（ID {userUsage.user?.id}）</h4><div className="usage-grid compact">{(userUsage.today?.items || []).map((item) => <div key={item.usage_type}><span>{item.display_name}</span><strong>{item.used} / {item.limit}</strong><small>预留 {item.reserved}，剩余 {item.remaining}</small></div>)}</div><div className="admin-table-scroll"><table className="admin-table compact-table"><thead><tr><th>日期</th><th>类型</th><th>状态</th><th>次数</th></tr></thead><tbody>{(userUsage.events || []).map((item, index) => <tr key={`${item.date}-${item.usage_type}-${item.status}-${index}`}><td>{item.date}</td><td>{item.usage_type}</td><td>{item.status}</td><td>{item.amount}</td></tr>)}</tbody></table></div>{!userUsage.events?.length && <p className="empty-text">所选日期范围暂无该用户用量事件。</p>}</div>}
              </div>
            </>
          )}
        </>
      )}
    </div>
  );
}

export default AdminUsage;
