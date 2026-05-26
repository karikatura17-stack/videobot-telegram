"""Railway Telegram bot: gathers render options and starts a Cloud Run job."""

import logging
import os

import aiohttp
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, ContextTypes, MessageHandler, filters

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

TOKEN = os.environ.get("BOT_TOKEN", "")
AUTHORIZED_USER = int(os.environ.get("AUTHORIZED_USER_ID", "0"))
CLOUD_RUN_URL = os.environ.get("CLOUD_RUN_URL", "")

user_state = {}

STYLES = {
    "phonk": "Phonk Universe",
    "japanese": "Japanese Trap",
    "house": "Deep House",
}

# These choices are implemented in video_processor.py with native ffmpeg filters.
EFFECTS_LABELS = {
    "film_grain": "Плёнка / зерно",
    "vignette": "Виньетка",
    "chromatic_aberration": "Хроматика",
    "vhs": "VHS",
    "bloom": "Bloom / свечение",
}

PRESET_EFFECTS = {
    "phonk": {"film_grain": True, "vignette": True, "vhs": True, "chromatic_aberration": False, "bloom": False},
    "japanese": {"film_grain": False, "vignette": True, "vhs": False, "chromatic_aberration": True, "bloom": True},
    "house": {"film_grain": False, "vignette": False, "vhs": False, "chromatic_aberration": False, "bloom": True},
}

VIS_DEFAULTS = {
    "phonk": {"type": "bars", "position": "bottom", "height": 80},
    "japanese": {"type": "waveform", "position": "top", "height": 60},
    "house": {"type": "circular", "position": "center_bottom", "height": 100},
}

MONTAGE_DEFAULTS = {
    "allow_mirror": True,
    "allow_reverse": False,
    "allow_mirror_reverse": False,
    "allow_random_trim": True,
    "transition_style": "cut",
    "beat_cut_mode": "auto",
    "clip_order_mode": "visual_match",
}

VIS_LABELS = {"bars": "Bars", "waveform": "Waveform", "circular": "Circular"}
POSITION_LABELS = {"bottom": "Bottom", "top": "Top", "center_bottom": "Center bottom"}
TRANSITION_LABELS = {"cut": "cut", "crossfade": "crossfade", "glitch": "glitch"}
BEAT_LABELS = {"auto": "auto", "4_beats": "4 beats", "8_beats": "8 beats", "16_beats": "16 beats"}
ORDER_LABELS = {"visual_match": "visual match", "random": "random", "quality_weighted": "quality weighted"}


def is_authorized(uid: int) -> bool:
    return AUTHORIZED_USER == 0 or uid == AUTHORIZED_USER


def state(uid: int) -> dict:
    if uid not in user_state:
        user_state[uid] = {}
    return user_state[uid]


def kb_styles() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(label, callback_data=f"style:{key}")]
        for key, label in STYLES.items()
    ])


def kb_effects(st: dict) -> InlineKeyboardMarkup:
    rows = []
    for key, label in EFFECTS_LABELS.items():
        mark = "✅" if st["effects_config"].get(key, False) else "⬜"
        rows.append([InlineKeyboardButton(f"{mark} {label}", callback_data=f"fx:{key}")])
    rows.append([InlineKeyboardButton("Продолжить →", callback_data="fx:done")])
    return InlineKeyboardMarkup(rows)


def kb_visualizer_type() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Без визуализатора", callback_data="vis_type:none")],
        [InlineKeyboardButton("Bars", callback_data="vis_type:bars"),
         InlineKeyboardButton("Waveform", callback_data="vis_type:waveform")],
        [InlineKeyboardButton("Circular", callback_data="vis_type:circular")],
    ])


def kb_visualizer_position() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Bottom", callback_data="vis_pos:bottom"),
         InlineKeyboardButton("Top", callback_data="vis_pos:top")],
        [InlineKeyboardButton("Center bottom", callback_data="vis_pos:center_bottom")],
    ])


def toggle_text(enabled: bool) -> str:
    return "ON" if enabled else "OFF"


