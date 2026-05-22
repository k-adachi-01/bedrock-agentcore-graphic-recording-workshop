from __future__ import annotations

import json
import os
import re
import asyncio
from typing import Optional
from typing import Protocol
from uuid import uuid4

from agent.actions import (
    ProgressCallback,
    generate_graphic_recording,
    regenerate_graphic_recording,
    summarize_url,
)
from agent.adk_agent import run_narration_turn
from agent.models import GraphicResult, SummaryResult
from agent.models import ProgressStep
from agent.runtime_contract import RuntimeSummaryPayload, RuntimeWorkflowResponse


class AgentClient(Protocol):
    async def summarize_url(
        self,
        url: str,
        on_progress: Optional[ProgressCallback] = None,
    ) -> SummaryResult:
        ...

    async def generate_graphic_recording(
        self,
        summary: SummaryResult,
        on_progress: Optional[ProgressCallback] = None,
    ) -> GraphicResult:
        ...

    async def regenerate_graphic_recording(
        self,
        summary: SummaryResult,
        feedback: str,
        on_progress: Optional[ProgressCallback] = None,
    ) -> GraphicResult:
        ...


class LocalAgentClient:
    async def summarize_url(
        self,
        url: str,
        on_progress: Optional[ProgressCallback] = None,
    ) -> SummaryResult:
        return await summarize_url(url, on_progress=on_progress)

    async def generate_graphic_recording(
        self,
        summary: SummaryResult,
        on_progress: Optional[ProgressCallback] = None,
    ) -> GraphicResult:
        return await generate_graphic_recording(summary, on_progress=on_progress)

    async def regenerate_graphic_recording(
        self,
        summary: SummaryResult,
        feedback: str,
        on_progress: Optional[ProgressCallback] = None,
    ) -> GraphicResult:
        return await regenerate_graphic_recording(summary, feedback, on_progress=on_progress)


class RuntimeAgentClient:
    """Calls the deployed Agent Runtime workflow and validates its JSON contract."""

    def __init__(self) -> None:
        self._remote_agent = None

    async def summarize_url(
        self,
        url: str,
        on_progress: Optional[ProgressCallback] = None,
    ) -> SummaryResult:
        await _emit_runtime_status("Agent Runtime に要約 workflow を送信", on_progress)
        response = await self._run_runtime_operation({"operation": "summarize_url", "url": url})
        if not response.summary:
            raise RuntimeError("Agent Runtime response did not include summary")
        return response.summary.to_result()

    async def generate_graphic_recording(
        self,
        summary: SummaryResult,
        on_progress: Optional[ProgressCallback] = None,
    ) -> GraphicResult:
        await _emit_runtime_status("Agent Runtime にグラレコ workflow を送信", on_progress)
        response = await self._run_runtime_operation(
            {
                "operation": "generate_graphic",
                "summary": RuntimeSummaryPayload.from_result(summary).model_dump(mode="json"),
            }
        )
        if not response.graphic:
            raise RuntimeError("Agent Runtime response did not include graphic")
        return response.graphic.to_result()

    async def regenerate_graphic_recording(
        self,
        summary: SummaryResult,
        feedback: str,
        on_progress: Optional[ProgressCallback] = None,
    ) -> GraphicResult:
        await _emit_runtime_status("Agent Runtime に再生成 workflow を送信", on_progress)
        response = await self._run_runtime_operation(
            {
                "operation": "regenerate_graphic",
                "summary": RuntimeSummaryPayload.from_result(summary).model_dump(mode="json"),
                "feedback": feedback,
            }
        )
        if not response.graphic:
            raise RuntimeError("Agent Runtime response did not include graphic")
        return response.graphic.to_result()

    async def _run_runtime_operation(self, payload: dict) -> RuntimeWorkflowResponse:
        remote_agent = self._get_remote_agent()
        return await asyncio.to_thread(self._run_runtime_operation_sync, remote_agent, payload)

    def _run_runtime_operation_sync(self, remote_agent, payload: dict) -> RuntimeWorkflowResponse:
        runtime_response = None
        final_text = ""
        for event in remote_agent.stream_query(
            user_id=os.getenv("AGENT_RUNTIME_USER_ID", "workshop-user"),
            message=json.dumps(payload, ensure_ascii=False),
        ):
            event_payload = _event_to_plain_data(event)
            candidate = _runtime_response_from_event(event_payload)
            if candidate:
                runtime_response = candidate
            final_text = _last_text_from_event(event_payload) or final_text

        if runtime_response:
            if runtime_response.error:
                raise RuntimeError(runtime_response.error)
            return runtime_response
        if final_text:
            return _runtime_response_from_text(final_text)
        raise RuntimeError("Agent Runtime returned no workflow response")

    def _get_remote_agent(self):
        if self._remote_agent is not None:
            return self._remote_agent

        resource_name = os.getenv("AGENT_RUNTIME_RESOURCE_NAME")
        if not resource_name:
            raise RuntimeError("Set AGENT_RUNTIME_RESOURCE_NAME when AGENT_BACKEND=runtime.")
        if _looks_like_placeholder(resource_name):
            raise RuntimeError(
                "AGENT_RUNTIME_RESOURCE_NAME still contains a placeholder. "
                "Set it to the exact projects/.../locations/.../reasoningEngines/... value "
                "printed by scripts/deploy-agent-runtime.py."
            )

        import vertexai

        client = vertexai.Client(
            project=os.getenv("GOOGLE_CLOUD_PROJECT") or os.getenv("PROJECT_ID"),
            location=os.getenv("AGENT_RUNTIME_LOCATION") or _location_from_resource_name(resource_name),
        )
        self._remote_agent = client.agent_engines.get(name=resource_name)
        return self._remote_agent


