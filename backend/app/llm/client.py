"""Local generation client.

Talks to Ollama over loopback when a model is available. When it is not, a
deterministic extractive stub takes over so the pipeline, the tests and the demo
all keep working with no downloads.

The stub is not a language model and does not pretend to be one: it selects and
stitches the most relevant sentences from the supplied context. That is a
legitimate answer strategy (it is the same thing the offline fallback route
does), and it is always labelled in the response so nobody mistakes it for
generated prose.
"""

from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass
from typing import Any, Iterator

from ..core.settings import settings
from .prompts import ContextBlock

log = logging.getLogger(__name__)


class LLMError(RuntimeError):
    """Base class for generation failures."""


class LLMUnavailable(LLMError):
    """The model server is not reachable or the model is not loaded."""


class LLMTimeout(LLMError):
    """The model took longer than the configured budget."""


@dataclass
class GenerationResult:
    text: str
    model: str
    stub: bool
    latency_ms: float
    prompt_tokens: int = 0
    completion_tokens: int = 0
    retries: int = 0


class LLMClient:
    """Generation with automatic degradation to a deterministic extractive stub."""

    def __init__(self, base_url: str | None = None, model: str | None = None) -> None:
        self.base_url = (base_url or settings.ollama_base_url).rstrip("/")
        self.model = model or settings.ollama_model
        self.fallback_model = settings.ollama_fallback_model
        self.timeout = settings.ollama_timeout_s
        self._status: str = "unknown"
        self._detail: str = "not probed yet"
        self._last_latency_ms: float | None = None
        self._model_missing: bool = False
        self._probe()

    # --- status ---------------------------------------------------------

    def _probe(self) -> None:
        if settings.stub_llm or not settings.allow_real_models:
            self._status = "degraded"
            self._detail = "stub LLM forced by configuration"
            return
        try:
            import httpx

            response = httpx.get(f"{self.base_url}/api/tags", timeout=2.0)
            response.raise_for_status()
            models = {m.get("name", "") for m in response.json().get("models", [])}
            available = ", ".join(sorted(models)) or "none"
            # A running server without our model is the common case on a fresh
            # machine. Detect it here so the first request does not spend the
            # whole timeout budget discovering it.
            if self.model not in models and not self._model_matches(models):
                self._status = "degraded"
                self._model_missing = True
                self._detail = (
                    f"ollama is running but {self.model} is not pulled "
                    f"(available: {available}); using stub"
                )
                return
            self._status = "ok"
            self._detail = f"ollama at {self.base_url}; models: {available}"
        except Exception as exc:
            self._status = "degraded"
            self._detail = f"ollama unavailable ({type(exc).__name__}); using stub"

    def _model_matches(self, models: set[str]) -> bool:
        """Whether any pulled tag satisfies the configured model name.

        Ollama reports ``phi3:mini`` as ``phi3:mini`` but may also list
        ``phi3:mini-4k``; a prefix match avoids a false 'missing' verdict.
        """
        base = self.model.split(":")[0]
        return any(name == self.model or name.startswith(f"{base}:") for name in models)

    def status(self) -> str:
        return self._status

    def status_detail(self) -> str:
        return self._detail

    @property
    def is_stub(self) -> bool:
        return self._status != "ok"

    @property
    def last_latency_ms(self) -> float | None:
        return self._last_latency_ms

    def healthy(self) -> bool:
        """Whether the model path should be attempted at all."""
        return not self.is_stub

    # --- generation -----------------------------------------------------

    def generate(
        self,
        prompt: str,
        system: str | None = None,
        context: list[ContextBlock] | None = None,
        question: str = "",
        temperature: float = 0.1,
    ) -> GenerationResult:
        """Generate an answer, falling back to extraction on any failure.

        ``context`` and ``question`` are needed by the stub, which answers by
        extracting from the retrieved passages rather than generating text.
        """
        if self.is_stub:
            return self._stub_result(question, context or [], model="stub-extractive")

        # A missing model will not appear because we waited longer; fail fast and
        # remember, so the second request is instant instead of timing out again.
        if self._model_missing:
            result = self._stub_result(question, context or [], model="stub-extractive")
            return result

        started = time.perf_counter()
        retries = 0
        last_error: Exception | None = None
        for attempt in range(settings.llm_max_retries + 1):
            try:
                text, usage = self._call_ollama(prompt, system, temperature)
                latency = (time.perf_counter() - started) * 1000
                self._last_latency_ms = latency
                self._status = "ok"
                return GenerationResult(
                    text=text,
                    model=self.model,
                    stub=False,
                    latency_ms=round(latency, 2),
                    prompt_tokens=int(usage.get("prompt_eval_count", 0) or 0),
                    completion_tokens=int(usage.get("eval_count", 0) or 0),
                    retries=retries,
                )
            except Exception as exc:
                last_error = exc
                retries = attempt
                log.warning("ollama generation attempt %d failed: %s", attempt + 1, exc)
                time.sleep(min(0.5 * (attempt + 1), 2.0))

        # Every attempt failed: degrade to extraction rather than failing the request.
        self._status = "degraded"
        self._detail = f"generation failed ({type(last_error).__name__}); using stub"
        if isinstance(last_error, LLMUnavailable) and "not pulled" in str(last_error):
            self._model_missing = True
        result = self._stub_result(question, context or [], model="stub-extractive")
        result.retries = retries
        return result

    def _call_ollama(
        self, prompt: str, system: str | None, temperature: float
    ) -> tuple[str, dict[str, Any]]:
        import httpx

        payload: dict[str, Any] = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            "keep_alive": settings.ollama_keep_alive,
            "options": {
                "temperature": temperature,
                "num_ctx": settings.ollama_num_ctx,
                # Keep generation short: we want grounded answers, not essays.
                "num_predict": 320,
            },
        }
        if system:
            payload["system"] = system

        try:
            response = httpx.post(
                f"{self.base_url}/api/generate", json=payload, timeout=self.timeout
            )
        except Exception as exc:
            raise LLMUnavailable(str(exc)) from exc

        if response.status_code == 404:
            raise LLMUnavailable(f"model {self.model} is not pulled")
        response.raise_for_status()
        body = response.json()
        return body.get("response", "").strip(), body

    def stream(
        self, prompt: str, system: str | None = None, question: str = "",
        context: list[ContextBlock] | None = None,
    ) -> Iterator[str]:
        """Yield answer chunks. The stub yields its whole text in one chunk."""
        if self.is_stub:
            yield self._stub_result(question, context or [], model="stub-extractive").text
            return

        import httpx

        payload: dict[str, Any] = {
            "model": self.model,
            "prompt": prompt,
            "stream": True,
            "keep_alive": settings.ollama_keep_alive,
            "options": {"temperature": 0.1, "num_ctx": settings.ollama_num_ctx,
                        "num_predict": 320},
        }
        if system:
            payload["system"] = system
        try:
            with httpx.stream(
                "POST", f"{self.base_url}/api/generate", json=payload, timeout=self.timeout
            ) as response:
                response.raise_for_status()
                for line in response.iter_lines():
                    if not line:
                        continue
                    chunk = json.loads(line)
                    piece = chunk.get("response", "")
                    if piece:
                        yield piece
                    if chunk.get("done"):
                        break
        except Exception as exc:
            log.warning("streaming failed (%s); emitting extractive answer", exc)
            yield self._stub_result(question, context or [], model="stub-extractive").text

    # --- the deterministic stub ----------------------------------------

    def _stub_result(
        self, question: str, context: list[ContextBlock], model: str
    ) -> GenerationResult:
        started = time.perf_counter()
        text = extractive_answer(question, context)
        latency = (time.perf_counter() - started) * 1000
        return GenerationResult(
            text=text, model=model, stub=True, latency_ms=round(latency, 2),
            prompt_tokens=sum(len(c.text.split()) for c in context),
        )


