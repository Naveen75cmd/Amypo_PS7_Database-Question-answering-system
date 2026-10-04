# Convenience wrapper. `make` is optional on Windows — the README lists the
# equivalent direct commands for every target below.

PY ?= python
BACKEND = cd backend &&
FRONTEND = cd frontend &&

.PHONY: install install-frontend db db-down seed ingest index api web dev test test-backend eval clean

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
	$(BACKEND) $(PY) -m app.eval.answer_eval

clean:
	rm -rf data/artifacts data/index
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
