import { useState } from "react";

import { useAuth } from "../auth/authContext";
import AuthShell from "../components/AuthShell";
import BrandLockup from "../components/BrandLockup";
import { getFriendlyErrorMessage } from "../utils/errorMessage";

function TemporaryPasswordChange({ onCompleted }) {
  const { changeTemporaryPassword, logout } = useAuth();
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);

  const submit = async (event) => {
    event.preventDefault();
    if (newPassword !== confirmPassword) {
      setError("两次输入的新密码不一致。");
      return;
    }
    setSubmitting(true);
    setError("");
    try {
      await changeTemporaryPassword({ newPassword, confirmPassword });
      onCompleted();
    } catch (requestError) {
      setError(getFriendlyErrorMessage(requestError, "密码更新失败，请稍后重试。"));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <AuthShell showVideo={false}>
      <div className="auth-card security-terminal">
        <div className="auth-brand"><BrandLockup compact /><p className="eyebrow">SECURITY CHECKPOINT</p><h1>需要更新密码</h1></div>
        <p className="auth-intro">你正在使用一次性临时密码。完成更新前，后端会拒绝所有业务与管理接口。</p>
        <form className="auth-form" onSubmit={submit}>
          <label htmlFor="temporary-new-password">新密码</label>
          <div className="password-field"><input id="temporary-new-password" type={showPassword ? "text" : "password"} value={newPassword} onChange={(event) => setNewPassword(event.target.value)} minLength={8} maxLength={72} autoComplete="new-password" required /><button type="button" className="password-toggle" onClick={() => setShowPassword((value) => !value)} aria-label={showPassword ? "隐藏密码" : "显示密码"}>{showPassword ? "隐藏" : "显示"}</button></div>
          <p className="auth-help">至少 8 个字符，且不能与临时密码相同。</p>
          <label htmlFor="temporary-confirm-password">确认新密码</label>
          <input id="temporary-confirm-password" type={showPassword ? "text" : "password"} value={confirmPassword} onChange={(event) => setConfirmPassword(event.target.value)} minLength={8} maxLength={72} autoComplete="new-password" required />
          {error && <p className="auth-error" role="alert">{error}</p>}
          <button className="auth-submit" type="submit" disabled={submitting}>{submitting ? "正在更新..." : "更新密码并重新登录"}</button>
        </form>
        <button type="button" className="auth-switch" onClick={() => void logout()}>退出登录</button>
      </div>
    </AuthShell>
  );
}

export default TemporaryPasswordChange;