class AdkAgentClient(LocalAgentClient):
    """Runs an ADK LlmAgent narration turn before the local tool pipeline."""

    async def summarize_url(
        self,
        url: str,
        on_progress: Optional[ProgressCallback] = None,
    ) -> SummaryResult:
        prefix = await self._adk_prefix(
            "ADK LlmAgent が summarize_url action を解説",
            f"URL {url} を要約するため、アプリケーションが次に進める tool/action を解説してください。",
            on_progress,
        )

        async def wrapped(progress: list[ProgressStep]) -> None:
            if on_progress:
                await on_progress(prefix + progress)

        summary = await summarize_url(url, on_progress=wrapped)
        summary.progress = prefix + summary.progress
        summary.text_backend = f"{summary.text_backend} / {prefix[0].detail}"
        return summary

    async def generate_graphic_recording(
        self,
        summary: SummaryResult,
        on_progress: Optional[ProgressCallback] = None,
    ) -> GraphicResult:
        prefix = await self._adk_prefix(
            "ADK LlmAgent が generate_graphic_recording action を解説",
            "確認済み要約からグラレコ構成案と画像 artifact を生成する手順を解説してください。",
            on_progress,
        )

        async def wrapped(progress: list[ProgressStep]) -> None:
            if on_progress:
                await on_progress(prefix + progress)

        graphic = await generate_graphic_recording(summary, on_progress=wrapped)
        graphic.progress = prefix + graphic.progress
        return graphic

    async def regenerate_graphic_recording(
        self,
        summary: SummaryResult,
        feedback: str,
        on_progress: Optional[ProgressCallback] = None,
    ) -> GraphicResult:
        prefix = await self._adk_prefix(
            "ADK LlmAgent が regenerate_graphic_recording action を解説",
            f"ユーザーフィードバック「{feedback}」を反映して再生成する手順を解説してください。",
            on_progress,
        )

        async def wrapped(progress: list[ProgressStep]) -> None:
            if on_progress:
                await on_progress(prefix + progress)

        graphic = await regenerate_graphic_recording(summary, feedback, on_progress=wrapped)
        graphic.progress = prefix + graphic.progress
        return graphic

    async def _adk_prefix(
        self,
        label: str,
        prompt: str,
        on_progress: Optional[ProgressCallback],
    ) -> list[ProgressStep]:
        running = [ProgressStep(label, "running")]
        if on_progress:
            await on_progress(running)

        try:
            detail = await run_narration_turn(prompt, session_id=uuid4().hex)
        except Exception as exc:
            detail = f"adk:fallback:{str(exc)[:120]}"

        done = [ProgressStep(label, "done", detail)]
        if on_progress:
            await on_progress(done)
        return done


def build_agent_client() -> AgentClient:
    backend = os.getenv("AGENT_BACKEND", "local").lower()
    if backend == "adk":
        return AdkAgentClient()
    if backend == "runtime":
        return RuntimeAgentClient()
    return LocalAgentClient()


async def _emit_runtime_status(
    label: str,
    on_progress: Optional[ProgressCallback],
) -> None:
    if on_progress:
        await on_progress([ProgressStep(label, "running")])


def _location_from_resource_name(resource_name: str) -> str:
    match = re.search(r"/locations/([^/]+)/", resource_name)
    if not match:
        return "us-central1"
    return match.group(1)


def _looks_like_placeholder(value: str) -> bool:
    placeholders = (
        "PROJECT_NUMBER",
        "RESOURCE_ID",
        "SERVICE_AGENT_EMAIL_FROM_EFFECTIVE_IDENTITY",
        "YOUR_PROJECT_ID",
        "CHANGE_ME",
    )
    return any(placeholder in value for placeholder in placeholders)


def _event_to_plain_data(event):
    if isinstance(event, dict):
        return event
    if hasattr(event, "model_dump"):
        return event.model_dump(mode="json")
    if hasattr(event, "to_dict"):
        return event.to_dict()
    return {}


def _runtime_response_from_event(event: dict) -> Optional[RuntimeWorkflowResponse]:
    content = event.get("content") or {}
    for part in content.get("parts") or []:
        function_response = part.get("function_response") or part.get("functionResponse") or {}
        response = function_response.get("response")
        if isinstance(response, dict):
            try:
                return RuntimeWorkflowResponse.model_validate(response)
            except Exception:
                continue
    return None


def _last_text_from_event(event: dict) -> str:
    content = event.get("content") or {}
    texts = []
    for part in content.get("parts") or []:
        text = part.get("text")
        if text:
            texts.append(text)
    return "\n".join(texts).strip()


def _runtime_response_from_text(text: str) -> RuntimeWorkflowResponse:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = stripped.strip("`")
        stripped = re.sub(r"^json\s*", "", stripped, flags=re.I).strip()
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start >= 0 and end > start:
        stripped = stripped[start : end + 1]
    return RuntimeWorkflowResponse.model_validate_json(stripped)
