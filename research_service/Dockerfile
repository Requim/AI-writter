FROM python:3.11-slim

ARG PIP_INDEX_URL=https://mirrors.aliyun.com/pypi/simple

WORKDIR /app

RUN pip install --no-cache-dir \
    --index-url "$PIP_INDEX_URL" \
    --default-timeout 180 \
    --retries 5 \
    "fastapi>=0.115.0" \
    "httpx>=0.27.0" \
    "pydantic>=2.0.0" \
    "pydantic-settings>=2.0.0" \
    "sqlalchemy[asyncio]>=2.0.0" \
    "asyncpg>=0.29.0" \
    "alembic>=1.13.0" \
    "uvicorn>=0.32.0"

COPY . /app/research_service

ENV PYTHONPATH=/app
CMD ["uvicorn", "research_service.api:app", "--host", "0.0.0.0", "--port", "8010"]
