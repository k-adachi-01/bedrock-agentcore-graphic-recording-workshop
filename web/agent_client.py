from __future__ import annotations

import os
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


class RuntimeAgentClient(LocalAgentClient):
    """Agent Runtime integration boundary.

    This intentionally fails fast until the remote workflow contract is wired.
    A silent local fallback would make Cloud Run deployments look successful
    while bypassing Agent Runtime entirely.
    """

    async def summarize_url(
        self,
        url: str,
        on_progress: Optional[ProgressCallback] = None,
    ) -> SummaryResult:
        raise _runtime_not_configured()

    async def generate_graphic_recording(
        self,
        summary: SummaryResult,
        on_progress: Optional[ProgressCallback] = None,
    ) -> GraphicResult:
        raise _runtime_not_configured()

    async def regenerate_graphic_recording(
        self,
        summary: SummaryResult,
        feedback: str,
        on_progress: Optional[ProgressCallback] = None,
    ) -> GraphicResult:
        raise _runtime_not_configured()


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


def _runtime_not_configured() -> RuntimeError:
    return RuntimeError(
        "AGENT_BACKEND=runtime is not wired yet. Deploy with AGENT_BACKEND=adk "
        "for the workshop path, or implement RuntimeAgentClient against the "
        "Agent Runtime async_stream_query contract before enabling runtime mode."
    )
