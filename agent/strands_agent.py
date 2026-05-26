from __future__ import annotations

import json
import os
from typing import Any, Optional

from . import runtime_workflows, tools
from .runtime_contract import RuntimeWorkflowResponse


GRAPHIC_RECORDING_AGENT_INSTRUCTION = """
You are a graphic recording agent for a Strands Agents and Amazon Bedrock AgentCore workshop demo.

Use the available tools to complete the workflow:
1. fetch_article retrieves public article text from a URL.
2. summarize_article creates a concise Japanese three-line summary and key points.
3. create_visual_plan turns the summary into a graphic recording composition.
4. generate_image attempts Bedrock image generation and returns SVG-compatible markup when available.
5. render_svg is the readable fallback when image generation is unavailable.
6. save_artifact stores the generated artifact.

Return concise progress-friendly outputs and fall back to SVG if the image model is unavailable.
"""

NARRATOR_INSTRUCTION = """
You are a Strands narrator agent for a Bedrock AgentCore workshop demo.

Briefly explain which action/tool phase the application will run next and why:
- summarize_url: fetch_article, then summarize_article.
- generate_graphic_recording: create_visual_plan, then generate_image_artifact, then save artifact.
- regenerate_graphic_recording: apply feedback, then regenerate the visual plan and artifact.

Return one short Japanese sentence. Do not use markdown.
"""


def build_graphic_recording_agent(model: Optional[str] = None) -> Any:
    """Build a Strands tools agent for the graphic recording workflow."""
    try:
        from strands import Agent
        from strands.models import BedrockModel
    except ImportError as exc:
        raise RuntimeError(
            "strands-agents is not installed. Install workshop dependencies before using Strands."
        ) from exc

    bedrock_model = BedrockModel(
        model_id=model or tools.text_model_name(),
        region_name=os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION") or "us-east-1",
    )
    return Agent(
        model=bedrock_model,
        system_prompt=GRAPHIC_RECORDING_AGENT_INSTRUCTION,
        tools=[
            tools.fetch_article,
            tools.summarize_article,
            tools.create_visual_plan,
            tools.generate_image,
            tools.render_svg,
            tools.save_artifact,
        ],
    )


async def dispatch_agentcore_payload(payload: dict[str, Any]) -> RuntimeWorkflowResponse:
    """Dispatch the AgentCore JSON request through the stable runtime contract."""
    return await runtime_workflows.dispatch_runtime_operation(payload)


def runtime_payload_from_event(event: Any) -> dict[str, Any]:
    """Parse an AgentCore event payload into the runtime operation JSON."""
    if isinstance(event, dict):
        if isinstance(event.get("payload"), dict):
            return event["payload"]
        if isinstance(event.get("body"), str):
            parsed = json.loads(event["body"])
            if isinstance(parsed, dict):
                return parsed
        return event
    if isinstance(event, str):
        parsed = json.loads(event)
        if isinstance(parsed, dict):
            return parsed
    raise ValueError("AgentCore request must be a JSON object")


async def run_narration_turn(prompt: str, session_id: str, user_id: str = "demo-user") -> str:
    """Run a compact Strands narration turn for progress UI."""
    if tools.is_mock_mode():
        return "strands:dry-run:mock-mode"
    if not tools.has_bedrock_credentials():
        return "strands:dry-run:no-bedrock-credentials"

    try:
        from strands import Agent
        from strands.models import BedrockModel
    except ImportError as exc:
        return f"strands:fallback:{str(exc)[:80]}"

    model_name = tools.text_model_name()
    bedrock_model = BedrockModel(
        model_id=model_name,
        region_name=os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION") or "us-east-1",
    )
    agent = Agent(model=bedrock_model, system_prompt=NARRATOR_INSTRUCTION)
    try:
        result = agent(prompt)
    except Exception as exc:
        return f"strands:fallback:{str(exc)[:120]}"
    text = str(result).strip()
    if text:
        return f"strands:{model_name}:{text[:80]}"
    return f"strands:{model_name}:{user_id}:{session_id[:8]}"
