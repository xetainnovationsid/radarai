import pytest

from scripts.check_deepseek_model_access import request_json


def test_deepseek_request_requires_key_without_making_a_network_call(monkeypatch) -> None:
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)

    with pytest.raises(RuntimeError, match="DEEPSEEK_API_KEY is not set"):
        request_json("/models")
