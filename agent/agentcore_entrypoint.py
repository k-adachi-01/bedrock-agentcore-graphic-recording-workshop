from __future__ import annotations

from agent.runtime_contract import RuntimeWorkflowResponse
from agent.strands_agent import dispatch_agentcore_payload, runtime_payload_from_event

try:
    from bedrock_agentcore.runtime import BedrockAgentCoreApp
except ImportError:
    BedrockAgentCoreApp = None


if BedrockAgentCoreApp is None:
    app = None
else:
    app = BedrockAgentCoreApp()


async def invoke(event):
    payload = {}
    try:
        payload = runtime_payload_from_event(event)
        response = await dispatch_agentcore_payload(payload)
    except Exception as exc:
        response = RuntimeWorkflowResponse(
            operation=payload.get("operation", "unknown") if isinstance(payload, dict) else "unknown",
            error=f"{type(exc).__name__}: {exc}",
        )
    return response.model_dump(mode="json")


if app is not None:
    app.entrypoint(invoke)
