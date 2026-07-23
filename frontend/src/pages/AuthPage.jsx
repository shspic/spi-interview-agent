import { useState } from "react";

import { useAuth } from "../auth/authContext";
import { getFriendlyErrorMessage } from "../utils/errorMessage";
import AuthShell from "../components/AuthShell";
import BrandLockup from "../components/BrandLockup";

const USERNAME_PATTERN = /^[a-z0-9_]{3,32}$/;

function AuthPage({ initialMode = "login", onModeChange, onPasswordReset }) {
  const { login, register } = useAuth();
  const mode = initialMode;
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [inviteCode, setInviteCode] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [errorMessage, setErrorMessage] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);

  const isRegisterMode = mode === "register";

  const switchMode = () => {
    const nextMode = isRegisterMode ? "login" : "register";
    onModeChange?.(nextMode);
    setPassword("");
    setConfirmPassword("");
    setInviteCode("");
    setErrorMessage("");
    setShowPassword(false);
  };

  const handleSubmit = async (event) => {
    event.preventDefault();
    setErrorMessage("");

    const normalizedUsername = username.trim().toLowerCase();

    if (!USERNAME_PATTERN.test(normalizedUsername)) {
      setErrorMessage("用户名需为 3 至 32 位小写字母、数字或下划线。");
      return;
    }

    if (password.length < 8) {
      setErrorMessage("密码长度不能少于 8 个字符。");
      return;
    }

    if (isRegisterMode && password !== confirmPassword) {
      setErrorMessage("两次输入的密码不一致。");
      return;
    }

    setIsSubmitting(true);

    try {
      if (isRegisterMode) {
        await register({
          username: normalizedUsername,
          password,
          inviteCode,
        });
      } else {
        await login({ username: normalizedUsername, password });
      }
    } catch (error) {
      setErrorMessage(
        getFriendlyErrorMessage(
          error,
          isRegisterMode ? "注册失败，请稍后重试。" : "登录失败，请稍后重试。",
        ),
      );
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <AuthShell>
      <div className="auth-card" aria-labelledby="auth-title">
        <div className="auth-brand">
          <BrandLockup compact />
          <h1 id="auth-title">{isRegisterMode ? "创建 AURORA 账号" : "登录 AURORA"}</h1>
        </div>

        <form className="auth-form" onSubmit={handleSubmit}>
          <label htmlFor="username">用户名</label>
          <input
            id="username"
            name="username"
            type="text"
            value={username}
            onChange={(event) => setUsername(event.target.value)}
            autoComplete="username"
            disabled={isSubmitting}
            required
          />
          <p className="auth-help">3 至 32 位，只能使用小写字母、数字和下划线。</p>

          <div className="auth-label-row"><label htmlFor="password">密码</label>{!isRegisterMode && <button type="button" className="auth-text-link" onClick={onPasswordReset}>忘记密码？申请重置</button>}</div>
          <div className="password-field">
            <input
              id="password"
              name="password"
              type={showPassword ? "text" : "password"}
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              autoComplete={isRegisterMode ? "new-password" : "current-password"}
              disabled={isSubmitting}
              required
            />
            <button
              type="button"
              className="password-toggle"
              onClick={() => setShowPassword((visible) => !visible)}
              disabled={isSubmitting}
              aria-label={showPassword ? "隐藏密码" : "显示密码"}
            >
              {showPassword ? "隐藏" : "显示"}
            </button>
          </div>
          <p className="auth-help">至少 8 个字符，建议同时使用大小写字母、数字和符号。</p>

          {isRegisterMode && (
            <>
              <label htmlFor="confirm-password">确认密码</label>
              <input
                id="confirm-password"
                name="confirm-password"
                type={showPassword ? "text" : "password"}
                value={confirmPassword}
                onChange={(event) => setConfirmPassword(event.target.value)}
                autoComplete="new-password"
                disabled={isSubmitting}
                required
              />

              <label htmlFor="invite-code">邀请码</label>
              <input
                id="invite-code"
                name="invite-code"
                type="password"
                value={inviteCode}
                onChange={(event) => setInviteCode(event.target.value)}
                autoComplete="off"
                disabled={isSubmitting}
                required
              />
            </>
          )}

          {errorMessage && (
            <p className="auth-error" role="alert">
              {errorMessage}
            </p>
          )}

          <button className="auth-submit" type="submit" disabled={isSubmitting}>
            {isSubmitting
              ? isRegisterMode
                ? "正在注册..."
                : "正在登录..."
              : isRegisterMode
                ? "注册并进入 AURORA"
                : "登录 AURORA"}
          </button>
        </form>

        <button
          type="button"
          className="auth-switch"
          onClick={switchMode}
          disabled={isSubmitting}
        >
          {isRegisterMode ? "已有账号？返回登录" : "没有账号？使用邀请码注册"}
        </button>
        {isRegisterMode && <button type="button" className="auth-text-link auth-reset-secondary" onClick={onPasswordReset}>忘记密码？申请重置</button>}
      </div>
    </AuthShell>
  );
}

export default AuthPage;
