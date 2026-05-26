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
    assert "AgentCore Runtime に要約 workflow を送信" in summary_job.text
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
    assert "画像を保存" in graphic
    assert f'href="/graphics/{session_id}/download"' in graphic
    assert "画像を開く" not in graphic
    assert "画像を開いて保存" not in graphic
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
    assert "Feedback:" not in regenerated
    assert "Agent Flow" not in regenerated
    assert "Visual Plan" not in regenerated
    assert "<svg" in regenerated


def test_real_fetch_rejects_localhost_when_mock_disabled(monkeypatch):
    monkeypatch.setenv("MOCK_MODE", "false")

    from agent.tools import _assert_public_http_url
    import asyncio
    import pytest

    with pytest.raises(ValueError):
        asyncio.run(_assert_public_http_url("http://127.0.0.1:8000"))


def test_non_mock_text_tools_fallback_without_bedrock_credentials(monkeypatch):
    monkeypatch.setenv("MOCK_MODE", "false")
    monkeypatch.delenv("AWS_ACCESS_KEY_ID", raising=False)
    monkeypatch.delenv("AWS_SECRET_ACCESS_KEY", raising=False)
    monkeypatch.delenv("AWS_PROFILE", raising=False)

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


def test_bedrock_credentials_detection(monkeypatch):
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "access")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "secret")

    from agent.tools import has_bedrock_credentials

    assert has_bedrock_credentials() is True


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
    assert display_model_name("amazon.nova-canvas-v1:0").endswith("(Nova Canvas)")


def test_fallback_svg_keeps_heading_and_summary_text_separate():
    from agent.tools import render_svg
    import asyncio

    svg = asyncio.run(
        render_svg(
            "Demo",
            [
                "Agent が記事取得から要約、画像生成までを一連の workflow として進めます。",
                "Strands では fetch / summarize / plan / render などの tool を分けて実装します。",
                "Phase 1 は mock mode と fallback SVG により、外部 API なしで確認します。",
            ],
            ["Web App は AgentCore Runtime 上の Agent を呼び出す境界を持つ"],
            ["中央に要約を配置"],
        )
    )

    assert 'y="180" class="label">3行要約' in svg
    assert '<tspan x="78" y="224">' in svg
    assert 'class="summary"><tspan' in svg
    assert "Agent Flow" not in svg
    assert "Visual Plan" not in svg
    assert "Demo..." not in svg


def test_graphic_prompt_excludes_workshop_runtime_scaffolding(monkeypatch):
    from agent import tools
    import asyncio

    captured = {}

    async def fake_generate_image_data(prompt: str):
        captured["prompt"] = prompt
        return b"png", "image/png"

    monkeypatch.setenv("MOCK_MODE", "false")
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "access")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "secret")
    monkeypatch.setenv("BEDROCK_IMAGE_MODEL_ID", "amazon.nova-canvas-v1:0")
    monkeypatch.setattr(tools, "_generate_image_data", fake_generate_image_data)

    image = asyncio.run(
        tools.generate_image_artifact(
            ["中央に3行要約、右側に重要ポイントを配置"],
            style="business",
            summary_lines=["要約1", "要約2", "要約3"],
            key_points=["ポイント1", "ポイント2"],
        )
    )

    assert image.data == b"png"
    assert "要約1" in captured["prompt"]
    assert "ポイント1" in captured["prompt"]
    for forbidden in ["勉強会", "デモ", "URL取得", "AgentCore Runtime", "Strands", "App Runner", "S3", "Visual Plan"]:
        assert forbidden not in captured["prompt"]


def test_svg_text_wrap_only_adds_ellipsis_when_truncated():
    from agent.tools import _wrap_svg_text

    assert _wrap_svg_text("Demo", max_chars=34, max_lines=2) == ["Demo"]
    assert _wrap_svg_text("短いタイトル", max_chars=34, max_lines=2) == ["短いタイトル"]
    assert _wrap_svg_text("あ" * 40, max_chars=29, max_lines=2) == [
        "あ" * 29,
        "あ" * 11,
    ]
    assert _wrap_svg_text("あ" * 80, max_chars=15, max_lines=3)[-1].endswith("...")


