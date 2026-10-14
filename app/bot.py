import asyncio
import io
import logging

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command, CommandStart
from aiogram.types import Message

from . import config, db, llm, rag

logging.basicConfig(level=logging.INFO)
dp = Dispatcher()

WELCOME = (
    "Сәлем! Я «Адал қоғам AI» — справочник-навигатор по внутренней политике Казахстана: "
    "Конституция 2026, законы, Послания Главы государства, ценности и принципы "
    "(«Закон и Порядок», «Адал азамат», «Справедливый Казахстан» и др.).\n\n"
    "Задайте вопрос текстом или голосом на русском или казахском — отвечу со ссылкой на источник. "
    "Если подтверждённой информации нет, так и скажу.\n\n"
    "Примеры:\n• Что такое «Слышащее государство»?\n• Закреплён ли принцип «Закон и Порядок» в Конституции?\n"
    "• Адал азамат деген не?"
)


@dp.message(CommandStart())
@dp.message(Command("help"))
async def start(m: Message):
    await m.answer(WELCOME)


@dp.message(Command("stats"))
async def stats(m: Message):
    if m.from_user.id not in config.ADMIN_IDS:
        return
    with db.connect() as conn:
        total, ok = conn.execute("SELECT count(*), count(*) FILTER (WHERE answered) FROM query_log").fetchone()
        top = conn.execute(
            "SELECT question, count(*) c FROM query_log GROUP BY question ORDER BY c DESC LIMIT 5"
        ).fetchall()
        langs = conn.execute("SELECT lang, count(*) FROM query_log GROUP BY lang").fetchall()
        docs, chunks = conn.execute("SELECT (SELECT count(*) FROM documents), (SELECT count(*) FROM chunks)").fetchone()
    text = (
        f"📊 Запросов: {total}, с ответом: {ok}, без данных: {total - ok}\n"
        f"Языки: {', '.join(f'{l}={c}' for l, c in langs) or '—'}\n"
        f"База: {docs} документов, {chunks} фрагментов\n\nТоп вопросов:\n"
        + "\n".join(f"{c}× {q}" for q, c in top)
    )
    await m.answer(text)


async def reply(m: Message, question: str):
    await m.bot.send_chat_action(m.chat.id, "typing")
    res = await rag.answer(question, m.from_user.id)
    out = res.text + rag.format_sources(res.sources)
    for i in range(0, len(out), 4000):  # лимит Telegram 4096
        await m.answer(out[i : i + 4000], disable_web_page_preview=True)


@dp.message(F.voice)
async def voice(m: Message):
    try:
        buf = io.BytesIO()
        await m.bot.download(m.voice, destination=buf)
        text = await llm.transcribe(buf.getvalue())
    except Exception as e:
        logging.error("voice error: %r", e)
        await m.answer("Не удалось распознать голосовое сообщение. Попробуйте ещё раз или напишите текстом.")
        return
    if not text:
        await m.answer("Не удалось разобрать речь. Попробуйте ещё раз.")
        return
    await m.answer(f"🎤 {text}")
    await reply(m, text)


@dp.message(F.text & ~F.text.startswith("/"))
async def text(m: Message):
    q = m.text.strip()
    if len(q) < 2:
        await m.answer("Пожалуйста, сформулируйте вопрос подробнее.")
        return
    await reply(m, q[:1000])


@dp.message()
async def other(m: Message):
    await m.answer("Я понимаю текстовые и голосовые сообщения. Задайте вопрос словами.")


async def main():
    db.init_schema()
    bot = Bot(config.TELEGRAM_BOT_TOKEN)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
