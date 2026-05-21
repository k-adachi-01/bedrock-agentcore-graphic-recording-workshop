from __future__ import annotations

import asyncio
import base64
import gzip
import html
import ipaddress
import logging
import os
import re
import socket
import zlib
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import Literal, Optional, Union
from urllib.parse import urljoin, urlparse

import httpx
from pydantic import BaseModel, Field

try:
    import trafilatura
except ImportError:
    trafilatura = None


logger = logging.getLogger(__name__)

DEFAULT_ARTICLE_FETCH_MAX_BYTES = 2_000_000
RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}
_GENAI_CLIENT = None

_DEFAULT_PLAN_ITEMS = [
    "左上に URL 入力から Agent 起動までの導入を配置",
    "中央に 3 行要約を大きく配置",
    "右側に重要ポイントを 4 つのアイコン付きノードで配置",
    "下部に ADK / Agent Runtime / Cloud Run / Cloud Storage の流れを描く",
]


class ArticleSummary(BaseModel):
    summary_lines: list[str] = Field(
        description="Exactly three concise Japanese summary lines.",
        min_length=3,
        max_length=3,
    )
    key_points: list[str] = Field(
        description="Four to six important points in Japanese.",
        min_length=4,
        max_length=6,
    )


class VisualPlan(BaseModel):
    plan_items: list[str] = Field(
        description="Four to six Japanese composition instructions for a graphic recording.",
        min_length=4,
        max_length=6,
    )


class StyleDecision(BaseModel):
    style: Literal["business", "pop", "minimal"] = Field(
        description="Best visual style for this article."
    )
    reason: str = Field(description="One concise Japanese sentence explaining the style choice.")


@dataclass
class GeneratedImage:
    data: bytes
    mime_type: str
    backend: str
    error: str = ""


def is_mock_mode() -> bool:
    return os.getenv("MOCK_MODE", "true").lower() in {"1", "true", "yes", "on"}


def text_model_name() -> str:
    return os.getenv("GEMINI_TEXT_MODEL", "gemini-3.5-flash")


def image_model_name() -> str:
    return os.getenv("GEMINI_IMAGE_MODEL", "gemini-3-pro-image-preview")


async def fetch_article(url: str) -> dict[str, str]:
    """Fetch a public article URL and return its title plus cleaned article text.

    Args:
        url: Public HTTP or HTTPS article URL to fetch.

    Returns:
        A dictionary with `title` and cleaned `text` keys.
    """
    if is_mock_mode():
        host = urlparse(url).netloc or "example.com"
        title = f"{host} の記事から学ぶ Agent Runtime 活用"
        body = (
            "この記事は、企業内の業務アプリケーションに AI Agent を組み込む方法を紹介しています。"
            "Agent は URL から情報を取得し、要約、構造化、成果物生成までを一連の action として実行します。"
            "Google ADK を使うと tool の責務を分けながら Agent の振る舞いを定義でき、"
            "Agent Runtime に配置することで Web App から安定して呼び出せます。"
            "Cloud Run は FastAPI の Web フロントエンドを動かし、Cloud Storage は生成画像や SVG を保存します。"
            "デモではまず mock mode で外部 API に依存せず UX と処理順序を確認し、"
            "その後 Gemini text model と Nano Banana Pro / Gemini image model に差し替えていきます。"
        )
        return {"title": title, "text": body}

    response = await _fetch_public_url(url)

    title, text = await _extract_article_text(response.text, str(response.url))
    return {"title": title, "text": text[:12000]}


