"""Gemini model fallback and cool-down, with a fake client (no network, no quota)."""

import asyncio
from types import SimpleNamespace

import pytest
from google.genai import errors

from app.config import settings
from app.core import llm as llm_module
from app.core.llm import GeminiLLM, LLMError

PRIMARY, FALLBACK = "primary-model", "fallback-model"


def _api_error(code: int, status: str) -> errors.APIError:
    return errors.ServerError(code, {"error": {"code": code, "message": status.lower(), "status": status}})


class FakeModels:
    def __init__(self, behaviours: dict[str, object]) -> None:
        self.behaviours = behaviours
        self.calls: list[str] = []

    async def generate_content(self, *, model: str, contents: str):
        self.calls.append(model)
        behaviour = self.behaviours[model]
        if isinstance(behaviour, Exception):
            raise behaviour
        if behaviour == "hang":
            await asyncio.sleep(5)
        return SimpleNamespace(text=f"answer from {model}")


@pytest.fixture
def make_llm(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(settings, "GEMINI_API_KEY", "test-key")
    monkeypatch.setattr(settings, "GEMINI_MODEL", PRIMARY)
    monkeypatch.setattr(settings, "GEMINI_FALLBACK_MODEL", FALLBACK)
    monkeypatch.setattr(settings, "GEMINI_TIMEOUT_SECONDS", 1)

    def _make(behaviours: dict[str, object]) -> tuple[GeminiLLM, FakeModels]:
        llm = GeminiLLM()
        fake = FakeModels(behaviours)
        llm._client = SimpleNamespace(aio=SimpleNamespace(models=fake))
        return llm, fake

    return _make


def test_uses_primary_model_when_healthy(make_llm) -> None:
    llm, fake = make_llm({PRIMARY: "ok", FALLBACK: "ok"})
    assert asyncio.run(llm.answer_question("q", "ctx")) == f"answer from {PRIMARY}"
    assert fake.calls == [PRIMARY]


@pytest.mark.parametrize("code,status", [(503, "UNAVAILABLE"), (429, "RESOURCE_EXHAUSTED"), (504, "DEADLINE_EXCEEDED")])
def test_falls_back_when_primary_overloaded(make_llm, code: int, status: str) -> None:
    llm, fake = make_llm({PRIMARY: _api_error(code, status), FALLBACK: "ok"})
    assert asyncio.run(llm.answer_question("q", "ctx")) == f"answer from {FALLBACK}"
    assert fake.calls == [PRIMARY, FALLBACK]


def test_falls_back_when_primary_times_out(make_llm) -> None:
    llm, fake = make_llm({PRIMARY: "hang", FALLBACK: "ok"})
    assert asyncio.run(llm.answer_question("q", "ctx")) == f"answer from {FALLBACK}"


def test_failed_model_is_skipped_during_cooldown(make_llm) -> None:
    llm, fake = make_llm({PRIMARY: _api_error(503, "UNAVAILABLE"), FALLBACK: "ok"})
    asyncio.run(llm.answer_question("q", "ctx"))
    fake.calls.clear()

    asyncio.run(llm.answer_question("q", "ctx"))
    assert fake.calls == [FALLBACK]


def test_primary_is_retried_after_cooldown(make_llm, monkeypatch: pytest.MonkeyPatch) -> None:
    llm, fake = make_llm({PRIMARY: _api_error(503, "UNAVAILABLE"), FALLBACK: "ok"})
    asyncio.run(llm.answer_question("q", "ctx"))
    fake.behaviours[PRIMARY] = "ok"
    monkeypatch.setattr(llm_module, "_COOLDOWN_SECONDS", 0)
    llm._cooldown_until = {PRIMARY: 0}
    fake.calls.clear()

    assert asyncio.run(llm.answer_question("q", "ctx")) == f"answer from {PRIMARY}"
    assert fake.calls == [PRIMARY]


def test_non_retryable_error_is_not_retried(make_llm) -> None:
    bad_request = errors.ClientError(400, {"error": {"code": 400, "message": "bad prompt", "status": "INVALID_ARGUMENT"}})
    llm, fake = make_llm({PRIMARY: bad_request, FALLBACK: "ok"})
    with pytest.raises(LLMError, match="bad prompt"):
        asyncio.run(llm.answer_question("q", "ctx"))
    assert fake.calls == [PRIMARY]


def test_all_models_failing_raises_friendly_error(make_llm) -> None:
    llm, _ = make_llm({PRIMARY: _api_error(503, "UNAVAILABLE"), FALLBACK: _api_error(503, "UNAVAILABLE")})
    with pytest.raises(LLMError, match="busy right now"):
        asyncio.run(llm.answer_question("q", "ctx"))


# --- embeddings ----------------------------------------------------------------


class FakeEmbedModels:
    def __init__(self, failures_before_success: int) -> None:
        self.failures_left = failures_before_success
        self.batch_sizes: list[int] = []

    async def embed_content(self, *, model: str, contents: list[str], config):
        if self.failures_left:
            self.failures_left -= 1
            raise _api_error(429, "RESOURCE_EXHAUSTED")
        self.batch_sizes.append(len(contents))
        return SimpleNamespace(embeddings=[SimpleNamespace(values=[0.0]) for _ in contents])


@pytest.fixture
def make_embedder(make_llm, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(llm_module, "_RATE_LIMIT_WAIT_SECONDS", 0)

    def _make(failures_before_success: int = 0) -> tuple[GeminiLLM, FakeEmbedModels]:
        llm, _ = make_llm({PRIMARY: "ok", FALLBACK: "ok"})
        fake = FakeEmbedModels(failures_before_success)
        llm._client = SimpleNamespace(aio=SimpleNamespace(models=fake))
        return llm, fake

    return _make


def test_large_inputs_are_split_to_respect_token_budget(make_embedder) -> None:
    llm, fake = make_embedder()
    texts = ["word " * 2000] * 20  # ~2.5k tokens each, ~50k total
    vectors = asyncio.run(llm.embed_documents(texts))
    assert len(vectors) == 20
    assert len(fake.batch_sizes) > 1
    assert all(size * 2501 <= llm_module._EMBED_BATCH_TOKENS + 2501 for size in fake.batch_sizes)


def test_quota_error_fails_fast_for_interactive_requests(make_embedder) -> None:
    llm, _ = make_embedder(failures_before_success=1)
    with pytest.raises(LLMError, match="quota"):
        asyncio.run(llm.embed_documents(["text"]))


def test_quota_error_is_retried_for_background_work(make_embedder) -> None:
    llm, fake = make_embedder(failures_before_success=2)
    assert len(asyncio.run(llm.embed_documents(["text"], wait_on_rate_limit=True))) == 1
    assert fake.failures_left == 0
