import json
from argparse import Namespace

import pytest

from evals import run_live_agent_smoke


def test_check_mode_is_offline_and_uses_only_fictional_cases(monkeypatch, capsys):
    monkeypatch.setattr("sys.argv", ["live-smoke", "--check", "--max-cases", "3"])
    monkeypatch.setattr(
        run_live_agent_smoke,
        "run_live",
        lambda args, cases: (_ for _ in ()).throw(AssertionError("不得联网")),
    )
    run_live_agent_smoke.main()
    result = json.loads(capsys.readouterr().out)
    assert result["network_allowed"] is False
    assert result["uses_real_user_data"] is False
    assert result["selected_cases"] == 3


def test_live_mode_requires_all_explicit_gates(monkeypatch):
    monkeypatch.delenv("ALLOW_LIVE_MODEL_EVAL", raising=False)
    args = Namespace(allow_network=False, confirm_cost=False)
    with pytest.raises(SystemExit, match="真实调用已拒绝"):
        run_live_agent_smoke.require_live_gates(args)


@pytest.mark.parametrize(
    ("name", "value"),
    [("max_cases", 6), ("max_calls", 11), ("max_estimated_tokens", 50_001)],
)
def test_live_limits_are_bounded(name, value):
    args = Namespace(max_cases=5, max_calls=10, max_estimated_tokens=50_000)
    setattr(args, name, value)
    with pytest.raises(SystemExit):
        run_live_agent_smoke.validate_limits(args)


def test_prompt_injection_case_is_fictional():
    cases = json.loads(run_live_agent_smoke.CASES_PATH.read_text(encoding="utf-8"))
    injection = next(item for item in cases if item["id"] == "prompt_injection")
    assert "虚构资料" in injection["input"]
    assert len(cases) == 9