async def summarize_article(title: str, article_text: str) -> dict[str, list[str]]:
    """Create a Japanese three-line summary and key points from article text.

    Args:
        title: Article title.
        article_text: Cleaned article body text.

    Returns:
        A dictionary containing `summary_lines`, `key_points`, and `backend`.
    """
    if is_mock_mode():
        return {
            "summary_lines": [
                "Agent が記事取得から要約、画像生成までを一連の workflow として進めます。",
                "ADK では fetch / summarize / plan / render などの tool を分けて実装します。",
                "Phase 1 は mock mode と fallback SVG により、外部 API なしでデモ体験を確認します。",
            ],
            "key_points": [
                "Web App は Agent Runtime 上の Agent を呼び出す境界を持つ",
                "ローカル開発では AGENT_BACKEND=local で同じ action を直接実行する",
                "画像生成失敗時も render_svg により結果確認まで進める",
                "生成結果は artifact として保存し、Cloud Storage へ差し替え可能にする",
            ],
            "backend": "mock",
        }

    prompt = f"""次の記事を日本語で要約してください。

制約:
- summary_lines は必ず3行
- key_points は4から6個
- 勉強会デモで説明しやすいように、具体的で短い表現にする
- 出力は指定 schema に厳密に従う

タイトル:
{title}

本文:
{article_text[:12000]}
"""
    try:
        summary = await _generate_structured_content(prompt, ArticleSummary)
    except Exception as exc:
        logger.warning("Gemini summarize failed, falling back to heuristic: %s", exc)
        return _heuristic_summary(title, article_text, reason=str(exc))

    return {
        "summary_lines": summary.summary_lines[:3],
        "key_points": summary.key_points[:6],
        "backend": f"gemini:{text_model_name()}",
    }


async def decide_style(
    summary_lines: list[str],
    key_points: list[str],
    feedback: str = "",
) -> StyleDecision:
    """Choose the visual style that best fits the article summary.

    Args:
        summary_lines: Three summary lines.
        key_points: Important points extracted from the article.
        feedback: Optional user feedback from regeneration.

    Returns:
        Style decision with a style name and concise reason.
    """
    if is_mock_mode():
        return _heuristic_style_decision(summary_lines, key_points, feedback, reason_prefix="mock")

    prompt = f"""次の要約と重要ポイントに最も合うグラフィックレコーディングのスタイルを1つ選んでください。

選択肢:
- business: 企業向け、落ち着いた配色、構造化された図解
- pop: 一般読者向け、明るい配色、親しみやすいアイコン
- minimal: 情報量を絞った、余白が多い、静かな資料調

3行要約:
{chr(10).join(summary_lines)}

重要ポイント:
{chr(10).join(key_points)}

ユーザーフィードバック:
{feedback or "なし"}

制約:
- style は business / pop / minimal のいずれか
- reason は日本語1文
- 出力は指定 schema に厳密に従う
"""
    try:
        return await _generate_structured_content(prompt, StyleDecision)
    except Exception as exc:
        logger.warning("Gemini style decision failed, falling back to heuristic: %s", exc)
        return _heuristic_style_decision(
            summary_lines,
            key_points,
            feedback,
            reason_prefix=f"fallback: {str(exc)[:80]}",
        )


async def create_visual_plan(summary_lines: list[str], key_points: list[str], feedback: str = "") -> list[str]:
    """Create composition instructions for a graphic recording image.

    Args:
        summary_lines: Three summary lines to visualize.
        key_points: Important points to include in the composition.
        feedback: Optional user feedback from regeneration.

    Returns:
        A list of Japanese visual composition instructions.
    """
    return await create_visual_plan_for_style(summary_lines, key_points, feedback, style="business")


async def create_visual_plan_for_style(
    summary_lines: list[str],
    key_points: list[str],
    feedback: str = "",
    style: str = "business",
) -> list[str]:
    """Create composition instructions for a graphic recording image using the selected style.

    Args:
        summary_lines: Three summary lines to visualize.
        key_points: Important points to include in the composition.
        feedback: Optional user feedback from regeneration.
        style: Selected visual style. Expected values are `business`, `pop`, or `minimal`.

    Returns:
        A list of Japanese visual composition instructions.
    """
    if is_mock_mode():
        plan = _default_plan_items_for_style(style)
        if feedback.strip():
            plan.append(f"フィードバック反映: {feedback.strip()[:80]}")
        return plan

    prompt = f"""グラフィックレコーディング画像の構成案を日本語で作成してください。

3行要約:
{chr(10).join(summary_lines)}

重要ポイント:
{chr(10).join(key_points)}

ユーザーフィードバック:
{feedback or "なし"}

選択スタイル:
{style}

制約:
- plan_items は4から6個
- 画面上の配置、強調する概念、視線誘導が分かる指示にする
- 選択スタイルに合う色調、密度、アイコン表現にする
- ADK / Agent Runtime / Gemini / Cloud Run / Cloud Storage の文脈が自然に伝わるようにする
- 出力は指定 schema に厳密に従う
"""
    try:
        visual_plan = await _generate_structured_content(prompt, VisualPlan)
        return visual_plan.plan_items[:6]
    except Exception as exc:
        logger.warning("Gemini visual plan failed, falling back to default plan: %s", exc)
        plan = _default_plan_items_for_style(style)
        if feedback.strip():
            plan.append(f"フィードバック反映: {feedback.strip()[:80]}")
        return plan


