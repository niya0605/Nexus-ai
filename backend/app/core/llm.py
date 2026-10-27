"""LLM interface using Google Gemini (google-genai SDK)."""

import asyncio
import logging
import time

from google import genai
from google.genai import errors

from app.config import settings

logger = logging.getLogger(__name__)

_ANSWER_PROMPT = """You are Nexus AI, answering questions about the user's uploaded documents.
Answer using ONLY the context below. If the context does not contain the answer,
say "I don't have that information in your documents." Be concise and mention
which source (and page, when given) the answer came from.

Context:
{context}

Question: {question}

Answer:"""

# Overloaded (503), rate-limited (429) or timed out server-side (504).
_RETRYABLE_STATUS = {429, 503, 504}
# After a model is overloaded or times out, skip it for this long so every
# question doesn't wait out the full timeout again.
_COOLDOWN_SECONDS = 300


class LLMError(Exception):
    """Every configured model failed; the message is safe to show users."""


class GeminiLLM:
    def __init__(self) -> None:
        if not settings.GEMINI_API_KEY:
            raise LLMError("GEMINI_API_KEY is not set in backend/.env")
        self._client = genai.Client(api_key=settings.GEMINI_API_KEY)
        self._models = [settings.GEMINI_MODEL]
        if settings.GEMINI_FALLBACK_MODEL and settings.GEMINI_FALLBACK_MODEL != settings.GEMINI_MODEL:
            self._models.append(settings.GEMINI_FALLBACK_MODEL)
        self._cooldown_until: dict[str, float] = {}

    def _models_in_order(self) -> list[str]:
        """Healthy models first, models still cooling down last (never dropped)."""
        now = time.monotonic()
        return sorted(self._models, key=lambda m: self._cooldown_until.get(m, 0) > now)

    async def _generate(self, prompt: str) -> str:
        last_error = "no model configured"
        for model in self._models_in_order():
            try:
                response = await asyncio.wait_for(
                    self._client.aio.models.generate_content(model=model, contents=prompt),
                    timeout=settings.GEMINI_TIMEOUT_SECONDS,
                )
                self._cooldown_until.pop(model, None)
                return response.text or ""
            except TimeoutError:
                last_error = f"{model} did not respond within {settings.GEMINI_TIMEOUT_SECONDS}s"
            except errors.APIError as exc:
                if exc.code not in _RETRYABLE_STATUS:
                    raise LLMError(f"{model}: {exc.message or exc.status}") from exc
                last_error = f"{model} is unavailable ({exc.code} {exc.status})"
            self._cooldown_until[model] = time.monotonic() + _COOLDOWN_SECONDS
            logger.warning("Gemini model unavailable, trying next: %s", last_error)
        raise LLMError(f"The AI model is busy right now — please try again shortly. ({last_error})")

    async def answer_question(self, question: str, context: str) -> str:
        return await self._generate(_ANSWER_PROMPT.format(context=context, question=question))


_llm_instance: GeminiLLM | None = None


def get_llm() -> GeminiLLM:
    global _llm_instance
    if _llm_instance is None:
        _llm_instance = GeminiLLM()
    return _llm_instance