def test_fallback_svg_wraps_dense_japanese_text():
    from agent.tools import _wrap_svg_text, render_svg
    import asyncio
    import html
    import re

    wrapped = _wrap_svg_text("あ" * 80, max_chars=15, max_lines=3)

    assert len(wrapped) == 3
    assert all(len(line) <= 18 for line in wrapped)
    assert wrapped[-1].endswith("...")

    svg = asyncio.run(
        render_svg(
            "とても長いタイトルのブログ記事を AgentCore Runtime でグラレコに変換するデモ",
            ["あ" * 80, "い" * 80, "う" * 80],
            ["え" * 80, "お" * 80, "か" * 80, "き" * 80],
            ["く" * 90, "け" * 90, "こ" * 90],
        )
    )
    key_point_lines = [
        html.unescape(match)
        for match in re.findall(r'<tspan x="808" y="[^"]+">([^<]+)</tspan>', svg)
    ]

    assert 'class="title"><tspan' in svg
    assert key_point_lines
    assert all(len(line) <= 16 for line in key_point_lines)


def test_summary_lock_does_not_target_result_feedback_textarea():
    index = (Path(__file__).resolve().parents[1] / "web/templates/index.html").read_text()
    styles = (Path(__file__).resolve().parents[1] / "web/static/styles.css").read_text()

    assert 'return review.querySelectorAll(".summary-card-grid textarea");' in index
    assert 'review.querySelectorAll("textarea")' not in index
    assert '[data-summary-review][data-locked="true"] .summary-card-grid textarea' in styles
    assert '[data-summary-review][data-locked="true"] textarea' not in styles


def test_graphic_failure_unlocks_summary_review_and_preserves_stage_until_swap():
    index = (Path(__file__).resolve().parents[1] / "web/templates/index.html").read_text()
    job = (Path(__file__).resolve().parents[1] / "web/templates/partials/job.html").read_text()
    graphic = (Path(__file__).resolve().parents[1] / "web/templates/partials/graphic.html").read_text()

    assert 'data-workflow-status="{{ job.status }}"' in job
    assert 'data-workflow-status="done"' in graphic
    assert 'updatedStep.dataset.workflowStatus === "failed"' in index
    assert "unlockSummaryReview(review);" in index
    assert "stage.innerHTML" not in index
    assert "data-graphic-workflow" in graphic


def test_job_polling_and_swap_animation_are_calm():
    job = (Path(__file__).resolve().parents[1] / "web/templates/partials/job.html").read_text()
    job_content = (Path(__file__).resolve().parents[1] / "web/templates/partials/job_content.html").read_text()
    styles = (Path(__file__).resolve().parents[1] / "web/static/styles.css").read_text()

    assert 'hx-trigger="every 2s"' in job
    assert 'hx-target="#{{ job.job_id }}-content"' in job
    assert 'hx-swap="innerHTML"' in job
    assert 'id="{{ job.job_id }}-content"' in job
    assert 'every 600ms' not in job
    assert 'job.kind == "summary"' in job_content
    assert "#graphic-stage > section" in styles
    assert "@keyframes fade-in" in styles
    assert "form.htmx-request button" in styles


def test_job_polling_updates_inner_content_until_terminal_swap():
    from web.main import AgentJob, jobs

    client = TestClient(app)
    job = AgentJob(job_id="summary-test-poll", kind="summary", title="要約中")
    jobs[job.job_id] = job
    try:
        running = client.get(
            f"/jobs/{job.job_id}",
            headers={"HX-Request": "true", "HX-Target": f"{job.job_id}-content"},
        )
        assert running.status_code == 200
        assert f'id="{job.job_id}"' not in running.text
        assert "Agent 処理中" in running.text

        job.status = "failed"
        job.error = "boom"
        failed = client.get(
            f"/jobs/{job.job_id}",
            headers={"HX-Request": "true", "HX-Target": f"{job.job_id}-content"},
        )
        assert failed.status_code == 200
        assert failed.headers["HX-Retarget"] == f"#{job.job_id}"
        assert failed.headers["HX-Reswap"] == "outerHTML"
        assert f'id="{job.job_id}"' in failed.text
    finally:
        jobs.pop(job.job_id, None)


def test_graphic_download_uses_attachment_response(tmp_path):
    from agent.models import GraphicResult
    from web.main import graphics

    artifact = tmp_path / "session-download.png"
    artifact.write_bytes(b"png-data")
    graphic = GraphicResult(
        session_id="session-download",
        visual_plan=[],
        artifact_path=str(artifact),
        artifact_mime_type="image/png",
    )
    graphics[graphic.session_id] = graphic
    client = TestClient(app)

    try:
        response = client.get(f"/graphics/{graphic.session_id}/download")
    finally:
        graphics.pop(graphic.session_id, None)

    assert response.status_code == 200
    assert response.content == b"png-data"
    assert response.headers["content-type"] == "image/png"
    assert "attachment" in response.headers["content-disposition"]
    assert "graphic-recording-session-" in response.headers["content-disposition"]


