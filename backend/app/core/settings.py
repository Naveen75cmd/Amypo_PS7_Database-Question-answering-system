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
    db_path: Path = PROJECT_ROOT / "data" / "amypo.db"

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
    reranker: str = "feature"  # feature | cross_encoder | none
    max_chunk_tokens: int = 450
    chunk_overlap_ratio: float = 0.15

    # --- generation -----------------------------------------------------
    ollama_base_url: str = "http://127.0.0.1:11434"
    ollama_model: str = "phi3:mini"
    ollama_fallback_model: str = "tinyllama"
    ollama_timeout_s: float = 45.0
    ollama_num_ctx: int = 4096
    ollama_keep_alive: str = "10m"
    llm_max_retries: int = 2
    allow_real_models: bool = True  # when false, force stub LLM + hash embeddings
    stub_llm: bool = False  # force the deterministic stub even if Ollama is up

    # --- grounding ------------------------------------------------------
    verifier_threshold: float = 0.55
    claim_similarity_threshold: float = 0.45
    snippet_max_chars: int = 240

    # --- cache ----------------------------------------------------------
    cache_cosine: float = 0.92
    cache_ttl_s: int = 60 * 60 * 24

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


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
