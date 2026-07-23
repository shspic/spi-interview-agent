import io
import logging
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from fastapi import HTTPException, Request, UploadFile
from pypdf import PdfWriter
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from starlette.datastructures import Headers
from starlette.testclient import TestClient

from app.api import chat as chat_api
from app.api import files as files_api
from app.api import llm as llm_api
from app.services import account_data_service
from app.core.config import Settings, settings
from app.db.database import Base, get_db
from app.db.models import FileRecord, RateLimitBucket, UsageEvent, User
from app.main import app
from app.services.llm_service import LLMServiceError
from app.services.rate_limit_service import (
    enforce_rate_limit,
    enforce_user_rate_limit,
    resolve_client_ip,
)
from app.services.upload_security import (
    UploadSecurityError,
    reserve_user_storage,
    sanitize_display_filename,
    stage_upload,
)
from auth_test_utils import cookie_headers, prepare_preauth


def assert_security_headers(response):
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["referrer-policy"] == "no-referrer"
    assert response.headers["permissions-policy"] == (
        "camera=(), microphone=(), geolocation=()"
    )
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-request-id"]
    assert "server" not in response.headers


def register(client, username="alice", password="secure-pass-123"):
    return client.post(
        "/api/auth/register",
        json={
            "username": username,
            "password": password,
            "invite_code": "test-invite-code",
        },
    )


def login(client, username="alice", password="secure-pass-123"):
    response = client.post(
        "/api/auth/login",
        json={"username": username, "password": password},
    )
    assert response.status_code == 200
    return cookie_headers(client)


def register_and_login(client, username="alice"):
    prepare_preauth(client)
    response = register(client, username=username)
    assert response.status_code == 201
    return login(client, username=username)


def pdf_bytes(page_count=1, encrypted=False):
    writer = PdfWriter()
    for _ in range(page_count):
        writer.add_blank_page(width=100, height=100)
    if encrypted:
        writer.encrypt("test-password")
    output = io.BytesIO()
    writer.write(output)
    return output.getvalue()


def upload_text(
    client,
    auth_headers,
    filename="notes.txt",
    content=b"hello",
    **kwargs,
):
    return client.post(
        "/api/files/upload",
        headers={**auth_headers, **kwargs.pop("extra_headers", {})},
        files={"file": (filename, content, kwargs.pop("mime", "text/plain"))},
        data={"category": kwargs.pop("category", "other")},
    )


def test_login_register_and_password_change_rate_limits(client, monkeypatch):
    monkeypatch.setattr(settings, "register_rate_limit_attempts", 1)
    assert register(client, "alice").status_code == 201
    limited_register = register(client, "bob")
    assert limited_register.status_code == 429
    assert limited_register.json()["detail"]["scope"] == "register"

    monkeypatch.setattr(settings, "login_rate_limit_attempts", 2)
    for _ in range(2):
        assert client.post(
            "/api/auth/login",
            json={"username": "alice", "password": "wrong-password"},
        ).status_code == 401
    limited_login = client.post(
        "/api/auth/login",
        json={"username": "alice", "password": "wrong-password"},
    )
    assert limited_login.status_code == 429
    assert_security_headers(limited_login)
    payload = limited_login.json()
    assert payload["error_code"] == "rate_limit_exceeded"
    assert payload["detail"]["retry_after_seconds"] > 0
    assert payload["detail"]["reset_at"]


def test_upload_change_password_and_chat_rate_limits(
    client,
    db_session,
    monkeypatch,
    tmp_path,
):
    monkeypatch.setattr(settings, "upload_dir", str(tmp_path / "uploads"))
    headers = register_and_login(client)
    user = db_session.query(User).filter_by(username="alice").one()
    user.is_quota_exempt = True
    db_session.commit()

    monkeypatch.setattr(settings, "upload_rate_limit_attempts", 1)
    assert upload_text(client, headers).status_code == 200
    assert upload_text(client, headers, filename="other.txt").status_code == 429

    monkeypatch.setattr(settings, "password_change_rate_limit_attempts", 1)
    first_change = client.post(
        "/api/auth/change-password",
        headers=headers,
        json={
            "current_password": "wrong-password",
            "new_password": "new-secure-pass-123",
            "confirm_password": "new-secure-pass-123",
        },
    )
    assert first_change.status_code == 400
    assert client.post(
        "/api/auth/change-password",
        headers=headers,
        json={
            "current_password": "secure-pass-123",
            "new_password": "new-secure-pass-123",
            "confirm_password": "new-secure-pass-123",
        },
    ).status_code == 429

    monkeypatch.setattr(settings, "chat_burst_rate_limit_attempts", 1)
    monkeypatch.setattr(
        chat_api,
        "ask_with_rag",
        lambda **kwargs: {"answer": "ok", "sources": []},
    )
    assert client.post(
        "/api/chat/ask", headers=headers, json={"question": "正常问题"}
    ).status_code == 200
    assert client.post(
        "/api/chat/ask", headers=headers, json={"question": "再次提问"}
    ).status_code == 429


