from __future__ import annotations

import os
from typing import Any, Optional

from . import tools
from . import runtime_workflows


GRAPHIC_RECORDING_AGENT_INSTRUCTION = """
You are a graphic recording agent for a Gemini Enterprise Agent Platform workshop demo.

Use the available tools to complete the workflow:
1. fetch_article retrieves public article text from a URL.
2. summarize_article creates a concise Japanese three-line summary and key points.
3. create_visual_plan turns the summary into a graphic recording composition.
4. generate_image attempts Nano Banana Pro image generation and returns SVG-compatible markup when available.
5. render_svg is the readable fallback when image generation is unavailable or low quality.
6. save_artifact stores the generated SVG artifact.

Always keep the user in the loop: produce concise progress-friendly outputs and
fall back to SVG if the image model is unavailable.
"""

ORCHESTRATOR_INSTRUCTION = """
You are an ADK narrator agent for a Gemini Enterprise Agent Platform workshop demo.

Your job is not to perform the whole workflow yourself. Instead, briefly explain
which action/tool phase the application will run next and why:
- summarize_url: fetch_article, then summarize_article.
- generate_graphic_recording: create_visual_plan, then generate_image_artifact, then save artifact.
- regenerate_graphic_recording: apply feedback, then regenerate the visual plan and artifact.

Return one short Japanese sentence. Do not use markdown.
"""

RUNTIME_WORKFLOW_INSTRUCTION = """
You are the Agent Runtime workflow boundary for a workshop web app.

The user message is JSON with one operation:
- summarize_url: call runtime_summarize_url with the URL.
- generate_graphic: call runtime_generate_graphic with the summary payload.
- regenerate_graphic: call runtime_regenerate_graphic with the summary payload and feedback.

Call exactly one matching tool. Do not invent fields. After the tool returns,
return the tool response JSON only.
"""


def build_graphic_recording_agent(model: Optional[str] = None) -> Any:
    """Build the tools-enabled Google ADK LlmAgent planned for the next phase.

    This agent is intentionally not connected to the web flow yet. The current
    `AGENT_BACKEND=adk` path uses `build_narrator_agent` to demonstrate ADK
    Runner execution while preserving the deterministic action/tool pipeline.
    The next phase can wire this tools-enabled agent into the workflow once the
    tool docstrings and model behavior are tuned.
    """
    try:
        from google.adk.agents import LlmAgent
    except ImportError as exc:
        raise RuntimeError(
            "google-adk is not installed. Install the optional ADK dependency "
            "before using the ADK agent."
        ) from exc

    return LlmAgent(
        name="graphic_recording_agent",
        model=model or os.getenv("GEMINI_TEXT_MODEL", "gemini-3.5-flash"),
        description="Summarizes blog URLs and creates graphic recording artifacts.",
        instruction=GRAPHIC_RECORDING_AGENT_INSTRUCTION,
        tools=[
            tools.fetch_article,
            tools.summarize_article,
            tools.create_visual_plan,
            tools.generate_image,
            tools.render_svg,
            tools.save_artifact,
        ],
    )


def build_narrator_agent(model: Optional[str] = None) -> Any:
    """Build a small ADK LlmAgent used by the web app to show ADK execution."""
    try:
        from google.adk.agents import LlmAgent
    except ImportError as exc:
        raise RuntimeError(
            "google-adk is not installed. Install google-adk before using AGENT_BACKEND=adk."
        ) from exc

    return LlmAgent(
        name="graphic_recording_narrator",
        model=model or os.getenv("GEMINI_TEXT_MODEL", "gemini-3.5-flash"),
        description="Explains the next action in the graphic recording workflow.",
        instruction=ORCHESTRATOR_INSTRUCTION,
    )


def build_runtime_workflow_agent(model: Optional[str] = None) -> Any:
    """Build the ADK agent deployed to Agent Runtime for the web backend."""
    try:
        from google.adk.agents import LlmAgent
    except ImportError as exc:
        raise RuntimeError(
            "google-adk is not installed. Install google-adk before deploying Agent Runtime."
        ) from exc

    return LlmAgent(
        name="graphic_recording_runtime_workflow",
        model=model or os.getenv("GEMINI_TEXT_MODEL", "gemini-3.5-flash"),
        description="Runs the graphic recording workflow and returns the JSON contract.",
        instruction=RUNTIME_WORKFLOW_INSTRUCTION,
        tools=[
            runtime_workflows.runtime_summarize_url,
            runtime_workflows.runtime_generate_graphic,
            runtime_workflows.runtime_regenerate_graphic,
        ],
    )


async def run_narration_turn(prompt: str, session_id: str, user_id: str = "demo-user") -> str:
    """Run one ADK Runner turn and return a compact backend label for progress UI."""
    if tools.is_mock_mode():
        return "adk:dry-run:mock-mode"
    if not tools.has_gemini_credentials():
        return "adk:dry-run:no-gemini-credentials"

    from google.adk.runners import Runner
    from google.adk.sessions import InMemorySessionService
    from google.genai import types

    app_name = "graphic_recording_demo"
    session_service = InMemorySessionService()
    await session_service.create_session(
        app_name=app_name,
        user_id=user_id,
        session_id=session_id,
    )
    runner = Runner(
        agent=build_narrator_agent(),
        app_name=app_name,
        session_service=session_service,
    )

    content = types.Content(role="user", parts=[types.Part(text=prompt)])
    final_text = ""
    async for event in runner.run_async(
        user_id=user_id,
        session_id=session_id,
        new_message=content,
    ):
        if event.is_final_response() and event.content and event.content.parts:
            final_text = event.content.parts[0].text or ""

    model = os.getenv("GEMINI_TEXT_MODEL", "gemini-3.5-flash")
    if final_text:
        return f"adk:{model}:{final_text[:80]}"
    return f"adk:{model}"
