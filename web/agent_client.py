from __future__ import annotations

import json
import logging
import os
import re
import asyncio
import hashlib
import time
from typing import Optional
from typing import Protocol
from uuid import uuid4

from agent.actions import (
    ProgressCallback,
    generate_graphic_recording,
    regenerate_graphic_recording,
    summarize_url,
)
from agent.strands_agent import run_narration_turn
from agent.models import GraphicResult, SummaryResult
from agent.models import ProgressStep
from agent.runtime_contract import RuntimeSummaryPayload, RuntimeWorkflowResponse

logger = logging.getLogger(__name__)


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
    """Calls the deployed AgentCore Runtime workflow and validates its JSON contract."""

    def __init__(self) -> None:
        self._agentcore_client = None

    async def summarize_url(
        self,
        url: str,
        on_progress: Optional[ProgressCallback] = None,
    ) -> SummaryResult:
        await _emit_runtime_status("AgentCore Runtime に要約 workflow を送信", on_progress)
        response = await self._run_runtime_operation({"operation": "summarize_url", "url": url})
        if not response.summary:
            raise RuntimeError("AgentCore Runtime response did not include summary")
        return response.summary.to_result()

    async def generate_graphic_recording(
        self,
        summary: SummaryResult,
        on_progress: Optional[ProgressCallback] = None,
    ) -> GraphicResult:
        await _emit_runtime_status("AgentCore Runtime にグラレコ workflow を送信", on_progress)
        response = await self._run_runtime_operation(
            {
                "operation": "generate_graphic",
                "summary": RuntimeSummaryPayload.from_result(summary).model_dump(mode="json"),
            }
        )
        if not response.graphic:
            raise RuntimeError("AgentCore Runtime response did not include graphic")
        return response.graphic.to_result()

    async def regenerate_graphic_recording(
        self,
        summary: SummaryResult,
        feedback: str,
        on_progress: Optional[ProgressCallback] = None,
    ) -> GraphicResult:
        await _emit_runtime_status("AgentCore Runtime に再生成 workflow を送信", on_progress)
        response = await self._run_runtime_operation(
            {
                "operation": "regenerate_graphic",
                "summary": RuntimeSummaryPayload.from_result(summary).model_dump(mode="json"),
                "feedback": feedback,
            }
        )
        if not response.graphic:
            raise RuntimeError("AgentCore Runtime response did not include graphic")
        return response.graphic.to_result()

    async def _run_runtime_operation(self, payload: dict) -> RuntimeWorkflowResponse:
        client = self._get_agentcore_client()
        return await asyncio.to_thread(self._run_runtime_operation_sync, client, payload)

    def _run_runtime_operation_sync(self, client, payload: dict) -> RuntimeWorkflowResponse:
        started = time.perf_counter()
        operation = str(payload.get("operation", "unknown"))
        runtime_arn = _agentcore_runtime_arn()
        response = client.invoke_agent_runtime(
            agentRuntimeArn=runtime_arn,
            runtimeSessionId=_runtime_session_id(payload),
            payload=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            contentType="application/json",
            accept="application/json",
        )
        runtime_response = _runtime_response_from_agentcore_response(response)

        elapsed_seconds = time.perf_counter() - started
        logger.info(
            "runtime_call_duration operation=%s elapsed_seconds=%.3f",
            operation,
            elapsed_seconds,
        )
        if runtime_response:
            return _validated_runtime_response(runtime_response)
        raise RuntimeError("AgentCore Runtime returned no workflow response")

    def _get_agentcore_client(self):
        if self._agentcore_client is not None:
            return self._agentcore_client

        runtime_arn = _agentcore_runtime_arn()
        if _looks_like_placeholder(runtime_arn):
            raise RuntimeError(
                "AGENTCORE_RUNTIME_ARN still contains a placeholder. "
                "Set it to the exact runtime ARN printed by the AgentCore deploy command."
            )

        import boto3

        self._agentcore_client = boto3.client(
            "bedrock-agentcore",
            region_name=os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION") or _region_from_arn(runtime_arn),
        )
        return self._agentcore_client