def kb_montage(config: dict) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"Mirror: {toggle_text(config['allow_mirror'])}", callback_data="montage:allow_mirror"),
         InlineKeyboardButton(f"Reverse: {toggle_text(config['allow_reverse'])}", callback_data="montage:allow_reverse")],
        [InlineKeyboardButton(f"Mirror + reverse: {toggle_text(config['allow_mirror_reverse'])}", callback_data="montage:allow_mirror_reverse")],
        [InlineKeyboardButton(f"Random trim: {toggle_text(config['allow_random_trim'])}", callback_data="montage:allow_random_trim")],
        [InlineKeyboardButton(f"Transition: {TRANSITION_LABELS[config['transition_style']]}", callback_data="montage:transition_style")],
        [InlineKeyboardButton(f"Beat cuts: {BEAT_LABELS[config['beat_cut_mode']]}", callback_data="montage:beat_cut_mode")],
        [InlineKeyboardButton(f"Order: {ORDER_LABELS[config['clip_order_mode']]}", callback_data="montage:clip_order_mode")],
        [InlineKeyboardButton("Проверить настройки →", callback_data="montage:done")],
    ])


def cycle(current: str, choices: list[str]) -> str:
    return choices[(choices.index(current) + 1) % len(choices)]


def summary_text(st: dict) -> str:
    effects = [label for key, label in EFFECTS_LABELS.items() if st["effects_config"].get(key)]
    vis = st["visualizer_config"]
    if vis["enabled"]:
        visualizer = f"{VIS_LABELS[vis['type']]}, {POSITION_LABELS[vis['position']]}, {vis['height']} px"
    else:
        visualizer = "выключен"
    montage = st["montage_config"]
    variants = [
        f"mirror {toggle_text(montage['allow_mirror'])}",
        f"reverse {toggle_text(montage['allow_reverse'])}",
        f"mirror+reverse {toggle_text(montage['allow_mirror_reverse'])}",
        f"random trim {toggle_text(montage['allow_random_trim'])}",
    ]
    return (
        "*Итоговые настройки*\n\n"
        f"*Style:* {STYLES[st['style']]}\n"
        f"*Effects:* {', '.join(effects) if effects else 'выключены'}\n"
        f"*Visualizer:* {visualizer}\n"
        f"*Montage:* {', '.join(variants)}; transition {montage['transition_style']}; "
        f"cuts {BEAT_LABELS[montage['beat_cut_mode']]}; order {ORDER_LABELS[montage['clip_order_mode']]}"
    )


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not is_authorized(uid):
        return
    user_state[uid] = {}
    await update.message.reply_text(
        "🎬 *VIDEO MONTAGE BOT*\n\nВыбери стиль:",
        parse_mode="Markdown",
        reply_markup=kb_styles(),
    )


