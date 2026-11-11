"""Synthetic text-only DeepSeek API connectivity check; never send patient data."""

import json
import os
import sys
import urllib.error
import urllib.request

API_BASE = "https://api.deepseek.com"
MODEL_ID = os.getenv("RADAR_MODEL_ID", "deepseek-flash")


def request_json(path: str, *, body: dict | None = None) -> dict:
    api_key = os.getenv("DEEPSEEK_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("DEEPSEEK_API_KEY is not set; add it in the DeepSeek Platform dashboard.")

    headers = {"Authorization": f"Bearer {api_key}", "Accept": "application/json"}
    data = None
    if body is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(body).encode("utf-8")
    request = urllib.request.Request(f"{API_BASE}{path}", data=data, headers=headers)
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read())


def main() -> int:
    try:
        catalog = request_json("/models")
        available_ids = {item["id"] for item in catalog.get("data", []) if "id" in item}
        if MODEL_ID not in available_ids:
            print(json.dumps({"available": False, "requested_model": MODEL_ID}, indent=2))
            return 1

        completion = request_json(
            "/chat/completions",
            body={
                "model": MODEL_ID,
                "messages": [
                    {
                        "role": "system",
                        "content": 'Reply with valid JSON containing a single key "status".',
                    },
                    {"role": "user", "content": "Return status ready."},
                ],
                "response_format": {"type": "json_object"},
                "max_tokens": 40,
                "thinking": {"type": "disabled"},
            },
        )
        print(
            json.dumps(
                {
                    "available": True,
                    "model_id": completion.get("model", MODEL_ID),
                    "finish_reason": (completion.get("choices") or [{}])[0].get("finish_reason"),
                    "usage": completion.get("usage", {}),
                    "note": "Synthetic text-only connectivity check; no study or patient data was sent.",
                },
                indent=2,
            )
        )
        return 0
    except RuntimeError as error:
        print(str(error), file=sys.stderr)
        return 2
    except urllib.error.HTTPError as error:
        print(f"DeepSeek API returned HTTP {error.code}.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
