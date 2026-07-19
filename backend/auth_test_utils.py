from app.core.config import settings
from app.core.security import create_access_token
from app.services.auth_session_service import create_session


def cookie_headers(client) -> dict[str, str]:
    csrf_token = client.cookies.get(settings.auth_csrf_cookie_name)
    cookie_header = "; ".join(
        f"{cookie.name}={cookie.value}" for cookie in client.cookies.jar
    )
    return {
        "Cookie": cookie_header,
        "X-CSRF-Token": csrf_token,
    }


def prepare_preauth(client) -> None:
    client.cookies.clear()
    client.get("/api/auth/csrf")


def session_headers(db, user) -> dict[str, str]:
    auth_session, refresh_token, csrf_token = create_session(db, user)
    access_token = create_access_token(
        user.id,
        auth_session.id,
        auth_session.token_version,
    )
    db.commit()
    return {
        "Cookie": (
            f"{settings.auth_access_cookie_name}={access_token}; "
            f"{settings.auth_refresh_cookie_name}={refresh_token}; "
            f"{settings.auth_csrf_cookie_name}={csrf_token}"
        ),
        "X-CSRF-Token": csrf_token,
    }
