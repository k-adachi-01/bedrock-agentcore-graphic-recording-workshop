from __future__ import annotations

import os

from google.cloud.aiplatform import vertexai

from agent.runtime_entrypoint import root_agent


def required_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise SystemExit(f"Set {name}.")
    return value


def main() -> None:
    project_id = required_env("PROJECT_ID")
    location = os.getenv("AGENT_RUNTIME_LOCATION", "us-central1")
    display_name = os.getenv("AGENT_DISPLAY_NAME", "graphic-recording-agent")

    client = vertexai.Client(project=project_id, location=location)
    remote_agent = client.agent_engines.create(
        agent=root_agent,
        config={
            "display_name": display_name,
            "description": "Graphic recording workshop ADK agent.",
            "requirements": "requirements.txt",
            "extra_packages": ["agent"],
            "agent_framework": "google-adk",
            "env_vars": {
                "MOCK_MODE": "false",
                "GOOGLE_GENAI_USE_VERTEXAI": "true",
                "GEMINI_TEXT_MODEL": os.getenv("GEMINI_TEXT_MODEL", "gemini-2.5-flash"),
                "GEMINI_IMAGE_MODEL": os.getenv(
                    "GEMINI_IMAGE_MODEL",
                    "gemini-3-pro-image-preview",
                ),
            },
            "min_instances": 0,
            "max_instances": 1,
        },
    )
    print(remote_agent.api_resource.name)


if __name__ == "__main__":
    main()
