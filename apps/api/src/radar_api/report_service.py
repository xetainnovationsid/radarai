"""Generate source-limited research report drafts with Meta's structured-output API."""

from __future__ import annotations

import json
import os
from typing import Any

import httpx

from radar_api.contracts import ReportContent

REPORT_PROMPT_VERSION = "radar-report-draft-v1"
DEFAULT_MODEL_ID = "muse-spark-1.3"


class ReportModelUnavailable(RuntimeError):
    """Meta report generation is not configured or is temporarily unavailable."""


class ReportOutputError(RuntimeError):
    """The model returned malformed or source-invalid report content."""


def generate_report_content(findings: list[dict[str, Any]]) -> tuple[ReportContent, str]:
    """Ask Meta for a JSON draft using only de-identified saved finding facts."""
    api_key = os.getenv("MODEL_API_KEY", "").strip()
    if not api_key:
        raise ReportModelUnavailable("MODEL_API_KEY is not configured")

    model_id = os.getenv("RADAR_MODEL_ID", DEFAULT_MODEL_ID).strip() or DEFAULT_MODEL_ID
    payload = {
        "model": model_id,
        "messages": [
            {
                "role": "developer",
                "content": (
                    "Draft a research-only brain CT report from the supplied, de-identified "
                    "model findings. Do not diagnose, infer clinical history, invent findings, "
                    "or add claims without citing one or more supplied finding_ids. Preserve "
                    "uncertainty. Every finding statement and the impression must cite source "
                    "finding_ids. State that the output requires human review and is not for "
                    "clinical use."
                ),
            },
            {"role": "user", "content": json.dumps({"findings": findings}, separators=(",", ":"))},
        ],
        "temperature": 0,
        "max_completion_tokens": 1200,
        "store": False,
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": "radar_report_draft",
                "strict": True,
                "schema": ReportContent.model_json_schema(),
            },
        },
    }
    try:
        response = httpx.post(
            "https://api.meta.ai/v1/chat/completions",
            headers={"Authorization": f"Bearer {api_key}", "Accept": "application/json"},
            json=payload,
            timeout=30.0,
        )
        response.raise_for_status()
        result = response.json()
        content = result["choices"][0]["message"]["content"]
        if not isinstance(content, str):
            raise ReportOutputError("Meta returned no structured report content")
        try:
            parsed = ReportContent.model_validate_json(content)
        except ValueError as error:
            raise ReportOutputError("Meta returned content outside the report contract") from error
        returned_model_id = str(result.get("model") or model_id)[:160]
        return parsed, returned_model_id
    except ReportOutputError:
        raise
    except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError) as error:
        raise ReportModelUnavailable("Meta report generation failed") from error
