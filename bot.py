"""
bot.py — Telegram bot for video montage control
Handles: style selection, effect toggles, Drive links, progress notifications
"""

import os
import logging
import asyncio
import tempfile
import shutil
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    ContextTypes, MessageHandler, filters
)
from drive_handler import download_folder_videos, download_audio_file, upload_file
from video_processor import analyze_clip, build_video, STYLE_PRESETS

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

TOKEN = os.environ.get("BOT_TOKEN", "")
AUTHORIZED_USER = int(os.environ.get("AUTHORIZED_USER_ID", "0"))

user_state = {}

# ─── STYLE CONFIG ─────────────────────────────────────────────────────────────

STYLES = {
    "phonk":    "🔥 Phonk Universe",
    "japanese": "⛩ Japanese Trap",
    "house":    "🎧 Deep House",
}

EFFECTS_LABELS = {
    "film_grain":          "📽 Плёнка/зерно",
    "vignette":            "🌑 Виньетка",
    "chromatic_aberration":"🌈 Хроматика",
    "rain":                "🌧 Дождь",
    "bloom":               "✨ Bloom/свечение",
    "sparkles":            "💫 Спарклс",
    "vhs":                 "📼 VHS эффект",
    "flash":               "⚡ Вспышки",
}

# ─── KEYBOARDS ────────────────────────────────────────────────────────────────

def kb_styles():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(label, callback_data=f"style:{key}")]
        for key, label in STYLES.items()
    ])


def kb_effects(style: str, overrides: dict):
    """Show effects toggle keyboard based on preset + user overrides."""
    preset_effects = STYLE_PRESETS[style]["effects"]
    rows = []
    for key, label in EFFECTS_LABELS.items():
        # Current state: preset default + override
        is_on = overrides.get(key, preset_effects.get(key, False))
        icon = "✅" if is_on else "⬜"
        rows.append([InlineKeyboardButton(
            f"{icon} {label}",
            callback_data=f"fx:{key}"
        )])
    rows.append([InlineKeyboardButton("▶️ Продолжить", callback_data="fx:done")])
    return InlineKeyboardMarkup(rows)


def kb_visualizer_confirm():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Оставить пресет", callback_data="vis:preset"),
         InlineKeyboardButton("❌ Без визуализатора", callback_data="vis:none")]
    ])


# ─── HANDLERS ─────────────────────────────────────────────────────────────────

def is_authorized(uid):
    return AUTHORIZED_USER == 0 or uid == AUTHORIZED_USER


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not is_authorized(uid):
        await update.message.reply_text("❌ Нет доступа.")
        return

    user_state[uid] = {"overrides": {}, "visualizer": True}
    await update.message.reply_text(
        "🎬 *VIDEO MONTAGE BOT*\n\n"
        "Автомонтаж видео под музыкальный трек.\n\n"
        "Выбери стиль канала:",
        parse_mode="Markdown",
        reply_markup=kb_styles()
    )


async def cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id
    data = q.data
    s = user_state.get(uid, {})

    # Style selection
    if data.startswith("style:"):
        style = data[6:]
        s["style"] = style
        user_state[uid] = s
        preset = STYLE_PRESETS[style]

        # Show effects with preset defaults
        style_label = STYLES[style]
        vis_type = preset["visualizer_type"]
        vis_pos = preset["visualizer_position"]

        await q.edit_message_text(
            f"✅ Стиль: *{style_label}*\n\n"
            f"📊 Визуализатор: *{vis_type}* ({vis_pos})\n\n"
            f"Настрой эффекты (нажми чтобы включить/выключить):",
            parse_mode="Markdown",
            reply_markup=kb_effects(style, s.get("overrides", {}))
        )

    # Effects toggle
    elif data.startswith("fx:"):
        effect = data[3:]
        if effect == "done":
            await q.edit_message_text(
                "🎬 Оставить визуализатор?\n\n"
                f"Пресет: *{STYLE_PRESETS[s['style']]['visualizer_type']}* "
                f"({STYLE_PRESETS[s['style']]['visualizer_position']})",
                parse_mode="Markdown",
                reply_markup=kb_visualizer_confirm()
            )
        else:
            overrides = s.get("overrides", {})
            preset_val = STYLE_PRESETS[s["style"]]["effects"].get(effect, False)
            # Toggle: if not in overrides use preset, then flip
            current = overrides.get(effect, preset_val)
            overrides[effect] = not current
            s["overrides"] = overrides
            user_state[uid] = s

            await q.edit_message_reply_markup(
                reply_markup=kb_effects(s["style"], overrides)
            )

    # Visualizer choice
    elif data.startswith("vis:"):
        choice = data[4:]
        s["visualizer"] = (choice == "preset")
        user_state[uid] = s
        s["step"] = "awaiting_video_link"

        await q.edit_message_text(
            "📁 Отправь ссылку на папку *Google Drive с видеоклипами* (MP4).\n\n"
            "⚠️ Папка должна быть открыта (Anyone with the link)",
            parse_mode="Markdown"
        )

    # Audio link (after video link received)
    elif data == "audio:next":
        s["step"] = "awaiting_audio_link"
        await q.edit_message_text(
            "🎵 Теперь отправь ссылку на *аудиофайл* в Google Drive (MP3).\n\n"
            "Это должен быть прямой файл, не папка.",
            parse_mode="Markdown"
        )


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not is_authorized(uid):
        return

    s = user_state.get(uid, {})
    text = update.message.text.strip()
    step = s.get("step", "")

    if step == "awaiting_video_link":
        if "drive.google.com" not in text:
            await update.message.reply_text("❌ Отправь ссылку на Google Drive папку.")
            return
        s["video_folder_link"] = text
        s["step"] = "awaiting_audio_link"
        user_state[uid] = s
        await update.message.reply_text(
            "✅ Папка с видео принята!\n\n"
            "🎵 Теперь отправь ссылку на *аудиофайл* (MP3) в Google Drive:",
            parse_mode="Markdown"
        )

    elif step == "awaiting_audio_link":
        if "drive.google.com" not in text:
            await update.message.reply_text("❌ Отправь ссылку на Google Drive файл.")
            return
        s["audio_link"] = text
        s["step"] = "processing"
        user_state[uid] = s
        await start_processing(update, context, uid)

    else:
        await update.message.reply_text("Напиши /start чтобы начать.")


