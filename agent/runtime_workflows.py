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


async def dispatch_runtime_operation(payload: dict[str, Any]) -> RuntimeWorkflowResponse:
    """Dispatch one runtime operation without involving an LLM routing step."""
    operation = payload.get("operation")
    if operation == "summarize_url":
        url = str(payload.get("url") or "").strip()
        if not url:
            raise ValueError("summarize_url requires a non-empty url")
        return await runtime_summarize_url(url)
    if operation == "generate_graphic":
        summary = payload.get("summary")
        if not isinstance(summary, dict):
            raise ValueError("generate_graphic requires a summary payload")
        return await runtime_generate_graphic(summary)
    if operation == "regenerate_graphic":
        summary = payload.get("summary")
        if not isinstance(summary, dict):
            raise ValueError("regenerate_graphic requires a summary payload")
        feedback = str(payload.get("feedback") or "")
        return await runtime_regenerate_graphic(summary, feedback)
    raise ValueError(f"Unsupported runtime operation: {operation!r}")


async def runtime_summarize_url(url: str) -> RuntimeWorkflowResponse:
    """Run the deterministic summary workflow and return the runtime JSON contract."""
    summary = await summarize_url(url)
    return RuntimeWorkflowResponse(
        operation="summarize_url",
        summary=RuntimeSummaryPayload.from_result(summary),
    )


async def runtime_generate_graphic(summary: dict[str, Any]) -> RuntimeWorkflowResponse:
    """Generate a graphic artifact from a summary payload."""
    _assert_runtime_artifact_store()
    summary_result = RuntimeSummaryPayload.model_validate(summary).to_result()
    graphic = await generate_graphic_recording(summary_result)
    return RuntimeWorkflowResponse(
        operation="generate_graphic",
        graphic=RuntimeGraphicPayload.from_result(graphic),
    )


async def runtime_regenerate_graphic(summary: dict[str, Any], feedback: str = "") -> RuntimeWorkflowResponse:
    """Regenerate a graphic artifact from a summary payload and feedback."""
    _assert_runtime_artifact_store()
    summary_result = RuntimeSummaryPayload.model_validate(summary).to_result()
    graphic = await regenerate_graphic_recording(summary_result, feedback)
    return RuntimeWorkflowResponse(
        operation="regenerate_graphic",
        graphic=RuntimeGraphicPayload.from_result(graphic),
    )


def _assert_runtime_artifact_store() -> None:
    if not os.getenv("S3_BUCKET"):
        raise RuntimeError(
            "S3_BUCKET is required for AgentCore Runtime graphic generation because "
            "ECS Express cannot serve files from the AgentCore Runtime filesystem."
        )
