from __future__ import annotations

import asyncio
import base64
import gzip
import html
import ipaddress
import json
import logging
import os
import re
import socket
import zlib
from dataclasses import dataclass
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
_DEFAULT_PLAN_ITEMS = [
    "上部に記事タイトルを短く配置",
    "左側に 3 行要約を大きく配置",
    "右側に重要ポイントをアイコン付きノードで配置",
    "要約と重要ポイントの関係だけを矢印や線で整理する",
]


class ArticleSummary(BaseModel):
    summary_lines: list[str] = Field(
        description="Exactly three concise Japanese lines that summarize the article's story.",
        min_length=3,
        max_length=3,
    )
    key_points: list[str] = Field(
        description="Four to six Japanese article-reading notes for graphic recording material.",
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
    return os.getenv("BEDROCK_TEXT_MODEL_ID", "us.anthropic.claude-sonnet-4-20250514-v1:0")


def image_model_name() -> str:
    return os.getenv("BEDROCK_IMAGE_MODEL_ID", "")


async def fetch_article(url: str) -> dict[str, str]:
    """Fetch a public article URL and return its title plus cleaned article text.

    Args:
        url: Public HTTP or HTTPS article URL to fetch.

    Returns:
        A dictionary with `title` and cleaned `text` keys.
    """
    if is_mock_mode():
        host = urlparse(url).netloc or "example.com"
        title = f"{host} の記事から学ぶ AgentCore Runtime 活用"
        body = (
            "この記事は、企業内の業務アプリケーションに AI Agent を組み込む方法を紹介しています。"
            "Agent は URL から情報を取得し、要約、構造化、成果物生成までを一連の action として実行します。"
            "Strands Agents を使うと tool の責務を分けながら Agent の振る舞いを定義でき、"
            "Bedrock AgentCore Runtime に配置することで Web App から安定して呼び出せます。"
            "Amazon ECS Express Mode (Fargate) は FastAPI の Web フロントエンドを動かし、S3 は生成画像や SVG を保存します。"
            "デモではまず mock mode で外部 API に依存せず UX と処理順序を確認し、"
            "その後 Bedrock text model と image model に差し替えていきます。"
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
                "Strands では fetch / summarize / plan / render などの tool を分けて実装します。",
                "Phase 1 は mock mode と fallback SVG により、外部 API なしでデモ体験を確認します。",
            ],
            "key_points": [
                "記事取得、要約、構成案作成、画像生成を一つの流れとして扱い、利用者は URL を入力するだけで結果まで確認できます。",
                "Strands の tool を小さく分けることで、記事取得、要約、描画、保存といった責務を追いやすくしています。",
                "mock mode と fallback SVG により、外部 API が使えない場面でも画面遷移と体験を先に確認できます。",
                "生成画像は artifact として保存され、あとから S3 や presigned URL を使う構成へ広げられます。",
            ],
            "backend": "mock",
        }

    prompt = f"""次の記事を日本語で要約し、グラフィックレコーディングに使う記事理解メモを作ってください。

制約:
- summary_lines は必ず3行
- summary_lines は記事の論旨・ストーリーを自然な説明文で3行にまとめる
- key_points は4から6個
- key_points は summary_lines の言い換えにせず、記事をどう読めばよいかが分かる補足メモにする
- key_points は背景、流れ、筆者の主張、印象的な工夫、具体例、読後の示唆を自然文で表す
- key_points は1項目60から120文字程度まで許容し、短くしすぎて分類ラベルや施策名だけにならないようにする
- key_points に「技術:」「解決:」「数値:」のような分類ラベルを機械的に付けない。必要な場合だけ自然に使う
- 固有名詞や数値は、記事の理解や雰囲気に効く場合だけ含める
- 記事に書かれている内容だけを使い、ふわっとした趣旨と具体例の両方が残る表現にする
- 出力は指定 schema に厳密に従う

タイトル:
{title}

本文:
{article_text[:12000]}
"""
    try:
        summary = await _generate_structured_content(prompt, ArticleSummary)
    except Exception as exc:
        logger.warning("Bedrock summarize failed, falling back to heuristic: %s", exc)
        return _heuristic_summary(title, article_text, reason=str(exc))

    return {
        "summary_lines": summary.summary_lines[:3],
        "key_points": summary.key_points[:6],
        "backend": f"bedrock:{text_model_name()}",
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
        logger.warning("Bedrock style decision failed, falling back to heuristic: %s", exc)
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
- 3行要約は記事全体のストーリーとして、上部見出し・中央フロー・短い説明帯の材料にする
- 重要ポイントは記事理解メモとして読み取り、画像内では短いラベル、付箋、吹き出し、アイコン横の注釈に要約して使う
- 重要ポイントを分類付きの施策リストとして扱わず、記事の雰囲気、主張、流れ、具体例が伝わる構成にする
- 3行要約と重要ポイントを同じ粒度の文章ボックスとして並べない
- 画像内に表示する文字は 3行要約と重要ポイントの内容だけに限定する
- 記事内容ではない、アプリの処理手順・生成基盤・説明用の文脈を入れない
- 出力は指定 schema に厳密に従う
"""
    try:
        visual_plan = await _generate_structured_content(prompt, VisualPlan)
        return visual_plan.plan_items[:6]
    except Exception as exc:
        logger.warning("Bedrock visual plan failed, falling back to default plan: %s", exc)
        plan = _default_plan_items_for_style(style)
        if feedback.strip():
            plan.append(f"フィードバック反映: {feedback.strip()[:80]}")
        return plan


async def generate_image(
    visual_plan: list[str],
    summary_lines: Optional[list[str]] = None,
    key_points: Optional[list[str]] = None,
) -> str:
    """Generate a graphic recording image and return SVG-compatible markup.

    Args:
        visual_plan: Composition instructions for the image model.
        summary_lines: Article summary lines allowed as rendered text.
        key_points: Article key points allowed as rendered text.

    Returns:
        SVG markup wrapping the generated image, or an empty string on fallback.
    """
    image = await generate_image_artifact(
        visual_plan,
        summary_lines=summary_lines,
        key_points=key_points,
    )
    if not image.data:
        return ""
    return _render_image_svg(image.data, image.mime_type)


async def generate_image_artifact(
    visual_plan: list[str],
    style: str = "business",
    summary_lines: Optional[list[str]] = None,
    key_points: Optional[list[str]] = None,
) -> GeneratedImage:
    """Generate a graphic recording image with a Bedrock image model for artifact storage.

    Args:
        visual_plan: Composition instructions for the image model.
        style: Selected visual style used to tune the image prompt.
        summary_lines: Article summary lines allowed as rendered text.
        key_points: Article key points allowed as rendered text.

    Returns:
        Generated image bytes and metadata, or an empty payload that signals SVG fallback.
    """
    if is_mock_mode():
        return GeneratedImage(b"", "", "fallback-svg:mock-mode")
    if not image_model_name():
        message = "BEDROCK_IMAGE_MODEL_ID is not configured"
        logger.warning("Bedrock image generation skipped: %s", message)
        return GeneratedImage(b"", "", f"fallback-svg:{message}")
    if not has_bedrock_credentials():
        message = "credentials are not configured"
        logger.warning("Bedrock image generation skipped: %s", message)
        return GeneratedImage(b"", "", f"fallback-svg:{message}")

    allowed_summary = summary_lines or []
    allowed_points = key_points or []
    prompt = f"""日本語のグラフィックレコーディング画像を生成してください。

目的:
- 記事の 3 行要約を全体ストーリー、重要ポイントを図解素材として使い、1枚の読みやすいグラフィックレコーディングとして表現する
- アプリケーションや生成システムの説明ではなく、記事内容そのものを図解する

画像内に表示してよい文字:
3行要約（全体ストーリーの材料）:
{chr(10).join(f"- {line}" for line in allowed_summary) or "- 3行要約"}

重要ポイント（記事理解メモ。必要に応じて短い表示文に要約する）:
{chr(10).join(f"- {point}" for point in allowed_points) or "- 重要ポイント"}

構成案（配置の参考のみ。構成案の文言は画像に書かない）:
{chr(10).join(f"- {item}" for item in visual_plan)}

選択スタイル:
{style}

スタイル指針:
{_style_image_directive(style)}

表現:
- 16:9 の横長
- 白背景、読みやすい太線、アイコン、矢印、付箋風メモ
- 日本語テキストは短く、大きく、読みやすく
- 3行要約は上部の短いストーリー帯、または中央の大きな流れとして扱う
- 重要ポイントは記事理解メモとして使い、画像内では付箋、吹き出し、キーワードチップ、アイコン横ラベルに短く言い換える
- 重要ポイントをそのまま長文で全部書かず、趣旨、印象的な例、流れ、示唆が伝わる短い表現に圧縮する
- 選択スタイルに合わせ、business は構造を明快に、pop は親しみやすく、minimal は余白と少数要素で表現する
- 3行要約と重要ポイントを同じ大きさの文章ボックスで並べるだけの構図にしない
- 表、長文カード、資料スライド風の箱詰めレイアウトに寄せすぎず、流れ・関係・対比・階層が見える構図にする
- 記事本文にないアプリの処理手順、生成基盤、説明用の文脈、構成案ラベルなどの語句を画像内に追加しない
- 見出しは「3行要約」「重要ポイント」など記事内容を示すものだけにする
- 選択スタイルと矛盾する色や装飾を混ぜない
"""
    try:
        image_bytes, mime_type = await _generate_image_data(prompt)
    except Exception as exc:
        logger.warning("Bedrock image generation failed, falling back to SVG: %s", exc)
        return GeneratedImage(b"", "", f"fallback-svg:{str(exc)[:120]}")

    if not image_bytes:
        message = "no image parts returned"
        logger.warning("Bedrock image generation returned %s", message)
        return GeneratedImage(b"", "", f"fallback-svg:{message}")

    return GeneratedImage(
        image_bytes,
        mime_type,
        f"bedrock:{display_model_name(image_model_name())}",
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
        visual_plan: Kept for workflow API symmetry; not rendered in the fallback SVG.
        feedback: Optional user feedback from regeneration.
        style: Selected visual style.

    Returns:
        SVG markup for the generated fallback artifact.
    """
    palette = _style_palette(style, feedback)
    accent = palette["accent"]
    title_node = _title_node(title)
    summary_items = "".join(
        _summary_node(i, line)
        for i, line in enumerate(summary_lines)
    )
    point_items = "".join(
        _point_node(i, point, accent)
        for i, point in enumerate(key_points[:6])
    )

    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="1100" height="680" viewBox="0 0 1100 680" role="img" aria-label="Graphic recording">
  <style>
    .bg {{ fill: #f8fafc; }}
    .panel {{ fill: #ffffff; stroke: #cbd5e1; stroke-width: 2; }}
    .title {{ font: 800 30px sans-serif; fill: #ffffff; }}
    .label {{ font: 700 16px sans-serif; fill: #475569; }}
    .summary {{ font: 600 18px sans-serif; fill: #0f172a; }}
    .small {{ font: 500 14px sans-serif; fill: #334155; }}
    .arrow {{ stroke: #64748b; stroke-width: 3; fill: none; marker-end: url(#arrow); }}
  </style>
  <defs>
    <marker id="arrow" markerWidth="10" markerHeight="10" refX="8" refY="3" orient="auto">
      <path d="M0,0 L0,6 L9,3 z" fill="#64748b" />
    </marker>
  </defs>
  <rect width="1100" height="680" rx="0" fill="{palette["background"]}" />
  <rect x="40" y="36" width="1020" height="92" rx="8" fill="{accent}" />
  {title_node}

  <rect class="panel" x="54" y="150" width="640" height="410" rx="8" />
  <text x="78" y="180" class="label">3行要約</text>
  {summary_items}

  <rect class="panel" x="732" y="150" width="314" height="410" rx="8" />
  <text x="758" y="184" class="label">重要ポイント</text>
  {point_items}
</svg>"""


async def save_artifact(session_id: str, svg: str) -> str:
    """Save a generated SVG artifact locally and optionally mirror it to S3.

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
    signed_url = await _upload_artifact_to_s3(path, "image/svg+xml")
    return str(path), signed_url


async def save_binary_artifact(session_id: str, data: bytes, mime_type: str) -> str:
    """Save a generated binary artifact locally and optionally mirror it to S3.

    Args:
        session_id: Stable session identifier used as the artifact filename.
        data: Binary artifact bytes.
        mime_type: MIME type for file extension and S3 metadata.

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
    signed_url = await _upload_artifact_to_s3(path, mime_type)
    return str(path), signed_url


def artifact_url_for_path(artifact_path: str) -> str:
    return f"/artifacts/{Path(artifact_path).name}"


async def _upload_artifact_to_s3(path: Path, content_type: str) -> str:
    bucket_name = os.getenv("S3_BUCKET")
    if not bucket_name:
        return ""

    def upload() -> str:
        import boto3

        prefix = os.getenv("S3_ARTIFACT_PREFIX", "artifacts").strip("/")
        object_key = f"{prefix}/{path.name}" if prefix else path.name
        client = boto3.client("s3")
        client.upload_file(
            str(path),
            bucket_name,
            object_key,
            ExtraArgs={"ContentType": content_type},
        )
        return client.generate_presigned_url(
            "get_object",
            Params={"Bucket": bucket_name, "Key": object_key},
            ExpiresIn=signed_artifact_url_ttl_seconds(),
        )

    try:
        return await asyncio.to_thread(upload)
    except Exception as exc:
        logger.warning("S3 artifact upload failed: %s", exc)
        return ""


def signed_artifact_url_ttl_seconds() -> int:
    value = os.getenv("S3_PRESIGNED_URL_TTL_SECONDS", "28800")
    try:
        return max(60, int(value))
    except ValueError:
        return 28800


async def _fetch_public_url(url: str) -> httpx.Response:
    current_url = url
    headers = {
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Encoding": "identity",
        "User-Agent": "BedrockAgentCoreWorkshop/1.0",
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
                max_bytes = article_fetch_max_bytes()
                raw_content = await _read_limited_response(response, max_bytes)
                content = _decode_response_content(raw_content, response.headers, max_bytes)
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


def _decode_response_content(raw_content: bytes, headers: httpx.Headers, max_bytes: int) -> bytes:
    encoding = headers.get("content-encoding", "").lower().strip()
    if not encoding or encoding == "identity":
        if len(raw_content) > max_bytes:
            raise ValueError(f"Article response exceeds {max_bytes} bytes")
        return raw_content

    try:
        if encoding == "gzip":
            decoded = gzip.decompress(raw_content)
            if len(decoded) > max_bytes:
                raise ValueError(f"Article response exceeds {max_bytes} bytes")
            return decoded
        if encoding == "deflate":
            decoded = zlib.decompress(raw_content)
            if len(decoded) > max_bytes:
                raise ValueError(f"Article response exceeds {max_bytes} bytes")
            return decoded
    except (OSError, zlib.error) as exc:
        logger.warning(
            "Ignoring invalid Content-Encoding=%s while fetching article: %s",
            encoding,
            exc,
        )
        if len(raw_content) > max_bytes:
            raise ValueError(f"Article response exceeds {max_bytes} bytes")
        return raw_content

    logger.warning("Ignoring unsupported Content-Encoding=%s while fetching article", encoding)
    if len(raw_content) > max_bytes:
        raise ValueError(f"Article response exceeds {max_bytes} bytes")
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
    if not has_bedrock_credentials():
        raise RuntimeError("AWS credentials for Bedrock are required")

    schema = schema_model.model_json_schema()
    structured_prompt = f"""{prompt}

Return only JSON that conforms to this JSON Schema:
{json.dumps(schema, ensure_ascii=False)}
"""
    response_text = await _call_with_retries(
        lambda: _invoke_bedrock_text_model(structured_prompt),
        operation="bedrock-structured-content",
    )
    return schema_model.model_validate_json(_extract_json_object(response_text))


async def _generate_image_data(prompt: str) -> tuple[bytes, str]:
    return await _call_with_retries(
        lambda: _invoke_bedrock_image_model(prompt),
        operation="bedrock-image-generation",
    )


async def _invoke_bedrock_text_model(prompt: str) -> str:
    def invoke() -> str:
        import boto3

        client = boto3.client(
            "bedrock-runtime",
            region_name=os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION") or "us-east-1",
        )
        response = client.invoke_model(
            modelId=text_model_name(),
            contentType="application/json",
            accept="application/json",
            body=json.dumps(
                {
                    "anthropic_version": "bedrock-2023-05-31",
                    "max_tokens": 2048,
                    "temperature": 0.2,
                    "messages": [{"role": "user", "content": [{"type": "text", "text": prompt}]}],
                }
            ),
        )
        payload = _read_bedrock_body(response)
        content = payload.get("content") or []
        texts = [part.get("text", "") for part in content if isinstance(part, dict)]
        return "\n".join(text for text in texts if text).strip()

    return await asyncio.to_thread(invoke)


async def _invoke_bedrock_image_model(prompt: str) -> tuple[bytes, str]:
    def invoke() -> tuple[bytes, str]:
        import boto3

        client = boto3.client(
            "bedrock-runtime",
            region_name=os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION") or "us-east-1",
        )
        response = client.invoke_model(
            modelId=image_model_name(),
            contentType="application/json",
            accept="application/json",
            body=json.dumps(_bedrock_image_request(prompt)),
        )
        payload = _read_bedrock_body(response)
        image_data = (
            payload.get("images", [None])[0]
            or payload.get("artifacts", [{}])[0].get("base64")
            or payload.get("image")
        )
        if not image_data:
            return b"", "image/png"
        return base64.b64decode(image_data), "image/png"

    return await asyncio.to_thread(invoke)


def _bedrock_image_request(prompt: str) -> dict[str, object]:
    model = image_model_name().lower()
    if "stability" in model or "stable" in model:
        return {
            "text_prompts": [{"text": prompt}],
            "cfg_scale": 8,
            "height": 768,
            "width": 1344,
            "samples": 1,
        }
    return {
        "taskType": "TEXT_IMAGE",
        "textToImageParams": {"text": prompt},
        "imageGenerationConfig": {
            "numberOfImages": 1,
            "height": 768,
            "width": 1344,
            "cfgScale": 8,
        },
    }


def _read_bedrock_body(response: dict[str, object]) -> dict[str, object]:
    body = response.get("body")
    raw = body.read() if hasattr(body, "read") else body
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8")
    if isinstance(raw, str):
        parsed = json.loads(raw)
        if isinstance(parsed, dict):
            return parsed
    if isinstance(raw, dict):
        return raw
    return {}


def _extract_json_object(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = stripped.strip("`")
        stripped = re.sub(r"^json\s*", "", stripped, flags=re.I).strip()
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start >= 0 and end > start:
        return stripped[start : end + 1]
    return stripped


def close_bedrock_client() -> None:
    return None


async def _call_with_retries(operation_factory, operation: str):
    max_attempts = max(1, int(os.getenv("BEDROCK_MAX_ATTEMPTS", "3")))
    base_delay = max(0.1, float(os.getenv("BEDROCK_RETRY_BASE_DELAY_SECONDS", "0.6")))
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


def has_bedrock_credentials() -> bool:
    if os.getenv("AWS_ACCESS_KEY_ID") and os.getenv("AWS_SECRET_ACCESS_KEY"):
        return True
    if os.getenv("AWS_PROFILE") or os.getenv("AWS_CONTAINER_CREDENTIALS_RELATIVE_URI"):
        return True
    if os.getenv("AWS_WEB_IDENTITY_TOKEN_FILE") and os.getenv("AWS_ROLE_ARN"):
        return True
    return False


def article_fetch_max_bytes() -> int:
    try:
        return max(1024, int(os.getenv("ARTICLE_FETCH_MAX_BYTES", str(DEFAULT_ARTICLE_FETCH_MAX_BYTES))))
    except ValueError:
        return DEFAULT_ARTICLE_FETCH_MAX_BYTES


def display_model_name(model_name: str) -> str:
    labels = {
        "amazon.nova-canvas-v1:0": "amazon.nova-canvas-v1:0 (Nova Canvas)",
        "stability.stable-image-core-v1:0": "stability.stable-image-core-v1:0 (Stable Image Core)",
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
    key_points = _heuristic_key_points(compact[3:9] or summary)
    return {
        "summary_lines": summary[:3],
        "key_points": key_points[:6],
        "backend": f"heuristic:{reason[:80]}" if reason else "heuristic",
    }


def _heuristic_key_points(sentences: list[str]) -> list[str]:
    points: list[str] = []
    for sentence in sentences[:6]:
        cleaned = sentence.strip().rstrip("。.!?")
        if not cleaned:
            continue
        if len(cleaned) > 110:
            cleaned = f"{cleaned[:109]}..."
        points.append(f"{cleaned}。")
    return points


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
    return StyleDecision(style="business", reason=f"{reason_prefix}: 記事内容を構造化して見せる図解が合うため。")


def _default_plan_items_for_style(style: str) -> list[str]:
    if style == "pop":
        return [
            "上部に記事タイトルを明るい見出しとして配置",
            "中央に 3 行要約を付箋風の大きな吹き出しで配置",
            "右側に重要ポイントをカラフルなノードで配置",
            "要約と重要ポイントのつながりを親しみやすい矢印で描く",
        ]
    if style == "minimal":
        return [
            "上部に記事タイトルと 3 行要約を余白多めに配置",
            "中央に記事の主要概念だけを細い線で整理",
            "右側に重要ポイントを少数のシンプルなラベルで配置",
            "補足要素は足さず、要約と重要ポイントの関係だけを控えめに示す",
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


def _title_node(title: str) -> str:
    tspans = _svg_tspans(title, x=72, first_y=76, max_chars=34, max_lines=2, line_gap=34)
    return f'<text class="title">{tspans}</text>'


def _summary_node(index: int, line: str) -> str:
    y = 224 + index * 108
    text = f"{index + 1}. {line}"
    tspans = _svg_tspans(text, x=78, first_y=y, max_chars=29, max_lines=3, line_gap=22)
    return f'<text class="summary">{tspans}</text>'


def _point_node(index: int, point: str, accent: str) -> str:
    y = 220 + index * 56
    tspans = _svg_tspans(point, x=808, first_y=y - 14, max_chars=13, max_lines=2, line_gap=16)
    return f"""
  <circle cx="774" cy="{y}" r="18" fill="{accent}" opacity="0.9" />
  <text x="768" y="{y + 6}" font-family="sans-serif" font-size="17" font-weight="800" fill="#ffffff">{index + 1}</text>
  <text class="small">{tspans}</text>"""


def _svg_tspans(text: str, x: int, first_y: int, max_chars: int, max_lines: int, line_gap: int) -> str:
    lines = _wrap_svg_text(text, max_chars=max_chars, max_lines=max_lines)
    return "".join(
        f'<tspan x="{x}" y="{first_y + i * line_gap}">{html.escape(line)}</tspan>'
        for i, line in enumerate(lines)
    )


def _wrap_svg_text(text: str, max_chars: int, max_lines: int) -> list[str]:
    compact = re.sub(r"\s+", " ", text).strip()
    if not compact:
        return [""]

    lines: list[str] = []
    remaining = compact
    while remaining and len(lines) < max_lines:
        if len(remaining) <= max_chars:
            lines.append(remaining)
            remaining = ""
            break
        split_at = remaining.rfind(" ", 0, max_chars + 1)
        if split_at < max_chars // 2:
            split_at = max_chars
        lines.append(remaining[:split_at].strip())
        remaining = remaining[split_at:].strip()

    if remaining and lines:
        lines[-1] = lines[-1].rstrip("。,.、") + "..."
    return lines
