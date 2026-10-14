import asyncio

from google import genai
from google.genai import types

from . import config

_client = genai.Client(api_key=config.GEMINI_API_KEY)

BATCH = 40          # фрагментов за один запрос
PAUSE = 25          # секунд между пачками (лимит free tier: 100 в минуту)


async def embed(texts: list[str], query: bool = False) -> list[list[float]]:
    """Эмбеддинги Gemini (мультиязычные, подходят для kk + ru) с паузами и повторами при лимите."""
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
                if getattr(e, "code", None) == 429 and attempt < 7:
                    print(f"Лимит Gemini, жду 20 с (попытка {attempt + 1}/8)...")
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


async def generate(system: str, prompt: str) -> str:
    for attempt in range(5):
        try:
            resp = await _client.aio.models.generate_content(
                model=config.GEN_MODEL,
                contents=prompt,
                config=types.GenerateContentConfig(system_instruction=system, temperature=0.2),
            )
            return (resp.text or "").strip()
        except Exception as e:
            code = getattr(e, "code", None)
            if code in (429, 500, 503) and attempt < 4:
                wait = 3 * (attempt + 1)
                print(f"Gemini занят ({code}), повтор через {wait} с (попытка {attempt + 1}/5)")
                await asyncio.sleep(wait)
                continue
            raise


async def transcribe(audio: bytes, mime: str = "audio/ogg") -> str:
    """Распознавание голосового сообщения (kk/ru)."""
    resp = await _client.aio.models.generate_content(
        model=config.GEN_MODEL,
        contents=[
            types.Part.from_bytes(data=audio, mime_type=mime),
            "Дословно расшифруй речь (казахский или русский). Верни только текст, без комментариев.",
        ],
    )
    return (resp.text or "").strip()