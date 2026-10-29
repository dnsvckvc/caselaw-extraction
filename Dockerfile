# API image (week 4). Installs the core dependencies only (no torch, spaCy or MLflow: those
# are the `ml` extra) and serves the FastAPI app on port 8000 against Postgres. The same image
# runs the loader (`caselaw db-load --runs-dir s3://...`) as a one-off Fargate task.
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS build
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
COPY pyproject.toml uv.lock README.md ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project --no-editable
COPY src ./src
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-editable

FROM python:3.12-slim-bookworm
WORKDIR /app
RUN useradd --create-home --uid 1000 app
COPY --from=build --chown=app:app /app/.venv /app/.venv
USER app
ENV PATH="/app/.venv/bin:$PATH" PYTHONUNBUFFERED=1 CASELAW_BACKEND=postgres CASELAW_RUN=regex-v0.4
EXPOSE 8000
CMD ["uvicorn", "caselaw_extraction.api:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
