# Convenience wrapper. `make` is optional on Windows — the README lists the
# equivalent direct commands for every target below.

PY ?= python
BACKEND = cd backend &&
FRONTEND = cd frontend &&

.PHONY: install install-frontend db db-down models seed ingest index api web dev test test-backend eval artefacts guides clean

install:
	$(PY) -m pip install -r backend/requirements.txt

install-frontend:
	$(FRONTEND) npm install

# Start MySQL alone and wait until its healthcheck passes. Everything else can
# then run against it from the host.
db:
	docker compose up -d --wait mysql

db-down:
	docker compose down

# Pull the local model into the Ollama *container* (its own model store).
# A pull from the host's Ollama app does not reach the container, which is the
# usual reason the dashboard says "model not pulled".
models:
	docker compose run --rm ollama-pull

seed:
	$(PY) scripts/generate_data.py

ingest:
	$(BACKEND) $(PY) -m app.ingest --path ../data/raw --structured ../data/synthetic

index:
	$(BACKEND) $(PY) -m app.retrieval

api:
	$(BACKEND) $(PY) -m uvicorn app.main:app --reload --port 8000

web:
	$(FRONTEND) npm run dev

dev:
	@echo "Run 'make api' and 'make web' in two terminals."

test-backend:
	$(BACKEND) $(PY) -m pytest

test:
	$(BACKEND) $(PY) -m pytest
	$(FRONTEND) npm run typecheck

eval:
	$(BACKEND) $(PY) ../scripts/evaluate.py

# Submission pack: architecture diagram, one-page summary, Postman collection.
# The summary reads docs/eval/report.json, so run `make eval` first.
artefacts:
	$(PY) scripts/make_artifacts.py

# Product guide, user manual and manual test guide (PDF). All three read the
# repo, so they cannot drift from the code or from the last evaluation report.
guides:
	$(PY) scripts/make_guides.py

clean:
	rm -rf data/artifacts data/index
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