def test_rate_limit_subject_isolation_expiration_and_no_business_usage(
    db_session,
    monkeypatch,
):
    monkeypatch.setattr(settings, "rate_limit_hash_salt", "a" * 32)
    monkeypatch.setattr(settings, "login_rate_limit_attempts", 1)
    enforce_rate_limit(
        db_session,
        scope="login",
        subject_type="anonymous_ip",
        identifier="203.0.113.10",
        now_timestamp=100,
    )
    enforce_rate_limit(
        db_session,
        scope="login",
        subject_type="anonymous_ip",
        identifier="203.0.113.11",
        now_timestamp=100,
    )
    with pytest.raises(HTTPException) as limited:
        enforce_rate_limit(
            db_session,
            scope="login",
            subject_type="anonymous_ip",
            identifier="203.0.113.10",
            now_timestamp=100,
        )
    assert limited.value.status_code == 429

    enforce_rate_limit(
        db_session,
        scope="login",
        subject_type="anonymous_ip",
        identifier="203.0.113.10",
        now_timestamp=100 + settings.login_rate_limit_window_seconds,
    )
    assert db_session.query(UsageEvent).count() == 0
    stored = db_session.query(RateLimitBucket).all()
    assert stored
    assert all("203.0.113" not in item.subject_hash for item in stored)


def test_user_rate_limit_does_not_exempt_admin(db_session, monkeypatch):
    monkeypatch.setattr(settings, "rate_limit_hash_salt", "a" * 32)
    monkeypatch.setattr(settings, "admin_write_rate_limit_attempts", 1)
    enforce_user_rate_limit(db_session, 1, "admin_write")
    enforce_user_rate_limit(db_session, 2, "admin_write")
    with pytest.raises(HTTPException) as limited:
        enforce_user_rate_limit(db_session, 1, "admin_write")
    assert limited.value.status_code == 429


def test_rate_limit_persists_across_database_sessions(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{(tmp_path / 'rate.db').as_posix()}")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)
    monkeypatch.setattr(settings, "login_rate_limit_attempts", 1)
    monkeypatch.setattr(settings, "rate_limit_hash_salt", "a" * 32)

    first = session_factory()
    enforce_rate_limit(
        first,
        scope="login",
        subject_type="anonymous_ip",
        identifier="198.51.100.10",
        now_timestamp=100,
    )
    first.close()

    second = session_factory()
    with pytest.raises(HTTPException) as limited:
        enforce_rate_limit(
            second,
            scope="login",
            subject_type="anonymous_ip",
            identifier="198.51.100.10",
            now_timestamp=100,
        )
    second.close()
    engine.dispose()
    assert limited.value.status_code == 429


def _request(peer, forwarded_for=None, real_ip=None):
    headers = []
    if forwarded_for is not None:
        headers.append((b"x-forwarded-for", forwarded_for.encode()))
    if real_ip is not None:
        headers.append((b"x-real-ip", real_ip.encode()))
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/api/health",
            "headers": headers,
            "client": (peer, 1234),
        }
    )


def test_proxy_headers_only_apply_to_trusted_chain(monkeypatch):
    monkeypatch.setattr(settings, "trusted_proxy_cidrs", ())
    assert resolve_client_ip(
        _request("203.0.113.20", forwarded_for="198.51.100.8")
    ) == "203.0.113.20"

    monkeypatch.setattr(settings, "trusted_proxy_cidrs", ("10.0.0.0/8",))
    trusted = _request(
        "10.0.0.2",
        forwarded_for="198.51.100.8, 10.0.0.1",
    )
    assert resolve_client_ip(trusted) == "198.51.100.8"
    forged_middle = _request(
        "10.0.0.2",
        forwarded_for="198.51.100.8, 203.0.113.44",
    )
    assert resolve_client_ip(forged_middle) == "203.0.113.44"
    assert resolve_client_ip(
        _request("10.0.0.2", real_ip="2001:db8::1")
    ) == "2001:db8::1"


