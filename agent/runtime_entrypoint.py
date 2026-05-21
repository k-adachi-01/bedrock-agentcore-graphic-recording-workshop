from __future__ import annotations

from vertexai.agent_engines import AdkApp

from agent.adk_agent import build_graphic_recording_agent


root_agent = AdkApp(agent=build_graphic_recording_agent())
