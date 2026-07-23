import { useCallback, useEffect, useRef, useState } from "react";

import {
  approvePasswordResetRequest,
  getPasswordResetRequests,
  rejectPasswordResetRequest,
} from "../../api/admin";
import { getFriendlyErrorMessage } from "../../utils/errorMessage";
import { formatDateTime } from "../../utils/format";

const statusLabels = {
  pending: "待处理",
  approved: "已批准",
  rejected: "已拒绝",
  cancelled: "已取消",
};

function AdminPasswordResets({ refreshKey, onForbidden }) {
  const [status, setStatus] = useState("pending");
  const [data, setData] = useState({ items: [], total: 0 });
  const [selected, setSelected] = useState(null);
  const [adminNote, setAdminNote] = useState("");
  const [temporaryPassword, setTemporaryPassword] = useState("");
  const [copyMessage, setCopyMessage] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [processing, setProcessing] = useState(false);
  const dialogRef = useRef(null);
  const triggerRef = useRef(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      setData(await getPasswordResetRequests({ status, page: 1, page_size: 100 }));
    } catch (requestError) {
      if (requestError.response?.status === 403) onForbidden?.();
      setError(getFriendlyErrorMessage(requestError, "密码重置申请读取失败。"));
    } finally {
      setLoading(false);
    }
  }, [onForbidden, status]);

  const closeDialog = () => {
    setSelected(null);
    setAdminNote("");
    setTemporaryPassword("");
    setCopyMessage("");
    setError("");
    window.setTimeout(() => triggerRef.current?.focus(), 0);
  };

  useEffect(() => {
    const timer = window.setTimeout(load, 0);
    return () => window.clearTimeout(timer);
  }, [load, refreshKey]);

  useEffect(() => {
    if (!selected && !temporaryPassword) return undefined;
    dialogRef.current?.focus();
    const handleDialogKey = (event) => {
      if (event.key === "Escape" && !processing) closeDialog();
      if (event.key !== "Tab") return;
      const focusable = dialogRef.current?.querySelectorAll(
        'button:not([disabled]), textarea:not([disabled]), input:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex="-1"])',
      );
      if (!focusable?.length) {
        event.preventDefault();
        dialogRef.current?.focus();
        return;
      }
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };
    window.addEventListener("keydown", handleDialogKey);
    return () => window.removeEventListener("keydown", handleDialogKey);
  });

  const approve = async () => {
    setProcessing(true);
    setError("");
    try {
      const result = await approvePasswordResetRequest(selected.id, adminNote);
      setTemporaryPassword(result.temporary_password);
      setSelected(null);
      await load();
    } catch (requestError) {
      if (requestError.response?.status === 403) onForbidden?.();
      setError(getFriendlyErrorMessage(requestError, "批准申请失败。"));
    } finally {
      setProcessing(false);
    }
  };

  const reject = async () => {
    setProcessing(true);
    setError("");
    try {
      await rejectPasswordResetRequest(selected.id, adminNote);
      closeDialog();
      await load();
    } catch (requestError) {
      if (requestError.response?.status === 403) onForbidden?.();
      setError(getFriendlyErrorMessage(requestError, "拒绝申请失败。"));
    } finally {
      setProcessing(false);
    }
  };

  const copyPassword = async () => {
    try {
      await navigator.clipboard.writeText(temporaryPassword);
      setCopyMessage("临时密码已复制。");
    } catch {
      setCopyMessage("复制失败，请手动选择临时密码。");
    }
  };

  return (
    <div className="admin-panel password-reset-admin">
      <div className="page-heading-row">
        <div><h2>密码重置申请</h2><p>批准后由系统生成一次性临时密码，并立即撤销目标用户的全部会话。</p></div>
        <label>状态筛选<select value={status} onChange={(event) => setStatus(event.target.value)}><option value="pending">待处理</option><option value="approved">已批准</option><option value="rejected">已拒绝</option><option value="">全部</option></select></label>
      </div>
      {error && <p className="inline-error" role="alert">{error}</p>}
      {loading && <p className="loading-line" role="status">正在读取申请...</p>}
      {!loading && data.items.length === 0 && <div className="empty-state"><strong>当前没有符合条件的申请</strong><p>新的匿名申请会在这里等待管理员处理。</p></div>}
      <div className="admin-table-scroll"><table className="admin-table password-reset-table"><thead><tr><th>用户</th><th>申请时间</th><th>申请备注</th><th>管理员备注</th><th>状态</th><th>操作</th></tr></thead><tbody>{data.items.map((item) => <tr key={item.id}><td><strong>{item.username}</strong><small>申请 #{item.id}</small></td><td>{formatDateTime(item.requested_at)}</td><td className="summary-cell">{item.request_note || "未填写"}</td><td className="summary-cell">{item.admin_note || "—"}</td><td><span className={`status-badge ${item.status === "approved" ? "success" : item.status === "rejected" ? "failed" : "warning"}`}>{statusLabels[item.status]}</span></td><td>{item.status === "pending" ? <button type="button" onClick={(event) => { triggerRef.current = event.currentTarget; setSelected(item); setError(""); }}>处理申请</button> : "已处理"}</td></tr>)}</tbody></table></div>

      {selected && <div className="confirmation-panel" role="dialog" aria-modal="true" aria-labelledby="password-reset-decision-title"><div className="confirmation-card" ref={dialogRef} tabIndex={-1}><h3 id="password-reset-decision-title">处理 {selected.username} 的申请</h3><p>批准会立即替换密码并撤销该用户的全部会话；拒绝不会修改账号。</p><label>管理员备注<textarea value={adminNote} onChange={(event) => setAdminNote(event.target.value)} maxLength={500} rows={4} /></label>{error && <p className="inline-error" role="alert">{error}</p>}<div className="dialog-actions"><button type="button" className="secondary-button" onClick={closeDialog} disabled={processing}>取消</button><button type="button" className="danger-button" onClick={reject} disabled={processing}>拒绝</button><button type="button" onClick={approve} disabled={processing}>批准并生成临时密码</button></div></div></div>}

      {temporaryPassword && <div className="confirmation-panel" role="dialog" aria-modal="true" aria-labelledby="temporary-password-title"><div className="confirmation-card one-time-secret" ref={dialogRef} tabIndex={-1}><h3 id="temporary-password-title">临时密码仅显示一次</h3><p>请通过可信渠道交给用户。页面关闭后无法再次查看。</p><output aria-label="一次性临时密码">{temporaryPassword}</output><p className="field-help" aria-live="polite">{copyMessage}</p><div className="dialog-actions"><button type="button" onClick={copyPassword}>复制临时密码</button><button type="button" className="secondary-button" onClick={closeDialog}>关闭并清除</button></div></div></div>}
    </div>
  );
}

export default AdminPasswordResets;