async def cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    uid = query.from_user.id
    if not is_authorized(uid):
        return
    data = query.data
    st = state(uid)

    if data.startswith("style:"):
        style = data.split(":", 1)[1]
        st.update({
            "style": style,
            "effects_config": dict(PRESET_EFFECTS[style]),
            "visualizer_config": {"enabled": True, **VIS_DEFAULTS[style]},
            "montage_config": dict(MONTAGE_DEFAULTS),
        })
        await query.edit_message_text(
            f"Стиль: *{STYLES[style]}*\n\nВыбери эффекты:",
            parse_mode="Markdown",
            reply_markup=kb_effects(st),
        )
        return

    if data.startswith("fx:"):
        effect = data.split(":", 1)[1]
        if effect == "done":
            await query.edit_message_text("Выбери визуализатор:", reply_markup=kb_visualizer_type())
        elif effect in EFFECTS_LABELS:
            st["effects_config"][effect] = not st["effects_config"].get(effect, False)
            await query.edit_message_reply_markup(reply_markup=kb_effects(st))
        return

    if data.startswith("vis_type:"):
        vis_type = data.split(":", 1)[1]
        if vis_type == "none":
            st["visualizer_config"]["enabled"] = False
            await query.edit_message_text("Настрой монтаж:", reply_markup=kb_montage(st["montage_config"]))
        else:
            st["visualizer_config"].update({"enabled": True, "type": vis_type})
            await query.edit_message_text("Где разместить визуализатор?", reply_markup=kb_visualizer_position())
        return

    if data.startswith("vis_pos:"):
        st["visualizer_config"]["position"] = data.split(":", 1)[1]
        await query.edit_message_text("Настрой монтаж:", reply_markup=kb_montage(st["montage_config"]))
        return

    if data.startswith("montage:"):
        choice = data.split(":", 1)[1]
        config = st["montage_config"]
        if choice in {"allow_mirror", "allow_reverse", "allow_mirror_reverse", "allow_random_trim"}:
            config[choice] = not config[choice]
            await query.edit_message_reply_markup(reply_markup=kb_montage(config))
        elif choice == "transition_style":
            config[choice] = cycle(config[choice], ["cut", "crossfade", "glitch"])
            await query.edit_message_reply_markup(reply_markup=kb_montage(config))
        elif choice == "beat_cut_mode":
            config[choice] = cycle(config[choice], ["auto", "4_beats", "8_beats", "16_beats"])
            await query.edit_message_reply_markup(reply_markup=kb_montage(config))
        elif choice == "clip_order_mode":
            config[choice] = cycle(config[choice], ["visual_match", "random", "quality_weighted"])
            await query.edit_message_reply_markup(reply_markup=kb_montage(config))
        elif choice == "done":
            await query.edit_message_text(
                summary_text(st),
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("✅ Start render setup", callback_data="setup:start")
                ]]),
            )
        return

    if data == "setup:start":
        st["step"] = "awaiting_video_link"
        await query.edit_message_text(
            "📁 Отправь ссылку на папку Google Drive с *видеоклипами* (MP4).\n\n"
            "Папка должна быть открыта по ссылке, а сервисный аккаунт добавлен как Editor.",
            parse_mode="Markdown",
        )


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not is_authorized(uid):
        return
    st = state(uid)
    text = update.message.text.strip()
    if st.get("step") == "awaiting_video_link":
        if "drive.google.com" not in text:
            await update.message.reply_text("Нужна ссылка на папку Google Drive.")
            return
        st["video_link"] = text
        st["step"] = "awaiting_audio_link"
        await update.message.reply_text(
            "Видео принято. Теперь отправь ссылку на *аудиофайл* MP3 в Google Drive:",
            parse_mode="Markdown",
        )
    elif st.get("step") == "awaiting_audio_link":
        if "drive.google.com" not in text:
            await update.message.reply_text("Нужна ссылка на аудиофайл Google Drive.")
            return
        st["audio_link"] = text
        st["step"] = "processing"
        await launch_render_job(update, uid)
    else:
        await update.message.reply_text("Напиши /start, чтобы начать.")


async def launch_render_job(update: Update, uid: int):
    st = state(uid)
    message = await update.message.reply_text("Отправляю задание на рендер. Прогресс появится здесь в сообщениях.")
    if not CLOUD_RUN_URL:
        await message.edit_text("CLOUD_RUN_URL не настроен.")
        return
    payload = {
        "style": st["style"],
        "effects_config": st["effects_config"],
        "visualizer_config": st["visualizer_config"],
        "montage_config": st["montage_config"],
        "video_link": st["video_link"],
        "audio_link": st["audio_link"],
        "bot_token": TOKEN,
        "user_id": uid,
    }
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{CLOUD_RUN_URL}/render",
                json=payload,
                timeout=aiohttp.ClientTimeout(total=30),
            ) as response:
                if response.status == 200:
                    result = await response.json()
                    await message.edit_text(f"✅ Задание принято. Job ID: `{result.get('job_id', 'unknown')}`", parse_mode="Markdown")
                else:
                    await message.edit_text(f"Ошибка сервера: {response.status}")
    except Exception as exc:
        logger.error("Cloud Run error: %s", exc)
        await message.edit_text(f"Не могу связаться с сервером рендера: {str(exc)[:200]}")
    st["step"] = "done"


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🎬 *VIDEO MONTAGE BOT*\n\n"
        "*/start* — новый монтаж\n"
        "Выбери стиль, реальные эффекты, визуализатор и параметры монтажа, затем отправь ссылки Drive.",
        parse_mode="Markdown",
    )


def main():
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CallbackQueryHandler(cb))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    logger.info("Video Bot started")
    app.run_polling()


if __name__ == "__main__":
    main()
