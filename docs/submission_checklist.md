# Submission checklist — AMYPO (PS7 + PS1)

Phase 10, submission item 10. Every row is evidence, not intent: the column on
the right is the command or request that proves it, run on this machine.

> Note: the repository does not contain the PS7 problem statement itself, so the
> rows below are the "Hard constraints", "Required API contract" and Phase 1–10
> deliverables transcribed from `PS7_PS1_Build_Prompts (1).md`. Tick these
> against the original PS7 document before submitting in case it lists further
> items.

## A. Hard constraints

| # | Requirement | Status | Evidence |
|---|---|---|---|
| A1 | No paid or external third-party API anywhere | ✅ | Autouse socket guard in `backend/tests/conftest.py`; the same guard in `scripts/evaluate.py`. `make eval` raises on a non-loopback connection |
| A2 | `cloud_api` route is a local simulator (quota, pricing, injected latency/failures) | ✅ | `GET /api/v1/resource-status` reports quota; `/api/v1/simulate` replays scenarios; no socket involved |
| A3 | Open-weight local models only, CPU-only, 8 GB total | ✅ | `docs/model_card.md` §4; eval reports peak RSS 179 MB and `docker-compose.yml` limits sum to 7.5 GB |
| A4 | Every answer carries citations (record_id + snippet); ungrounded answers refused or flagged | ✅ | `/api/v1/ask` returns `sources[]`; the verifier flags unsupported claims in the UI and abstains when nothing is supportable |
| A5 | Runs offline and starts with one command | ✅ | `docker compose up` (mysql + backend + frontend + ollama); `README.md` has the one-command path and the offline pre-pull notes |

## B. Required API contract

| # | Endpoint | Status | Evidence |
|---|---|---|---|
| B1 | `POST /ask` → `{answer, sources[{record_id,snippet}], confidence}` | ✅ | Live call returns all three; extra fields documented in `openapi.yaml` |
| B2 | `GET /health` | ✅ | `GET /api/v1/health` → `{"status":"ok", ...}` with per-component detail |
| B3 | `POST /route` → `{request_id, routed_to, reasoning, latency_ms, estimated_cost}` | ✅ | `POST /api/v1/route`; response shape pinned by `tests/test_router.py` |
| B4 | `GET /resource-status` → `{ram_available_mb, cpu_load_pct, bandwidth_kbps, api_quota_remaining}` | ✅ | Live call returns exactly those keys |
| B5 | Extra response fields documented in `openapi.yaml` | ✅ | `tests/test_contract.py` + `tests/test_phase8_addons.py::test_contract_yaml_documents_the_new_addon_fields` compare the spec against the response models |

## C. Phase 10 deliverables

| # | Deliverable | Status | Evidence |
|---|---|---|---|
| C1 | `docker-compose.yml` with mysql (volume, healthcheck, init scripts), backend, frontend, ollama, `mem_limit`s | ✅ | `docker compose up -d --wait mysql` reaches healthy; limits sum to 7.5 GB |
| C2 | `README.md`: prerequisites, one-command start, offline setup, seed data, eval, ports, troubleshooting, structure | ✅ | See `README.md` |
| C3 | `openapi.yaml` complete + Postman collection | ✅ | 16 documented paths; `python scripts/make_artifacts.py --only postman` → `docs/postman_collection.json` (16 items derived from the spec) |
| C4 | Architecture diagram (PNG + PDF) | ✅ | `docs/architecture.png` (1746×1167), `docs/architecture.pdf` — regenerate with `make artefacts` |
| C5 | Model / technique card | ✅ | `docs/model_card.md` |
| C6 | Evaluation report | ✅ | `make eval` → `docs/eval/report.html` + `report.json` (Phase 9) |
| C7 | One-page final summary (PDF) | ✅ | `docs/final_summary.pdf`, built from the eval report by `make artefacts` |
| C8 | Demo video script (3–5 min) with click path | ✅ | `docs/demo_script.md` |
| C9 | Clean git history, conventional commits, tagged milestones | ✅ | Phase 8/9/10 committed in three conventional commits (`feat: complete the Phase 8 add-ons…`, `feat(eval): add the Phase 9 harness…`, `docs: add the Phase 10 submission pack…`); `git tag -n1` → `stage1`, `stage2-mvp`, `final`. History is local: the repo has no remote |
| C10 | Final checklist + "no external network call" proof | ✅ | This file, plus the guards in A1 |

## D. Judging criteria sanity check

| Criterion | Where it is proved |
|---|---|
| Answer accuracy / groundedness (PS7) | `docs/eval/report.json` → `answers.accuracy`, `answers.groundedness` |
| Retrieval precision@k / recall / MRR | `docs/eval/report.json` → `retrieval`, plus the dense/BM25/hybrid ablation |
| Hallucination rate | `docs/eval/report.json` → `answers.hallucination_rate` (5.4 %), `failure_analysis` |
| Abstention on unanswerable questions | `answers.abstention_rate_unanswerable` (60.9 %, 14/23) with `retrieval_relevance_floor` swept in model card §3 |
| Cost/latency reduction vs always-cloud (PS1) | `routing.cumulative_cost_inr` vs `always_cloud_cost_inr` (≈ 98.9 % saved) |
| Routing accuracy | `routing.agreement` against oracle labels — 100.0 % on the last full run (`docs/eval/report.json`, 2026-10-13) |
| Resource adaptivity | `scenarios` (ram crash, bandwidth drop, quota exhausted, Ollama down) 6/6 |
| Engineering quality | Typed contracts, `tests/test_contract.py`, module-level tests, `docs/model_card.md` limitations section |

## E. Known gaps at submission time

1. **One working-tree change is deliberately left uncommitted**: the tracked
   `PS7_PS1_Build_Prompts.md` is deleted and a newer
   `PS7_PS1_Build_Prompts (1).md` sits beside it. That is the owner's own copy of
   the problem statement, so it is left exactly as found rather than restaged.
2. **Item 5's tier 2 is inert**: `tinyllama` is not pulled, so degradation jumps
   from `phi3:mini` to the extractive path (see model card §5).
3. **Abstention on unanswerable questions is 60.9 %** (14/23) in the extractive
   configuration, and 5.4 % of all questions are still hallucinated. The fix
   that got it there is `retrieval_relevance_floor`: abstaining *before*
   generation when the best BM25 score retrieval produced is too low took
   hallucination from 7.7 % to 5.4 % without losing a single correct answer. The
   nine questions still answered anyway are named with their cause and their
   fix in the report's failure analysis; closing them needs a sentence embedder
   to separate "the corpus never mentions this" from "the corpus words it
   differently".
4. **Dense retrieval is effectively off** without `sentence-transformers`, so the
   reported hybrid numbers equal BM25.
