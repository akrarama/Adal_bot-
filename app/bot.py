import asyncio
import io
import logging

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command, CommandStart
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from . import config, db, llm, rag

logging.basicConfig(level=logging.INFO)
dp = Dispatcher()

# Состояние по пользователям (в памяти): последние вопросы, последний ответ, прогресс викторины
STATE: dict[int, dict] = {}


def st(uid: int) -> dict:
    return STATE.setdefault(uid, {"history": [], "last": None, "score": 0})


WELCOME = (
    "Сәлем! Я «Адал қоғам AI» — справочник-навигатор по внутренней политике Казахстана: "
    "Конституция 2026, законы, Послания Главы государства, ценности и принципы "
    "(«Закон и Порядок», «Адал азамат», «Справедливый Казахстан» и др.).\n\n"
    "Задайте вопрос текстом или голосом на русском или казахском — отвечу со ссылкой на источник. "
    "Если подтверждённой информации нет, так и скажу.\n\n"
    "Примеры:\n• Что такое «Слышащее государство»?\n• Закреплён ли принцип «Закон и Порядок» в Конституции?\n"
    "• Президентті қанша жылға сайлайды?\n\n"
    "Команды: /quiz — викторина по Конституции, /help — справка."
)


@dp.message(CommandStart())
@dp.message(Command("help"))
async def start(m: Message):
    await m.answer(WELCOME)


# ---------- аналитика ----------
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


# ---------- ответы на вопросы ----------
def answer_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="💡 Объяснить проще", callback_data="simple"),
                InlineKeyboardButton(text="📄 Текст статьи", callback_data="text"),
            ]
        ]
    )


async def send_long(target: Message, text: str, kb=None):
    parts = [text[i : i + 4000] for i in range(0, len(text), 4000)] or [""]
    for idx, part in enumerate(parts):
        last = idx == len(parts) - 1
        await target.answer(part, disable_web_page_preview=True, reply_markup=kb if last else None)


async def reply(m: Message, question: str, user_id: int, simple: bool = False):
    s = st(user_id)
    await m.bot.send_chat_action(m.chat.id, "typing")
    res = await rag.answer(question, user_id, history=s["history"][-2:], simple=simple)
    s["last"] = res
    if not simple:
        s["history"].append(question)
        s["history"] = s["history"][-5:]
    out = res.text + rag.format_sources(res.sources)
    await send_long(m, out, answer_kb() if res.answered else None)


@dp.callback_query(F.data == "simple")
async def cb_simple(cb: CallbackQuery):
    await cb.answer()
    last = st(cb.from_user.id)["last"]
    if not last or not last.question:
        await cb.message.answer("Сначала задайте вопрос.")
        return
    await reply(cb.message, last.question, cb.from_user.id, simple=True)


@dp.callback_query(F.data == "text")
async def cb_text(cb: CallbackQuery):
    await cb.answer()
    last = st(cb.from_user.id)["last"]
    if not last or not last.sources:
        await cb.message.answer("Нет источника для показа. Задайте вопрос.")
        return
    for s in last.sources[:2]:
        await send_long(cb.message, f"📄 {s['title']}, {s['section']}\n\n{s['content']}")


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
    await reply(m, text, m.from_user.id)


# ---------- викторина ----------
QUIZ = [
    {"q": "На какой срок избирается Президент Республики Казахстан?", "opts": ["5 лет", "7 лет", "6 лет"], "a": 1, "src": "Статья 43"},
    {"q": "Сколько депутатов в Курултае?", "opts": ["125", "145", "175"], "a": 1, "src": "Статья 53"},
    {"q": "Как Конституция относится к смертной казни?", "opts": ["Запрещена", "Допускается за особо тяжкие преступления", "Допускается в военное время"], "a": 0, "src": "Статья 17"},
    {"q": "Допускается ли двойное гражданство?", "opts": ["Да, по заявлению", "Нет", "Только для экс-Президентов"], "a": 1, "src": "Статья 13"},
    {"q": "Какой язык является государственным?", "opts": ["Русский", "Казахский", "Казахский и английский"], "a": 1, "src": "Статья 9"},
    {"q": "Допускается ли цензура?", "opts": ["Допускается в военное время", "Запрещена", "Допускается по решению суда"], "a": 1, "src": "Статья 23"},
    {"q": "С какой даты вступает в силу Конституция, принятая на референдуме 15 марта 2026?", "opts": ["15 марта 2026", "1 июля 2026", "1 января 2027"], "a": 1, "src": "Статья 94"},
    {"q": "На какой срок назначаются судьи Конституционного Суда?", "opts": ["5 лет", "8 лет", "10 лет"], "a": 1, "src": "Статья 72"},
]


def quiz_kb(i: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text=o, callback_data=f"qz:{i}:{j}")] for j, o in enumerate(QUIZ[i]["opts"])]
    )


@dp.message(Command("quiz"))
async def quiz_start(m: Message):
    st(m.from_user.id)["score"] = 0
    await m.answer(f"🎯 Викторина по Конституции 2026 ({len(QUIZ)} вопросов)\n\n1/{len(QUIZ)}. {QUIZ[0]['q']}", reply_markup=quiz_kb(0))


@dp.callback_query(F.data.startswith("qz:"))
async def quiz_answer(cb: CallbackQuery):
    _, i, j = cb.data.split(":")
    i, j = int(i), int(j)
    q = QUIZ[i]
    s = st(cb.from_user.id)
    right = j == q["a"]
    if right:
        s["score"] += 1
    await cb.answer("Верно! ✅" if right else "Неверно ❌")
    await cb.message.edit_text(
        f"{i + 1}/{len(QUIZ)}. {q['q']}\n\n"
        + ("✅ Верно" if right else f"❌ Неверно. Правильный ответ: {q['opts'][q['a']]}")
        + f" ({q['src']})"
    )
    if i + 1 < len(QUIZ):
        await cb.message.answer(f"{i + 2}/{len(QUIZ)}. {QUIZ[i + 1]['q']}", reply_markup=quiz_kb(i + 1))
    else:
        await cb.message.answer(f"🏁 Готово! Ваш результат: {s['score']} из {len(QUIZ)}. Ещё раз: /quiz")


# ---------- обычные сообщения ----------
@dp.message(F.text & ~F.text.startswith("/"))
async def text(m: Message):
    q = m.text.strip()
    if len(q) < 2:
        await m.answer("Пожалуйста, сформулируйте вопрос подробнее.")
        return
    await reply(m, q[:1000], m.from_user.id)


@dp.message()
async def other(m: Message):
    await m.answer("Я понимаю текстовые и голосовые сообщения. Задайте вопрос словами.")


async def main():
    db.init_schema()
    bot = Bot(config.TELEGRAM_BOT_TOKEN)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