class StrandsAgentClient(LocalAgentClient):
    """Runs a Strands narration turn before the local tool pipeline."""

    async def summarize_url(
        self,
        url: str,
        on_progress: Optional[ProgressCallback] = None,
    ) -> SummaryResult:
        prefix = await self._strands_prefix(
            "Strands Agent が summarize_url action を解説",
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
        prefix = await self._strands_prefix(
            "Strands Agent が generate_graphic_recording action を解説",
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
        prefix = await self._strands_prefix(
            "Strands Agent が regenerate_graphic_recording action を解説",
            f"ユーザーフィードバック「{feedback}」を反映して再生成する手順を解説してください。",
            on_progress,
        )

        async def wrapped(progress: list[ProgressStep]) -> None:
            if on_progress:
                await on_progress(prefix + progress)

        graphic = await regenerate_graphic_recording(summary, feedback, on_progress=wrapped)
        graphic.progress = prefix + graphic.progress
        return graphic

    async def _strands_prefix(
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
            detail = f"strands:fallback:{str(exc)[:120]}"

        done = [ProgressStep(label, "done", detail)]
        if on_progress:
            await on_progress(done)
        return done


def build_agent_client() -> AgentClient:
    backend = os.getenv("AGENT_BACKEND", "local").lower()
    if backend == "strands":
        return StrandsAgentClient()
    if backend == "runtime":
        return RuntimeAgentClient()
    return LocalAgentClient()


async def _emit_runtime_status(
    label: str,
    on_progress: Optional[ProgressCallback],
) -> None:
    if on_progress:
        await on_progress([ProgressStep(label, "running")])


def _agentcore_runtime_arn() -> str:
    runtime_arn = os.getenv("AGENTCORE_RUNTIME_ARN")
    if not runtime_arn:
        raise RuntimeError("Set AGENTCORE_RUNTIME_ARN when AGENT_BACKEND=runtime.")
    return runtime_arn


def _region_from_arn(arn: str) -> str:
    parts = arn.split(":")
    return parts[3] if len(parts) > 3 and parts[3] else "us-east-1"


def _runtime_session_id(payload: dict) -> str:
    seed = (
        str(payload.get("summary", {}).get("session_id") if isinstance(payload.get("summary"), dict) else "")
        or str(payload.get("url") or "")
        or json.dumps(payload, sort_keys=True, ensure_ascii=False)
    )
    digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()
    return f"workshop-session-{digest}"[:64]


def _looks_like_placeholder(value: str) -> bool:
    placeholders = (
        "ACCOUNT_ID",
        "RUNTIME_ID",
        "YOUR_RUNTIME_ARN",
        "YOUR_ACCOUNT_ID",
        "CHANGE_ME",
        "PASTE_HERE",
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
        text = part.get("text")
        if isinstance(text, str) and text.strip():
            try:
                return _runtime_response_from_text(text)
            except Exception:
                continue
    return None


def _runtime_response_from_agentcore_response(response: dict) -> Optional[RuntimeWorkflowResponse]:
    for key in ("response", "output", "payload", "body"):
        value = response.get(key)
        parsed = _runtime_response_from_agentcore_value(value)
        if parsed:
            return parsed
    return None


def _runtime_response_from_agentcore_value(value) -> Optional[RuntimeWorkflowResponse]:
    if value is None:
        return None
    if isinstance(value, RuntimeWorkflowResponse):
        return value
    if isinstance(value, dict):
        try:
            return RuntimeWorkflowResponse.model_validate(value)
        except Exception:
            for nested in value.values():
                parsed = _runtime_response_from_agentcore_value(nested)
                if parsed:
                    return parsed
            return None
    if isinstance(value, bytes):
        value = value.decode("utf-8")
    elif hasattr(value, "read"):
        raw = value.read()
        value = raw.decode("utf-8") if isinstance(raw, bytes) else raw
    if isinstance(value, str) and value.strip():
        return _runtime_response_from_text(value)
    return None


def _validated_runtime_response(response: RuntimeWorkflowResponse) -> RuntimeWorkflowResponse:
    logger.info(
        "runtime_contract operation=%s has_summary=%s has_graphic=%s error=%s",
        response.operation,
        response.summary is not None,
        response.graphic is not None,
        bool(response.error),
    )
    if response.error:
        raise RuntimeError(response.error)
    return response


def _event_shape(event: dict) -> str:
    content = event.get("content") or {}
    part_shapes = []
    for part in content.get("parts") or []:
        keys = sorted(part.keys())
        if "text" in part and isinstance(part.get("text"), str):
            keys.append(f"text_len={len(part['text'])}")
        if "function_response" in part or "functionResponse" in part:
            function_response = part.get("function_response") or part.get("functionResponse") or {}
            keys.append(f"function={function_response.get('name', '')}")
        part_shapes.append(",".join(keys))
    return f"author={event.get('author', '')} parts={part_shapes}"


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
