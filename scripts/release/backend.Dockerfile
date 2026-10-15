ARG BASE_IMAGE=novel-writer-backend:materials-20260922-r2
FROM ${BASE_IMAGE}
WORKDIR /app
RUN find /app -mindepth 1 -maxdepth 1 ! -name .venv -exec rm -rf -- {} +
COPY writter_back/pyproject.toml writter_back/uv.lock ./
RUN uv export --frozen --no-dev --no-hashes --no-emit-project \
    | uv pip sync --python /app/.venv/bin/python \
        --index-url https://mirrors.aliyun.com/pypi/simple -
COPY writter_back/ ./
RUN find /app -type d -name __pycache__ -prune -exec rm -rf -- {} + \
    && sed -i 's/\r$//' /app/docker-entrypoint.sh \
    && chmod +x /app/docker-entrypoint.sh
ARG SOURCE_SHA256
LABEL novel-writer.source-sha256=${SOURCE_SHA256}
ENTRYPOINT ["/app/docker-entrypoint.sh"]
