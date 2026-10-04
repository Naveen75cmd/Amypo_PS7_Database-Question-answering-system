"""Local LLM access: Ollama client, deterministic stub, prompt building."""

from .client import LLMClient, LLMError, LLMUnavailable, LLMTimeout
from .prompts import build_answer_prompt, build_phrase_prompt

__all__ = [
    "LLMClient",
    "LLMError",
    "LLMUnavailable",
    "LLMTimeout",
    "build_answer_prompt",
    "build_phrase_prompt",
]
