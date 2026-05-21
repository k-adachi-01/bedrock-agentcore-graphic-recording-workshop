from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, Optional
from uuid import uuid4

from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from agent.models import GraphicResult, SummaryResult
from agent.tools import close_genai_client
from web.auth import (
    AUTH_COOKIE_NAME,
    assert_auth_config,
    auth_enabled,
    cookie_max_age,
    create_auth_cookie,
    password_matches,
    request_is_authenticated,
)
from web.agent_client import build_agent_client
from web.logging_config import configure_logging


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


@asynccontextmanager
async def lifespan(app: FastAPI):
    global agent_client
    configure_logging()
    assert_auth_config()
    agent_client = build_agent_client()
    yield
    close_genai_client()
    agent_client = None


app = FastAPI(title="Graphic Recording Agent Demo", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
app.mount("/artifacts", StaticFiles(directory=Path("artifacts")), name="artifacts")

templates = Jinja2Templates(directory=BASE_DIR / "templates")
agent_client = None

sessions: dict[str, SummaryResult] = {}
graphics: dict[str, GraphicResult] = {}
jobs: dict[str, AgentJob] = {}
background_tasks: set[asyncio.Task] = set()


@app.middleware("http")
async def require_password_auth(request: Request, call_next) -> Response:
    if _is_auth_exempt_path(request.url.path) or request_is_authenticated(request):
        return await call_next(request)

    if request.method == "GET":
        return RedirectResponse(url=f"/login?next={request.url.path}", status_code=303)
    return PlainTextResponse(
        "Authentication required",
        status_code=401,
        headers={"HX-Redirect": "/login"},
    )


@app.get("/healthz", response_class=PlainTextResponse)
async def healthz() -> str:
    return "ok"


@app.get("/login", response_class=HTMLResponse)
async def login_form(request: Request, next: str = "/") -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "login.html",
        {"next_path": _safe_next_path(next), "error": ""},
    )


@app.post("/login")
async def login(
    request: Request,
    password: str = Form(...),
    next_path: str = Form("/"),
) -> Response:
    next_url = _safe_next_path(next_path)
    if not auth_enabled():
        return RedirectResponse(url=next_url, status_code=303)
    if not password_matches(password):
        return templates.TemplateResponse(
            request,
            "login.html",
            {
                "next_path": next_url,
                "error": "パスワードが違います。",
            },
            status_code=401,
        )

    response = RedirectResponse(url=next_url, status_code=303)
    response.set_cookie(
        AUTH_COOKIE_NAME,
        create_auth_cookie(),
        max_age=cookie_max_age(),
        httponly=True,
        secure=request.url.scheme == "https",
        samesite="lax",
    )
    return response


@app.post("/logout")
async def logout() -> Response:
    response = RedirectResponse(url="/login", status_code=303)
    response.delete_cookie(AUTH_COOKIE_NAME)
    return response


@app.get("/", response_class=HTMLResponse)
async def index(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "index.html",
        {"auth_enabled": auth_enabled()},
    )


@app.post("/summaries", response_class=HTMLResponse)
async def summarize(request: Request, url: str = Form(...)) -> HTMLResponse:
    job = _create_job("summary", "記事を要約しています")
    _schedule_background_task(_run_summary_job(job.job_id, url))
    return templates.TemplateResponse(
        request,
        "partials/job.html",
        {"job": job},
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
        request,
        "partials/job.html",
        {"job": job},
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
        request,
        "partials/job.html",
        {"job": job},
    )


@app.get("/jobs/{job_id}", response_class=HTMLResponse)
async def poll_job(request: Request, job_id: str) -> HTMLResponse:
    job = jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    if job.status == "done" and job.kind == "summary" and job.summary:
        return templates.TemplateResponse(
            request,
            "partials/summary.html",
            {"summary": job.summary},
        )

    if job.status == "done" and job.kind == "graphic" and job.summary and job.graphic:
        return templates.TemplateResponse(
            request,
            "partials/graphic.html",
            {
                "summary": job.summary,
                "graphic": job.graphic,
                "feedback": job.feedback,
            },
        )

    return templates.TemplateResponse(
        request,
        "partials/job.html",
        {"job": job},
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
        summary = await _agent_client().summarize_url(url, on_progress=update_progress)
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
            graphic = await _agent_client().regenerate_graphic_recording(
                summary,
                feedback,
                on_progress=update_progress,
            )
        else:
            graphic = await _agent_client().generate_graphic_recording(
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


def _is_auth_exempt_path(path: str) -> bool:
    return path in {"/login", "/healthz"} or path.startswith("/static/")


def _safe_next_path(path: str) -> str:
    # Minimal open redirect guard: only same-origin absolute paths are allowed.
    if not path or not path.startswith("/") or path.startswith("//"):
        return "/"
    if path.startswith("/login"):
        return "/"
    return path


def _agent_client():
    global agent_client
    if agent_client is None:
        agent_client = build_agent_client()
    return agent_client