async def start_processing(update: Update, context: ContextTypes.DEFAULT_TYPE, uid: int):
    s = user_state.get(uid, {})
    msg = await update.message.reply_text("⏳ Начинаю обработку...")

    async def progress(text: str):
        try:
            await msg.edit_text(text)
        except:
            pass

    tmpdir = tempfile.mkdtemp()
    try:
        # Extract IDs
        video_folder_id = extract_drive_id(s["video_folder_link"], is_folder=True)
        audio_file_id = extract_drive_id(s["audio_link"], is_folder=False)

        if not video_folder_id or not audio_file_id:
            await msg.edit_text("❌ Не могу распознать ссылки Drive. Проверь формат.")
            return

        await progress("📥 Скачиваю видеоклипы из Drive...")
        video_clips = await asyncio.get_event_loop().run_in_executor(
            None, download_folder_videos, video_folder_id, tmpdir
        )

        if not video_clips:
            await msg.edit_text("❌ В папке нет MP4 файлов.")
            return

        await progress(f"📥 Скачано {len(video_clips)} клипов. Скачиваю аудио...")
        audio_path = await asyncio.get_event_loop().run_in_executor(
            None, download_audio_file, audio_file_id, tmpdir
        )

        if not audio_path:
            await msg.edit_text("❌ Не удалось скачать аудиофайл.")
            return

        await progress(f"🔍 Анализирую {len(video_clips)} клипов...")
        clips = []
        for vp in video_clips:
            clip_data = await asyncio.get_event_loop().run_in_executor(
                None, analyze_clip, vp
            )
            if clip_data:
                clips.append(clip_data)

        await progress(f"✅ Проанализировано {len(clips)} клипов. Строю монтаж...")

        output_path = os.path.join(tmpdir, "FINAL_VIDEO.mp4")

        def sync_progress(text):
            asyncio.run_coroutine_threadsafe(progress(text), context.application.loop)

        result = await asyncio.get_event_loop().run_in_executor(
            None, build_video,
            clips, audio_path, s["style"],
            s.get("overrides", {}),
            tmpdir, output_path, sync_progress
        )

        await progress("📤 Загружаю в Google Drive...")
        drive_link = await asyncio.get_event_loop().run_in_executor(
            None, upload_file, output_path, video_folder_id
        )

        await msg.edit_text(
            f"🎉 *ГОТОВО!*\n\n"
            f"⏱ Длина: {result['duration']}\n"
            f"🥁 BPM: {result['bpm']}\n"
            f"🎬 Клипов использовано: {result['clips_used']}\n"
            f"💾 Размер: {result['file_size_gb']} GB\n\n"
            f"🔗 [Скачать видео]({drive_link})\n\n"
            f"Напиши /start для нового видео.",
            parse_mode="Markdown",
            disable_web_page_preview=True
        )

    except Exception as e:
        logger.error(f"Processing error: {e}", exc_info=True)
        await msg.edit_text(f"❌ Ошибка: {str(e)[:300]}\n\nНапиши /start снова.")
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
        s["step"] = "done"
        user_state[uid] = s


def extract_drive_id(url: str, is_folder: bool) -> str:
    import re
    if is_folder:
        patterns = [r'/folders/([a-zA-Z0-9_-]+)', r'id=([a-zA-Z0-9_-]+)']
    else:
        patterns = [r'/file/d/([a-zA-Z0-9_-]+)', r'id=([a-zA-Z0-9_-]+)']
    for p in patterns:
        m = re.search(p, url)
        if m:
            return m.group(1)
    return ""


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🎬 *VIDEO MONTAGE BOT*\n\n"
        "*/start* — начать новый монтаж\n\n"
        "*Пайплайн:*\n"
        "1. Выбери стиль канала\n"
        "2. Настрой эффекты\n"
        "3. Выбери визуализатор\n"
        "4. Отправь ссылку на папку с видео\n"
        "5. Отправь ссылку на аудиофайл\n"
        "6. Получи готовое видео в Drive\n\n"
        "*Стили:*\n"
        "🔥 Phonk — тёмный, зерно, виньетка\n"
        "⛩ Japanese — неон, дождь, хроматика\n"
        "🎧 Deep House — тепло, bloom, спарклс",
        parse_mode="Markdown"
    )


def main():
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CallbackQueryHandler(cb))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    logger.info("Video Montage Bot started!")
    app.run_polling()


if __name__ == "__main__":
    main()
