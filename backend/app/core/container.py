"""Process-wide service container.

Heavy objects (embedder, FAISS index, BM25 corpus, classifier) are built lazily
on first use so importing the app stays cheap and tests can swap components.
"""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover
    from ..cache.semantic_cache import SemanticCache
    from ..grounding.verifier import GroundingVerifier
    from ..llm.client import LLMClient
    from ..monitor.resources import ResourceMonitor
    from ..placement.engine import PlacementEngine
    from ..retrieval.index import RetrievalIndex
    from ..router.classifier import ComplexityClassifier
    from ..router.engine import RouterEngine


class Container:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._cache: dict[str, Any] = {}
        self._builders: dict[str, Any] = {
            "index": self._build_index,
            "llm": self._build_llm,
            "verifier": self._build_verifier,
            "cache": self._build_cache,
            "classifier": self._build_classifier,
            "monitor": self._build_monitor,
            "router": self._build_router,
            "placement": self._build_placement,
        }

    def get(self, name: str) -> Any:
        if name in self._cache:
            return self._cache[name]
        with self._lock:
            if name not in self._cache:
                if name not in self._builders:
                    raise KeyError(f"unknown component: {name}")
                self._cache[name] = self._builders[name]()
            return self._cache[name]

    def override(self, name: str, value: Any) -> None:
        """Test hook: inject a fake component."""
        self._cache[name] = value

    def reset(self, name: str | None = None) -> None:
        with self._lock:
            if name is None:
                self._cache.clear()
            else:
                self._cache.pop(name, None)

    # --- builders -------------------------------------------------------
    def _build_index(self) -> "RetrievalIndex":
        from ..retrieval.index import RetrievalIndex

        return RetrievalIndex.load_or_build()

    def _build_llm(self) -> "LLMClient":
        from ..llm.client import LLMClient

        return LLMClient()

    def _build_verifier(self) -> "GroundingVerifier":
        from ..grounding.verifier import GroundingVerifier

        return GroundingVerifier(self.get("index"))

    def _build_cache(self) -> "SemanticCache":
        from ..cache.semantic_cache import SemanticCache

        return SemanticCache(self.get("index"))

    def _build_classifier(self) -> "ComplexityClassifier":
        from ..router.classifier import ComplexityClassifier

        return ComplexityClassifier.load_or_train()

    def _build_monitor(self) -> "ResourceMonitor":
        from ..monitor.resources import ResourceMonitor

        return ResourceMonitor()

    def _build_router(self) -> "RouterEngine":
        from ..router.engine import RouterEngine

        return RouterEngine(
            index=self.get("index"),
            llm=self.get("llm"),
            verifier=self.get("verifier"),
            cache=self.get("cache"),
            classifier=self.get("classifier"),
            monitor=self.get("monitor"),
        )

    def _build_placement(self) -> "PlacementEngine":
        from ..placement.engine import PlacementEngine

        return PlacementEngine()


container = Container()


def get_container() -> Container:
    return container
