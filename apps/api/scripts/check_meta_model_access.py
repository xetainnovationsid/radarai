"""Live, low-cost Meta Model API smoke check; never send patient data to this script."""

import json
import os
import sys
import urllib.error
import urllib.request

API_BASE = "https://api.meta.ai/v1"
MODEL_ID = os.getenv("RADAR_MODEL_ID", "muse-spark-1.3")
STANDARD_INPUT_PER_MILLION = 1.25
STANDARD_CACHED_INPUT_PER_MILLION = 0.15
STANDARD_OUTPUT_PER_MILLION = 4.25


def request_json(
    path: str,
    *,
    method: str = "GET",
    body: dict | None = None,
) -> tuple[dict, object]:
    api_key = os.getenv("MODEL_API_KEY")
    if not api_key:
        raise RuntimeError(
            "MODEL_API_KEY is not set; create a key in the Meta Model API dashboard."
        )

    headers = {"Authorization": f"Bearer {api_key}", "Accept": "application/json"}
    data = None
    if body is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(body).encode("utf-8")
    request = urllib.request.Request(
        f"{API_BASE}{path}", data=data, headers=headers, method=method
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read()), response.headers


def estimated_standard_cost_usd(usage: dict) -> float:
    prompt_tokens = usage.get("prompt_tokens", 0)
    completion_tokens = usage.get("completion_tokens", 0)
    cached_tokens = usage.get("prompt_tokens_details", {}).get("cached_tokens", 0)
    uncached_tokens = max(prompt_tokens - cached_tokens, 0)
    return (
        uncached_tokens * STANDARD_INPUT_PER_MILLION
        + cached_tokens * STANDARD_CACHED_INPUT_PER_MILLION
        + completion_tokens * STANDARD_OUTPUT_PER_MILLION
    ) / 1_000_000


def main() -> int:
    try:
        catalog, _ = request_json("/models")
        available_ids = {item["id"] for item in catalog.get("data", []) if "id" in item}
        if MODEL_ID not in available_ids:
            print(json.dumps({"available": False, "requested_model": MODEL_ID}, indent=2))
            return 1

        completion, headers = request_json(
            "/chat/completions",
            method="POST",
            body={
                "model": MODEL_ID,
                "messages": [{"role": "user", "content": "Reply with the single word: ready"}],
            },
        )
        usage = completion.get("usage") or {}
        result = {
            "available": True,
            "model_id": completion.get("model", MODEL_ID),
            "finish_reason": (completion.get("choices") or [{}])[0].get("finish_reason"),
            "usage": {
                "prompt_tokens": usage.get("prompt_tokens"),
                "completion_tokens": usage.get("completion_tokens"),
                "total_tokens": usage.get("total_tokens"),
                "cached_prompt_tokens": usage.get("prompt_tokens_details", {}).get(
                    "cached_tokens", 0
                ),
            },
            "estimated_standard_cost_usd": estimated_standard_cost_usd(usage),
            "rate_limits": {
                name: headers.get(name)
                for name in (
                    "x-ratelimit-limit-tokens",
                    "x-ratelimit-remaining-tokens",
                    "x-ratelimit-limit-requests",
                    "x-ratelimit-remaining-requests",
                )
            },
            "note": "Synthetic text-only connectivity check; no study or patient data was sent.",
        }
        print(json.dumps(result, indent=2))
        return 0
    except RuntimeError as error:
        print(str(error), file=sys.stderr)
        return 2
    except urllib.error.HTTPError as error:
        print(f"Meta Model API returned HTTP {error.code}.", file=sys.stderr)
        return 1
    except (urllib.error.URLError, TimeoutError) as error:
        reason = error.reason if isinstance(error, urllib.error.URLError) else error
        print(f"Could not reach Meta Model API: {reason}", file=sys.stderr)
        return 1
    except (KeyError, TypeError, ValueError) as error:
        print(f"Unexpected Meta Model API response: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