async def generate_image(visual_plan: list[str]) -> str:
    """Generate a graphic recording image and return SVG-compatible markup.

    Args:
        visual_plan: Composition instructions for the image model.

    Returns:
        SVG markup wrapping the generated image, or an empty string on fallback.
    """
    image = await generate_image_artifact(visual_plan)
    if not image.data:
        return ""
    return _render_image_svg(image.data, image.mime_type)


async def generate_image_artifact(visual_plan: list[str], style: str = "business") -> GeneratedImage:
    """Generate a graphic recording image with Gemini image model for artifact storage.

    Args:
        visual_plan: Composition instructions for the image model.
        style: Selected visual style used to tune the image prompt.

    Returns:
        Generated image bytes and metadata, or an empty payload that signals SVG fallback.
    """
    if is_mock_mode():
        return GeneratedImage(b"", "", "fallback-svg:mock-mode")
    if not has_gemini_credentials():
        message = "credentials are not configured"
        logger.warning("Gemini image generation skipped: %s", message)
        return GeneratedImage(b"", "", f"fallback-svg:{message}")

    prompt = f"""日本語のグラフィックレコーディング画像を生成してください。

目的:
- 勉強会デモで、URL取得から要約、構成案、画像生成まで Agent が進める流れを見せる
- Gemini Enterprise Agent Platform / ADK / Agent Runtime / Cloud Run / Cloud Storage の関係が一目で分かる

構成案:
{chr(10).join(f"- {item}" for item in visual_plan)}

選択スタイル:
{style}

スタイル指針:
{_style_image_directive(style)}

表現:
- 16:9 の横長
- 白背景、読みやすい太線、アイコン、矢印、付箋風メモ
- 日本語テキストは短く、大きく、読みやすく
- 企業向け勉強会の資料として使える完成度にする
- 選択スタイルと矛盾する色や装飾を混ぜない
"""
    try:
        image_bytes, mime_type = await _generate_image_data(prompt)
    except Exception as exc:
        logger.warning("Gemini image generation failed, falling back to SVG: %s", exc)
        return GeneratedImage(b"", "", f"fallback-svg:{str(exc)[:120]}")

    if not image_bytes:
        message = "no image parts returned"
        logger.warning("Gemini image generation returned %s", message)
        return GeneratedImage(b"", "", f"fallback-svg:{message}")

    return GeneratedImage(
        image_bytes,
        mime_type,
        f"gemini:{display_model_name(image_model_name())}",
    )


