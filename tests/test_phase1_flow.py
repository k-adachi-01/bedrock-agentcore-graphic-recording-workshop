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
    assert "現在の目安" in summary_job.text
    assert "Agent Runtime に要約 workflow を送信" in summary_job.text
    summary_job_id = _job_id(summary_job.text, "summary")

    summary = _poll_job(client, summary_job_id)
    assert "要約確認" in summary
    assert "3 行要約を編集" in summary
    assert 'data-summary-review' in summary
    assert 'hx-target="#graphic-stage"' in summary
    assert 'id="graphic-stage"' in summary
    assert "要約を修正して再生成" not in summary
    assert "Step 2 of 4" not in summary
    assert "Step 5-8" not in summary

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
    assert 'hx-swap-oob="true"' in graphic_job.text
    assert 'data-workflow-step="3"' in graphic_job.text
    assert "Step 3 of 4" not in graphic_job.text
    graphic_job_id = _job_id(graphic_job.text, "graphic")

    graphic = _poll_job(client, graphic_job_id)
    assert "グラレコ結果" in graphic
    assert 'data-workflow-step="4"' in graphic
    assert 'data-current-step="4"' in graphic
    assert 'hx-swap-oob="true"' in graphic
    assert 'aria-current="step"' in graphic
    assert "Step 4 of 4" not in graphic
    assert "Step 5-8" not in graphic
    assert "生成中..." not in graphic
    assert "生成完了" in graphic
    assert "生成画像" in graphic
    assert "生成情報" in graphic
    assert "<svg" in graphic
    assert "編集済み要約 1" in graphic
    assert "Agent style:" in graphic
    assert "判断理由:" in graphic

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


def test_fallback_svg_keeps_heading_and_summary_text_separate():
    from agent.tools import render_svg
    import asyncio

    svg = asyncio.run(
        render_svg(
            "Demo",
            [
                "Agent が記事取得から要約、画像生成までを一連の workflow として進めます。",
                "ADK では fetch / summarize / plan / render などの tool を分けて実装します。",
                "Phase 1 は mock mode と fallback SVG により、外部 API なしで確認します。",
            ],
            ["Web App は Agent Runtime 上の Agent を呼び出す境界を持つ"],
            ["中央に要約を配置"],
        )
    )

    assert 'y="180" class="label">3 Line Summary' in svg
    assert '<tspan x="78" y="212">' in svg
    assert 'class="summary"><tspan' in svg


def test_summary_lock_does_not_target_result_feedback_textarea():
    index = (Path(__file__).resolve().parents[1] / "web/templates/index.html").read_text()
    styles = (Path(__file__).resolve().parents[1] / "web/static/styles.css").read_text()

    assert 'return review.querySelectorAll(".summary-card-grid textarea");' in index
    assert 'review.querySelectorAll("textarea")' not in index
    assert '[data-summary-review][data-locked="true"] .summary-card-grid textarea' in styles
    assert '[data-summary-review][data-locked="true"] textarea' not in styles


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
    assert "ブログ記事を 1 枚のグラレコに" in authenticated_root.text


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


def test_runtime_backend_requires_resource_name(monkeypatch):
    monkeypatch.setenv("AGENT_BACKEND", "runtime")
    monkeypatch.delenv("AGENT_RUNTIME_RESOURCE_NAME", raising=False)

    from web.agent_client import build_agent_client
    import asyncio
    import pytest

    client = build_agent_client()
    with pytest.raises(RuntimeError, match="AGENT_RUNTIME_RESOURCE_NAME"):
        asyncio.run(client.summarize_url("https://example.com"))


def test_runtime_backend_rejects_placeholder_resource_name(monkeypatch):
    monkeypatch.setenv("AGENT_BACKEND", "runtime")
    monkeypatch.setenv(
        "AGENT_RUNTIME_RESOURCE_NAME",
        "projects/PROJECT_NUMBER/locations/us-central1/reasoningEngines/RESOURCE_ID",
    )

    from web.agent_client import build_agent_client
    import asyncio
    import pytest

    client = build_agent_client()
    with pytest.raises(RuntimeError, match="placeholder"):
        asyncio.run(client.summarize_url("https://example.com"))


