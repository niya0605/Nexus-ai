"""Deterministic stand-in for the Gemini client in tests (no network, no quota).

Embeddings are bag-of-concepts vectors: synonyms share a dimension, so
"income" and "money" are similar even though the words differ — enough to
exercise semantic search without the real model.
"""

import hashlib
import math

import pytest

from app.core.llm import EMBEDDING_DIMENSIONS, LLMError

_CONCEPTS = {
    "money": {"revenue", "income", "money", "earn", "earnings", "sales", "profit"},
    "food": {"cafeteria", "soup", "lunch", "food", "menu", "salad"},
    "launch": {"launch", "launches", "release", "ship", "ships"},
}
_WORD_TO_CONCEPT = {word: concept for concept, words in _CONCEPTS.items() for word in words}


def fake_embedding(text: str) -> list[float]:
    vector = [0.0] * EMBEDDING_DIMENSIONS
    for word in "".join(ch if ch.isalnum() else " " for ch in text.lower()).split():
        key = _WORD_TO_CONCEPT.get(word, word)
        index = int(hashlib.md5(key.encode()).hexdigest(), 16) % EMBEDDING_DIMENSIONS
        vector[index] += 1.0
    norm = math.sqrt(sum(v * v for v in vector)) or 1.0
    return [v / norm for v in vector]


class FakeLLM:
    def __init__(self) -> None:
        self.embedding_available = True
        self.embedded_documents = 0
        self.answers_fail = False
        self.answer_calls: list[dict] = []

    async def embed_documents(
        self, texts: list[str], *, wait_on_rate_limit: bool = False
    ) -> list[list[float]]:
        if not self.embedding_available:
            raise LLMError("embedding service unavailable (fake)")
        self.embedded_documents += len(texts)
        return [fake_embedding(t) for t in texts]

    async def embed_query(self, text: str) -> list[float]:
        if not self.embedding_available:
            raise LLMError("embedding service unavailable (fake)")
        return fake_embedding(text)

    async def answer_question(
        self, question: str, context: str, history: list[tuple[str, str]] | None = None
    ) -> str:
        if self.answers_fail:
            raise LLMError("The AI model is busy right now (fake)")
        self.answer_calls.append({"question": question, "context": context, "history": history or []})
        return f"fake answer to: {question}"


@pytest.fixture(autouse=True)
def fake_llm(monkeypatch: pytest.MonkeyPatch) -> FakeLLM:
    fake = FakeLLM()
    for module in ("app.modules.documents.service", "app.modules.chat.retrieval", "app.modules.chat.service"):
        monkeypatch.setattr(f"{module}.get_llm", lambda: fake)
    return fake
