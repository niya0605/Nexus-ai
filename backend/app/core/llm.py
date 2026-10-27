"""LLM interface using Google Gemini (google-genai SDK)."""

import asyncio
import logging
import time
from collections.abc import AsyncIterator

from google import genai
from google.genai import errors, types

from app.config import settings

logger = logging.getLogger(__name__)

_ANSWER_PROMPT = """You are Nexus AI, answering questions about the user's uploaded documents.
Answer using ONLY the context below. If the context does not contain the answer,
say "I don't have that information in your documents." and cite nothing.
Be concise. Each source in the context starts with a number in brackets, like [2].
Cite the sources that support each statement with those numbers right after it,
e.g. "The target is $2M [2]." Cite only sources you actually used; never cite a
source just because it is in the context.
{history}
Context:
{context}

Question: {question}

Answer:"""

_HISTORY_BLOCK = """
Earlier in this conversation (use it only to understand what the question refers
to — facts must still come from the context):
{turns}
"""
# Keep follow-up context short: it is resent with every question.
_HISTORY_CHARS_PER_MESSAGE = 1500

# Overloaded (503), rate-limited (429) or timed out server-side (504).
_RETRYABLE_STATUS = {429, 503, 504}
# After a model is overloaded or times out, skip it for this long so every
# question doesn't wait out the full timeout again.
_COOLDOWN_SECONDS = 300
# The Gemini API accepts at most 100 texts per embedding request; the free tier
# allows ~30k embedding tokens per minute, so keep each request well below it.
_EMBED_BATCH_SIZE = 100
_EMBED_BATCH_TOKENS = 12_000
_RATE_LIMIT_WAIT_SECONDS = 30
_RATE_LIMIT_MAX_ATTEMPTS = 5
# Must match the vector(N) column created in alembic 20261027_add_chunk_embeddings.
EMBEDDING_DIMENSIONS = 768


class LLMError(Exception):
    """Every configured model failed; the message is safe to show users."""


