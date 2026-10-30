FROM python:3.12-slim-bookworm
# RDKit 绘图扩展仍依赖系统共享库，精简基底未包含这些库。
RUN apt-get update \
    && apt-get install -y --no-install-recommends libxrender1 libxext6 libexpat1 \
    && rm -rf /var/lib/apt/lists/*
# 可按构建环境选择公开 Python 包镜像，参数只在构建阶段使用。
ARG PIP_INDEX_URL=https://pypi.org/simple
ARG PIP_DEFAULT_TIMEOUT=120
RUN pip install --no-cache-dir uv==0.9.22
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY src ./src
RUN uv sync --frozen --no-dev --no-editable \
    && .venv/bin/python -c "from rdkit.Chem.Draw import rdMolDraw2D" \
    && useradd --uid 10001 --create-home reference \
    && mkdir -p /app/var/runs && chown -R reference:reference /app/var
ENV PATH="/app/.venv/bin:$PATH" RR_STORE_PATH=/app/var/runs PYTHONDONTWRITEBYTECODE=1
USER reference
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health/live',timeout=3)"
CMD ["reaction-reference", "serve", "--host", "0.0.0.0", "--port", "8000"]
