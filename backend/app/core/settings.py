"""Application settings.

Every tunable lives here so the eval harness can sweep thresholds without code
changes. Environment overrides use the ``AMYPO_`` prefix (see ``.env.example``).
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# backend/app/core/settings.py -> core -> app -> backend -> project root
PROJECT_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(PROJECT_ROOT / ".env"),
        env_prefix="AMYPO_",
        extra="ignore",
    )

    # --- identity -------------------------------------------------------
    app_name: str = "AMYPO Campus Assistant"
    version: str = "0.1.0"
    api_prefix: str = "/api/v1"
    log_level: str = "INFO"
    cors_origins: list[str] = Field(
        default_factory=lambda: [
            "http://localhost:3000",
            "http://127.0.0.1:3000",
        ]
    )

    # --- paths ----------------------------------------------------------
    project_root: Path = PROJECT_ROOT
    data_dir: Path = PROJECT_ROOT / "data"
    docs_dir: Path = PROJECT_ROOT / "docs"
    db_migrations_dir: Path = PROJECT_ROOT / "db" / "migrations"

    # --- MySQL ----------------------------------------------------------
    # Structured data, chunk text/metadata and every exact record live in MySQL.
    # The defaults match docker-compose; override with AMYPO_MYSQL_* for a
    # different server or a throwaway test schema.
    mysql_host: str = "127.0.0.1"
    mysql_port: int = 3306
    mysql_user: str = "amypo"
    mysql_password: str = "amypo"
    mysql_database: str = "amypo"
    mysql_pool_size: int = 5
    mysql_max_overflow: int = 5
    mysql_pool_recycle_s: int = 1800
    # Used only by the test suite, which creates/grants this schema so it never
    # touches the seeded ``amypo`` database.
    mysql_test_database: str = "amypo_test"
    mysql_root_password: str = "amypo-root"

    @property
    def mysql_url(self) -> str:
        """SQLAlchemy URL. Credentials are percent-encoded so odd passwords work."""
        from urllib.parse import quote_plus

        user = quote_plus(self.mysql_user)
        password = quote_plus(self.mysql_password)
        return (
            f"mysql+pymysql://{user}:{password}"
            f"@{self.mysql_host}:{self.mysql_port}/{self.mysql_database}"
            "?charset=utf8mb4"
        )

    @property
    def raw_dir(self) -> Path:
        return self.data_dir / "raw"

    @property
    def synthetic_dir(self) -> Path:
        return self.data_dir / "synthetic"

    @property
    def eval_dir(self) -> Path:
        return self.data_dir / "eval"

    @property
    def sim_dir(self) -> Path:
        return self.data_dir / "sim"

    @property
    def artifacts_dir(self) -> Path:
        """Trained model artefacts (complexity classifier, reranker config)."""
        return self.data_dir / "artifacts"

    # --- retrieval ------------------------------------------------------
    embed_model_name: str = "sentence-transformers/all-MiniLM-L6-v2"
    embed_dim: int = 384
    dense_top_k: int = 30
    bm25_top_k: int = 30
    final_top_k: int = 5
    rrf_k: int = 60
    # Dense contribution to RRF when the deterministic hash embedder is active.
    #
    # Measured, not assumed: sweeping this weight over the 145 answerable
    # benchmark questions showed S@1 falling monotonically from 0.745 at weight
    # 0.0 to 0.634 at weight 1.0. The hash embedder is a signed bag-of-words
    # cosine with no IDF weighting, so it is a strictly weaker lexical signal
    # than BM25 and fusing it only adds noise. It is therefore disabled, and the
    # ablation table reports hybrid == bm25 for that configuration rather than
    # pretending otherwise. With a real sentence-transformer both default to 1.0.
    dense_fusion_weight_fallback: float = 0.0
    # Dense similarity weight inside the feature reranker. Same measurement,
    # same reasoning: 0.0 scored MRR 0.789 against 0.780 at 0.34.
    reranker_dense_weight: float = 0.34
    reranker_dense_weight_fallback: float = 0.0
    reranker: str = "feature"  # feature | cross_encoder | none
    max_chunk_tokens: int = 450
    chunk_overlap_ratio: float = 0.15

    # --- generation -----------------------------------------------------
    ollama_base_url: str = "http://127.0.0.1:11434"
    ollama_model: str = "phi3:mini"
    ollama_fallback_model: str = "tinyllama"
    # Tier 2 of the three-tier local degradation: when *available* RAM falls
    # below this, unload phi3:mini and serve the smaller fallback model rather
    # than jumping straight to the extractive path. Tier 3 is ram_floor_mb.
    # Prefixed ``llm_`` (not ``model_``) because pydantic reserves ``model_``.
    llm_downgrade_ram_mb: int = 1400
    # Kill switch for the tier selector (tests pin the tier instead of the host).
    llm_tiering: bool = True
    ollama_timeout_s: float = 45.0
    ollama_num_ctx: int = 4096
    ollama_keep_alive: str = "10m"
    llm_max_retries: int = 2
    allow_real_models: bool = True  # when false, force stub LLM + hash embeddings
    stub_llm: bool = False  # force the deterministic stub even if Ollama is up

    # --- grounding ------------------------------------------------------
    verifier_threshold: float = 0.55
    # Lexical coverage a claim must reach against its evidence. Earlier this sat
    # at 0.35 because citation markers ("[S1] [S2]") were counted as content and
    # diluted coverage; now that markers are stripped before scoring, 0.45 is the
    # better operating point. Measured end-to-end with the extractive fallback:
    # unanswerable abstention 7/23 -> 11/23 while answerable abstention stays at
    # 1-2/145. Numbers remain the hard gate, so this admits no fabrications.
    claim_similarity_threshold: float = 0.45
    # Relevance gate: the best sparse score retrieval produced must reach this
    # before we answer from passages at all. Retrieval always returns its top-k,
    # so "passages were found" is not "an answer was found": without this, a
    # question about something the corpus never mentions (a staff member's home
    # address, this year's electricity bill) was answered by quoting whatever
    # unrelated passage shared an ordinary word with it. BM25 is the signal
    # rather than a word-overlap ratio because it has no denominator over the
    # question's words, so a paraphrase that shares only some of them still
    # scores well. The gate never fires when no sparse score is available, nor
    # for answers built from SQL rows or the placement engine.
    #
    # Measured with the answer harness over the 145 answerable / 23 unanswerable
    # benchmark items (extractive path, staff role). `correct` is the report's
    # rubric; `lost` are answers that were correct and became abstentions:
    #
    #   floor  correct  lost  unanswerable abstained  hallucinated
    #   0.0    110      0     10/23                   13
    #   6.0    110      0     11/23                   12
    #   9.0    110      0     14/23                    9   <- default
    #  12.0    107      3     20/23                    3
    #  15.0    102      8     21/23                    2
    #
    # 9.0 is the point where abstention improves and hallucination drops by
    # nearly a third without giving up a single correct answer; anything
    # stricter starts trading real answers for the last few. A paraphrase is the
    # hard case either way: with no sentence embedder on this box the gate is
    # lexical, which is why it stops here rather than at 12.0.
    retrieval_relevance_floor: float = 9.0
    snippet_max_chars: int = 240

    # --- cache ----------------------------------------------------------
    cache_cosine: float = 0.92
    cache_ttl_s: int = 60 * 60 * 24
    # Phase 8 item 5: how many of the historical questions to warm into the
    # cache at ingest time. 0 disables pre-warming (the tests use 0 so a warm
    # run never answers 200 questions during the suite).
    cache_prewarm_n: int = 25

    # --- retraining from live feedback (Phase 8, item 1) -----------------
    # How many rated questions a retrain pulls from the query log, and how much
    # each one counts against the derived static examples. A handful of thumbs
    # ratings must be able to move a 280-example corpus, and a human verdict is
    # worth far more than a label derived by the same rule the model is trying
    # to learn, so rated rows carry ``retrain_feedback_weight``.
    retrain_max_feedback: int = 200
    retrain_feedback_weight: float = 20.0

    # --- cache pre-warming scopes (Phase 8, item 5) ----------------------
    # A cache entry is keyed by access scope, so warming only the anonymous
    # ``public`` scope would never be hit: the UI always sends a role, and a
    # student sends their id. These are the identities the demo uses, warmed
    # with the answer that identity is entitled to (never a shared key).
    cache_prewarm_scopes: tuple[str, ...] = ("staff", "student:S102")

    # --- router ---------------------------------------------------------
    ram_floor_mb: int = 900
    ram_comfort_mb: int = 2600
    cpu_high_pct: float = 85.0
    bandwidth_min_kbps: int = 800
    latency_budget_ms: int = 6000
    monitor_interval_s: float = 1.5
    ewma_alpha: float = 0.3

    # --- simulated cloud (never a real network call) --------------------
    cloud_quota_per_day: int = 100
    cloud_price_inr_per_call: float = 1.75
    cloud_latency_ms: int = 1800
    cloud_failure_rate: float = 0.03
    local_price_inr_per_call: float = 0.02  # electricity, see docs/model_card.md

    # --- access control -------------------------------------------------
    staff_roles: tuple[str, ...] = ("staff", "admin")
    log_pii: bool = False

    # --- query understanding --------------------------------------------
    # TTL for the course/student/company vocab that entity matching checks
    # against. 0 disables caching (exact but 3 DB round-trips per question).
    # The test suite sets 0 so an INSERT is visible to the very next call.
    intent_vocab_ttl_s: float = 10.0


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
