import { useCallback, useEffect, useState } from "react";

import {
  deleteAdminUser,
  getAdminUser,
  getAdminUsers,
  resetAdminUserPassword,
  updateAdminUserStatus,
} from "../../api/admin";
import { getFriendlyErrorMessage } from "../../utils/errorMessage";
import { formatDateTime } from "../../utils/format";

const emptyAction = { type: "", user: null };

function formatUsage(item) {
  return `${item.used}/${item.unlimited ? "无限" : item.limit}`;
}

function AdminUsers({ refreshKey, onForbidden }) {
  const [filters, setFilters] = useState({ username: "", is_active: "", is_admin: "", sort_order: "desc" });
  const [appliedFilters, setAppliedFilters] = useState(filters);
  const [page, setPage] = useState(1);
  const [data, setData] = useState({ items: [], total: 0, page: 1, page_size: 10 });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [action, setAction] = useState(emptyAction);
  const [actionLoading, setActionLoading] = useState(false);
  const [temporaryPassword, setTemporaryPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [confirmUsername, setConfirmUsername] = useState("");
  const [deleteResult, setDeleteResult] = useState(null);
  const [userDetail, setUserDetail] = useState(null);

  const loadUsers = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      setData(await getAdminUsers({ ...appliedFilters, page, page_size: 10 }));
    } catch (requestError) {
      if (requestError.response?.status === 403) onForbidden?.();
      setError(getFriendlyErrorMessage(requestError, "用户列表读取失败。"));
    } finally {
      setLoading(false);
    }
  }, [appliedFilters, page, onForbidden]);

  useEffect(() => {
    const timer = window.setTimeout(loadUsers, 0);
    return () => window.clearTimeout(timer);
  }, [loadUsers, refreshKey]);

  const applyFilters = (event) => {
    event.preventDefault();
    setPage(1);
    setAppliedFilters(filters);
  };

  const closeAction = () => {
    setAction(emptyAction);
    setTemporaryPassword("");
    setConfirmPassword("");
    setConfirmUsername("");
    setDeleteResult(null);
    setUserDetail(null);
  };

  const openDetail = async (user) => {
    setAction({ type: "detail", user });
    setActionLoading(true);
    setError("");
    try {
      setUserDetail(await getAdminUser(user.id));
    } catch (requestError) {
      if (requestError.response?.status === 403) onForbidden?.();
      setError(getFriendlyErrorMessage(requestError, "用户详情读取失败。"));
    } finally {
      setActionLoading(false);
    }
  };

  const executeStatus = async () => {
    setActionLoading(true); setError(""); setMessage("");
    try {
      await updateAdminUserStatus(action.user.id, !action.user.is_active);
      setMessage(`${action.user.username} 已${action.user.is_active ? "禁用" : "启用"}。`);
      closeAction(); await loadUsers();
    } catch (requestError) {
      if (requestError.response?.status === 403) onForbidden?.();
      setError(getFriendlyErrorMessage(requestError, "账号状态更新失败。"));
    } finally { setActionLoading(false); }
  };

  const executeReset = async (event) => {
    event.preventDefault();
    if (temporaryPassword !== confirmPassword) { setError("两次输入的临时密码不一致。"); return; }
    setActionLoading(true); setError(""); setMessage("");
    try {
      await resetAdminUserPassword(action.user.id, temporaryPassword);
      setTemporaryPassword(""); setConfirmPassword("");
      setMessage(`${action.user.username} 的密码已重置，请通过安全渠道告知用户。`);
      closeAction();
    } catch (requestError) {
      if (requestError.response?.status === 403) onForbidden?.();
      setError(getFriendlyErrorMessage(requestError, "密码重置失败。"));
    } finally { setActionLoading(false); }
  };

  const executeDelete = async (event) => {
    event.preventDefault(); setActionLoading(true); setError(""); setMessage(""); setDeleteResult(null);
    try {
      const result = await deleteAdminUser(action.user.id, confirmUsername);
      setDeleteResult(result);
      setConfirmUsername("");
      if (result.success) { setMessage(`${action.user.username} 及关联数据已删除。`); await loadUsers(); }
    } catch (requestError) {
      if (requestError.response?.status === 403) onForbidden?.();
      setError(getFriendlyErrorMessage(requestError, "用户删除失败。"));
    } finally { setActionLoading(false); }
  };

  const pageCount = Math.max(1, Math.ceil(data.total / data.page_size));

  return (
    <div className="admin-panel">
      <form className="filter-toolbar" onSubmit={applyFilters}>
        <label>用户名<input value={filters.username} onChange={(e) => setFilters((v) => ({ ...v, username: e.target.value }))} /></label>
        <label>账号状态<select value={filters.is_active} onChange={(e) => setFilters((v) => ({ ...v, is_active: e.target.value }))}><option value="">全部</option><option value="true">正常</option><option value="false">停用</option></select></label>
        <label>账号角色<select value={filters.is_admin} onChange={(e) => setFilters((v) => ({ ...v, is_admin: e.target.value }))}><option value="">全部</option><option value="true">管理员</option><option value="false">普通用户</option></select></label>
        <label>创建时间<select value={filters.sort_order} onChange={(e) => setFilters((v) => ({ ...v, sort_order: e.target.value }))}><option value="desc">从新到旧</option><option value="asc">从旧到新</option></select></label>
        <button type="submit">筛选</button>
      </form>
      {error && <p className="inline-error" role="alert">{error}</p>}
      {message && <p className="inline-success" role="status">{message}</p>}
      <div className="admin-table-scroll"><table className="admin-table"><thead><tr><th>用户</th><th>状态</th><th>角色</th><th>创建 / 登录</th><th>今日用量</th><th>资源</th><th>操作</th></tr></thead><tbody>
        {data.items.map((user) => <tr key={user.id}><td><strong>{user.username}</strong><small>ID {user.id}</small></td><td><span className={`status-badge ${user.is_active ? "success" : "failed"}`}>{user.is_active ? "正常" : "停用"}</span></td><td>{user.is_admin ? "管理员" : "普通用户"}<small>{user.is_quota_exempt ? "额度豁免" : "额度受限"}</small></td><td><small>创建 {formatDateTime(user.created_at)}<br />登录 {formatDateTime(user.last_login_at)}</small></td><td><div className="usage-cell">{(user.today_usage || []).map((item) => <span key={item.usage_type}>{item.display_name} {formatUsage(item)}</span>)}</div></td><td>文件 {user.file_count}<br />会话 {user.interview_session_count}</td><td><div className="row-actions"><button type="button" onClick={() => openDetail(user)}>详情</button><button type="button" onClick={() => setAction({ type: "status", user })}>{user.is_active ? "禁用" : "启用"}</button><button type="button" onClick={() => setAction({ type: "reset", user })}>重置密码</button><button type="button" className="danger-link" onClick={() => setAction({ type: "delete", user })}>删除</button></div></td></tr>)}
      </tbody></table></div>
      {loading && <p className="loading-line">正在读取用户...</p>}
      {!loading && !data.items.length && <p className="empty-text">没有符合条件的用户。</p>}
      <div className="pagination"><button type="button" disabled={page <= 1 || loading} onClick={() => setPage((v) => v - 1)}>上一页</button><span>第 {page} / {pageCount} 页，共 {data.total} 条</span><button type="button" disabled={page >= pageCount || loading} onClick={() => setPage((v) => v + 1)}>下一页</button></div>

      {action.user && <div className="confirmation-panel" role="dialog" aria-modal="true"><div className="confirmation-card">
        {error && <p className="inline-error" role="alert">{error}</p>}
        {action.type === "detail" && <><h3>用户详情</h3>{actionLoading ? <p>正在读取...</p> : userDetail && <><dl className="account-detail-grid"><div><dt>用户名</dt><dd>{userDetail.username}</dd></div><div><dt>状态</dt><dd>{userDetail.is_active ? "正常" : "停用"}</dd></div><div><dt>角色</dt><dd>{userDetail.is_admin ? "管理员" : "普通用户"}</dd></div><div><dt>额度</dt><dd>{userDetail.is_quota_exempt ? "豁免" : "受限"}</dd></div><div><dt>文件 / 会话</dt><dd>{userDetail.file_count} / {userDetail.interview_session_count}</dd></div></dl><div className="usage-cell detail-usage">{(userDetail.today_usage || []).map((item) => <span key={item.usage_type}>{item.display_name} {formatUsage(item)}</span>)}</div></>}<div className="dialog-actions"><button type="button" className="secondary-button" onClick={closeAction}>关闭</button></div></>}
        {action.type === "status" && <><h3>{action.user.is_active ? "禁用" : "启用"}用户</h3><p>确认{action.user.is_active ? "禁用" : "启用"}账号 <strong>{action.user.username}</strong>？禁用后已有 JWT 将在下一次请求时失效。</p><div className="dialog-actions"><button type="button" onClick={executeStatus} disabled={actionLoading}>确认操作</button><button type="button" className="secondary-button" onClick={closeAction}>取消</button></div></>}
        {action.type === "reset" && <form onSubmit={executeReset}><h3>重置 {action.user.username} 的密码</h3><label>新临时密码<input type="password" value={temporaryPassword} onChange={(e) => setTemporaryPassword(e.target.value)} minLength={8} maxLength={72} required autoComplete="new-password" /></label><label>确认临时密码<input type="password" value={confirmPassword} onChange={(e) => setConfirmPassword(e.target.value)} minLength={8} maxLength={72} required autoComplete="new-password" /></label><p className="field-help">这是兼容的管理员紧急重置入口。成功后会撤销用户全部会话，临时密码按系统配置的有效期生效，用户登录后必须立即修改。密码不会被保存到浏览器存储或在成功后回显。</p><div className="dialog-actions"><button type="submit" disabled={actionLoading}>确认重置</button><button type="button" className="secondary-button" onClick={closeAction}>取消</button></div></form>}
        {action.type === "delete" && <form onSubmit={executeDelete}><h3>删除用户及业务数据</h3><p>将删除 <strong>{action.user.username}</strong> 的上传文件、向量、面试记录和生成内容。此操作不可恢复。</p><label>输入目标用户名确认<input value={confirmUsername} onChange={(e) => setConfirmUsername(e.target.value)} required autoComplete="off" /></label><div className="dialog-actions"><button type="submit" className="danger-button" disabled={actionLoading || confirmUsername !== action.user.username}>永久删除</button><button type="button" className="secondary-button" onClick={closeAction}>取消</button></div>{deleteResult && <div className={deleteResult.success ? "operation-result success" : "operation-result partial"}><strong>{deleteResult.success ? "删除完成" : "仅部分完成"}</strong><p>{Object.entries(deleteResult.deleted_counts || {}).map(([name, count]) => `${name} ${count}`).join("，")}</p>{(deleteResult.failed_items || []).map((item, index) => <p key={index}>{item.resource_type}：{item.error_type}</p>)}</div>}</form>}
      </div></div>}
    </div>
  );
}

export default AdminUsers;