@pytest.mark.parametrize(
    "filename",
    [
        "../secret.txt",
        "..\\secret.txt",
        "C:\\temp\\secret.txt",
        "CON.txt",
        "NUL.md",
        "payload.exe.pdf",
        "a" * 181 + ".txt",
    ],
)
def test_unsafe_filenames_are_rejected(filename):
    with pytest.raises(UploadSecurityError):
        sanitize_display_filename(filename)


def test_filename_control_characters_are_replaced():
    assert sanitize_display_filename("file\x00.txt") == "file_.txt"


def test_filename_tail_is_normalized_and_storage_name_is_random(
    client,
    db_session,
    monkeypatch,
    tmp_path,
):
    monkeypatch.setattr(settings, "upload_dir", str(tmp_path / "uploads"))
    headers = register_and_login(client)
    first = upload_text(client, headers, filename="report.txt. ")
    second = upload_text(client, headers, filename="report.txt")
    assert first.status_code == second.status_code == 200
    assert first.json()["filename"] == "report.txt"
    records = db_session.query(FileRecord).order_by(FileRecord.id).all()
    assert records[0].file_id != records[1].file_id
    assert records[0].file_path != records[1].file_path
    assert all(Path(record.file_path).name != record.filename for record in records)


@pytest.mark.parametrize(
    ("filename", "content", "mime", "expected_status"),
    [
        ("valid.txt", "正常中文\n```python\nprint(1)\n```".encode(), "text/plain", 200),
        ("valid.md", b"# heading\ncontent", "text/markdown", 200),
        ("fake.pdf", b"not a pdf", "application/pdf", 415),
        ("binary.txt", b"abc\x00def", "text/plain", 415),
        ("mismatch.txt", b"plain text", "image/png", 415),
        ("fake.csv", b"a,b\n1,2", "text/csv", 415),
        ("fake.png", b"\x89PNG\r\n\x1a\n", "image/png", 415),
        ("fake.xlsx", b"PK\x03\x04", "application/octet-stream", 415),
        ("page.html", b"<html></html>", "text/html", 415),
        ("archive.zip", b"PK\x03\x04", "application/zip", 415),
        ("program.exe", b"MZ", "application/octet-stream", 415),
    ],
)
def test_file_type_content_and_mime_rules(
    client,
    monkeypatch,
    tmp_path,
    filename,
    content,
    mime,
    expected_status,
):
    monkeypatch.setattr(settings, "upload_dir", str(tmp_path / "uploads"))
    headers = register_and_login(client)
    response = upload_text(
        client,
        headers,
        filename=filename,
        content=content,
        mime=mime,
    )
    assert response.status_code == expected_status
    assert_security_headers(response)
    assert str(tmp_path) not in response.text


def test_valid_pdf_missing_mime_and_pdf_resource_limits(
    client,
    monkeypatch,
    tmp_path,
):
    monkeypatch.setattr(settings, "upload_dir", str(tmp_path / "uploads"))
    headers = register_and_login(client)
    valid = client.post(
        "/api/files/upload",
        headers=headers,
        files={"file": ("valid.pdf", pdf_bytes(), None)},
    )
    assert valid.status_code == 200

    monkeypatch.setattr(settings, "max_pdf_pages", 1)
    too_many = client.post(
        "/api/files/upload",
        headers=headers,
        files={"file": ("pages.pdf", pdf_bytes(2), "application/pdf")},
    )
    encrypted = client.post(
        "/api/files/upload",
        headers=headers,
        files={"file": ("encrypted.pdf", pdf_bytes(encrypted=True), "application/pdf")},
    )
    assert too_many.status_code == 413
    assert encrypted.status_code == 415
    assert_security_headers(too_many)
    assert_security_headers(encrypted)


