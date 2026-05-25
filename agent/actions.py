from __future__ import annotations

import asyncio
import logging
import os
import time
from collections.abc import Awaitable, Callable
from typing import Optional
from uuid import uuid4

from .models import GraphicResult, ProgressStep, SummaryResult
from . import tools

ProgressCallback = Callable[[list[ProgressStep]], Optional[Awaitable[None]]]
logger = logging.getLogger(__name__)


async def summarize_url(url: str, on_progress: Optional[ProgressCallback] = None) -> SummaryResult:
    workflow_started = time.perf_counter()
    session_id = uuid4().hex
    progress = [
        ProgressStep("URL を受け取りました", "done", url),
        ProgressStep("記事本文を取得中", "running"),
        ProgressStep("3 行要約と重要ポイントを生成", "pending"),
    ]
    await _emit(progress, on_progress)
    await _mock_step_delay()

    started = time.perf_counter()
    article = await tools.fetch_article(url)
    _log_duration("summarize_url", "fetch_article", started, session_id=session_id)
    progress[1] = ProgressStep("記事本文を取得", "done", article["title"])
    progress[2] = ProgressStep("3 行要約と重要ポイントを生成中", "running")
    await _emit(progress, on_progress)
    await _mock_step_delay()

    started = time.perf_counter()
    summary = await tools.summarize_article(article["title"], article["text"])
    _log_duration("summarize_url", "summarize_article", started, session_id=session_id)
    text_backend = summary.get("backend", "unknown")
    progress[2] = ProgressStep("3 行要約と重要ポイントを生成", "done", text_backend)
    await _emit(progress, on_progress)

    _log_duration("summarize_url", "total", workflow_started, session_id=session_id)
    return SummaryResult(
        session_id=session_id,
        url=url,
        title=article["title"],
        summary_lines=summary["summary_lines"],
        key_points=summary["key_points"],
        article_text=article["text"],
        text_backend=text_backend,
        progress=progress,
    )


async def generate_graphic_recording(
    summary: SummaryResult,
    on_progress: Optional[ProgressCallback] = None,
) -> GraphicResult:
    return await _build_graphic(summary, feedback="", on_progress=on_progress)


async def regenerate_graphic_recording(
    summary: SummaryResult,
    feedback: str,
    on_progress: Optional[ProgressCallback] = None,
) -> GraphicResult:
    return await _build_graphic(summary, feedback=feedback, on_progress=on_progress)


async def _build_graphic(
    summary: SummaryResult,
    feedback: str,
    on_progress: Optional[ProgressCallback] = None,
) -> GraphicResult:
    workflow_started = time.perf_counter()
    progress = [
        ProgressStep("要約確認を受け取りました", "done"),
        ProgressStep("Agent が visual style を判断中", "running"),
        ProgressStep("グラレコ構成案を作成", "pending"),
        ProgressStep("画像生成を実行", "pending"),
        ProgressStep("成果物を保存", "pending"),
    ]
    await _emit(progress, on_progress)
    await _mock_step_delay()

    started = time.perf_counter()
    style_decision = await tools.decide_style(summary.summary_lines, summary.key_points, feedback)
    _log_duration("generate_graphic", "decide_style", started, session_id=summary.session_id)
    progress[1] = ProgressStep(
        f"Agent が {style_decision.style} スタイルを選択",
        "done",
        style_decision.reason,
    )
    progress[2] = ProgressStep("Agent が構成案を作成中", "running")
    await _emit(progress, on_progress)
    await _mock_step_delay()

    started = time.perf_counter()
    visual_plan = await tools.create_visual_plan_for_style(
        summary.summary_lines,
        summary.key_points,
        feedback,
        style=style_decision.style,
    )
    _log_duration("generate_graphic", "create_visual_plan", started, session_id=summary.session_id)
    progress[2] = ProgressStep("Agent が構成案を作成", "done", style_decision.style)
    progress[3] = ProgressStep("画像生成を実行中", "running")
    await _emit(progress, on_progress)
    await _mock_step_delay()

    started = time.perf_counter()
    generated_image = await tools.generate_image_artifact(
        visual_plan,
        style=style_decision.style,
        summary_lines=summary.summary_lines,
        key_points=summary.key_points,
    )
    _log_duration("generate_graphic", "generate_image", started, session_id=summary.session_id)
    artifact_url = ""
    artifact_mime_type = "image/svg+xml"
    if generated_image.data:
        svg = ""
        image_backend = generated_image.backend
        progress[3] = ProgressStep("画像生成を実行", "done", image_backend)
    else:
        svg = await tools.render_svg(
            summary.title,
            summary.summary_lines,
            summary.key_points,
            visual_plan,
            feedback,
            style=style_decision.style,
        )
        image_backend = generated_image.backend
        progress[3] = ProgressStep("画像生成を fallback SVG で完了", "done", image_backend)
    await _emit(progress, on_progress)
    await _mock_step_delay()

    progress[4] = ProgressStep("成果物を保存中", "running")
    await _emit(progress, on_progress)
    started = time.perf_counter()
    if generated_image.data:
        artifact_path, artifact_url = await tools.save_binary_artifact_with_url(
            summary.session_id,
            generated_image.data,
            generated_image.mime_type,
        )
        artifact_mime_type = generated_image.mime_type
        if not artifact_url:
            artifact_url = tools.artifact_url_for_path(artifact_path)
    else:
        artifact_path, artifact_url = await tools.save_artifact_with_url(summary.session_id, svg)
        if not artifact_url:
            artifact_url = tools.artifact_url_for_path(artifact_path)
    _log_duration("generate_graphic", "save_artifact", started, session_id=summary.session_id)
    progress[4] = ProgressStep("成果物を保存", "done", artifact_path)
    await _emit(progress, on_progress)

    _log_duration("generate_graphic", "total", workflow_started, session_id=summary.session_id)
    return GraphicResult(
        session_id=summary.session_id,
        visual_plan=visual_plan,
        svg=svg,
        artifact_path=artifact_path,
        image_backend=image_backend,
        artifact_url=artifact_url,
        artifact_mime_type=artifact_mime_type,
        visual_style=style_decision.style,
        style_reason=style_decision.reason,
        progress=progress,
    )


async def _emit(progress: list[ProgressStep], on_progress: Optional[ProgressCallback]) -> None:
    if not on_progress:
        return
    snapshot = [ProgressStep(step.label, step.status, step.detail) for step in progress]
    result = on_progress(snapshot)
    if result:
        await result


async def _mock_step_delay() -> None:
    if not tools.is_mock_mode():
        return
    delay = float(os.getenv("MOCK_STEP_DELAY", "0.45"))
    if delay > 0:
        await asyncio.sleep(delay)


def _log_duration(operation: str, phase: str, started: float, session_id: str) -> None:
    logger.info(
        "workflow_duration operation=%s phase=%s session_id=%s elapsed_seconds=%.3f",
        operation,
        phase,
        session_id,
        time.perf_counter() - started,
    )
