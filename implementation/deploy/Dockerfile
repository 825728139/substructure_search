FROM python:3.12-slim-bookworm
RUN pip install --no-cache-dir uv==0.9.22
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY src ./src
RUN uv sync --frozen --no-dev --no-editable \
    && useradd --uid 10001 --create-home reference \
    && mkdir -p /app/var/runs && chown -R reference:reference /app/var
ENV PATH="/app/.venv/bin:$PATH" RR_STORE_PATH=/app/var/runs PYTHONDONTWRITEBYTECODE=1
USER reference
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health/live',timeout=3)"
CMD ["reaction-reference", "serve", "--host", "0.0.0.0", "--port", "8000"]