def test_file_size_count_quota_and_failed_cleanup(
    client,
    db_session,
    monkeypatch,
    tmp_path,
):
    upload_root = tmp_path / "uploads"
    monkeypatch.setattr(settings, "upload_dir", str(upload_root))
    monkeypatch.setattr(settings, "max_upload_file_size_mb", 1)
    headers = register_and_login(client)
    user = db_session.query(User).filter_by(username="alice").one()
    user.is_quota_exempt = True
    db_session.commit()

    oversized = upload_text(
        client,
        headers,
        filename="large.txt",
        content=b"a\n" * (3 * 1024 * 1024),
    )
    assert oversized.status_code == 413
    assert_security_headers(oversized)
    assert db_session.query(FileRecord).count() == 0
    assert not list(upload_root.rglob("*.part"))

    too_many = client.post(
        "/api/files/upload",
        headers=headers,
        files=[
            ("file", ("one.txt", b"one", "text/plain")),
            ("file", ("two.txt", b"two", "text/plain")),
        ],
    )
    assert too_many.status_code == 413
    assert db_session.query(FileRecord).count() == 0

    monkeypatch.setattr(settings, "max_user_storage_mb", 1)
    assert upload_text(
        client,
        headers,
        filename="first.txt",
        content=b"a\n" * 350_000,
    ).status_code == 200
    quota = upload_text(
        client,
        headers,
        filename="second.txt",
        content=b"b\n" * 200_000,
    )
    assert quota.status_code == 413
    assert db_session.query(FileRecord).count() == 1
    assert not list(upload_root.rglob("*.part"))


def test_streaming_stops_before_reading_entire_oversized_file(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "upload_dir", str(tmp_path / "uploads"))
    monkeypatch.setattr(settings, "max_upload_file_size_mb", 1)
    source = io.BytesIO(b"a\n" * (3 * 1024 * 1024))
    upload = UploadFile(
        file=source,
        filename="large.txt",
        headers=Headers({"content-type": "text/plain"}),
    )
    with pytest.raises(UploadSecurityError) as error:
        stage_upload(upload, 1)
    assert error.value.status_code == 413
    assert source.tell() < len(source.getvalue())
    assert not list((tmp_path / "uploads").rglob("*.part"))


def test_upload_idempotency_and_database_failure_compensation(
    client,
    db_session,
    monkeypatch,
    tmp_path,
):
    upload_root = tmp_path / "uploads"
    monkeypatch.setattr(settings, "upload_dir", str(upload_root))
    headers = register_and_login(client)
    request_headers = {"Idempotency-Key": "upload-key-0001"}
    first = upload_text(client, headers, extra_headers=request_headers)
    second = upload_text(client, headers, extra_headers=request_headers)
    assert first.status_code == second.status_code == 200
    assert first.json()["file_id"] == second.json()["file_id"]
    assert db_session.query(FileRecord).count() == 1

    original_commit = db_session.commit
    commit_count = 0

    def fail_final_commit():
        nonlocal commit_count
        commit_count += 1
        if commit_count == 4:
            raise RuntimeError("simulated database failure")
        return original_commit()

    monkeypatch.setattr(db_session, "commit", fail_final_commit)
    failed = upload_text(client, headers, filename="db-failure.txt")
    assert failed.status_code == 500
    assert "simulated" not in failed.text
    assert db_session.query(FileRecord).count() == 1
    assert not list(upload_root.rglob("db-failure*"))
    assert not list(upload_root.rglob("*.part"))


def test_move_failure_cleanup_is_idempotent(
    client,
    db_session,
    monkeypatch,
    tmp_path,
):
    upload_root = tmp_path / "uploads"
    monkeypatch.setattr(settings, "upload_dir", str(upload_root))
    headers = register_and_login(client)
    monkeypatch.setattr(
        files_api,
        "move_staged_upload",
        lambda staged: (_ for _ in ()).throw(OSError("move failed")),
    )
    response = upload_text(client, headers)
    assert response.status_code == 500
    assert db_session.query(FileRecord).count() == 0
    assert not list(upload_root.rglob("*.part"))


