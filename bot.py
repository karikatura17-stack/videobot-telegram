"""
bot.py — Telegram bot (Railway)
Lightweight: accepts commands, sends render job to Cloud Run, notifies user
"""

import os
import json
import logging
import asyncio
import aiohttp
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    ContextTypes, MessageHandler, filters
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

TOKEN = os.environ.get("BOT_TOKEN", "")
AUTHORIZED_USER = int(os.environ.get("AUTHORIZED_USER_ID", "0"))
CLOUD_RUN_URL = os.environ.get("CLOUD_RUN_URL", "")  # set after Cloud Run deploy

user_state = {}

STYLES = {
    "phonk":    "🔥 Phonk Universe",
    "japanese": "⛩ Japanese Trap",
    "house":    "🎧 Deep House",
}

EFFECTS_LABELS = {
    "film_grain":           "📽 Плёнка/зерно",
    "vignette":             "🌑 Виньетка",
    "chromatic_aberration": "🌈 Хроматика",
    "rain":                 "🌧 Дождь",
    "bloom":                "✨ Bloom/свечение",
    "sparkles":             "💫 Спарклс",
    "vhs":                  "📼 VHS эффект",
    "flash":                "⚡ Вспышки",
}

PRESET_EFFECTS = {
    "phonk":    {"film_grain": True, "vignette": True, "vhs": True, "flash": True,
                 "chromatic_aberration": False, "rain": False, "bloom": False, "sparkles": False},
    "japanese": {"chromatic_aberration": True, "rain": True, "bloom": True, "vignette": True,
                 "film_grain": False, "vhs": False, "flash": False, "sparkles": False},
    "house":    {"bloom": True, "sparkles": True,
                 "film_grain": False, "vignette": False, "chromatic_aberration": False,
                 "rain": False, "vhs": False, "flash": False},
}


def is_authorized(uid):
    return AUTHORIZED_USER == 0 or uid == AUTHORIZED_USER


def s(uid):
    if uid not in user_state:
        user_state[uid] = {"overrides": {}}
    return user_state[uid]


def kb_styles():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(label, callback_data=f"style:{key}")]
        for key, label in STYLES.items()
    ])


def kb_effects(style, overrides):
    preset = PRESET_EFFECTS.get(style, {})
    rows = []
    for key, label in EFFECTS_LABELS.items():
        is_on = overrides.get(key, preset.get(key, False))
        icon = "✅" if is_on else "⬜"
        rows.append([InlineKeyboardButton(f"{icon} {label}", callback_data=f"fx:{key}")])
    rows.append([InlineKeyboardButton("▶️ Продолжить", callback_data="fx:done")])
    return InlineKeyboardMarkup(rows)


def kb_visualizer():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Оставить пресет", callback_data="vis:yes"),
         InlineKeyboardButton("❌ Без визуализатора", callback_data="vis:no")]
    ])


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not is_authorized(uid):
        return
    user_state[uid] = {"overrides": {}}
    await update.message.reply_text(
        "🎬 *VIDEO MONTAGE BOT*\n\nВыбери стиль канала:",
        parse_mode="Markdown",
        reply_markup=kb_styles()
    )


async def cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id
    data = q.data
    st = s(uid)

    if data.startswith("style:"):
        st["style"] = data[6:]
        await q.edit_message_text(
            f"✅ Стиль: *{STYLES[st['style']]}*\n\nНастрой эффекты:",
            parse_mode="Markdown",
            reply_markup=kb_effects(st["style"], st.get("overrides", {}))
        )

    elif data.startswith("fx:"):
        effect = data[3:]
        if effect == "done":
            await q.edit_message_text(
                "Оставить визуализатор?",
                reply_markup=kb_visualizer()
            )
        else:
            ov = st.get("overrides", {})
            preset_val = PRESET_EFFECTS.get(st["style"], {}).get(effect, False)
            ov[effect] = not ov.get(effect, preset_val)
            st["overrides"] = ov
            await q.edit_message_reply_markup(
                reply_markup=kb_effects(st["style"], ov)
            )

    elif data.startswith("vis:"):
        st["visualizer"] = data[4:] == "yes"
        st["step"] = "awaiting_video_link"
        await q.edit_message_text(
            "📁 Отправь ссылку на папку Google Drive с *видеоклипами* (MP4).\n\n"
            "⚠️ Папка открыта для просмотра (Anyone with the link)\n"
            "⚠️ Сервис аккаунт добавлен как Editor в папку",
            parse_mode="Markdown"
        )


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not is_authorized(uid):
        return
    st = s(uid)
    text = update.message.text.strip()
    step = st.get("step", "")

    if step == "awaiting_video_link":
        if "drive.google.com" not in text:
            await update.message.reply_text("❌ Нужна ссылка на Google Drive папку.")
            return
        st["video_link"] = text
        st["step"] = "awaiting_audio_link"
        await update.message.reply_text(
            "✅ Папка с видео принята!\n\n"
            "🎵 Теперь ссылку на *аудиофайл* (MP3) в Google Drive:",
            parse_mode="Markdown"
        )

    elif step == "awaiting_audio_link":
        if "drive.google.com" not in text:
            await update.message.reply_text("❌ Нужна ссылка на Google Drive файл.")
            return
        st["audio_link"] = text
        st["step"] = "processing"
        await launch_render_job(update, context, uid)

    else:
        await update.message.reply_text("Напиши /start чтобы начать.")


async def launch_render_job(update: Update, context: ContextTypes.DEFAULT_TYPE, uid: int):
    st = s(uid)
    msg = await update.message.reply_text(
        "🚀 Отправляю задание на рендер...\n"
        "Это займёт 30-90 минут в зависимости от длины трека.\n"
        "Я пришлю уведомление когда будет готово!"
    )

    if not CLOUD_RUN_URL:
        await msg.edit_text("❌ CLOUD_RUN_URL не настроен. Обратись к администратору.")
        return

    payload = {
        "user_id": uid,
        "style": st["style"],
        "overrides": st.get("overrides", {}),
        "visualizer": st.get("visualizer", True),
        "video_link": st["video_link"],
        "audio_link": st["audio_link"],
        "bot_token": TOKEN,
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{CLOUD_RUN_URL}/render",
                json=payload,
                timeout=aiohttp.ClientTimeout(total=30)
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    await msg.edit_text(
                        f"✅ Задание принято!\n\n"
                        f"🆔 Job ID: `{data.get('job_id', 'unknown')}`\n\n"
                        f"Пришлю ссылку когда видео будет готово.",
                        parse_mode="Markdown"
                    )
                else:
                    await msg.edit_text(f"❌ Ошибка сервера: {resp.status}")
    except Exception as e:
        logger.error(f"Cloud Run error: {e}")
        await msg.edit_text(f"❌ Не могу связаться с сервером рендера: {str(e)[:200]}")

    st["step"] = "done"


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🎬 *VIDEO MONTAGE BOT*\n\n"
        "*/start* — новый монтаж\n"
        "*/help* — помощь\n\n"
        "*Пайплайн:*\n"
        "1. Стиль канала\n"
        "2. Эффекты (включить/выключить)\n"
        "3. Визуализатор\n"
        "4. Ссылка на папку с видео (Drive)\n"
        "5. Ссылка на аудио (Drive)\n"
        "6. Ждёшь — получаешь ссылку на готовое видео",
        parse_mode="Markdown"
    )


def main():
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CallbackQueryHandler(cb))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    logger.info("Video Bot started!")
    app.run_polling()


if __name__ == "__main__":
    main()
