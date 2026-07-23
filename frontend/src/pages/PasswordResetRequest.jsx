import { useState } from "react";

import apiClient from "../api/client";
import AuthShell from "../components/AuthShell";
import BrandLockup from "../components/BrandLockup";
import { getFriendlyErrorMessage } from "../utils/errorMessage";

function PasswordResetRequest({ onBack }) {
  const [username, setUsername] = useState("");
  const [requestNote, setRequestNote] = useState("");
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);

  const submit = async (event) => {
    event.preventDefault();
    setError("");
    setMessage("");
    setSubmitting(true);
    try {
      const response = await apiClient.post("/api/auth/password-reset-requests", {
        username: username.trim().toLowerCase(),
        request_note: requestNote,
      });
      setMessage(response.data.message);
    } catch (requestError) {
      setError(getFriendlyErrorMessage(requestError, "申请提交失败，请稍后重试。"));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <AuthShell>
      <div className="auth-card">
        <div className="auth-brand"><BrandLockup compact /><h1>申请重置密码</h1></div>
        <p className="auth-intro">申请会进入管理员审批。为保护账号隐私，我们不会提示用户名是否存在。</p>
        <form className="auth-form" onSubmit={submit}>
          <label htmlFor="reset-username">用户名</label>
          <input id="reset-username" value={username} onChange={(event) => setUsername(event.target.value)} autoComplete="username" required maxLength={64} />
          <label htmlFor="reset-note">申请说明或联系备注（可选）</label>
          <textarea id="reset-note" value={requestNote} onChange={(event) => setRequestNote(event.target.value)} maxLength={500} rows={4} />
          <p className="auth-help">{requestNote.length} / 500，仅作为纯文本提交。</p>
          {error && <p className="auth-error" role="alert">{error}</p>}
          {message && <p className="auth-success" aria-live="polite">{message}</p>}
          <button className="auth-submit" type="submit" disabled={submitting}>{submitting ? "正在提交..." : "提交重置申请"}</button>
        </form>
        <button type="button" className="auth-switch" onClick={onBack}>返回登录</button>
      </div>
    </AuthShell>
  );
}

export default PasswordResetRequest;