def test_cleanup_never_deletes_cross_user_physical_file(
    db_session,
    monkeypatch,
    tmp_path,
):
    upload_root = tmp_path / "uploads"
    monkeypatch.setattr(settings, "upload_dir", str(upload_root))
    first = User(
        username="cleanup-owner",
        password_hash="unused",
        is_active=True,
        is_admin=False,
        created_at="2026-07-20T00:00:00",
    )
    second = User(
        username="physical-owner",
        password_hash="unused",
        is_active=True,
        is_admin=False,
        created_at="2026-07-20T00:00:00",
    )
    db_session.add_all([first, second])
    db_session.commit()
    other_file = upload_root / str(second.id) / "private.txt"
    other_file.parent.mkdir(parents=True)
    other_file.write_text("private", encoding="utf-8")
    db_session.add(
        FileRecord(
            user_id=first.id,
            file_id="forged-cross-user-file",
            filename="private.txt",
            file_type="txt",
            file_path=str(other_file),
            category="other",
            status="uploaded",
            created_at="2026-07-20T00:00:00",
            updated_at="2026-07-20T00:00:00",
        )
    )
    db_session.commit()
    vector_calls = []
    monkeypatch.setattr(
        account_data_service,
        "delete_user_vectors",
        lambda user_id: vector_calls.append(user_id),
    )
    result = account_data_service.cleanup_user_business_data(
        db_session,
        first.id,
    )
    assert result["success"] is False
    assert other_file.exists()
    assert vector_calls == []
    assert db_session.query(FileRecord).filter_by(user_id=first.id).count() == 1


def test_download_is_attachment_and_enforces_owner(
    client,
    monkeypatch,
    tmp_path,
):
    monkeypatch.setattr(settings, "upload_dir", str(tmp_path / "uploads"))
    alice_headers = register_and_login(client, "alice")
    bob_headers = register_and_login(client, "bob")
    uploaded = upload_text(client, alice_headers, filename="resume.txt")
    file_id = uploaded.json()["file_id"]

    download = client.get(f"/api/files/{file_id}/download", headers=alice_headers)
    forbidden = client.get(f"/api/files/{file_id}/download", headers=bob_headers)
    assert download.status_code == 200
    assert download.headers["content-type"] == "application/octet-stream"
    assert download.headers["content-disposition"].startswith("attachment;")
    assert download.headers["x-content-type-options"] == "nosniff"
    assert str(tmp_path) not in download.headers["content-disposition"]
    assert forbidden.status_code == 404


@pytest.mark.parametrize(
    ("path", "method", "expected_status"),
    [
        ("/api/health", "get", 200),
        ("/api/auth/me", "get", 401),
        ("/api/not-found", "get", 404),
    ],
)
def test_security_headers_cover_normal_and_error_responses(
    client,
    path,
    method,
    expected_status,
):
    response = getattr(client, method)(path)
    assert response.status_code == expected_status
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["referrer-policy"] == "no-referrer"
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-request-id"]


def test_validation_500_and_request_id_are_safely_shaped(
    client,
    db_session,
    monkeypatch,
):
    headers = register_and_login(client)
    long_secret = "敏感内容" * 3000
    invalid = client.post(
        "/api/chat/ask",
        headers=headers,
        json={"question": long_secret},
    )
    assert invalid.status_code == 422
    assert_security_headers(invalid)
    assert long_secret not in invalid.text
    assert "input" not in invalid.json()["detail"][0]

    user = db_session.query(User).filter(User.username == "alice").one()
    user.is_admin = True
    db_session.commit()
    monkeypatch.setattr(
        llm_api,
        "chat_completion",
        lambda message: (_ for _ in ()).throw(
            LLMServiceError(r"database failed at C:\\private\\app.db")
        ),
    )
    failed = client.post(
        "/api/llm/test",
        headers=headers,
        json={"message": "test"},
    )
    assert failed.status_code == 500
    assert_security_headers(failed)
    assert failed.json()["detail"] == "服务器内部错误，请稍后重试"
    assert "private" not in failed.text

    valid_id = "9cf2f7f6-48b3-4ed0-9ddf-bdfd7145d10a"
    accepted = client.get("/api/health", headers={"X-Request-ID": valid_id})
    replaced = client.get("/api/health", headers={"X-Request-ID": "x" * 1000})
    assert accepted.headers["x-request-id"] == valid_id
    assert replaced.headers["x-request-id"] != "x" * 1000
    assert len(replaced.headers["x-request-id"]) == 36


def test_cors_allows_configured_origin_and_rejects_malicious_origin(client):
    preflight_headers = {
        "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Headers": "X-CSRF-Token,Content-Type",
    }
    trusted = client.options(
        "/api/chat/ask",
        headers={"Origin": "http://localhost:5173", **preflight_headers},
    )
    malicious = client.options(
        "/api/chat/ask",
        headers={"Origin": "https://evil.example", **preflight_headers},
    )
    assert trusted.headers.get("access-control-allow-origin") == (
        "http://localhost:5173"
    )
    assert "access-control-allow-origin" not in malicious.headers


