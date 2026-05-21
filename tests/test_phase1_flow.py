import os
import sys
from pathlib import Path

from fastapi.testclient import TestClient

os.environ["MOCK_MODE"] = "true"
os.environ["AGENT_BACKEND"] = "local"
os.environ["MOCK_STEP_DELAY"] = "0"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from web.main import app  # noqa: E402


def test_phase1_url_to_svg_regeneration_flow():
    client = TestClient(app)

    root = client.get("/")
    assert root.status_code == 200

    summary_job = client.post("/summaries", data={"url": "https://example.com/blog/demo"})
    assert summary_job.status_code == 200
    summary_job_id = _job_id(summary_job.text, "summary")

    summary = _poll_job(client, summary_job_id)
    assert "要約確認" in summary
    assert "3 行要約を編集" in summary

    session_id = summary.split('name="session_id" value="', 1)[1].split('"', 1)[0]
    graphic_job = client.post(
        "/graphics",
        data={
            "session_id": session_id,
            "summary_text": "編集済み要約 1\n編集済み要約 2\n編集済み要約 3",
            "key_points_text": "編集済みポイント A\n編集済みポイント B",
        },
    )
    assert graphic_job.status_code == 200
    graphic_job_id = _job_id(graphic_job.text, "graphic")

    graphic = _poll_job(client, graphic_job_id)
    assert "グラレコ結果" in graphic
    assert "<svg" in graphic
    assert "編集済み要約 1" in graphic
    assert "Agent decision:" in graphic

    regen_job = client.post(
        "/graphics/regenerate",
        data={"session_id": session_id, "feedback": "業務フローを強調"},
    )
    assert regen_job.status_code == 200
    regen_job_id = _job_id(regen_job.text, "graphic")

    regenerated = _poll_job(client, regen_job_id)
    assert "Feedback:" in regenerated
    assert "<svg" in regenerated


def test_real_fetch_rejects_localhost_when_mock_disabled(monkeypatch):
    monkeypatch.setenv("MOCK_MODE", "false")

    from agent.tools import _assert_public_http_url
    import asyncio
    import pytest

    with pytest.raises(ValueError):
        asyncio.run(_assert_public_http_url("http://127.0.0.1:8000"))


def test_non_mock_text_tools_fallback_without_gemini_credentials(monkeypatch):
    monkeypatch.setenv("MOCK_MODE", "false")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_GENAI_USE_VERTEXAI", raising=False)

    from agent.tools import create_visual_plan, summarize_article
    import asyncio

    summary = asyncio.run(
        summarize_article("Demo", "First. Second. Third. Fourth. Fifth. Sixth.")
    )
    plan = asyncio.run(create_visual_plan(summary["summary_lines"], summary["key_points"]))

    assert summary["summary_lines"] == ["First.", "Second.", "Third."]
    assert summary["backend"].startswith("heuristic")
    assert len(plan) >= 4


def test_style_decision_affects_plan_in_mock(monkeypatch):
    monkeypatch.setenv("MOCK_MODE", "true")

    from agent.tools import create_visual_plan_for_style, decide_style
    import asyncio

    decision = asyncio.run(decide_style(["一般読者向けの記事です"], ["note 読者に届ける"]))
    plan = asyncio.run(create_visual_plan_for_style(["a"], ["b"], style=decision.style))

    assert decision.style == "pop"
    assert any("明るい" in item or "カラフル" in item for item in plan)


def test_gemini_vertex_credentials_detection(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.setenv("GOOGLE_GENAI_USE_VERTEXAI", "true")
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "demo-project")
    monkeypatch.setenv("GOOGLE_CLOUD_LOCATION", "global")

    from agent.tools import has_gemini_credentials

    assert has_gemini_credentials() is True


def test_image_artifact_helpers():
    from agent.tools import (
        _extension_for_mime_type,
        _render_image_svg,
        artifact_url_for_path,
        display_model_name,
    )

    svg = _render_image_svg(b"abc", "image/png")

    assert "data:image/png;base64,YWJj" in svg
    assert _extension_for_mime_type("image/png") == ".png"
    assert artifact_url_for_path("/tmp/custom-artifacts/abc.png") == "/artifacts/abc.png"
    assert display_model_name("gemini-2.5-flash-image").endswith("(Nano Banana)")
    assert display_model_name("gemini-3-pro-image-preview").endswith("(Nano Banana Pro)")


def test_adk_backend_adds_narration_progress(monkeypatch):
    monkeypatch.setenv("MOCK_MODE", "true")
    monkeypatch.setenv("MOCK_STEP_DELAY", "0")

    from web.agent_client import AdkAgentClient
    import asyncio

    summary = asyncio.run(AdkAgentClient().summarize_url("https://example.com/adk-demo"))

    assert summary.progress[0].label == "ADK LlmAgent が summarize_url action を解説"
    assert summary.progress[0].detail == "adk:dry-run:mock-mode"


