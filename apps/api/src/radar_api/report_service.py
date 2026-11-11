"""Generate source-limited research report drafts with DeepSeek's API."""

from __future__ import annotations

import json
import os
from typing import Any

import httpx

from radar_api.contracts import ReportContent

REPORT_PROMPT_VERSION = "radar-report-draft-v2-deepseek"
DEFAULT_MODEL_ID = "deepseek-flash"


class ReportModelUnavailable(RuntimeError):
    """DeepSeek report generation is not configured or is temporarily unavailable."""


class ReportOutputError(RuntimeError):
    """The model returned malformed or source-invalid report content."""


def generate_report_content(findings: list[dict[str, Any]]) -> tuple[ReportContent, str]:
    """Ask DeepSeek for a JSON draft using only de-identified saved finding facts."""
    api_key = os.getenv("DEEPSEEK_API_KEY", "").strip()
    if not api_key:
        raise ReportModelUnavailable("DEEPSEEK_API_KEY is not configured")

    model_id = os.getenv("RADAR_MODEL_ID", DEFAULT_MODEL_ID).strip() or DEFAULT_MODEL_ID
    schema = json.dumps(ReportContent.model_json_schema(), separators=(",", ":"))
    payload = {
        "model": model_id,
        "messages": [
            {
                "role": "system",
                "content": (
                    "Draft a research-only brain CT report from the supplied, de-identified "
                    "model findings. Do not diagnose, infer clinical history, invent findings, "
                    "or add claims without citing one or more supplied finding_ids. Preserve "
                    "uncertainty. Every finding statement and the impression must cite source "
                    "finding_ids. State that the output requires human review and is not for "
                    "clinical use. Return valid JSON matching this JSON Schema: "
                    f"{schema}"
                ),
            },
            {"role": "user", "content": json.dumps({"findings": findings}, separators=(",", ":"))},
        ],
        "temperature": 0,
        "max_tokens": 1200,
        "thinking": {"type": "disabled"},
        "response_format": {"type": "json_object"},
    }
    try:
        response = httpx.post(
            "https://api.deepseek.com/chat/completions",
            headers={"Authorization": f"Bearer {api_key}", "Accept": "application/json"},
            json=payload,
            timeout=30.0,
        )
        response.raise_for_status()
        result = response.json()
        content = result["choices"][0]["message"]["content"]
        if not isinstance(content, str):
            raise ReportOutputError("DeepSeek returned no structured report content")
        try:
            parsed = ReportContent.model_validate_json(content)
        except ValueError as error:
            raise ReportOutputError(
                "DeepSeek returned content outside the report contract"
            ) from error
        returned_model_id = str(result.get("model") or model_id)[:160]
        return parsed, returned_model_id
    except ReportOutputError:
        raise
    except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError) as error:
        raise ReportModelUnavailable("DeepSeek report generation failed") from error
