from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, Optional
from uuid import uuid4

from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from agent.models import GraphicResult, SummaryResult
from web.agent_client import build_agent_client


BASE_DIR = Path(__file__).resolve().parent
JobKind = Literal["summary", "graphic"]
JobStatus = Literal["running", "done", "failed"]


@dataclass
class AgentJob:
    job_id: str
    kind: JobKind
    title: str
    status: JobStatus = "running"
    progress: list = field(default_factory=list)
    summary: Optional[SummaryResult] = None
    graphic: Optional[GraphicResult] = None
    feedback: str = ""
    error: str = ""

app = FastAPI(title="Graphic Recording Agent Demo")
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
app.mount("/artifacts", StaticFiles(directory=Path("artifacts")), name="artifacts")

templates = Jinja2Templates(directory=BASE_DIR / "templates")
agent_client = build_agent_client()

sessions: dict[str, SummaryResult] = {}
graphics: dict[str, GraphicResult] = {}
jobs: dict[str, AgentJob] = {}
background_tasks: set[asyncio.Task] = set()


@app.get("/", response_class=HTMLResponse)
async def index(request: Request) -> HTMLResponse:
    return templates.TemplateResponse("index.html", {"request": request})


@app.post("/summaries", response_class=HTMLResponse)
async def summarize(request: Request, url: str = Form(...)) -> HTMLResponse:
    job = _create_job("summary", "記事を要約しています")
    _schedule_background_task(_run_summary_job(job.job_id, url))
    return templates.TemplateResponse(
        "partials/job.html",
        {"request": request, "job": job},
    )


@app.post("/graphics", response_class=HTMLResponse)
async def create_graphic(
    request: Request,
    session_id: str = Form(...),
    summary_text: str = Form(""),
    key_points_text: str = Form(""),
) -> HTMLResponse:
    summary = _get_summary(session_id)
    _apply_summary_edits(summary, summary_text, key_points_text)
    job = _create_job("graphic", "グラレコを生成しています")
    _schedule_background_task(_run_graphic_job(job.job_id, summary, feedback=""))
    return templates.TemplateResponse(
        "partials/job.html",
        {"request": request, "job": job},
    )


@app.post("/graphics/regenerate", response_class=HTMLResponse)
async def regenerate_graphic(
    request: Request,
    session_id: str = Form(...),
    feedback: str = Form(""),
) -> HTMLResponse:
    summary = _get_summary(session_id)
    job = _create_job("graphic", "フィードバックを反映しています", feedback=feedback)
    _schedule_background_task(_run_graphic_job(job.job_id, summary, feedback=feedback))
    return templates.TemplateResponse(
        "partials/job.html",
        {"request": request, "job": job},
    )


@app.get("/jobs/{job_id}", response_class=HTMLResponse)
async def poll_job(request: Request, job_id: str) -> HTMLResponse:
    job = jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    if job.status == "done" and job.kind == "summary" and job.summary:
        return templates.TemplateResponse(
            "partials/summary.html",
            {"request": request, "summary": job.summary},
        )

    if job.status == "done" and job.kind == "graphic" and job.summary and job.graphic:
        return templates.TemplateResponse(
            "partials/graphic.html",
            {
                "request": request,
                "summary": job.summary,
                "graphic": job.graphic,
                "feedback": job.feedback,
            },
        )

    return templates.TemplateResponse(
        "partials/job.html",
        {"request": request, "job": job},
    )


def _get_summary(session_id: str) -> SummaryResult:
    summary = sessions.get(session_id)
    if not summary:
        raise HTTPException(status_code=404, detail="Session not found")
    return summary


def _create_job(kind: JobKind, title: str, feedback: str = "") -> AgentJob:
    job_id = f"{kind}-{uuid4().hex}"
    job = AgentJob(job_id=job_id, kind=kind, title=title, feedback=feedback)
    jobs[job_id] = job
    return job


def _schedule_background_task(coro) -> None:
    task = asyncio.create_task(coro)
    background_tasks.add(task)
    task.add_done_callback(background_tasks.discard)


async def _run_summary_job(job_id: str, url: str) -> None:
    job = jobs[job_id]

    async def update_progress(progress: list) -> None:
        job.progress = progress

    try:
        summary = await agent_client.summarize_url(url, on_progress=update_progress)
    except Exception as exc:
        job.status = "failed"
        job.error = str(exc)
        return

    sessions[summary.session_id] = summary
    job.summary = summary
    job.progress = summary.progress
    job.status = "done"


async def _run_graphic_job(job_id: str, summary: SummaryResult, feedback: str) -> None:
    job = jobs[job_id]
    job.summary = summary

    async def update_progress(progress: list) -> None:
        job.progress = progress

    try:
        if feedback:
            graphic = await agent_client.regenerate_graphic_recording(
                summary,
                feedback,
                on_progress=update_progress,
            )
        else:
            graphic = await agent_client.generate_graphic_recording(
                summary,
                on_progress=update_progress,
            )
    except Exception as exc:
        job.status = "failed"
        job.error = str(exc)
        return

    graphics[summary.session_id] = graphic
    job.graphic = graphic
    job.progress = graphic.progress
    job.status = "done"


def _apply_summary_edits(summary: SummaryResult, summary_text: str, key_points_text: str) -> None:
    summary_lines = [line.strip() for line in summary_text.splitlines() if line.strip()]
    key_points = [line.strip() for line in key_points_text.splitlines() if line.strip()]
    if summary_lines:
        summary.summary_lines = summary_lines[:3]
    if key_points:
        summary.key_points = key_points[:6]
