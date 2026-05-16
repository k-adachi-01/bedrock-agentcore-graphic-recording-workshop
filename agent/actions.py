from __future__ import annotations

import asyncio
import os
from collections.abc import Awaitable, Callable
from typing import Optional
from uuid import uuid4

from .models import GraphicResult, ProgressStep, SummaryResult
from . import tools

ProgressCallback = Callable[[list[ProgressStep]], Optional[Awaitable[None]]]


async def summarize_url(url: str, on_progress: Optional[ProgressCallback] = None) -> SummaryResult:
    session_id = uuid4().hex
    progress = [
        ProgressStep("URL を受け取りました", "done", url),
        ProgressStep("記事本文を取得中", "running"),
        ProgressStep("3 行要約と重要ポイントを生成", "pending"),
    ]
    await _emit(progress, on_progress)
    await _mock_step_delay()

    article = await tools.fetch_article(url)
    progress[1] = ProgressStep("記事本文を取得", "done", article["title"])
    progress[2] = ProgressStep("3 行要約と重要ポイントを生成中", "running")
    await _emit(progress, on_progress)
    await _mock_step_delay()

    summary = await tools.summarize_article(article["title"], article["text"])
    text_backend = summary.get("backend", "unknown")
    progress[2] = ProgressStep("3 行要約と重要ポイントを生成", "done", text_backend)
    await _emit(progress, on_progress)

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
    progress = [
        ProgressStep("要約確認を受け取りました", "done"),
        ProgressStep("Agent がスタイルを選択中", "running"),
        ProgressStep("グラレコ構成案を作成", "pending"),
        ProgressStep("画像生成を実行", "pending"),
        ProgressStep("成果物を保存", "pending"),
    ]
    await _emit(progress, on_progress)
    await _mock_step_delay()

    style_decision = await tools.decide_style(summary.summary_lines, summary.key_points, feedback)
    progress[1] = ProgressStep(
        "Agent がスタイルを選択",
        "done",
        f"{style_decision.style}: {style_decision.reason}",
    )
    progress[2] = ProgressStep("グラレコ構成案を作成中", "running")
    await _emit(progress, on_progress)
    await _mock_step_delay()

    visual_plan = await tools.create_visual_plan_for_style(
        summary.summary_lines,
        summary.key_points,
        feedback,
        style=style_decision.style,
    )
    progress[2] = ProgressStep("グラレコ構成案を作成", "done", style_decision.style)
    progress[3] = ProgressStep("画像生成を実行中", "running")
    await _emit(progress, on_progress)
    await _mock_step_delay()

    generated_image = await tools.generate_image_artifact(visual_plan, style=style_decision.style)
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
    if generated_image.data:
        artifact_path = await tools.save_binary_artifact(
            summary.session_id,
            generated_image.data,
            generated_image.mime_type,
        )
        artifact_mime_type = generated_image.mime_type
        artifact_url = tools.artifact_url_for_path(artifact_path)
    else:
        artifact_path = await tools.save_artifact(summary.session_id, svg)
        artifact_url = ""
    progress[4] = ProgressStep("成果物を保存", "done", artifact_path)
    await _emit(progress, on_progress)

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
