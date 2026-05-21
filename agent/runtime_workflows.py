from __future__ import annotations

import os
from typing import Any

from agent.actions import (
    generate_graphic_recording,
    regenerate_graphic_recording,
    summarize_url,
)
from agent.runtime_contract import (
    RuntimeGraphicPayload,
    RuntimeSummaryPayload,
    RuntimeWorkflowResponse,
)


async def runtime_summarize_url(url: str) -> dict[str, Any]:
    """Run the deterministic summary workflow and return the runtime JSON contract."""
    summary = await summarize_url(url)
    response = RuntimeWorkflowResponse(
        operation="summarize_url",
        summary=RuntimeSummaryPayload.from_result(summary),
    )
    return response.model_dump(mode="json")


async def runtime_generate_graphic(summary: dict[str, Any]) -> dict[str, Any]:
    """Generate a graphic artifact from a summary payload."""
    _assert_runtime_artifact_store()
    summary_result = RuntimeSummaryPayload.model_validate(summary).to_result()
    graphic = await generate_graphic_recording(summary_result)
    response = RuntimeWorkflowResponse(
        operation="generate_graphic",
        graphic=RuntimeGraphicPayload.from_result(graphic),
    )
    return response.model_dump(mode="json")


async def runtime_regenerate_graphic(summary: dict[str, Any], feedback: str = "") -> dict[str, Any]:
    """Regenerate a graphic artifact from a summary payload and feedback."""
    _assert_runtime_artifact_store()
    summary_result = RuntimeSummaryPayload.model_validate(summary).to_result()
    graphic = await regenerate_graphic_recording(summary_result, feedback)
    response = RuntimeWorkflowResponse(
        operation="regenerate_graphic",
        graphic=RuntimeGraphicPayload.from_result(graphic),
    )
    return response.model_dump(mode="json")


def _assert_runtime_artifact_store() -> None:
    if not os.getenv("GCS_BUCKET"):
        raise RuntimeError(
            "GCS_BUCKET is required for Agent Runtime graphic generation because "
            "Cloud Run cannot serve files from the Agent Runtime filesystem."
        )