def test_deploy_builds_use_workshop_constraints():
    root = Path(__file__).resolve().parents[1]
    dockerfile = (root / "Dockerfile").read_text(encoding="utf-8")
    deploy_script = (root / "scripts" / "deploy-agent-runtime.py").read_text(encoding="utf-8")

    assert "COPY requirements.txt constraints-workshop.txt" in dockerfile
    assert "pip install --no-cache-dir -r requirements.txt -c constraints-workshop.txt" in dockerfile
    assert '"constraints-workshop.txt"' in deploy_script
    assert '"requirements": requirements_file' in deploy_script


def test_user_facing_error_message_mapping():
    from web.main import _display_error

    model_error = _display_error(
        RuntimeError("Publisher Model projects/demo/locations/us-central1/models/gemini-3.5-flash was not found")
    )
    signed_url_error = _display_error(RuntimeError("signBlob permission denied"))
    empty_error = _display_error(AssertionError())

    assert "Gemini model が見つかりません" in model_error
    assert "技術詳細:" in model_error
    assert "signed URL 生成権限" in signed_url_error
    assert "AssertionError" in empty_error


def test_slow_job_message_after_threshold():
    from datetime import timedelta
    from web.main import AgentJob

    job = AgentJob(job_id="graphic-test", kind="graphic", title="生成中")
    job.started_at = job.started_at - timedelta(seconds=241)

    assert job.is_slow is True
    assert "Agent Runtime logs" in job.slow_message


def test_runtime_contract_round_trip():
    from agent.models import ProgressStep, SummaryResult
    from agent.runtime_contract import RuntimeSummaryPayload, RuntimeWorkflowResponse

    summary = SummaryResult(
        session_id="session-1",
        url="https://example.com",
        title="Demo",
        summary_lines=["a", "b", "c"],
        key_points=["p1", "p2", "p3", "p4"],
        article_text="body",
        text_backend="gemini:test",
        progress=[ProgressStep("done", "done", "ok")],
    )

    response = RuntimeWorkflowResponse(
        operation="summarize_url",
        summary=RuntimeSummaryPayload.from_result(summary),
    )
    restored = RuntimeWorkflowResponse.model_validate_json(response.model_dump_json())

    assert restored.summary is not None
    assert restored.summary.to_result().title == "Demo"
    assert restored.summary.to_result().progress[0].detail == "ok"


def test_runtime_client_parses_function_response_event():
    from web.agent_client import _runtime_response_from_event

    event = {
        "content": {
            "parts": [
                {
                    "function_response": {
                        "name": "runtime_summarize_url",
                        "response": {
                            "operation": "summarize_url",
                            "summary": {
                                "session_id": "s1",
                                "url": "https://example.com",
                                "title": "Title",
                                "summary_lines": ["a", "b", "c"],
                                "key_points": ["p1", "p2", "p3", "p4"],
                                "article_text": "body",
                                "text_backend": "runtime",
                                "progress": [],
                            },
                        },
                    }
                }
            ]
        }
    }

    response = _runtime_response_from_event(event)

    assert response is not None
    assert response.operation == "summarize_url"
    assert response.summary is not None
    assert response.summary.title == "Title"


def test_article_fetch_size_limit_helpers(monkeypatch):
    monkeypatch.setenv("ARTICLE_FETCH_MAX_BYTES", "4096")

    from agent.tools import article_fetch_max_bytes, signed_artifact_url_ttl_seconds

    assert article_fetch_max_bytes() == 4096

    monkeypatch.setenv("ARTICLE_FETCH_MAX_BYTES", "not-a-number")
    assert article_fetch_max_bytes() == 2_000_000

    monkeypatch.setenv("GCS_SIGNED_URL_TTL_SECONDS", "120")
    assert signed_artifact_url_ttl_seconds() == 120

    monkeypatch.setenv("GCS_SIGNED_URL_TTL_SECONDS", "bad")
    assert signed_artifact_url_ttl_seconds() == 28800


def test_signed_url_credentials_uses_explicit_signing_service_account(monkeypatch):
    from agent import tools

    class Credentials:
        token = "token"

        def refresh(self, _request):
            self.token = "fresh-token"

    monkeypatch.setenv("GCS_SIGNING_SERVICE_ACCOUNT", "runtime@example.iam.gserviceaccount.com")
    monkeypatch.setattr(tools, "google_auth_default_for_test", None, raising=False)

    import google.auth

    monkeypatch.setattr(google.auth, "default", lambda scopes: (Credentials(), "project"))

    credentials, service_account_email = tools._signed_url_credentials()

    assert credentials.token == "fresh-token"
    assert service_account_email == "runtime@example.iam.gserviceaccount.com"


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
