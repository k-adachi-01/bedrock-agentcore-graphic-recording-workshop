from __future__ import annotations

import os
from typing import Any, Optional

from . import tools


GRAPHIC_RECORDING_AGENT_INSTRUCTION = """
You are a graphic recording agent for a workshop demo.

Use the available tools to complete the workflow:
1. fetch_article retrieves article text from a URL.
2. summarize_article creates a concise three-line summary and key points.
3. create_visual_plan turns the summary into a graphic recording composition.
4. generate_image attempts image generation.
5. render_svg is the fallback when image generation is unavailable or fails.
6. save_artifact stores the generated artifact.

Always keep the user in the loop: produce concise progress-friendly outputs and
fall back to SVG if the image model is unavailable.
"""


def build_graphic_recording_agent(model: Optional[str] = None) -> Any:
    """Build the Google ADK LlmAgent used by later phases.

    The web app still uses the deterministic local workflow in Phase 1. This
    factory is intentionally isolated so installing google-adk remains optional.
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
        model=model or os.getenv("GEMINI_TEXT_MODEL", "gemini-flash-latest"),
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
