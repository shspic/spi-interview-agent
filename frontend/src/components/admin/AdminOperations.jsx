import { useCallback, useEffect, useState } from "react";

import {
  getRegistrationSettings,
  previewAdminCleanup,
  runAdminCleanup,
  updateRegistrationInviteCode,
} from "../../api/admin";
import { getFriendlyErrorMessage } from "../../utils/errorMessage";
import { formatDateTime } from "../../utils/format";

function AdminOperations({ kind, refreshKey, onForbidden, onCompleted }) {
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [registration, setRegistration] = useState(null);
  const [invite, setInvite] = useState("");
  const [inviteConfirm, setInviteConfirm] = useState("");
  const [acknowledged, setAcknowledged] = useState(false);
  const [preview, setPreview] = useState(null);
  const [cleanupConfirm, setCleanupConfirm] = useState("");
  const [cleanupAcknowledged, setCleanupAcknowledged] = useState(false);
  const [cleanupResult, setCleanupResult] = useState(null);

  const loadRegistration = useCallback(async () => {
    if (kind !== "invite") { setLoading(false); return; }
    setLoading(true); setError("");
    try { setRegistration(await getRegistrationSettings()); }
    catch (requestError) { if (requestError.response?.status === 403) onForbidden?.(); setError(getFriendlyErrorMessage(requestError, "邀请码设置读取失败。")); }
    finally { setLoading(false); }
  }, [kind, onForbidden]);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      loadRegistration();
    }, 0);
    return () => window.clearTimeout(timer);
  }, [loadRegistration, refreshKey]);

  const updateInvite = async (event) => {
    event.preventDefault(); setError(""); setMessage("");
    if (invite !== inviteConfirm) { setError("两次输入的新邀请码不一致。"); return; }
    if (!acknowledged) { setError("请确认旧邀请码将立即失效。"); return; }
    setLoading(true);
    try {
      const result = await updateRegistrationInviteCode(invite);
      setRegistration(result); setInvite(""); setInviteConfirm(""); setAcknowledged(false);
      setMessage("邀请码已更新，旧邀请码已立即失效。新邀请码不会在页面中回显。"); onCompleted?.();
    } catch (requestError) { if (requestError.response?.status === 403) onForbidden?.(); setError(getFriendlyErrorMessage(requestError, "邀请码更新失败。")); }
    finally { setLoading(false); }
  };

  const loadPreview = async () => {
    setLoading(true); setError(""); setMessage(""); setCleanupResult(null);
    try { setPreview(await previewAdminCleanup()); }
    catch (requestError) { if (requestError.response?.status === 403) onForbidden?.(); setError(getFriendlyErrorMessage(requestError, "清理预览读取失败。")); }
    finally { setLoading(false); }
  };

  const cleanup = async (event) => {
    event.preventDefault();
    if (!preview) { setError("请先执行清理预览。"); return; }
    if (!cleanupAcknowledged) { setError("请确认已了解清理影响。"); return; }
    setLoading(true); setError(""); setMessage("");
    try {
      const result = await runAdminCleanup(cleanupConfirm);
      setCleanupResult(result); setCleanupConfirm(""); setCleanupAcknowledged(false); setPreview(null);
      setMessage(result.success ? "过期业务数据清理完成。" : "清理仅部分完成，请检查失败项。");
    } catch (requestError) { if (requestError.response?.status === 403) onForbidden?.(); setError(getFriendlyErrorMessage(requestError, "过期数据清理失败。")); }
    finally { setLoading(false); }
  };

  if (kind === "invite") return <div className="admin-panel"><div className="admin-subpanel sensitive-panel">
    <h3>固定邀请码</h3>
    {loading && !registration ? <p>正在读取配置...</p> : <dl className="account-detail-grid"><div><dt>配置状态</dt><dd>{registration?.configured ? "已配置" : "未配置"}</dd></div><div><dt>最近更新时间</dt><dd>{formatDateTime(registration?.updated_at)}</dd></div><div><dt>更新管理员</dt><dd>{registration?.updated_by ?? "--"}</dd></div></dl>}
    <p className="field-help">系统不会返回当前邀请码明文或哈希。新邀请码需满足后端长度和字符规则。</p>
    <form className="settings-form" onSubmit={updateInvite}>
      <label>新邀请码<input type="password" value={invite} onChange={(e) => setInvite(e.target.value)} minLength={6} maxLength={64} required autoComplete="off" /></label>
      <label>确认新邀请码<input type="password" value={inviteConfirm} onChange={(e) => setInviteConfirm(e.target.value)} minLength={6} maxLength={64} required autoComplete="off" /></label>
      <label className="checkbox-row"><input type="checkbox" checked={acknowledged} onChange={(e) => setAcknowledged(e.target.checked)} />我确认修改后旧邀请码立即失效</label>
      <button type="submit" disabled={loading || !acknowledged}>确认修改</button>
    </form>
    {error && <p className="inline-error">{error}</p>}{message && <p className="inline-success">{message}</p>}
  </div></div>;

  return <div className="admin-panel"><div className="admin-subpanel danger-zone">
    <h3>7 天业务数据清理</h3>
    <p>清理范围包括过期原始文件、向量、历史、面试训练、简历描述和 Agent 运行记录。账号、个人资料、目标岗位与管理员设置保留。</p>
    <p className="warning-line">若出现 <code>legacy_owner_missing</code>，说明旧数据缺少用户归属，应先执行旧数据迁移，不能直接删除。</p>
    <button type="button" onClick={loadPreview} disabled={loading}>{loading ? "读取中..." : "执行清理预览"}</button>
    {preview && <form className="cleanup-confirm-panel" onSubmit={cleanup}>
      <div className="account-detail-grid"><div><dt>保留天数</dt><dd>{preview.retention_days}</dd></div><div><dt>时区</dt><dd>{preview.timezone}</dd></div><div><dt>cutoff</dt><dd>{formatDateTime(preview.cutoff)}</dd></div></div>
      <div className="resource-count-grid">{Object.entries(preview.estimated_counts || {}).map(([name, count]) => <div key={name}><span>{name}</span><strong>{count}</strong></div>)}</div>
      <label>输入确认文本 <code>DELETE_EXPIRED_DATA</code><input value={cleanupConfirm} onChange={(e) => setCleanupConfirm(e.target.value)} required autoComplete="off" /></label>
      <label className="checkbox-row"><input type="checkbox" checked={cleanupAcknowledged} onChange={(e) => setCleanupAcknowledged(e.target.checked)} />我确认已核对预览，且了解清理不可恢复</label>
      <button type="submit" className="danger-button" disabled={loading || cleanupConfirm !== "DELETE_EXPIRED_DATA" || !cleanupAcknowledged}>执行清理</button>
    </form>}
    {cleanupResult && <div className={cleanupResult.success ? "operation-result success" : "operation-result partial"}><strong>{cleanupResult.success ? "清理完成" : "部分清理完成"}</strong><p>{Object.entries(cleanupResult.deleted_counts || {}).map(([name, count]) => `${name} ${count}`).join("，")}</p>{(cleanupResult.failed_items || []).map((item, index) => <p key={index}>{item.resource_type} / {item.resource_id}：{item.error_type}</p>)}</div>}
    {error && <p className="inline-error">{error}</p>}{message && <p className={cleanupResult?.success === false ? "inline-warning" : "inline-success"}>{message}</p>}
  </div></div>;
}

export default AdminOperations;
