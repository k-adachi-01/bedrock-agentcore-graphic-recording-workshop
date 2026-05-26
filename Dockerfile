FROM python:3.11-slim
COPY --from=ghcr.io/astral-sh/uv:0.5.31 /uv /usr/local/bin/uv

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PORT=8080

WORKDIR /app

RUN addgroup --system app && adduser --system --ingroup app app

COPY requirements.txt constraints-workshop.txt ./
RUN uv pip install --system --no-cache -r requirements.txt -c constraints-workshop.txt

COPY . .

RUN chown -R app:app /app
USER app

CMD ["sh", "-c", "uvicorn web.main:app --host 0.0.0.0 --port ${PORT}"]
