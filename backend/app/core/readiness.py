"""认证和数据库就绪状态检查。"""

from __future__ import annotations

from app.core.config import Settings


BOOTSTRAP_COMMAND = "python -m scripts.bootstrap_local_env"


def auth_configuration_issues(config: Settings) -> tuple[str, ...]:
    issues: list[str] = []
    jwt_secret = config.jwt_secret_key.strip()
    csrf_secret = config.auth_csrf_secret.strip()
    if not jwt_secret or jwt_secret == "change-me":
        issues.append("JWT_SECRET_KEY")
    if not csrf_secret or csrf_secret == "change-me":
        issues.append("AUTH_CSRF_SECRET")
    if jwt_secret and csrf_secret and jwt_secret == csrf_secret:
        issues.append("AUTH_CSRF_SECRET_INDEPENDENT")
    return tuple(issues)


def is_auth_ready(config: Settings) -> bool:
    return not auth_configuration_issues(config)


def auth_unavailable_message(config: Settings) -> str:
    if config.app_environment == "development":
        return f"认证配置未初始化。请运行：{BOOTSTRAP_COMMAND}"
    return "认证服务暂不可用"


def validate_auth_startup(config: Settings) -> None:
    issues = auth_configuration_issues(config)
    if issues and config.app_environment == "production":
        names = ", ".join(issues)
        raise RuntimeError(f"生产认证配置无效，请检查：{names}")
