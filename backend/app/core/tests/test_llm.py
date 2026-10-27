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
