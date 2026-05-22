from __future__ import annotations

import os
import sys
from pathlib import Path

import vertexai

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent.runtime_entrypoint import root_agent


def required_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise SystemExit(f"Set {name}.")
    return value


def gcs_uri(value: str) -> str:
    return value if value.startswith("gs://") else f"gs://{value}"


def main() -> None:
    project_id = required_env("PROJECT_ID")
    location = os.getenv("AGENT_RUNTIME_LOCATION", "us-central1")
    display_name = os.getenv("AGENT_DISPLAY_NAME", "graphic-recording-agent")
    staging_bucket = gcs_uri(
        os.getenv("AGENT_RUNTIME_STAGING_BUCKET")
        or required_env("GCS_BUCKET")
    )
    requirements_file = os.getenv("AGENT_RUNTIME_REQUIREMENTS_FILE", "constraints-workshop.txt")

    client = vertexai.Client(project=project_id, location=location)
    remote_agent = client.agent_engines.create(
        agent=root_agent,
        config={
            "display_name": display_name,
            "description": "Graphic recording workshop ADK agent.",
            "staging_bucket": staging_bucket,
            "requirements": requirements_file,
            "extra_packages": ["agent"],
            "agent_framework": "google-adk",
            "env_vars": {
                "MOCK_MODE": "false",
                "GOOGLE_GENAI_USE_VERTEXAI": "true",
                "GOOGLE_CLOUD_LOCATION": os.getenv("GOOGLE_CLOUD_LOCATION", "global"),
                "GEMINI_TEXT_MODEL": os.getenv("GEMINI_TEXT_MODEL", "gemini-3.5-flash"),
                "GEMINI_IMAGE_MODEL": os.getenv(
                    "GEMINI_IMAGE_MODEL",
                    "gemini-3-pro-image-preview",
                ),
                "GCS_BUCKET": os.getenv("GCS_BUCKET", ""),
                "GCS_ARTIFACT_PREFIX": os.getenv("GCS_ARTIFACT_PREFIX", "artifacts"),
                "GCS_SIGNED_URL_TTL_SECONDS": os.getenv("GCS_SIGNED_URL_TTL_SECONDS", "28800"),
                "GCS_SIGNING_SERVICE_ACCOUNT": os.getenv("GCS_SIGNING_SERVICE_ACCOUNT", ""),
                "ARTICLE_FETCH_MAX_BYTES": os.getenv("ARTICLE_FETCH_MAX_BYTES", "2000000"),
                "GEMINI_MAX_ATTEMPTS": os.getenv("GEMINI_MAX_ATTEMPTS", "3"),
                "GEMINI_RETRY_BASE_DELAY_SECONDS": os.getenv(
                    "GEMINI_RETRY_BASE_DELAY_SECONDS",
                    "0.6",
                ),
            },
            "min_instances": 0,
            "max_instances": 1,
        },
    )
    print(remote_agent.api_resource.name)
    spec = remote_agent.api_resource.spec if remote_agent.api_resource else None
    effective_identity = getattr(spec, "effective_identity", None)
    if effective_identity:
        print(f"effective_identity={effective_identity}")


if __name__ == "__main__":
    main()
