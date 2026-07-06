.PHONY: backend frontend test lint

backend:
	cd backend && uvicorn app.main:app --reload

frontend:
	cd frontend && pnpm dev

test:
	cd backend && pytest

lint:
	cd backend && ruff check app tests
	cd frontend && pnpm typecheck