def test_strands_backend_adds_narration_progress(monkeypatch):
    monkeypatch.setenv("MOCK_MODE", "true")
    monkeypatch.setenv("MOCK_STEP_DELAY", "0")

    from web.agent_client import StrandsAgentClient
    import asyncio

    summary = asyncio.run(StrandsAgentClient().summarize_url("https://example.com/strands-demo"))

    assert summary.progress[0].label == "Strands Agent が summarize_url action を解説"
    assert summary.progress[0].detail == "strands:dry-run:mock-mode"


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
    monkeypatch.delenv("AGENTCORE_RUNTIME_ARN", raising=False)

    from web.agent_client import build_agent_client
    import asyncio
    import pytest

    client = build_agent_client()
    with pytest.raises(RuntimeError, match="AGENTCORE_RUNTIME_ARN"):
        asyncio.run(client.summarize_url("https://example.com"))


def test_runtime_backend_rejects_placeholder_resource_name(monkeypatch):
    monkeypatch.setenv("AGENT_BACKEND", "runtime")
    monkeypatch.setenv(
        "AGENTCORE_RUNTIME_ARN",
        "arn:aws:bedrock-agentcore:us-east-1:ACCOUNT_ID:runtime/RUNTIME_ID",
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
    deploy_script = (root / "scripts" / "deploy-agentcore-runtime.py").read_text(encoding="utf-8")

    assert "COPY requirements.txt constraints-workshop.txt" in dockerfile
    assert "uv pip install --system --no-cache -r requirements.txt -c constraints-workshop.txt" in dockerfile
    assert '"constraints-workshop.txt"' in deploy_script
    assert "prepare_runtime_requirements_file" in deploy_script


def test_agent_runtime_requirements_file_omits_comments_and_blank_lines(tmp_path):
    import importlib.util

    root = Path(__file__).resolve().parents[1]
    script_path = root / "scripts" / "deploy-agentcore-runtime.py"
    spec = importlib.util.spec_from_file_location("deploy_agent_runtime", script_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)

    source = tmp_path / "constraints.txt"
    source.write_text(
        "\n".join(
            [
                "# Workshop constraints.",
                "",
                "  # indented comment",
                "boto3>=1.39.8",
                "bedrock-agentcore[strands-agents]>=0.1.0",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    prepared = Path(module.prepare_runtime_requirements_file(str(source), tmp_path / "out"))

    assert prepared.read_text(encoding="utf-8") == (
        "boto3>=1.39.8\n"
        "bedrock-agentcore[strands-agents]>=0.1.0\n"
    )


def test_user_facing_error_message_mapping():
    from web.main import _display_error

    model_error = _display_error(
        RuntimeError("model amazon.nova-canvas-v1:0 returned 404")
    )
    signed_url_error = _display_error(RuntimeError("S3 AccessDenied while creating presigned URL"))
    empty_error = _display_error(AssertionError())

    assert "Bedrock model が見つかりません" in model_error
    assert "技術詳細:" in model_error
    assert "presigned URL 生成" in signed_url_error
    assert "AssertionError" in empty_error


def test_slow_job_message_after_threshold():
    from datetime import timedelta
    from web.main import AgentJob

    job = AgentJob(job_id="graphic-test", kind="graphic", title="生成中")
    job.started_at = job.started_at - timedelta(seconds=241)

    assert job.is_slow is True
    assert "AgentCore Runtime logs" in job.slow_message


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
        text_backend="bedrock:test",
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


def test_runtime_client_parses_text_response_event():
    from web.agent_client import _runtime_response_from_event

    event = {
        "content": {
            "parts": [
                {
                    "text": (
                        '{"operation":"summarize_url","summary":{'
                        '"session_id":"s1","url":"https://example.com","title":"Title",'
                        '"summary_lines":["a","b","c"],"key_points":["p1"],'
                        '"article_text":"body","text_backend":"runtime","progress":[]}}'
                    )
                }
            ]
        }
    }

    response = _runtime_response_from_event(event)

    assert response is not None
    assert response.operation == "summarize_url"
    assert response.summary is not None
    assert response.summary.title == "Title"


def test_runtime_operation_sync_accepts_text_part_contract():
    from web.agent_client import RuntimeAgentClient
    from io import BytesIO

    class AgentCoreClient:
        def invoke_agent_runtime(self, **_kwargs):
            return {
                "body": BytesIO(
                    (
                        '{"operation":"summarize_url","summary":{'
                        '"session_id":"s1","url":"https://example.com","title":"Title",'
                        '"summary_lines":["a","b","c"],"key_points":["p1"],'
                        '"article_text":"body","text_backend":"runtime","progress":[]}}'
                    ).encode("utf-8")
                )
            }

    os.environ["AGENTCORE_RUNTIME_ARN"] = "arn:aws:bedrock-agentcore:us-east-1:123456789012:runtime/demo"
    response = RuntimeAgentClient()._run_runtime_operation_sync(
        AgentCoreClient(),
        {"operation": "summarize_url"},
    )

    assert response.summary is not None
    assert response.summary.title == "Title"


def test_agentcore_entrypoint_returns_error_contract_for_bad_payload(monkeypatch):
    import asyncio

    from agent import agentcore_entrypoint
    from agent.runtime_contract import RuntimeWorkflowResponse

    async def fake_dispatch(_payload):
        raise ValueError("bad payload")

    monkeypatch.setattr(agentcore_entrypoint, "dispatch_agentcore_payload", fake_dispatch)

    result = asyncio.run(agentcore_entrypoint.invoke({"operation": "summarize_url"}))
    response = RuntimeWorkflowResponse.model_validate(result)

    assert response.operation == "summarize_url"
    assert "ValueError" in response.error


def test_runtime_dispatcher_calls_summary_workflow_directly(monkeypatch):
    import asyncio

    from agent.models import ProgressStep, SummaryResult
    from agent import runtime_workflows

    async def fake_summarize_url(url: str) -> SummaryResult:
        return SummaryResult(
            session_id="session-1",
            url=url,
            title="Direct",
            summary_lines=["a", "b", "c"],
            key_points=["p1", "p2", "p3", "p4"],
            article_text="body",
            text_backend="test",
            progress=[ProgressStep("direct dispatch", "done", "ok")],
        )

    monkeypatch.setattr(runtime_workflows, "summarize_url", fake_summarize_url)

    response = asyncio.run(
        runtime_workflows.dispatch_runtime_operation(
            {"operation": "summarize_url", "url": "https://example.com"}
        )
    )

    assert response.operation == "summarize_url"
    assert response.summary is not None
    assert response.summary.title == "Direct"


def test_runtime_payload_parser_reads_user_message_json():
    from agent.strands_agent import runtime_payload_from_event

    assert runtime_payload_from_event('{"operation":"summarize_url","url":"https://example.com"}') == {
        "operation": "summarize_url",
        "url": "https://example.com",
    }


def test_article_fetch_size_limit_helpers(monkeypatch):
    monkeypatch.setenv("ARTICLE_FETCH_MAX_BYTES", "4096")

    from agent.tools import article_fetch_max_bytes, signed_artifact_url_ttl_seconds

    assert article_fetch_max_bytes() == 4096

    monkeypatch.setenv("ARTICLE_FETCH_MAX_BYTES", "not-a-number")
    assert article_fetch_max_bytes() == 2_000_000

    monkeypatch.setenv("S3_PRESIGNED_URL_TTL_SECONDS", "120")
    assert signed_artifact_url_ttl_seconds() == 120

    monkeypatch.setenv("S3_PRESIGNED_URL_TTL_SECONDS", "bad")
    assert signed_artifact_url_ttl_seconds() == 28800


def test_s3_upload_returns_presigned_url(monkeypatch, tmp_path):
    from agent import tools
    import asyncio

    calls = {}

    class S3Client:
        def upload_file(self, filename, bucket, key, ExtraArgs):
            calls["upload"] = (filename, bucket, key, ExtraArgs)

        def generate_presigned_url(self, operation, Params, ExpiresIn):
            calls["presign"] = (operation, Params, ExpiresIn)
            return "https://signed.example/artifact"

    class Boto3:
        @staticmethod
        def client(service):
            assert service == "s3"
            return S3Client()

    artifact = tmp_path / "a.svg"
    artifact.write_text("<svg/>", encoding="utf-8")
    monkeypatch.setenv("S3_BUCKET", "bucket")
    monkeypatch.setenv("S3_ARTIFACT_PREFIX", "artifacts")
    monkeypatch.setitem(sys.modules, "boto3", Boto3)

    url = asyncio.run(tools._upload_artifact_to_s3(artifact, "image/svg+xml"))

    assert url == "https://signed.example/artifact"
    assert calls["upload"][1] == "bucket"
    assert calls["upload"][2] == "artifacts/a.svg"


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
