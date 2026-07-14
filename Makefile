.PHONY: backend frontend desktop-build test lint

backend:
	cd backend && uvicorn app.main:app --reload

frontend:
	cd frontend && pnpm dev

desktop-build:
	cd frontend && pnpm desktop:build

test:
	cd backend && uv run python -m pytest

lint:
	cd backend && uv run ruff check app tests
	cd frontend && pnpm typecheck