def test_forbidden_and_request_body_limit_have_security_headers(client):
    headers = register_and_login(client)
    forbidden = client.get("/api/admin/users", headers=headers)
    oversized = client.post(
        "/api/health",
        content=b"",
        headers={"Content-Length": str(26 * 1024 * 1024)},
    )
    assert forbidden.status_code == 403
    assert oversized.status_code == 413
    assert_security_headers(forbidden)
    assert_security_headers(oversized)


def test_concurrent_storage_reservations_cannot_exceed_quota(
    tmp_path,
    monkeypatch,
):
    engine = create_engine(
        f"sqlite:///{(tmp_path / 'quota.db').as_posix()}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)
    setup = session_factory()
    setup.add(
        User(
            id=1,
            username="quota-user",
            password_hash="unused",
            is_active=True,
            is_admin=False,
            created_at="2026-07-20T00:00:00",
        )
    )
    setup.commit()
    setup.close()
    monkeypatch.setattr(settings, "max_user_storage_mb", 1)

    def reserve():
        db = session_factory()
        try:
            return reserve_user_storage(db, 1, 700_000)
        except UploadSecurityError as exc:
            return exc.error_code
        finally:
            db.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: reserve(), range(2)))
    engine.dispose()
    assert results.count("user_storage_limit_exceeded") == 1
    assert sum(item != "user_storage_limit_exceeded" for item in results) == 1


@pytest.mark.parametrize(
    ("method", "path", "payload"),
    [
        ("post", "/api/chat/ask", {"question": "问" * 6001}),
        (
            "post",
            "/api/jobs/analyze",
            {"job_description": "岗" * 30001, "use_web_search": False},
        ),
        (
            "post",
            "/api/interview/evaluate",
            {
                "interview_type": "技术面试",
                "job_description": "正常 JD",
                "question_index": 1,
                "question": "请介绍项目",
                "user_answer": "答" * 12001,
            },
        ),
        (
            "put",
            "/api/profile",
            {
                "display_name": "测试用户",
                "target_direction": "后端开发",
                "self_introduction": "我" * 5001,
                "technical_skills": ["Python"],
            },
        ),
        (
            "post",
            "/api/agent/ask",
            {"question": "任务" * 6001, "mode": "local"},
        ),
    ],
)
def test_business_field_limits_return_422_without_echo(
    client,
    method,
    path,
    payload,
):
    headers = register_and_login(client)
    response = getattr(client, method)(path, headers=headers, json=payload)
    assert response.status_code == 422
    assert_security_headers(response)
    assert "input" not in response.text


def test_control_characters_are_rejected_but_normal_chinese_markdown_works(
    client,
    monkeypatch,
):
    headers = register_and_login(client)
    monkeypatch.setattr(
        chat_api,
        "ask_with_rag",
        lambda **kwargs: {"answer": "ok", "sources": []},
    )
    rejected = client.post(
        "/api/chat/ask",
        headers=headers,
        json={"question": "正常内容\x00恶意尾部"},
    )
    accepted = client.post(
        "/api/chat/ask",
        headers=headers,
        json={"question": "中文问题\n```python\nprint('ok')\n```"},
    )
    assert rejected.status_code == 422
    assert accepted.status_code == 200


def test_text_single_line_limit_is_enforced(client, monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "upload_dir", str(tmp_path / "uploads"))
    monkeypatch.setattr(settings, "max_text_line_chars", 1000)
    headers = register_and_login(client)
    response = upload_text(client, headers, content=b"a" * 1001)
    assert response.status_code == 413


def test_logs_do_not_include_credentials_or_full_content(client, caplog):
    caplog.set_level(logging.INFO)
    password = "unique-password-123"
    invite_code = "test-invite-code"
    register(client, username="logger", password=password)
    client.get(
        "/api/health",
        headers={"Authorization": "Bearer unique-secret-token"},
    )
    assert password not in caplog.text
    assert invite_code not in caplog.text
    assert "unique-secret-token" not in caplog.text


def test_invalid_security_configuration_fails_controlled_validation():
    with pytest.raises(ValueError):
        Settings(cors_allowed_origins=("*",))
    with pytest.raises(ValueError):
        Settings(trusted_proxy_cidrs=("not-a-cidr",))
    with pytest.raises(ValueError):
        Settings(max_request_body_mb=1, max_upload_file_size_mb=2)
