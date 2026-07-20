import { useEffect, useState } from "react";

import {
  changeMyPassword,
  cleanupMyBusinessData,
  deleteMyAccount,
  getMyProfile,
  previewMyDataCleanup,
} from "../api/account";
import { useAuth } from "../auth/authContext";
import { getFriendlyErrorMessage } from "../utils/errorMessage";
import { formatDateTime } from "../utils/format";

const CLEANUP_CONFIRMATION = "DELETE_MY_DATA";
const ACCOUNT_DELETE_CONFIRMATION = "DELETE_MY_ACCOUNT";

function Settings({ onDataCleaned }) {
  const { currentUser, logout, logoutAll } = useAuth();
  const [profile, setProfile] = useState(null);
  const [profileError, setProfileError] = useState("");
  const [passwordForm, setPasswordForm] = useState({
    current_password: "",
    new_password: "",
    confirm_password: "",
  });
  const [showPasswords, setShowPasswords] = useState(false);
  const [passwordLoading, setPasswordLoading] = useState(false);
  const [passwordMessage, setPasswordMessage] = useState("");
  const [passwordError, setPasswordError] = useState("");
  const [cleanupPreview, setCleanupPreview] = useState(null);
  const [cleanupResult, setCleanupResult] = useState(null);
  const [cleanupLoading, setCleanupLoading] = useState(false);
  const [cleanupError, setCleanupError] = useState("");
  const [cleanupPassword, setCleanupPassword] = useState("");
  const [cleanupConfirm, setCleanupConfirm] = useState("");
  const [cleanupAcknowledged, setCleanupAcknowledged] = useState(false);
  const [deleteForm, setDeleteForm] = useState({
    current_password: "",
    confirm_username: "",
    confirm: "",
  });
  const [deleteLoading, setDeleteLoading] = useState(false);
  const [deleteError, setDeleteError] = useState("");

  useEffect(() => {
    let active = true;
    getMyProfile()
      .then((data) => active && setProfile(data))
      .catch((error) => {
        if (active) {
          setProfileError(getFriendlyErrorMessage(error, "个人资料读取失败。"));
        }
      });
    return () => {
      active = false;
    };
  }, []);

  const submitPassword = async (event) => {
    event.preventDefault();
    setPasswordError("");
    setPasswordMessage("");
    if (passwordForm.new_password !== passwordForm.confirm_password) {
      setPasswordError("两次输入的新密码不一致。");
      return;
    }
    setPasswordLoading(true);
    try {
      const result = await changeMyPassword(passwordForm);
      setPasswordForm({ current_password: "", new_password: "", confirm_password: "" });
      setPasswordMessage(result.message || "密码修改成功，即将退出登录。");
      await new Promise((resolve) => window.setTimeout(resolve, 700));
      logout();
    } catch (error) {
      setPasswordError(getFriendlyErrorMessage(error, "密码修改失败。"));
    } finally {
      setPasswordLoading(false);
    }
  };

  const loadCleanupPreview = async () => {
    setCleanupLoading(true);
    setCleanupError("");
    setCleanupResult(null);
    try {
      setCleanupPreview(await previewMyDataCleanup());
    } catch (error) {
      setCleanupError(getFriendlyErrorMessage(error, "清理预览读取失败。"));
    } finally {
      setCleanupLoading(false);
    }
  };

  const executeCleanup = async (event) => {
    event.preventDefault();
    if (!cleanupPreview) {
      setCleanupError("请先查看预计删除内容。");
      return;
    }
    if (!cleanupAcknowledged) {
      setCleanupError("请确认你已了解此操作不可撤销。");
      return;
    }
    setCleanupLoading(true);
    setCleanupError("");
    try {
      const result = await cleanupMyBusinessData({
        current_password: cleanupPassword,
        confirm: cleanupConfirm,
      });
      setCleanupResult(result);
      setCleanupPassword("");
      setCleanupConfirm("");
      setCleanupAcknowledged(false);
      setCleanupPreview(null);
      if (result.success) {
        onDataCleaned?.();
      }
    } catch (error) {
      setCleanupError(getFriendlyErrorMessage(error, "个人业务数据清理失败。"));
    } finally {
      setCleanupLoading(false);
    }
  };

  const executeAccountDeletion = async (event) => {
    event.preventDefault();
    if (!window.confirm("确认永久删除当前账号及全部关联数据？此操作不可撤销。")) return;
    setDeleteLoading(true);
    setDeleteError("");
    try {
      const result = await deleteMyAccount(deleteForm);
      if (!result.success) {
        setDeleteError("文件或索引清理失败，账号已保留。请稍后重试或联系管理员。");
        return;
      }
      await logout();
    } catch (error) {
      setDeleteError(getFriendlyErrorMessage(error, "账号删除失败，账号与数据均未确认删除。"));
    } finally {
      setDeleteLoading(false);
    }
  };

  return (
    <section className="management-page settings-page">
      <div className="page-heading-row">
        <div>
          <h1>设置</h1>
          <p>查看账号状态，管理登录密码和个人业务数据。</p>
        </div>
      </div>

      <div className="settings-section">
        <div className="section-heading"><h2>账号信息</h2><span>只读</span></div>
        {profileError && <p className="inline-error">{profileError}</p>}
        <dl className="account-detail-grid">
          <div><dt>用户名</dt><dd>{currentUser?.username || "--"}</dd></div>
          <div><dt>显示名称</dt><dd>{profile?.profile?.display_name || "未设置"}</dd></div>
          <div><dt>账号角色</dt><dd>{currentUser?.is_admin ? "管理员" : "普通用户"}</dd></div>
          <div><dt>账号状态</dt><dd>{currentUser?.is_active ? "正常" : "已停用"}</dd></div>
          <div><dt>创建时间</dt><dd>{formatDateTime(currentUser?.created_at)}</dd></div>
          <div><dt>最近登录</dt><dd>{formatDateTime(currentUser?.last_login_at)}</dd></div>
        </dl>
      </div>

      <div className="settings-section">
        <div className="section-heading"><h2>安全设置</h2><span>修改后需重新登录</span></div>
        <form className="settings-form" onSubmit={submitPassword}>
          <label>当前密码<input type={showPasswords ? "text" : "password"} value={passwordForm.current_password} onChange={(event) => setPasswordForm((value) => ({ ...value, current_password: event.target.value }))} required autoComplete="current-password" /></label>
          <label>新密码<input type={showPasswords ? "text" : "password"} value={passwordForm.new_password} onChange={(event) => setPasswordForm((value) => ({ ...value, new_password: event.target.value }))} required minLength={8} maxLength={72} autoComplete="new-password" /></label>
          <label>确认新密码<input type={showPasswords ? "text" : "password"} value={passwordForm.confirm_password} onChange={(event) => setPasswordForm((value) => ({ ...value, confirm_password: event.target.value }))} required minLength={8} maxLength={72} autoComplete="new-password" /></label>
          <label className="checkbox-row"><input type="checkbox" checked={showPasswords} onChange={(event) => setShowPasswords(event.target.checked)} />显示密码</label>
          <p className="field-help">密码至少 8 个字符，且不能超过 72 个 UTF-8 字节。</p>
          {passwordError && <p className="inline-error" role="alert">{passwordError}</p>}
          {passwordMessage && <p className="inline-success" role="status">{passwordMessage}</p>}
          <button type="submit" disabled={passwordLoading}>{passwordLoading ? "提交中..." : "修改密码"}</button>
        </form>
        <button
          type="button"
          className="secondary-button"
          onClick={() => {
            if (window.confirm("确认退出所有设备？所有登录会话都会立即失效。")) {
              logoutAll();
            }
          }}
        >
          退出所有设备
        </button>
      </div>

      <div className="settings-section danger-zone">
        <div className="section-heading"><h2>数据与隐私</h2><span>危险操作</span></div>
        <p>上传文件和面试业务数据默认保留 7 天。账号、个人资料和目标岗位不会自动清理。</p>
        <p>手动清理会删除你的上传原文件、向量、历史、面试训练、改进任务、简历描述和业务运行记录，且不可恢复。</p>
        <button type="button" className="secondary-button" onClick={loadCleanupPreview} disabled={cleanupLoading}>
          {cleanupLoading ? "读取中..." : "查看预计删除内容"}
        </button>

        {cleanupPreview && (
          <form className="cleanup-confirm-panel" onSubmit={executeCleanup}>
            <h3>预计删除内容</h3>
            <div className="resource-count-grid">
              {Object.entries(cleanupPreview.estimated_counts || {}).map(([name, count]) => (
                <div key={name}><span>{name}</span><strong>{count}</strong></div>
              ))}
            </div>
            <p>保留：{(cleanupPreview.retained_resources || []).join("、")}</p>
            <label>当前密码<input type="password" value={cleanupPassword} onChange={(event) => setCleanupPassword(event.target.value)} required autoComplete="current-password" /></label>
            <label>输入确认文本 <code>{CLEANUP_CONFIRMATION}</code><input value={cleanupConfirm} onChange={(event) => setCleanupConfirm(event.target.value)} required autoComplete="off" /></label>
            <label className="checkbox-row"><input type="checkbox" checked={cleanupAcknowledged} onChange={(event) => setCleanupAcknowledged(event.target.checked)} />我确认已查看预计影响，并了解数据不可恢复</label>
            <button type="submit" className="danger-button" disabled={cleanupLoading || cleanupConfirm !== CLEANUP_CONFIRMATION || !cleanupAcknowledged}>
              {cleanupLoading ? "清理中..." : "永久清理个人业务数据"}
            </button>
          </form>
        )}

        {cleanupError && <p className="inline-error" role="alert">{cleanupError}</p>}
        {cleanupResult && (
          <div className={cleanupResult.success ? "operation-result success" : "operation-result partial"}>
            <strong>{cleanupResult.success ? "个人业务数据已清理" : "清理未完整完成"}</strong>
            {Object.keys(cleanupResult.deleted_counts || {}).length > 0 && <p>删除数量：{Object.entries(cleanupResult.deleted_counts).map(([name, count]) => `${name} ${count}`).join("，")}</p>}
            {(cleanupResult.failed_items || []).map((item, index) => <p key={`${item.resource_type}-${index}`}>{item.resource_type} / {item.resource_id}：{item.error_type}</p>)}
          </div>
        )}
        <form className="cleanup-confirm-panel account-delete-panel" onSubmit={executeAccountDeletion}>
          <h3>永久删除账号</h3>
          <p>将删除账号、登录会话、个人资料、岗位、上传文件、索引及训练记录。操作失败时不会声称删除成功。</p>
          <label>当前密码<input type="password" value={deleteForm.current_password} onChange={(event) => setDeleteForm((value) => ({ ...value, current_password: event.target.value }))} required autoComplete="current-password" /></label>
          <label>输入当前用户名 <code>{currentUser?.username}</code><input value={deleteForm.confirm_username} onChange={(event) => setDeleteForm((value) => ({ ...value, confirm_username: event.target.value }))} required autoComplete="off" /></label>
          <label>输入确认文本 <code>{ACCOUNT_DELETE_CONFIRMATION}</code><input value={deleteForm.confirm} onChange={(event) => setDeleteForm((value) => ({ ...value, confirm: event.target.value }))} required autoComplete="off" /></label>
          {deleteError && <p className="inline-error" role="alert">{deleteError}</p>}
          <button type="submit" className="danger-button" disabled={deleteLoading || deleteForm.confirm !== ACCOUNT_DELETE_CONFIRMATION || deleteForm.confirm_username !== currentUser?.username}>{deleteLoading ? "删除中…" : "永久删除账号"}</button>
        </form>
      </div>
    </section>
  );
}

export default Settings;
