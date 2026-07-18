FROM python:3.10-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc libpq-dev && \
    rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md ./
COPY src/ ./src/

# 国内网络可用 --build-arg PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple 加速
ARG PIP_INDEX_URL=https://pypi.org/simple
# 环境变量形式对 build-isolation 子进程同样生效
ENV PIP_INDEX_URL=${PIP_INDEX_URL} PIP_RETRIES=10 PIP_DEFAULT_TIMEOUT=120

RUN pip install --no-cache-dir -e ".[dev]"

RUN mkdir -p /app/data

COPY alembic.ini ./
COPY alembic/ ./alembic/

EXPOSE 8000

CMD ["sh", "-c", "alembic upgrade head && uvicorn agent_hub.app:app --host 0.0.0.0 --reload --reload-dir src"]
