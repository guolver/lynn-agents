.PHONY: setup dev dev-api dev-web lint lint-py lint-fe test test-py test-pg test-neo4j test-worker worker format clean infra infra-up infra-down migrate up down logs

# — 初始化 ————————————————————————————————————

setup: ## 完整初始化：虚拟环境 + 后端依赖 + 前端依赖
	python3 -m venv .venv
	. .venv/bin/activate && pip install -e '.[dev]'
	cd frontend && corepack enable && pnpm install
	cp -n .env.example .env 2>/dev/null || true
	cp -n frontend/.env.example frontend/.env.local 2>/dev/null || true
	npm install

# — 开发 ————————————————————————————————————

dev: ## 同时启动后端和前端
	@$(MAKE) dev-api &
	@$(MAKE) dev-web

dev-api: ## 启动后端 (FastAPI)
	. .venv/bin/activate && uvicorn agent_hub.app:app --reload

dev-web: ## 启动前端 (Next.js)
	cd frontend && pnpm dev

# — 代码质量 ————————————————————————————————————

lint: lint-py lint-fe ## 全量代码检查

lint-py: ## Python lint (ruff)
	. .venv/bin/activate && ruff check agent_hub/ tests/

lint-fe: ## 前端 lint (eslint)
	cd frontend && pnpm lint

test: test-py ## 运行所有测试

test-py: ## Python 单元测试（不需要 PostgreSQL）
	. .venv/bin/activate && python -m unittest discover -s tests -v

test-pg: ## PostgreSQL 集成测试（需要运行 make infra-up && make migrate）
	. .venv/bin/activate && TEST_DATABASE_URL=postgresql+psycopg://agent_hub:agent_hub@127.0.0.1:5432/agent_hub_test \
		python -m unittest tests.test_postgres_repository tests.test_postgres_concurrency tests.test_postgres_workflow -v

test-worker: ## Celery 集成测试（需要 Redis + PostgreSQL）
	. .venv/bin/activate && TEST_DATABASE_URL=postgresql+psycopg://agent_hub:agent_hub@127.0.0.1:5432/agent_hub_test \
		python -m unittest tests.test_celery_tasks tests.test_workflow_tracker tests.test_error_classification -v

test-neo4j: ## Neo4j skill graph integration tests (requires Docker image neo4j:5)
	. .venv/bin/activate && python -m pytest tests/test_skill_graph.py -v

worker: ## 启动 Celery worker
	. .venv/bin/activate && celery -A agent_hub.worker.celery_app:celery_app worker \
		--loglevel=info --concurrency=2

# — Docker 全栈 ————————————————————————————————————

up: ## 全栈启动（前后端 + 基础设施）
	docker compose up -d --build --wait

down: ## 全栈停止
	docker compose down

logs: ## 查看全栈日志
	docker compose logs -f

# — 基础设施 ————————————————————————————————————

infra-up: infra ## 启动本地 PostgreSQL 和 Redis
infra: ## 启动本地 PostgreSQL、Redis 和 Neo4j
	docker compose up -d --wait postgres redis neo4j

infra-down: ## 停止基础设施（保留数据卷）
	docker compose down

migrate: ## 应用数据库迁移
	. .venv/bin/activate && DATABASE_URL=postgresql+psycopg://agent_hub:agent_hub@127.0.0.1:5432/agent_hub \
		alembic upgrade head

format: ## 格式化代码
	. .venv/bin/activate && ruff format agent_hub/ tests/
	. .venv/bin/activate && ruff check --fix agent_hub/ tests/

# — 清理 ————————————————————————————————————

clean: ## 清理构建产物
	rm -rf .venv/ .pytest_cache/ .ruff_cache/ __pycache__/
	rm -rf frontend/.next/ frontend/node_modules/
	rm -rf node_modules/

# — 帮助 ————————————————————————————————————

help: ## 显示帮助
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-15s\033[0m %s\n", $$1, $$2}'
