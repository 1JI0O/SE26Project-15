.PHONY: backend frontend desktop-build test lint core-test extension-build extension-dev extension-bundle

backend:
	cd backend && uvicorn app.main:app --reload

frontend:
	cd frontend && pnpm dev

desktop-build:
	cd frontend && pnpm desktop:build

core-test:
	cd packages/tracelab_core && uv sync --extra dev && uv run pytest -q

extension-bundle:
	bash scripts/bundle_vscode_runtime.sh

extension-build: extension-bundle
	cd vscode-extension && npm install && npm run compile

extension-dev: extension-build
	code --extensionDevelopmentPath=vscode-extension

test: core-test
	cd backend && uv run python -m pytest

lint:
	cd backend && uv run ruff check app tests
	cd packages/tracelab_core && uv run ruff check tracelab_core tests
	cd frontend && pnpm typecheck
	cd vscode-extension && npm run compile