def test_password_auth_redirects_and_allows_login(monkeypatch):
    monkeypatch.setenv("APP_PASSWORD", "demo-password")
    monkeypatch.setenv("APP_SECRET_KEY", "test-secret")

    client = TestClient(app, follow_redirects=False)

    root = client.get("/")
    assert root.status_code == 303
    assert root.headers["location"] == "/login?next=/"

    blocked_post = client.post("/summaries", data={"url": "https://example.com"})
    assert blocked_post.status_code == 401
    assert blocked_post.headers["hx-redirect"] == "/login"

    bad_login = client.post(
        "/login",
        data={"password": "wrong", "next_path": "/"},
    )
    assert bad_login.status_code == 401

    good_login = client.post(
        "/login",
        data={"password": "demo-password", "next_path": "/"},
    )
    assert good_login.status_code == 303
    assert "gea_workshop_auth" in good_login.headers["set-cookie"]

    authenticated_root = client.get("/")
    assert authenticated_root.status_code == 200
    assert "Blog URL to Graphic Recording" in authenticated_root.text


def test_production_requires_app_password(monkeypatch):
    monkeypatch.delenv("APP_PASSWORD", raising=False)
    monkeypatch.delenv("APP_SECRET_KEY", raising=False)
    monkeypatch.setenv("K_SERVICE", "cloud-run-service")

    from web.auth import assert_auth_config
    import pytest

    with pytest.raises(RuntimeError):
        assert_auth_config()

    monkeypatch.setenv("APP_PASSWORD", "demo-password")
    with pytest.raises(RuntimeError, match="APP_SECRET_KEY"):
        assert_auth_config()

    monkeypatch.setenv("APP_SECRET_KEY", "test-secret")
    assert_auth_config()


def test_runtime_backend_fails_fast(monkeypatch):
    monkeypatch.setenv("AGENT_BACKEND", "runtime")

    from web.agent_client import build_agent_client
    import asyncio
    import pytest

    client = build_agent_client()
    with pytest.raises(RuntimeError, match="AGENT_BACKEND=runtime is not wired yet"):
        asyncio.run(client.summarize_url("https://example.com"))


def test_article_fetch_size_limit_helpers(monkeypatch):
    monkeypatch.setenv("ARTICLE_FETCH_MAX_BYTES", "4096")

    from agent.tools import article_fetch_max_bytes

    assert article_fetch_max_bytes() == 4096

    monkeypatch.setenv("ARTICLE_FETCH_MAX_BYTES", "not-a-number")
    assert article_fetch_max_bytes() == 2_000_000


def test_read_limited_response_rejects_oversized_body():
    from agent.tools import _read_limited_response
    import asyncio
    import pytest

    class Response:
        async def aiter_raw(self):
            yield b"abc"
            yield b"def"

    with pytest.raises(ValueError, match="exceeds 5 bytes"):
        asyncio.run(_read_limited_response(Response(), 5))


def test_invalid_content_encoding_falls_back_to_raw_body():
    from agent.tools import _decode_response_content
    import httpx

    body = b"<html><title>Plain HTML</title></html>"
    decoded = _decode_response_content(body, httpx.Headers({"content-encoding": "gzip"}))

    assert decoded == body


def test_retryable_exception_detection():
    from agent.tools import _is_retryable_exception

    class RetryableError(Exception):
        status_code = 429

    class FatalError(Exception):
        status_code = 400

    assert _is_retryable_exception(RetryableError("quota")) is True
    assert _is_retryable_exception(FatalError("bad request")) is False


def test_call_with_retries_succeeds_after_retry(monkeypatch):
    from agent import tools
    import asyncio

    class RetryableError(Exception):
        status_code = 503

    async def no_sleep(_delay):
        return None

    monkeypatch.setattr(tools.asyncio, "sleep", no_sleep)

    attempts = {"count": 0}

    async def operation():
        attempts["count"] += 1
        if attempts["count"] == 1:
            raise RetryableError("temporarily unavailable")
        return "ok"

    result = asyncio.run(tools._call_with_retries(lambda: operation(), "test-op"))

    assert result == "ok"
    assert attempts["count"] == 2


def test_call_with_retries_stops_on_fatal_error():
    from agent import tools
    import asyncio
    import pytest

    class FatalError(Exception):
        status_code = 400

    attempts = {"count": 0}

    async def operation():
        attempts["count"] += 1
        raise FatalError("bad request")

    with pytest.raises(FatalError):
        asyncio.run(tools._call_with_retries(lambda: operation(), "test-op"))

    assert attempts["count"] == 1


def _job_id(html: str, prefix: str) -> str:
    marker = f'id="{prefix}-'
    return prefix + "-" + html.split(marker, 1)[1].split('"', 1)[0]


def _poll_job(client: TestClient, job_id: str) -> str:
    for _ in range(20):
        response = client.get(f"/jobs/{job_id}")
        assert response.status_code == 200
        if f'id="{job_id}"' not in response.text:
            return response.text
    raise AssertionError(f"job did not finish: {job_id}")
