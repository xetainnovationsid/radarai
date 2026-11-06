import pytest

from scripts.check_meta_model_access import estimated_standard_cost_usd, request_json


def test_standard_cost_estimate_accounts_for_cached_input_tokens() -> None:
    cost = estimated_standard_cost_usd(
        {
            "prompt_tokens": 100,
            "completion_tokens": 10,
            "prompt_tokens_details": {"cached_tokens": 25},
        }
    )

    assert cost == pytest.approx(0.00014)


def test_meta_request_requires_key_without_making_a_network_call(monkeypatch) -> None:
    monkeypatch.delenv("MODEL_API_KEY", raising=False)

    with pytest.raises(RuntimeError, match="MODEL_API_KEY is not set"):
        request_json("/models")
