import asyncio

from google import genai
from google.genai import types

from . import config

_client = genai.Client(api_key=config.GEMINI_API_KEY)

BATCH = 40  # фрагментов за один запрос эмбеддингов
PAUSE = 25  # пауза между пачками (free tier: 100 запросов в минуту)
FALLBACK_MODELS = ["gemini-flash-latest"]  # запасная модель, если основная перегружена
RETRY_CODES = (429, 500, 503)


async def embed(texts: list[str], query: bool = False) -> list[list[float]]:
    """Эмбеддинги Gemini (мультиязычные: kk + ru) с паузами и повторами при лимите."""
    task = "RETRIEVAL_QUERY" if query else "RETRIEVAL_DOCUMENT"
    out: list[list[float]] = []
    for i in range(0, len(texts), BATCH):
        chunk = texts[i : i + BATCH]
        for attempt in range(8):
            try:
                resp = await _client.aio.models.embed_content(
                    model=config.EMBED_MODEL,
                    contents=chunk,
                    config=types.EmbedContentConfig(
                        task_type=task, output_dimensionality=config.EMBED_DIM
                    ),
                )
                break
            except Exception as e:
                if getattr(e, "code", None) in RETRY_CODES and attempt < 7:
                    print(f"Лимит/перегрузка Gemini, жду 20 с (попытка {attempt + 1}/8)...")
                    await asyncio.sleep(20)
                    continue
                raise
        out.extend(_normalize(e.values) for e in resp.embeddings)
        if i + BATCH < len(texts):
            print(f"  обработано {i + BATCH}/{len(texts)}")
            await asyncio.sleep(PAUSE)
    return out


def _normalize(v: list[float]) -> list[float]:
    # при усечённой размерности вектор нужно нормировать
    n = sum(x * x for x in v) ** 0.5 or 1.0
    return [x / n for x in v]


async def _call_with_fallback(make_request):
    """Пробует основную модель с повторами, затем запасные. make_request(model) -> response."""
    models = [config.GEN_MODEL] + FALLBACK_MODELS
    last_error: Exception | None = None
    for model in models:
        for attempt in range(3):
            try:
                return await make_request(model)
            except Exception as e:
                last_error = e
                code = getattr(e, "code", None)
                if code in RETRY_CODES and attempt < 2:
                    wait = 3 * (attempt + 1)
                    print(f"{model} занят ({code}), повтор через {wait} с")
                    await asyncio.sleep(wait)
                    continue
                print(f"{model} не сработал ({code}), пробую следующую модель")
                break
    raise last_error  # type: ignore[misc]


async def generate(system: str, prompt: str) -> str:
    async def req(model: str):
        return await _client.aio.models.generate_content(
            model=model,
            contents=prompt,
            config=types.GenerateContentConfig(system_instruction=system, temperature=0.2),
        )

    resp = await _call_with_fallback(req)
    return (resp.text or "").strip()


async def transcribe(audio: bytes, mime: str = "audio/ogg") -> str:
    """Распознавание голосового сообщения (kk/ru)."""

    async def req(model: str):
        return await _client.aio.models.generate_content(
            model=model,
            contents=[
                types.Part.from_bytes(data=audio, mime_type=mime),
                "Дословно расшифруй речь (казахский или русский). Верни только текст, без комментариев.",
            ],
        )

    resp = await _call_with_fallback(req)
    return (resp.text or "").strip()
