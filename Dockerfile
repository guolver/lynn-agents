FROM python:3.10-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc libpq-dev && \
    rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md ./
COPY src/ ./src/

RUN pip install --no-cache-dir -e ".[dev]"

RUN mkdir -p /app/data

COPY alembic.ini ./
COPY alembic/ ./alembic/

EXPOSE 8000

CMD ["sh", "-c", "alembic upgrade head && uvicorn agent_hub.app:app --host 0.0.0.0 --reload --reload-dir src"]
