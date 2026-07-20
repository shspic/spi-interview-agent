from scripts import release_preflight


def test_configuration_preflight_never_exposes_secret_values(monkeypatch):
    monkeypatch.setattr(release_preflight.settings, "jwt_secret_key", "DO-NOT-PRINT-JWT")
    monkeypatch.setattr(release_preflight.settings, "auth_csrf_secret", "DO-NOT-PRINT-CSRF")

    checks = release_preflight.configuration_checks(dry_run=True)
    rendered = "\n".join(item.message for item in checks)

    assert checks
    assert {item.status for item in checks} <= {"pass", "warn", "fail"}
    assert "DO-NOT-PRINT-JWT" not in rendered
    assert "DO-NOT-PRINT-CSRF" not in rendered


def test_dry_run_downgrades_missing_production_requirements(monkeypatch):
    monkeypatch.setattr(release_preflight.settings, "app_environment", "development")
    monkeypatch.setattr(release_preflight.settings, "auth_cookie_secure", False)

    checks = release_preflight.configuration_checks(dry_run=True)
    by_name = {item.name: item for item in checks}

    assert by_name["production_mode"].status == "warn"
    assert by_name["cookie_secure"].status == "warn"