class GeminiLLM:
    def __init__(self) -> None:
        if not settings.GEMINI_API_KEY:
            raise LLMError("GEMINI_API_KEY is not set in backend/.env")
        self._client = genai.Client(api_key=settings.GEMINI_API_KEY)
        self._models = [settings.GEMINI_MODEL]
        for model in settings.GEMINI_FALLBACK_MODELS.split(","):
            if model.strip() and model.strip() not in self._models:
                self._models.append(model.strip())
        self._cooldown_until: dict[str, float] = {}

    def _models_in_order(self) -> list[str]:
        """Healthy models first, models still cooling down last (never dropped)."""
        now = time.monotonic()
        return sorted(self._models, key=lambda m: self._cooldown_until.get(m, 0) > now)

    def _unavailable(self, model: str, exc: TimeoutError | errors.APIError) -> str:
        """Put a failing model on cooldown and describe why; non-retryable errors raise."""
        if isinstance(exc, TimeoutError):
            reason = f"{model} did not respond within {settings.GEMINI_TIMEOUT_SECONDS}s"
        elif exc.code in _RETRYABLE_STATUS:
            reason = f"{model} is unavailable ({exc.code} {exc.status})"
        else:
            raise LLMError(f"{model}: {exc.message or exc.status}") from exc
        self._cooldown_until[model] = time.monotonic() + _COOLDOWN_SECONDS
        logger.warning("Gemini model unavailable, trying next: %s", reason)
        return reason

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
            except (TimeoutError, errors.APIError) as exc:
                last_error = self._unavailable(model, exc)
        raise LLMError(f"The AI model is busy right now — please try again shortly. ({last_error})")

    async def _stream(self, prompt: str) -> AsyncIterator[str]:
        """Yield text as the model writes it. A model that fails before its first
        text falls back to the next one; a failure after text was sent can't be
        retried invisibly, so it raises LLMError."""
        timeout = settings.GEMINI_TIMEOUT_SECONDS
        last_error = "no model configured"
        for model in self._models_in_order():
            try:
                stream = await asyncio.wait_for(
                    self._client.aio.models.generate_content_stream(model=model, contents=prompt),
                    timeout=timeout,
                )
                first = await asyncio.wait_for(anext(stream, None), timeout=timeout)
            except (TimeoutError, errors.APIError) as exc:
                last_error = self._unavailable(model, exc)
                continue
            self._cooldown_until.pop(model, None)
            chunk = first
            try:
                while chunk is not None:
                    if chunk.text:
                        yield chunk.text
                    chunk = await asyncio.wait_for(anext(stream, None), timeout=timeout)
            except (TimeoutError, errors.APIError) as exc:
                raise LLMError("The AI model stopped responding mid-answer — please try again.") from exc
            return
        raise LLMError(f"The AI model is busy right now — please try again shortly. ({last_error})")

    async def answer_question(
        self, question: str, context: str, history: list[tuple[str, str]] | None = None
    ) -> str:
        """`history` is earlier (role, text) turns, oldest first; role is "user" or "assistant"."""
        return await self._generate(build_answer_prompt(question, context, history))

    def stream_answer(
        self, question: str, context: str, history: list[tuple[str, str]] | None = None
    ) -> AsyncIterator[str]:
        """Like answer_question, but yields the answer's text as it is generated."""
        return self._stream(build_answer_prompt(question, context, history))

    async def embed_documents(
        self, texts: list[str], *, wait_on_rate_limit: bool = False
    ) -> list[list[float]]:
        """Embed chunks. With `wait_on_rate_limit`, a free-tier quota error waits
        for the per-minute window to reset and retries (for background work);
        otherwise it fails fast (for requests a user is waiting on)."""
        return await self._embed(texts, "RETRIEVAL_DOCUMENT", wait_on_rate_limit)

    async def embed_query(self, text: str) -> list[float]:
        return (await self._embed([text], "RETRIEVAL_QUERY", False))[0]

    async def _embed(
        self, texts: list[str], task_type: str, wait_on_rate_limit: bool
    ) -> list[list[float]]:
        config = types.EmbedContentConfig(
            task_type=task_type, output_dimensionality=EMBEDDING_DIMENSIONS
        )
        vectors: list[list[float]] = []
        for batch in _token_budget_batches(texts):
            for attempt in range(1, _RATE_LIMIT_MAX_ATTEMPTS + 1):
                try:
                    result = await asyncio.wait_for(
                        self._client.aio.models.embed_content(
                            model=settings.GEMINI_EMBEDDING_MODEL, contents=batch, config=config
                        ),
                        timeout=settings.GEMINI_TIMEOUT_SECONDS,
                    )
                    break
                except TimeoutError as exc:
                    raise LLMError("The embedding model did not respond in time.") from exc
                except errors.APIError as exc:
                    rate_limited = exc.code == 429
                    if rate_limited and wait_on_rate_limit and attempt < _RATE_LIMIT_MAX_ATTEMPTS:
                        logger.info("Embedding quota reached; retrying in %ss", _RATE_LIMIT_WAIT_SECONDS)
                        await asyncio.sleep(_RATE_LIMIT_WAIT_SECONDS)
                        continue
                    reason = "free-tier quota reached" if rate_limited else (exc.message or exc.status)
                    raise LLMError(f"Embedding failed: {reason}") from exc
            vectors.extend(e.values for e in result.embeddings)
        return vectors


def build_answer_prompt(
    question: str, context: str, history: list[tuple[str, str]] | None = None
) -> str:
    history_block = ""
    if history:
        turns = "\n".join(
            f"{'User' if role == 'user' else 'Nexus'}: {text[:_HISTORY_CHARS_PER_MESSAGE]}"
            for role, text in history
        )
        history_block = _HISTORY_BLOCK.format(turns=turns)
    return _ANSWER_PROMPT.format(history=history_block, context=context, question=question)


def _token_budget_batches(texts: list[str]) -> list[list[str]]:
    """Group texts so each request stays under the per-request item limit and
    well under the free tier's per-minute token budget."""
    batches: list[list[str]] = []
    current: list[str] = []
    current_tokens = 0
    for text in texts:
        tokens = len(text) // 4 + 1
        if current and (
            len(current) >= _EMBED_BATCH_SIZE or current_tokens + tokens > _EMBED_BATCH_TOKENS
        ):
            batches.append(current)
            current, current_tokens = [], 0
        current.append(text)
        current_tokens += tokens
    if current:
        batches.append(current)
    return batches


_llm_instance: GeminiLLM | None = None


def get_llm() -> GeminiLLM:
    global _llm_instance
    if _llm_instance is None:
        _llm_instance = GeminiLLM()
    return _llm_instance
