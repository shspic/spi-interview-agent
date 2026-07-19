import { useCallback, useEffect, useState } from "react";

import { getAdminAgentRuns, getAdminAuditLogs } from "../../api/admin";
import { getFriendlyErrorMessage } from "../../utils/errorMessage";
import { formatDateTime, formatShortId } from "../../utils/format";

function CopyId({ value }) {
  const copy = async () => {
    if (value != null) await navigator.clipboard.writeText(String(value));
  };
  return <button type="button" className="copy-id" title={String(value || "")} onClick={copy}>{formatShortId(value)}</button>;
}

function AdminRecords({ kind, dateRange, refreshKey, onForbidden }) {
  const [filters, setFilters] = useState(kind === "agent" ? { user_id: "", session_id: "", agent_name: "", status: "" } : { action: "", admin_user_id: "", target_user_id: "", status: "" });
  const [applied, setApplied] = useState(filters);
  const [page, setPage] = useState(1);
  const [data, setData] = useState({ items: [], total: 0, page_size: 20 });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    setLoading(true); setError("");
    try {
      const params = { ...applied, ...dateRange, page, page_size: 20 };
      setData(kind === "agent" ? await getAdminAgentRuns(params) : await getAdminAuditLogs(params));
    } catch (requestError) {
      if (requestError.response?.status === 403) onForbidden?.();
      setError(getFriendlyErrorMessage(requestError, kind === "agent" ? "Agent 运行记录读取失败。" : "审计日志读取失败。"));
    } finally { setLoading(false); }
  }, [applied, dateRange, kind, page, onForbidden]);

  useEffect(() => {
    const timer = window.setTimeout(load, 0);
    return () => window.clearTimeout(timer);
  }, [load, refreshKey]);

  const apply = (event) => { event.preventDefault(); setPage(1); setApplied(filters); };
  const clear = () => {
    const next = kind === "agent" ? { user_id: "", session_id: "", agent_name: "", status: "" } : { action: "", admin_user_id: "", target_user_id: "", status: "" };
    setFilters(next); setApplied(next); setPage(1);
  };
  const pageCount = Math.max(1, Math.ceil(data.total / data.page_size));

  return <div className="admin-panel">
    <form className="filter-toolbar" onSubmit={apply}>
      {kind === "agent" ? <>
        <label>用户 ID<input type="number" min="1" value={filters.user_id} onChange={(e) => setFilters((v) => ({ ...v, user_id: e.target.value }))} /></label>
        <label>会话 ID<input type="number" min="1" value={filters.session_id} onChange={(e) => setFilters((v) => ({ ...v, session_id: e.target.value }))} /></label>
        <label>Agent<input value={filters.agent_name} onChange={(e) => setFilters((v) => ({ ...v, agent_name: e.target.value }))} placeholder="evaluation" /></label>
      </> : <>
        <label>操作<input value={filters.action} onChange={(e) => setFilters((v) => ({ ...v, action: e.target.value }))} placeholder="delete_user" /></label>
        <label>管理员 ID<input type="number" min="1" value={filters.admin_user_id} onChange={(e) => setFilters((v) => ({ ...v, admin_user_id: e.target.value }))} /></label>
        <label>目标用户 ID<input type="number" min="1" value={filters.target_user_id} onChange={(e) => setFilters((v) => ({ ...v, target_user_id: e.target.value }))} /></label>
      </>}
      <label>状态<select value={filters.status} onChange={(e) => setFilters((v) => ({ ...v, status: e.target.value }))}><option value="">全部</option><option value="success">success</option><option value={kind === "agent" ? "error" : "failed"}>{kind === "agent" ? "error" : "failed"}</option></select></label>
      <button type="submit">筛选</button><button type="button" className="secondary-button" onClick={clear}>清空</button>
    </form>
    {error && <p className="inline-error">{error}</p>}
    <div className="admin-table-scroll"><table className="admin-table"><thead>{kind === "agent" ? <tr><th>run_id</th><th>用户 / 会话</th><th>Agent / Prompt</th><th>状态</th><th>耗时</th><th>错误类型</th><th>时间</th></tr> : <tr><th>管理员</th><th>操作</th><th>目标用户</th><th>资源</th><th>状态</th><th>脱敏摘要</th><th>时间</th></tr>}</thead><tbody>
      {data.items.map((item) => kind === "agent" ? <tr key={item.id}><td><CopyId value={item.run_id} /></td><td>用户 {item.user_id}<br />会话 {item.session_id}</td><td><strong>{item.agent_name}</strong><br /><small>{item.prompt_version}</small></td><td><span className={`status-badge ${item.status === "success" ? "success" : "failed"}`}>{item.status}</span></td><td>{item.latency_ms} ms</td><td>{item.error_type || "--"}</td><td>{formatDateTime(item.created_at)}</td></tr> : <tr key={item.id}><td>{item.admin_user_id ?? "--"}</td><td><strong>{item.action}</strong></td><td>{item.target_user_id ?? "--"}</td><td>{item.resource_type}<br /><CopyId value={item.resource_id} /></td><td><span className={`status-badge ${item.status === "success" ? "success" : "failed"}`}>{item.status}</span></td><td className="summary-cell">{item.detail_summary}</td><td>{formatDateTime(item.created_at)}</td></tr>)}
    </tbody></table></div>
    {loading && <p className="loading-line">正在读取记录...</p>}
    {!loading && !data.items.length && <p className="empty-text">没有符合条件的记录。</p>}
    <div className="pagination"><button type="button" disabled={page <= 1 || loading} onClick={() => setPage((v) => v - 1)}>上一页</button><span>第 {page} / {pageCount} 页，共 {data.total} 条</span><button type="button" disabled={page >= pageCount || loading} onClick={() => setPage((v) => v + 1)}>下一页</button></div>
  </div>;
}

export default AdminRecords;
