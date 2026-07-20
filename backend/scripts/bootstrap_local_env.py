"""安全初始化后端本地开发环境变量。"""

from __future__ import annotations

import argparse
import os
import secrets
import tempfile
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]
DEFAULT_EXAMPLE_PATH = BACKEND_DIR / ".env.example"
DEFAULT_ENV_PATH = BACKEND_DIR / ".env"

SECRET_FACTORIES = {
    "JWT_SECRET_KEY": lambda: secrets.token_urlsafe(48),
    "AUTH_CSRF_SECRET": lambda: secrets.token_urlsafe(48),
    "REGISTRATION_INVITE_CODE": lambda: secrets.token_urlsafe(24),
    "RATE_LIMIT_HASH_SALT": lambda: secrets.token_urlsafe(32),
}

LOCAL_DEFAULTS = {
    "APP_ENVIRONMENT": "development",
    "AUTH_ACCESS_TOKEN_MINUTES": "15",
    "AUTH_REFRESH_TOKEN_DAYS": "7",
    "AUTH_MAX_ACTIVE_SESSIONS": "5",
    "AUTH_COOKIE_SECURE": "false",
    "AUTH_COOKIE_SAMESITE": "lax",
    "AUTH_COOKIE_DOMAIN": "",
    "AUTH_ACCESS_COOKIE_NAME": "spi_access",
    "AUTH_REFRESH_COOKIE_NAME": "spi_refresh",
    "AUTH_CSRF_COOKIE_NAME": "spi_csrf",
    "AUTH_REQUIRE_ORIGIN_CHECK": "true",
    "CORS_ALLOWED_ORIGINS": "http://localhost:5173",
}


def _variable_names(content: str) -> set[str]:
    names: set[str] = set()
    for line in content.splitlines():
        candidate = line.strip()
        if not candidate or candidate.startswith("#") or "=" not in candidate:
            continue
        name = candidate.split("=", 1)[0].strip()
        if name.replace("_", "").isalnum() and name[0].isalpha():
            names.add(name)
    return names


def _read_declared_environment(content: str) -> str:
    for line in content.splitlines():
        candidate = line.strip()
        if candidate.startswith("APP_ENVIRONMENT="):
            return candidate.split("=", 1)[1].strip().lower()
    return ""


def _variable_value(content: str, target_name: str) -> str:
    for line in content.splitlines():
        candidate = line.strip()
        if candidate.startswith(f"{target_name}="):
            return candidate.split("=", 1)[1]
    return ""


def _ensure_distinct_auth_secrets(values: dict[str, str], current_content: str) -> None:
    jwt_secret = values.get("JWT_SECRET_KEY") or _variable_value(
        current_content, "JWT_SECRET_KEY"
    )
    csrf_secret = values.get("AUTH_CSRF_SECRET") or _variable_value(
        current_content, "AUTH_CSRF_SECRET"
    )
    while jwt_secret and jwt_secret == csrf_secret:
        if "AUTH_CSRF_SECRET" in values:
            values["AUTH_CSRF_SECRET"] = SECRET_FACTORIES["AUTH_CSRF_SECRET"]()
            csrf_secret = values["AUTH_CSRF_SECRET"]
        elif "JWT_SECRET_KEY" in values:
            values["JWT_SECRET_KEY"] = SECRET_FACTORIES["JWT_SECRET_KEY"]()
            jwt_secret = values["JWT_SECRET_KEY"]
        else:
            raise RuntimeError("JWT 与 CSRF Secret 必须不同，请手动修正现有配置")


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
        text=True,
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
    except Exception:
        if temporary_path.exists():
            temporary_path.unlink()
        raise


def bootstrap_local_env(example_path: Path, env_path: Path) -> tuple[bool, list[str]]:
    if not example_path.is_file():
        raise FileNotFoundError("未找到 .env.example")

    existed = env_path.exists()
    current_content = env_path.read_text(encoding="utf-8-sig") if existed else ""
    declared_environment = _read_declared_environment(current_content)
    process_environment = os.getenv("APP_ENVIRONMENT", "").strip().lower()
    if "production" in {declared_environment, process_environment}:
        raise RuntimeError("本地初始化工具拒绝修改生产环境配置")

    example_content = example_path.read_text(encoding="utf-8-sig")
    if not existed:
        generated = {name: factory() for name, factory in SECRET_FACTORIES.items()}
        _ensure_distinct_auth_secrets(generated, "")
        lines: list[str] = []
        for line in example_content.splitlines():
            candidate = line.strip()
            name = candidate.split("=", 1)[0].strip() if "=" in candidate else ""
            if name in generated and not candidate.startswith("#"):
                lines.append(f"{name}={generated[name]}")
            else:
                lines.append(line)
        _atomic_write(env_path, "\n".join(lines).rstrip("\n") + "\n")
        return False, sorted(_variable_names(example_content))

    existing_names = _variable_names(current_content)
    additions: dict[str, str] = {}
    for name, factory in SECRET_FACTORIES.items():
        if name not in existing_names:
            additions[name] = factory()
    _ensure_distinct_auth_secrets(additions, current_content)
    for name, value in LOCAL_DEFAULTS.items():
        if name not in existing_names:
            additions[name] = value

    if not additions:
        return existed, []

    base_content = current_content.rstrip("\r\n")
    appended = "\n".join(f"{name}={value}" for name, value in additions.items())
    new_content = f"{base_content}\n\n{appended}\n"
    _atomic_write(env_path, new_content)
    return existed, sorted(additions)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="安全初始化本地后端 .env")
    parser.add_argument("--env-file", type=Path, default=DEFAULT_ENV_PATH)
    parser.add_argument("--example-file", type=Path, default=DEFAULT_EXAMPLE_PATH)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    existed, changed_names = bootstrap_local_env(
        args.example_file.resolve(),
        args.env_file.resolve(),
    )
    if not changed_names:
        print("本地环境配置已就绪，无需更改。")
        return
    action = "已补充变量" if existed else "已创建本地配置并写入变量"
    print(f"{action}：{', '.join(changed_names)}")
    print("未输出任何配置值。")


if __name__ == "__main__":
    main()
