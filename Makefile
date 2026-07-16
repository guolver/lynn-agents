.PHONY: setup dev dev-api dev-web lint lint-py lint-fe test test-py format clean

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
	. .venv/bin/activate && ruff check src/ tests/

lint-fe: ## 前端 lint (eslint)
	cd frontend && pnpm lint

test: test-py ## 运行所有测试

test-py: ## Python 单元测试
	. .venv/bin/activate && python -m unittest discover -s tests -v

format: ## 格式化代码
	. .venv/bin/activate && ruff format src/ tests/
	. .venv/bin/activate && ruff check --fix src/ tests/

# — 清理 ————————————————————————————————————

clean: ## 清理构建产物
	rm -rf .venv/ .pytest_cache/ .ruff_cache/ __pycache__/
	rm -rf frontend/.next/ frontend/node_modules/
	rm -rf node_modules/

# — 帮助 ————————————————————————————————————

help: ## 显示帮助
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-15s\033[0m %s\n", $$1, $$2}'
