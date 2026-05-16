from __future__ import annotations

import os
from typing import Optional
from typing import Protocol

from agent.actions import (
    ProgressCallback,
    generate_graphic_recording,
    regenerate_graphic_recording,
    summarize_url,
)
from agent.models import GraphicResult, SummaryResult


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
    """Placeholder for Agent Runtime.

    Phase 1 intentionally falls back to the local mock implementation so the
    complete demo works without external services.
    """


def build_agent_client() -> AgentClient:
    backend = os.getenv("AGENT_BACKEND", "local").lower()
    if backend == "runtime":
        return RuntimeAgentClient()
    return LocalAgentClient()