async def render_svg(
    title: str,
    summary_lines: list[str],
    key_points: list[str],
    visual_plan: list[str],
    feedback: str = "",
    style: str = "business",
) -> str:
    """Render a deterministic fallback SVG graphic recording.

    Args:
        title: Article title.
        summary_lines: Three summary lines to render.
        key_points: Important points to render.
        visual_plan: Composition instructions selected by the agent pipeline.
        feedback: Optional user feedback from regeneration.
        style: Selected visual style.

    Returns:
        SVG markup for the generated fallback artifact.
    """
    palette = _style_palette(style, feedback)
    accent = palette["accent"]
    safe_title = html.escape(title)
    summary_items = "".join(
        f'<text x="78" y="{180 + i * 34}" class="summary">{html.escape(line)}</text>'
        for i, line in enumerate(summary_lines)
    )
    point_items = "".join(
        _point_node(i, point, accent)
        for i, point in enumerate(key_points[:4])
    )
    plan_text = " / ".join(visual_plan[:3])
    feedback_note = (
        f'<text x="78" y="548" class="note">Feedback: {html.escape(feedback[:90])}</text>'
        if feedback.strip()
        else '<text x="78" y="548" class="note">Fallback SVG generated in MOCK_MODE</text>'
    )

    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="1100" height="680" viewBox="0 0 1100 680" role="img" aria-label="Graphic recording">
  <style>
    .bg {{ fill: #f8fafc; }}
    .panel {{ fill: #ffffff; stroke: #cbd5e1; stroke-width: 2; }}
    .title {{ font: 700 32px sans-serif; fill: #0f172a; }}
    .label {{ font: 700 16px sans-serif; fill: #475569; }}
    .summary {{ font: 600 22px sans-serif; fill: #0f172a; }}
    .small {{ font: 500 15px sans-serif; fill: #334155; }}
    .note {{ font: 500 16px sans-serif; fill: #0f766e; }}
    .arrow {{ stroke: #64748b; stroke-width: 3; fill: none; marker-end: url(#arrow); }}
  </style>
  <defs>
    <marker id="arrow" markerWidth="10" markerHeight="10" refX="8" refY="3" orient="auto">
      <path d="M0,0 L0,6 L9,3 z" fill="#64748b" />
    </marker>
  </defs>
  <rect width="1100" height="680" rx="0" fill="{palette["background"]}" />
  <rect x="40" y="36" width="1020" height="92" rx="8" fill="{accent}" />
  <text x="72" y="92" font-family="sans-serif" font-size="34" font-weight="800" fill="#ffffff">{safe_title}</text>

  <rect class="panel" x="54" y="150" width="640" height="166" rx="8" />
  <text x="78" y="172" class="label">3 Line Summary</text>
  {summary_items}

  <rect class="panel" x="732" y="150" width="314" height="380" rx="8" />
  <text x="758" y="184" class="label">Key Points</text>
  {point_items}

  <rect class="panel" x="54" y="350" width="640" height="180" rx="8" />
  <text x="78" y="386" class="label">Agent Flow</text>
  <circle cx="130" cy="444" r="34" fill="{palette["soft"]}" stroke="{accent}" stroke-width="3" />
  <text x="106" y="450" class="small">URL</text>
  <path class="arrow" d="M166 444 H256" />
  <circle cx="306" cy="444" r="42" fill="#ecfeff" stroke="#0891b2" stroke-width="3" />
  <text x="280" y="450" class="small">ADK</text>
  <path class="arrow" d="M350 444 H454" />
  <circle cx="510" cy="444" r="50" fill="#fef3c7" stroke="#d97706" stroke-width="3" />
  <text x="465" y="440" class="small">Agent</text>
  <text x="463" y="460" class="small">Runtime</text>
  <path class="arrow" d="M562 444 H612" />
  <rect x="620" y="407" width="50" height="74" rx="8" fill="#dcfce7" stroke="#16a34a" stroke-width="3" />
  <text x="630" y="449" class="small">SVG</text>

  <rect x="54" y="562" width="992" height="74" rx="8" fill="#e2e8f0" />
  <text x="78" y="592" class="label">Visual Plan</text>
  <text x="78" y="620" class="small">Style: {html.escape(style)} / {html.escape(plan_text[:110])}</text>
  {feedback_note}
</svg>"""


async def save_artifact(session_id: str, svg: str) -> str:
    """Save a generated SVG artifact locally and optionally mirror it to Cloud Storage.

    Args:
        session_id: Stable session identifier used as the artifact filename.
        svg: SVG markup to save.

    Returns:
        Local artifact path.
    """
    path, _signed_url = await save_artifact_with_url(session_id, svg)
    return path


async def save_artifact_with_url(session_id: str, svg: str) -> tuple[str, str]:
    """Save a generated SVG artifact and return a browser URL when available."""
    artifact_dir = Path(os.getenv("ARTIFACT_DIR", "artifacts"))
    artifact_dir.mkdir(parents=True, exist_ok=True)
    path = artifact_dir / f"{session_id}.svg"
    path.write_text(svg, encoding="utf-8")
    signed_url = await _upload_artifact_to_gcs(path, "image/svg+xml")
    return str(path), signed_url


async def save_binary_artifact(session_id: str, data: bytes, mime_type: str) -> str:
    """Save a generated binary artifact locally and optionally mirror it to Cloud Storage.

    Args:
        session_id: Stable session identifier used as the artifact filename.
        data: Binary artifact bytes.
        mime_type: MIME type for file extension and Cloud Storage metadata.

    Returns:
        Local artifact path.
    """
    path, _signed_url = await save_binary_artifact_with_url(session_id, data, mime_type)
    return path


async def save_binary_artifact_with_url(
    session_id: str,
    data: bytes,
    mime_type: str,
) -> tuple[str, str]:
    """Save a generated binary artifact and return a browser URL when available."""
    artifact_dir = Path(os.getenv("ARTIFACT_DIR", "artifacts"))
    artifact_dir.mkdir(parents=True, exist_ok=True)
    path = artifact_dir / f"{session_id}{_extension_for_mime_type(mime_type)}"
    path.write_bytes(data)
    signed_url = await _upload_artifact_to_gcs(path, mime_type)
    return str(path), signed_url


def artifact_url_for_path(artifact_path: str) -> str:
    return f"/artifacts/{Path(artifact_path).name}"


async def _upload_artifact_to_gcs(path: Path, content_type: str) -> str:
    bucket_name = os.getenv("GCS_BUCKET")
    if not bucket_name:
        return ""

    def upload() -> str:
        from google.cloud import storage

        prefix = os.getenv("GCS_ARTIFACT_PREFIX", "artifacts").strip("/")
        object_name = f"{prefix}/{path.name}" if prefix else path.name
        client = storage.Client()
        blob = client.bucket(bucket_name).blob(object_name)
        blob.upload_from_filename(str(path), content_type=content_type)
        return _generate_signed_artifact_url(blob)

    try:
        return await asyncio.to_thread(upload)
    except Exception as exc:
        logger.warning("Cloud Storage artifact upload failed: %s", exc)
        return ""


def _generate_signed_artifact_url(blob) -> str:
    ttl_seconds = signed_artifact_url_ttl_seconds()
    credentials, service_account_email = _signed_url_credentials()
    return blob.generate_signed_url(
        version="v4",
        expiration=timedelta(seconds=ttl_seconds),
        method="GET",
        credentials=credentials,
        service_account_email=service_account_email,
        access_token=credentials.token,
    )


def signed_artifact_url_ttl_seconds() -> int:
    value = os.getenv("GCS_SIGNED_URL_TTL_SECONDS", "28800")
    try:
        return max(60, int(value))
    except ValueError:
        return 28800


def _signed_url_credentials():
    import google.auth
    from google.auth.transport.requests import Request

    credentials, _project = google.auth.default(
        scopes=["https://www.googleapis.com/auth/cloud-platform"]
    )
    auth_request = Request()
    credentials.refresh(auth_request)

    service_account_email = os.getenv("GCS_SIGNING_SERVICE_ACCOUNT") or getattr(
        credentials,
        "service_account_email",
        "",
    )
    if not service_account_email:
        raise RuntimeError(
            "Could not determine the service account email for signed URL generation. "
            "Set GCS_SIGNING_SERVICE_ACCOUNT to the Agent Runtime service account."
        )
    return credentials, service_account_email


async def _fetch_public_url(url: str) -> httpx.Response:
    current_url = url
    headers = {
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Encoding": "identity",
        "User-Agent": "GeminiEnterpriseAgentWorkshop/1.0",
    }
    async with httpx.AsyncClient(follow_redirects=False, timeout=15, headers=headers) as client:
        for _ in range(5):
            await _assert_public_http_url(current_url)
            async with client.stream("GET", current_url) as response:
                if response.is_redirect:
                    location = response.headers.get("location")
                    if not location:
                        break
                    current_url = urljoin(str(response.url), location)
                    continue
                response.raise_for_status()
                raw_content = await _read_limited_response(response, article_fetch_max_bytes())
                content = _decode_response_content(raw_content, response.headers)
                headers = httpx.Headers(response.headers)
                headers.pop("content-encoding", None)
                headers["content-length"] = str(len(content))
                return httpx.Response(
                    response.status_code,
                    headers=headers,
                    content=content,
                    request=response.request,
                    extensions=response.extensions,
                )
    raise ValueError("Too many redirects while fetching article")


async def _read_limited_response(response: httpx.Response, max_bytes: int) -> bytes:
    chunks: list[bytes] = []
    total = 0
    async for chunk in response.aiter_raw():
        total += len(chunk)
        if total > max_bytes:
            raise ValueError(f"Article response exceeds {max_bytes} bytes")
        chunks.append(chunk)
    return b"".join(chunks)


def _decode_response_content(raw_content: bytes, headers: httpx.Headers) -> bytes:
    encoding = headers.get("content-encoding", "").lower().strip()
    if not encoding or encoding == "identity":
        return raw_content

    try:
        if encoding == "gzip":
            return gzip.decompress(raw_content)
        if encoding == "deflate":
            return zlib.decompress(raw_content)
    except (OSError, zlib.error) as exc:
        logger.warning(
            "Ignoring invalid Content-Encoding=%s while fetching article: %s",
            encoding,
            exc,
        )
        return raw_content

    logger.warning("Ignoring unsupported Content-Encoding=%s while fetching article", encoding)
    return raw_content


async def _extract_article_text(raw_html: str, url: str) -> tuple[str, str]:
    title = _extract_title(raw_html) or url

    if trafilatura:
        extracted = await asyncio.to_thread(
            trafilatura.extract,
            raw_html,
            url=url,
            include_comments=False,
            include_tables=False,
            favor_precision=True,
        )
        if extracted and extracted.strip():
            return title, _normalize_text(extracted)

    return title, _clean_html(raw_html)


async def _generate_structured_content(prompt: str, schema_model):
    if not has_gemini_credentials():
        raise RuntimeError(
            "GEMINI_API_KEY, GOOGLE_API_KEY, or Vertex AI Gemini environment settings are required"
        )

    async_client = _get_genai_client().aio
    response = await _call_with_retries(
        lambda: async_client.models.generate_content(
            model=text_model_name(),
            contents=prompt,
            config={
                "response_mime_type": "application/json",
                "response_schema": schema_model,
            },
        ),
        operation="gemini-structured-content",
    )
    if response.parsed is not None:
        return response.parsed
    return schema_model.model_validate_json(response.text)


async def _generate_image_data(prompt: str) -> tuple[bytes, str]:
    from google.genai import types

    async_client = _get_genai_client().aio
    response = await _call_with_retries(
        lambda: async_client.models.generate_content(
            model=image_model_name(),
            contents=prompt,
            config=types.GenerateContentConfig(
                response_modalities=[types.Modality.TEXT, types.Modality.IMAGE],
                candidate_count=1,
            ),
        ),
        operation="gemini-image-generation",
    )
    if not response.candidates:
        return b"", "image/png"
    parts = response.candidates[0].content.parts if response.candidates[0].content else []
    for part in parts:
        if part.inline_data and part.inline_data.data:
            data = part.inline_data.data
            if isinstance(data, str):
                data = base64.b64decode(data)
            return data, part.inline_data.mime_type or "image/png"
    return b"", "image/png"


def _get_genai_client():
    global _GENAI_CLIENT
    if _GENAI_CLIENT is None:
        _GENAI_CLIENT = _build_genai_client()
    return _GENAI_CLIENT


def _build_genai_client():
    from google import genai

    return genai.Client()


def close_genai_client() -> None:
    global _GENAI_CLIENT
    if _GENAI_CLIENT is None:
        return
    close = getattr(_GENAI_CLIENT, "close", None)
    if close:
        close()
    _GENAI_CLIENT = None


async def _call_with_retries(operation_factory, operation: str):
    max_attempts = max(1, int(os.getenv("GEMINI_MAX_ATTEMPTS", "3")))
    base_delay = max(0.1, float(os.getenv("GEMINI_RETRY_BASE_DELAY_SECONDS", "0.6")))
    last_error: Optional[Exception] = None
    for attempt in range(1, max_attempts + 1):
        try:
            return await operation_factory()
        except Exception as exc:
            last_error = exc
            if attempt >= max_attempts or not _is_retryable_exception(exc):
                raise
            delay = base_delay * (2 ** (attempt - 1))
            logger.warning(
                "%s failed with retryable error on attempt %s/%s; retrying in %.1fs: %s",
                operation,
                attempt,
                max_attempts,
                delay,
                exc,
            )
            await asyncio.sleep(delay)
    raise RuntimeError(f"{operation} failed") from last_error


def _is_retryable_exception(exc: Exception) -> bool:
    status_code = _exception_status_code(exc)
    if status_code in RETRYABLE_STATUS_CODES:
        return True
    message = str(exc)
    return any(str(code) in message for code in RETRYABLE_STATUS_CODES)


def _exception_status_code(exc: Exception) -> Optional[int]:
    for attr in ("status_code", "code"):
        value = getattr(exc, attr, None)
        if isinstance(value, int):
            return value
        enum_value = getattr(value, "value", None)
        if isinstance(enum_value, int):
            return enum_value

    response = getattr(exc, "response", None)
    status_code = getattr(response, "status_code", None)
    return status_code if isinstance(status_code, int) else None


def has_gemini_credentials() -> bool:
    if os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY"):
        return True
    return _use_vertex_ai()


def _use_vertex_ai() -> bool:
    return os.getenv("GOOGLE_GENAI_USE_VERTEXAI", "").lower() in {"1", "true", "yes", "on"}


def article_fetch_max_bytes() -> int:
    try:
        return max(1024, int(os.getenv("ARTICLE_FETCH_MAX_BYTES", str(DEFAULT_ARTICLE_FETCH_MAX_BYTES))))
    except ValueError:
        return DEFAULT_ARTICLE_FETCH_MAX_BYTES


def display_model_name(model_name: str) -> str:
    labels = {
        "gemini-2.5-flash-image": "gemini-2.5-flash-image (Nano Banana)",
        "gemini-3-pro-image-preview": "gemini-3-pro-image-preview (Nano Banana Pro)",
    }
    return labels.get(model_name, model_name)


async def _assert_public_http_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("Only http and https URLs are allowed")
    if not parsed.hostname:
        raise ValueError("URL host is required")

    host = parsed.hostname
    try:
        literal_ip = ipaddress.ip_address(host)
    except ValueError:
        literal_ip = None

    if literal_ip:
        _reject_private_address(literal_ip)
        return

    addresses = await _resolve_host(host)
    if not addresses:
        raise ValueError("URL host could not be resolved")

    for address in addresses:
        _reject_private_address(ipaddress.ip_address(address))


async def _resolve_host(host: str) -> set[str]:
    def resolve() -> set[str]:
        return {
            result[4][0]
            for result in socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)
        }
    return await asyncio.to_thread(resolve)


def _reject_private_address(address: Union[ipaddress.IPv4Address, ipaddress.IPv6Address]) -> None:
    if (
        address.is_loopback
        or address.is_private
        or address.is_link_local
        or address.is_multicast
        or address.is_reserved
        or address.is_unspecified
    ):
        raise ValueError("Private, local, or reserved network addresses are not allowed")


def _clean_html(raw_html: str) -> str:
    without_scripts = re.sub(r"<(script|style).*?</\1>", " ", raw_html, flags=re.I | re.S)
    without_tags = re.sub(r"<[^>]+>", " ", without_scripts)
    unescaped = html.unescape(without_tags)
    return _normalize_text(unescaped)


def _extract_title(raw_html: str) -> Optional[str]:
    title_match = re.search(r"<title[^>]*>(.*?)</title>", raw_html, flags=re.I | re.S)
    return _clean_html(title_match.group(1)) if title_match else None


def _normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(text)).strip()


def _heuristic_summary(title: str, article_text: str, reason: str = "") -> dict[str, list[str]]:
    sentences = re.split(r"(?<=[。.!?])\s*", article_text)
    compact = [s.strip() for s in sentences if s.strip()]
    summary = compact[:3] or [title]
    while len(summary) < 3:
        summary.append(title)
    key_points = compact[3:9] or summary
    return {
        "summary_lines": summary[:3],
        "key_points": key_points[:6],
        "backend": f"heuristic:{reason[:80]}" if reason else "heuristic",
    }


def _heuristic_style_decision(
    summary_lines: list[str],
    key_points: list[str],
    feedback: str = "",
    reason_prefix: str = "heuristic",
) -> StyleDecision:
    text = " ".join(summary_lines + key_points + [feedback]).lower()
    if any(word in text for word in ["pop", "ポップ", "親しみ", "一般", "note", "読者", "キャリア"]):
        return StyleDecision(style="pop", reason=f"{reason_prefix}: 一般読者向けの親しみやすい表現が合うため。")
    if any(word in text for word in ["minimal", "ミニマル", "シンプル", "余白", "簡潔"]):
        return StyleDecision(style="minimal", reason=f"{reason_prefix}: 情報を絞った静かな見せ方が合うため。")
    return StyleDecision(style="business", reason=f"{reason_prefix}: 企業向けデモとして構造化された図解が合うため。")


def _default_plan_items_for_style(style: str) -> list[str]:
    if style == "pop":
        return [
            "左上に URL 入力から Agent 起動までを明るいアイコン付きで配置",
            "中央に 3 行要約を付箋風の大きな吹き出しで配置",
            "右側に重要ポイントをカラフルなノードで配置",
            "下部に ADK / Agent Runtime / Cloud Run / Cloud Storage の流れを親しみやすい矢印で描く",
        ]
    if style == "minimal":
        return [
            "上部に記事タイトルと 3 行要約を余白多めに配置",
            "中央に Agent の action/tool flow を細い線で整理",
            "右側に重要ポイントを少数のシンプルなラベルで配置",
            "下部に ADK / Agent Runtime / Cloud Storage の関係だけを控えめに示す",
        ]
    return list(_DEFAULT_PLAN_ITEMS)


def _style_palette(style: str, feedback: str = "") -> dict[str, str]:
    if feedback.strip():
        return {"accent": "#0f766e", "soft": "#ccfbf1", "background": "#f8fafc"}
    if style == "pop":
        return {"accent": "#ea580c", "soft": "#ffedd5", "background": "#fff7ed"}
    if style == "minimal":
        return {"accent": "#475569", "soft": "#e2e8f0", "background": "#f8fafc"}
    return {"accent": "#2563eb", "soft": "#dbeafe", "background": "#f8fafc"}


def _style_image_directive(style: str) -> str:
    directives = {
        "business": "色: 落ち着いたブルー/グレー。線: 細めで整然。アイコン: 企業資料風。余白: 標準。",
        "pop": "色: ビビッドな黄・オレンジ・ターコイズ。線: 太め手描き風。アイコン: 丸く親しみやすい。表現: 明るく活発。",
        "minimal": "色: モノトーン+1色アクセント。線: 細めシャープ。余白: 多め。要素数: 抑える。雰囲気: 静か。",
    }
    return directives.get(style, directives["business"])


def _render_image_svg(image_bytes: bytes, mime_type: str = "image/png") -> str:
    encoded = base64.b64encode(image_bytes).decode("ascii")
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="1100" height="680" viewBox="0 0 1100 680" role="img" aria-label="Graphic recording">
  <rect width="1100" height="680" fill="#ffffff" />
  <image href="data:{html.escape(mime_type)};base64,{encoded}" x="0" y="0" width="1100" height="680" preserveAspectRatio="xMidYMid meet" />
</svg>"""


def _extension_for_mime_type(mime_type: str) -> str:
    return {
        "image/png": ".png",
        "image/jpeg": ".jpg",
        "image/webp": ".webp",
    }.get(mime_type, ".bin")


def _point_node(index: int, point: str, accent: str) -> str:
    y = 230 + index * 72
    safe_point = html.escape(point[:48])
    return f"""
  <circle cx="774" cy="{y}" r="18" fill="{accent}" opacity="0.9" />
  <text x="768" y="{y + 6}" font-family="sans-serif" font-size="17" font-weight="800" fill="#ffffff">{index + 1}</text>
  <text x="808" y="{y + 5}" class="small">{safe_point}</text>"""
