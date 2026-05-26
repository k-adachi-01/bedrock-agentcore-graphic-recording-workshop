from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def required_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise SystemExit(f"Set {name}.")
    return value


def reject_placeholder(name: str, value: str) -> None:
    if any(token in value for token in ("CHANGE_ME", "PASTE_HERE", "YOUR_", "ACCOUNT_ID")):
        raise SystemExit(f"{name} still contains a placeholder: {value}")


def prepare_runtime_requirements_file(source: str, output_dir: str | Path) -> str:
    destination = Path(output_dir) / "requirements-runtime.txt"
    lines = []
    for raw_line in Path(source).read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if line and not line.startswith("#"):
            lines.append(line)
    destination.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return str(destination)


def main() -> int:
    runtime_name = os.getenv("AGENTCORE_RUNTIME_NAME", "GraphicRecordingAgent")
    s3_bucket = required_env("S3_BUCKET")
    reject_placeholder("S3_BUCKET", s3_bucket)

    prepare_runtime_requirements_file(str(ROOT / "constraints-workshop.txt"), ROOT / "artifacts")

    if not (ROOT / "agentcore" / "agentcore.json").is_file():
        raise SystemExit(
            "AgentCore project metadata is missing. Initialize it first with:\n"
            f"  pnpm exec agentcore create --name {runtime_name} --framework Strands "
            "--protocol HTTP --model-provider Bedrock --memory none\n"
            "Then copy or point the generated agent app to agent/agentcore_entrypoint.py "
            "and rerun this script."
        )

    env = os.environ.copy()
    env.setdefault("BEDROCK_TEXT_MODEL_ID", "us.anthropic.claude-sonnet-4-20250514-v1:0")
    env.setdefault("S3_ARTIFACT_PREFIX", "artifacts")
    env.setdefault("S3_PRESIGNED_URL_TTL_SECONDS", "28800")

    command = ["pnpm", "exec", "agentcore", "deploy", "-y"]
    subprocess.run(command, cwd=ROOT, env=env, check=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
