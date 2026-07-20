"""输出不含敏感值的本地认证与数据库就绪状态。"""

from app.core.config import settings
from app.core.readiness import auth_configuration_issues
from app.db.database import engine
from app.db.schema_version import get_schema_status


def main() -> None:
    auth_issues = auth_configuration_issues(settings)
    try:
        schema_state = get_schema_status(engine).state
    except Exception:
        schema_state = "unavailable"
    print(f"auth_ready={str(not auth_issues).lower()}")
    print(f"schema_ready={str(schema_state == 'current').lower()}")
    print(f"schema_state={schema_state}")
    if auth_issues:
        print("missing_or_invalid=" + ",".join(auth_issues))


if __name__ == "__main__":
    main()