_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")


def extractive_answer(question: str, context: list[ContextBlock]) -> str:
    """Compose an answer by selecting the best-matching sentences.

    This is deliberately *not* paraphrase: every sentence is copied verbatim from
    a cited passage, so the grounding verifier can check it and the user can see
    exactly which record it came from.
    """
    if not context:
        return ""

    from ..grounding.injection import is_injection
    from ..retrieval.tokenize import tokenize_query

    query_terms = set(tokenize_query(question))
    scored: list[tuple[float, str, ContextBlock]] = []

    for block in context:
        for sentence in _SENTENCE_SPLIT.split(block.text):
            sentence = sentence.strip()
            if len(sentence) < 25:
                continue
            # Never emit a sentence that reads as an instruction to the
            # assistant. The corpus plants these on purpose; without this the
            # extractive answer quoted them back as if they were facts.
            if is_injection(sentence):
                continue
            terms = set(tokenize_query(sentence))
            if not terms:
                continue
            overlap = len(query_terms & terms)
            if not overlap:
                continue
            coverage = overlap / max(1, len(query_terms))
            # Favour sentences that carry the specific numbers and identifiers
            # the question is about.
            number_bonus = 0.0
            question_numbers = {t for t in query_terms if any(ch.isdigit() for ch in t)}
            if question_numbers and question_numbers & terms:
                number_bonus = 0.15
            score = coverage + number_bonus - min(0.1, len(sentence) / 4000.0)
            scored.append((score, sentence, block))

    if not scored:
        # Nothing overlapped. Returning the top passage here used to guarantee a
        # non-empty string, which meant an unanswerable question was answered with
        # whichever record happened to rank first ("What is the Wi-Fi password?"
        # was answered with a teamwork skill row). An empty answer is the honest
        # signal: the verifier finds no claims and the pipeline abstains.
        return ""

    scored.sort(key=lambda item: -item[0])
    chosen: list[tuple[str, ContextBlock]] = []
    seen: set[str] = set()
    for _score, sentence, block in scored:
        key = sentence.lower()
        if key in seen:
            continue
        seen.add(key)
        chosen.append((sentence, block))
        if len(chosen) >= 3:
            break

    parts: list[str] = []
    for sentence, block in chosen:
        marker = f" [S{block.index}]"
        parts.append(sentence if sentence.endswith(marker.strip()) else sentence + marker)
    return " ".join(parts)
