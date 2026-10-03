"""LLM interface using Google Gemini (free API)."""

import asyncio

import google.generativeai as genai

from app.config import settings

_ANSWER_PROMPT = """You are Nexus AI, answering questions about the user's uploaded documents.
Answer using ONLY the context below. If the context does not contain the answer,
say "I don't have that information in your documents." Be concise and mention
which source the answer came from.

Context:
{context}

Question: {question}

Answer:"""


class GeminiLLM:
    def __init__(self) -> None:
        if not settings.GEMINI_API_KEY:
            raise ValueError("GEMINI_API_KEY is not set in backend/.env")
        genai.configure(api_key=settings.GEMINI_API_KEY)
        self.model = genai.GenerativeModel(settings.GEMINI_MODEL)

    async def _generate(self, prompt: str) -> str:
        # The SDK call is blocking; keep it off the event loop.
        response = await asyncio.to_thread(self.model.generate_content, prompt)
        return response.text

    async def answer_question(self, question: str, context: str) -> str:
        return await self._generate(_ANSWER_PROMPT.format(context=context, question=question))

    async def generate_quiz_question(
        self, context: str, difficulty: str = "medium", question_type: str = "mcq"
    ) -> dict:
        prompt = f"""Generate a {difficulty} {question_type} question based on this text.

Text: {context}

For MCQ: provide exactly 4 options (a, b, c, d) and the correct answer.
Format: Question: ... A) ... B) ... C) ... D) ... Answer: (letter)"""
        return {"question": await self._generate(prompt), "type": question_type}


_llm_instance: GeminiLLM | None = None


def get_llm() -> GeminiLLM:
    global _llm_instance
    if _llm_instance is None:
        _llm_instance = GeminiLLM()
    return _llm_instance
