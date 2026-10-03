# Convenience wrapper. `make` is optional on Windows — the README lists the
# equivalent direct commands for every target below.

PY ?= python
BACKEND = cd backend &&
FRONTEND = cd frontend &&

.PHONY: install install-frontend seed ingest index api web dev test test-backend eval clean

install:
	$(PY) -m pip install -r backend/requirements.txt

install-frontend:
	$(FRONTEND) npm install

seed:
	$(PY) scripts/generate_data.py

ingest:
	$(BACKEND) $(PY) -m app.ingest --path ../data/raw

index:
	$(BACKEND) $(PY) -m app.retrieval.build_index

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
	$(PY) scripts/evaluate.py

clean:
	rm -rf data/*.db data/*.db-wal data/*.db-shm data/artifacts data/index
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
