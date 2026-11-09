# Local development runs in Docker (Linux, like Vercel). See README.md.
RUN = docker compose run --rm app uv run --frozen

.PHONY: up down test lint format css css-watch migrate migration invite-admin requirements

up:            ## serve http://localhost:8000 with auto-reload
	docker compose up --build

down:
	docker compose down

test:
	$(RUN) pytest

lint:
	$(RUN) ruff check .
	$(RUN) ruff format --check .

format:
	$(RUN) ruff format .
	$(RUN) ruff check --fix .

css:
	$(RUN) python scripts/build_css.py

css-watch:
	$(RUN) python scripts/build_css.py --watch

migrate:       ## apply migrations to DATABASE_URL (your dev branch, from .env)
	$(RUN) alembic upgrade head

migration:     ## make migration m="describe the change"
	$(RUN) alembic revision --autogenerate -m "$(m)"

invite-admin:  ## one-time admin passkey setup link for the dev database
	$(RUN) python -m app.cli invite --admin

requirements:  ## regenerate requirements.txt after changing dependencies
	uv export --no-dev --no-hashes --no-emit-project --format requirements-txt -o requirements.txt
