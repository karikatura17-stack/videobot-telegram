"""Railway Telegram bot: polished setup flow for montage render jobs."""

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
active_jobs = {}

STYLES = {
    "phonk": "🔥 Phonk Universe",
    "japanese": "⛩ Japanese Trap",
    "house": "🎧 Deep House",
}

EFFECTS = {
    "high_contrast": {"title": "High contrast", "emoji": "◐", "category": "🎨 Color / Look"},
    "saturation_boost": {"title": "Saturation boost", "emoji": "🌈", "category": "🎨 Color / Look"},
    "dark_phonk_grade": {"title": "Dark phonk grade", "emoji": "🌑", "category": "🎨 Color / Look"},
    "cold_neon_grade": {"title": "Cold neon grade", "emoji": "🧊", "category": "🎨 Color / Look"},
    "warm_gold_grade": {"title": "Warm gold grade", "emoji": "🌅", "category": "🎨 Color / Look"},
    "film_grain": {"title": "Film grain", "emoji": "🎞", "category": "🎞 Texture"},
    "vignette": {"title": "Vignette", "emoji": "🌘", "category": "🎞 Texture"},
    "scanlines": {"title": "Scanlines", "emoji": "▤", "category": "🎞 Texture"},
    "chromatic_aberration": {"title": "Chromatic aberration", "emoji": "⚡", "category": "⚡ Energy FX"},
}
EFFECT_CATEGORIES = ["🎨 Color / Look", "🎞 Texture", "⚡ Energy FX"]

VISUALIZER_DEFAULTS = {
    "enabled": True,
    "type": "waveform",
    "position": "bottom",
    "size": "small",
    "background_opacity": "none",
    "color": "white",
    "glow": "soft",
    "intensity": "normal",
}
VISUALIZER_TYPES = {
    "waveform": "Waveform",
    "thin_waveform": "Thin waveform",
    "compact_waveform": "Compact waveform",
    "minimal_corner_bars": "Minimal corner bars",
    "label_bars": "Corner label bars",
    "bars": "Full-width bars",
}
STRIP_VISUALIZERS = {"waveform", "thin_waveform", "bars"}
VISUALIZER_STRIP_POSITIONS = {"bottom": "Bottom", "top": "Top"}
VISUALIZER_CORNER_POSITIONS = {
    "bottom_left": "Bottom left",
    "bottom_right": "Bottom right",
    "top_left": "Top left",
    "top_right": "Top right",
}
VISUALIZER_POSITION_LABELS = {**VISUALIZER_STRIP_POSITIONS, **VISUALIZER_CORNER_POSITIONS}
VISUALIZER_SIZES = {"small": "Small", "medium": "Medium", "large": "Large"}
VISUALIZER_BACKGROUNDS = {"none": "None", "soft": "Soft", "medium": "Medium"}
VISUALIZER_COLORS = {
    "purple": "Purple", "red": "Red", "blue": "Blue", "gold": "Gold",
    "white": "White", "cyan": "Cyan", "pink": "Pink",
}
VISUALIZER_GLOWS = {"off": "Off", "soft": "Soft", "strong": "Strong"}
VISUALIZER_INTENSITIES = {"soft": "Soft", "normal": "Normal", "strong": "Strong"}
EFFECT_INTENSITIES = {
    "soft": "Soft - subtle look",
    "normal": "Normal - balanced visible effect",
    "strong": "Strong - expressive/music-video look",
}

MONTAGE_DEFAULTS = {
    "allow_mirror": True,
    "allow_reverse": False,
    "allow_mirror_reverse": False,
    "allow_random_trim": True,
    "transition_style": "cut",
    "beat_cut_mode": "auto",
    "clip_order_mode": "visual_match",
    "speed_accents_mode": "off",
    "speed_accents_amount": 0.20,
    "speed_accents_speed": 1.25,
}
TRANSITIONS = {"cut": "Clean seamless cut", "crossfade": "Crossfade"}
BEAT_CUTS = {
    "auto": "Auto, mixed smooth rhythm",
    "4_beats": "4 beats, short fast cuts",
    "8_beats": "8 beats, medium cuts",
    "12_beats": "12 beats, balanced smooth cuts",
    "16_beats": "16 beats, long calm cuts",
}
CLIP_ORDERS = {"visual_match": "Visual match", "random": "Random", "quality_weighted": "Quality weighted"}
SPEED_ACCENT_MODES = {"off": "OFF", "auto": "AUTO", "manual": "MANUAL"}
SPEED_ACCENT_AMOUNTS = {0.10: "10% of segments", 0.20: "20% of segments", 0.30: "30% of segments"}
SPEED_ACCENT_SPEEDS = {1.15: "1.15x", 1.25: "1.25x", 1.35: "1.35x", 1.50: "1.50x"}


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


def effects_config() -> dict:
    return {effect_id: False for effect_id in EFFECTS}


def kb_effects(st: dict) -> InlineKeyboardMarkup:
    selected = st["effects_config"]
    clean_mark = "✅" if not any(selected.values()) else "⬜"
    rows = [[InlineKeyboardButton(f"{clean_mark} 🧼 Clean render / no effects", callback_data="fx:clean")]]
    for category in EFFECT_CATEGORIES:
        for effect_id, effect in EFFECTS.items():
            if effect["category"] == category:
                mark = "✅" if selected[effect_id] else "⬜"
                rows.append([InlineKeyboardButton(
                    f"{mark} {category.split()[0]} {effect['emoji']} {effect['title']}", callback_data=f"fx:{effect_id}"
                )])
    rows.append([InlineKeyboardButton("Continue →", callback_data="fx:done")])
    rows.append([InlineKeyboardButton("Restart setup", callback_data="nav:restart")])
    return InlineKeyboardMarkup(rows)


def kb_visualizer_type() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("🚫 No visualizer", callback_data="vis_type:none")]] + [
        [InlineKeyboardButton(label, callback_data=f"vis_type:{vis_type}")]
        for vis_type, label in VISUALIZER_TYPES.items()
        ] + [[InlineKeyboardButton("Back", callback_data="nav:back"), InlineKeyboardButton("Restart setup", callback_data="nav:restart")]]
    )


def option_keyboard(prefix: str, options: dict, navigation: bool = True) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(label, callback_data=f"{prefix}:{value}")]
            for value, label in options.items()]
    if navigation:
        rows.append([InlineKeyboardButton("Back", callback_data="nav:back"), InlineKeyboardButton("Restart setup", callback_data="nav:restart")])
    return InlineKeyboardMarkup(rows)


def visualizer_positions(vis_type: str) -> dict:
    return VISUALIZER_STRIP_POSITIONS if vis_type in STRIP_VISUALIZERS else VISUALIZER_CORNER_POSITIONS


def visualizer_position_label(position: str) -> str:
    legacy_positions = {"bottom_overlay": "bottom", "top_overlay": "top", "center_bottom": "bottom"}
    return VISUALIZER_POSITION_LABELS.get(legacy_positions.get(position, position), "Bottom")


def on_off(enabled: bool) -> str:
    return "ON" if enabled else "OFF"


def kb_montage(config: dict) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"🪞 Mirror: {on_off(config['allow_mirror'])}", callback_data="montage:allow_mirror")],
        [InlineKeyboardButton(f"↩ Reverse: {on_off(config['allow_reverse'])}", callback_data="montage:allow_reverse")],
        [InlineKeyboardButton(f"🪞↩ Mirror + reverse: {on_off(config['allow_mirror_reverse'])}", callback_data="montage:allow_mirror_reverse")],
        [InlineKeyboardButton(f"✂ Random trim: {on_off(config['allow_random_trim'])}", callback_data="montage:allow_random_trim")],
        [InlineKeyboardButton(f"Transition: {TRANSITIONS[config['transition_style']]}", callback_data="montage:transition_style")],
        [InlineKeyboardButton(f"Beat cut: {BEAT_CUTS[config['beat_cut_mode']]}", callback_data="montage:beat_cut_mode")],
        [InlineKeyboardButton(f"Clip order: {CLIP_ORDERS[config['clip_order_mode']]}", callback_data="montage:clip_order_mode")],
        [InlineKeyboardButton(f"⚡ Speed accents: {SPEED_ACCENT_MODES[config['speed_accents_mode']]}", callback_data="montage:speed_accents_mode")],
        [InlineKeyboardButton("Review setup →", callback_data="montage:done")],
        [InlineKeyboardButton("Back", callback_data="nav:back"), InlineKeyboardButton("Restart setup", callback_data="nav:restart")],
    ])


def kb_speed_accents_mode() -> InlineKeyboardMarkup:
    return option_keyboard("speed_mode", SPEED_ACCENT_MODES)


def cycle(current: str, choices: list[str]) -> str:
    return choices[(choices.index(current) + 1) % len(choices)]


def montage_text() -> str:
    return (
        "🎬 *Montage settings*\n\n"
        "Toggle options and choose an edit rhythm.\n\n"
        "🪞 Mirror is usually safe.\n"
        "↩ Reverse should be disabled for walking or directional clips.\n"
        "✂ Random trim helps repeated clips feel less repetitive.\n"
        "🎨 Visual match orders clips by color, brightness and motion compatibility.\n\n"
        "⚡ Speed accents randomly speed up selected video segments under the beat.\n"
        "Use AUTO for quick testing. MANUAL 10-20% at 1.15x-1.25x keeps edits clean.\n"
        "Use 30% at 1.35x-1.50x only for dynamic edits. Audio is never changed."
        "\n\nBeat auto = mostly 12-beat cuts, some 8-beat cuts, rare 4-beat accents, no 16-beat cuts."
    )


def speed_accents_summary(config: dict) -> str:
    mode = config["speed_accents_mode"]
    if mode != "manual":
        return SPEED_ACCENT_MODES[mode]
    return f"MANUAL, {config['speed_accents_amount']:.0%}, {config['speed_accents_speed']:.2f}x"


def set_screen(st: dict, screen: str):
    current = st.get("screen")
    if current and current != screen:
        st.setdefault("history", []).append(current)
    st["screen"] = screen


async def show_screen(query, st: dict, screen: str):
    st["screen"] = screen
    if screen == "effects":
        await query.edit_message_text(
            f"{STYLES[st['style']]}\n\n✨ *Effects*\n"
            "Select any combination, or keep a clean render.\n\n"
            "🎨 Color / Look\n🎞 Texture\n⚡ Energy FX",
            parse_mode="Markdown",
            reply_markup=kb_effects(st),
        )
    elif screen == "effects_intensity":
        await query.edit_message_text(
            "🎚 *Effects intensity*\n\nChoose one strength for all selected effects.\nClean render ignores this setting.",
            parse_mode="Markdown",
            reply_markup=option_keyboard("fx_intensity", EFFECT_INTENSITIES),
        )
    elif screen == "visualizer_type":
        await query.edit_message_text(
            "📊 *Visualizer*\n\nChoose an overlay style. Waveform is the recommended clean option.",
            parse_mode="Markdown",
            reply_markup=kb_visualizer_type(),
        )
    elif screen == "visualizer_position":
        vis_type = st["visualizer_config"]["type"]
        await query.edit_message_text(
            "📍 *Visualizer placement*" if vis_type in STRIP_VISUALIZERS else "📍 *Visualizer position*",
            parse_mode="Markdown",
            reply_markup=option_keyboard("vis_pos", visualizer_positions(vis_type)),
        )
    elif screen == "visualizer_size":
        await query.edit_message_text("📐 *Visualizer size*", parse_mode="Markdown", reply_markup=option_keyboard("vis_size", VISUALIZER_SIZES))
    elif screen == "visualizer_color":
        await query.edit_message_text("🎨 *Visualizer color*", parse_mode="Markdown", reply_markup=option_keyboard("vis_color", VISUALIZER_COLORS))
    elif screen == "visualizer_bg":
        await query.edit_message_text(
            "◼ *Visualizer background*\n\nNone has no panel. Soft and Medium add a semi-transparent backing.",
            parse_mode="Markdown",
            reply_markup=option_keyboard("vis_bg", VISUALIZER_BACKGROUNDS),
        )
    elif screen == "montage":
        await query.edit_message_text(montage_text(), parse_mode="Markdown", reply_markup=kb_montage(st["montage_config"]))
    elif screen == "speed_mode":
        await query.edit_message_text(
            "⚡ *Speed accents*\n\nSelected video segments are sped up under the beat; the music track is never changed.\n"
            "Use AUTO for quick testing, or MANUAL for direct control.",
            parse_mode="Markdown",
            reply_markup=kb_speed_accents_mode(),
        )
    elif screen == "speed_amount":
        await query.edit_message_text(
            "🎚 *Amount*\n\nHow many video segments may receive a speed accent?",
            parse_mode="Markdown",
            reply_markup=option_keyboard("speed_amount", SPEED_ACCENT_AMOUNTS),
        )
    elif screen == "speed_value":
        await query.edit_message_text(
            "🚀 *Speed*\n\nChoose video-only playback speed for accented segments.",
            parse_mode="Markdown",
            reply_markup=option_keyboard("speed_value", SPEED_ACCENT_SPEEDS),
        )


def summary_text(st: dict) -> str:
    selected_effects = [
        f"{effect['emoji']} {effect['title']}"
        for effect_id, effect in EFFECTS.items()
        if st["effects_config"][effect_id]
    ]
    vis = st["visualizer_config"]
    if vis["enabled"]:
        visualizer = (
            f"{VISUALIZER_TYPES[vis['type']]}; {visualizer_position_label(vis['position']).lower()}; "
            f"size {VISUALIZER_SIZES[vis['size']].lower()}; color {VISUALIZER_COLORS[vis['color']].lower()}; "
            f"background {VISUALIZER_BACKGROUNDS[vis['background_opacity']].lower()}"
        )
    else:
        visualizer = "🚫 No visualizer"
    montage = st["montage_config"]
    return (
        "✅ *Final summary*\n\n"
        f"*Style:* {STYLES[st['style']]}\n"
        f"*Effects:* {', '.join(selected_effects) if selected_effects else '🧼 Clean render / no effects'}\n"
        f"*Effects intensity:* {st['effects_intensity'].title()}"
        f"{' (ignored for clean render)' if not selected_effects else ''}\n"
        f"*Visualizer:* {visualizer}\n"
        f"*Speed accents:* {speed_accents_summary(montage)}\n"
        f"*Montage:* mirror {on_off(montage['allow_mirror'])}, reverse {on_off(montage['allow_reverse'])}, "
        f"mirror+reverse {on_off(montage['allow_mirror_reverse'])}, random trim {on_off(montage['allow_random_trim'])}; "
        f"{TRANSITIONS[montage['transition_style']]}; {BEAT_CUTS[montage['beat_cut_mode']]}; "
        f"{CLIP_ORDERS[montage['clip_order_mode']]}"
    )


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not is_authorized(uid):
        return
    user_state[uid] = {}
    await update.message.reply_text(
        "🎬 *VIDEO MONTAGE BOT*\n\n"
        "Create a beat-aware montage from your selected clips.\n\n"
        "Choose a style to begin:",
        parse_mode="Markdown",
        reply_markup=kb_styles(),
    )


async def show_status(update: Update, uid: int):
    job = active_jobs.get(uid)
    if not job:
        await update.message.reply_text("No active render job.")
        return
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(job["status_url"], timeout=aiohttp.ClientTimeout(total=15)) as response:
                if response.status != 200:
                    await update.message.reply_text(f"Status unavailable for job `{job['job_id']}`.", parse_mode="Markdown")
                    return
                data = await response.json(content_type=None)
    except Exception as exc:
        await update.message.reply_text(f"Status check failed: {str(exc)[:200]}")
        return
    stage = data.get("stage", data.get("status", "unknown"))
    progress = data.get("progress", "?")
    message = data.get("message", "")
    text = f"Job `{job['job_id']}`\nStage: {stage}\nProgress: {progress}%\n{message}"
    if data.get("clips_downloaded") is not None:
        text += f"\nClips downloaded: {data.get('clips_downloaded')}/{data.get('clips_found', '?')}"
    if data.get("clips_analyzed") is not None:
        text += f"\nClips analyzed: {data.get('clips_analyzed')}"
    if data.get("current_segment") is not None:
        text += f"\nSegment: {data.get('current_segment')}/{data.get('total_segments', '?')}"
    if data.get("download_link"):
        text += f"\n\nDownload link:\n{data['download_link']}"
    if stage in {"done", "failed", "canceled"}:
        active_jobs.pop(uid, None)
    await update.message.reply_text(text, parse_mode="Markdown")


async def status_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not is_authorized(uid):
        return
    await show_status(update, uid)


async def cancel_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not is_authorized(uid):
        return
    st = state(uid)
    if st.get("step") not in {None, "done", "processing"}:
        user_state[uid] = {}
        await update.message.reply_text("Setup canceled. Send /start to begin again.")
        return
    job = active_jobs.get(uid)
    if not job:
        await update.message.reply_text("No active render job to cancel.")
        return
    try:
        async with aiohttp.ClientSession() as session:
            async with session.put(
                job["cancel_url"],
                data=b"cancel_requested",
                headers={"Content-Type": "text/plain"},
                timeout=aiohttp.ClientTimeout(total=15),
            ) as response:
                if response.status in {200, 201}:
                    await update.message.reply_text(f"Cancel requested for job `{job['job_id']}`.", parse_mode="Markdown")
                else:
                    await update.message.reply_text(f"Cancel request failed: {response.status}")
    except Exception as exc:
        await update.message.reply_text(f"Cancel request failed: {str(exc)[:200]}")


async def cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    uid = query.from_user.id
    if not is_authorized(uid):
        return
    data = query.data
    st = state(uid)
    if data == "nav:restart":
        user_state[uid] = {}
        await query.edit_message_text(
            "🎬 *VIDEO MONTAGE BOT*\n\nChoose a style to begin:",
            parse_mode="Markdown",
            reply_markup=kb_styles(),
        )
        return
    if data == "nav:back":
        previous = st.get("history", []).pop() if st.get("history") else None
        if previous:
            await show_screen(query, st, previous)
        else:
            await query.answer("Nothing to go back to.")
        return
    if data.startswith("style:"):
        style = data.split(":", 1)[1]
        st.update({
            "style": style,
            "effects_config": effects_config(),
            "effects_intensity": "normal",
            "visualizer_config": dict(VISUALIZER_DEFAULTS),
            "montage_config": dict(MONTAGE_DEFAULTS),
        })
        set_screen(st, "effects")
        await show_screen(query, st, "effects")
        return

    if data.startswith("fx:"):
        effect_id = data.split(":", 1)[1]
        if effect_id == "done":
            set_screen(st, "effects_intensity")
            await show_screen(query, st, "effects_intensity")
        elif effect_id == "clean":
            st["effects_config"] = effects_config()
            await query.edit_message_reply_markup(reply_markup=kb_effects(st))
        elif effect_id in EFFECTS:
            st["effects_config"][effect_id] = not st["effects_config"][effect_id]
            await query.edit_message_reply_markup(reply_markup=kb_effects(st))
        return

    if data.startswith("fx_intensity:"):
        intensity = data.split(":", 1)[1]
        if intensity in EFFECT_INTENSITIES:
            st["effects_intensity"] = intensity
            set_screen(st, "visualizer_type")
            await show_screen(query, st, "visualizer_type")
        return

    if data.startswith("vis_type:"):
        vis_type = data.split(":", 1)[1]
        if vis_type == "none":
            st["visualizer_config"]["enabled"] = False
            set_screen(st, "montage")
            await show_screen(query, st, "montage")
        elif vis_type in VISUALIZER_TYPES:
            positions = visualizer_positions(vis_type)
            default_position = next(iter(positions))
            st["visualizer_config"].update({"enabled": True, "type": vis_type, "position": default_position})
            set_screen(st, "visualizer_position")
            await show_screen(query, st, "visualizer_position")
        return

    if data.startswith("vis_pos:"):
        st["visualizer_config"]["position"] = data.split(":", 1)[1]
        set_screen(st, "visualizer_size")
        await show_screen(query, st, "visualizer_size")
        return

    if data.startswith("vis_size:"):
        st["visualizer_config"]["size"] = data.split(":", 1)[1]
        set_screen(st, "visualizer_color")
        await show_screen(query, st, "visualizer_color")
        return

    if data.startswith("vis_color:"):
        st["visualizer_config"]["color"] = data.split(":", 1)[1]
        set_screen(st, "visualizer_bg")
        await show_screen(query, st, "visualizer_bg")
        return

    if data.startswith("vis_bg:"):
        st["visualizer_config"]["background_opacity"] = data.split(":", 1)[1]
        set_screen(st, "montage")
        await show_screen(query, st, "montage")
        return

    if data.startswith("speed_mode:"):
        mode = data.split(":", 1)[1]
        if mode not in SPEED_ACCENT_MODES:
            return
        st["montage_config"]["speed_accents_mode"] = mode
        if mode == "manual":
            set_screen(st, "speed_amount")
            await show_screen(query, st, "speed_amount")
        else:
            set_screen(st, "montage")
            await show_screen(query, st, "montage")
        return

    if data.startswith("speed_amount:"):
        amount = float(data.split(":", 1)[1])
        if amount in SPEED_ACCENT_AMOUNTS:
            st["montage_config"]["speed_accents_amount"] = amount
            set_screen(st, "speed_value")
            await show_screen(query, st, "speed_value")
        return

    if data.startswith("speed_value:"):
        speed = float(data.split(":", 1)[1])
        if speed in SPEED_ACCENT_SPEEDS:
            st["montage_config"]["speed_accents_speed"] = speed
            set_screen(st, "montage")
            await show_screen(query, st, "montage")
        return

    if data.startswith("montage:"):
        choice = data.split(":", 1)[1]
        config = st["montage_config"]
        if choice in {"allow_mirror", "allow_reverse", "allow_mirror_reverse", "allow_random_trim"}:
            config[choice] = not config[choice]
            await query.edit_message_reply_markup(reply_markup=kb_montage(config))
        elif choice == "transition_style":
            config[choice] = cycle(config[choice], list(TRANSITIONS))
            await query.edit_message_reply_markup(reply_markup=kb_montage(config))
        elif choice == "beat_cut_mode":
            config[choice] = cycle(config[choice], list(BEAT_CUTS))
            await query.edit_message_reply_markup(reply_markup=kb_montage(config))
        elif choice == "clip_order_mode":
            config[choice] = cycle(config[choice], list(CLIP_ORDERS))
            await query.edit_message_reply_markup(reply_markup=kb_montage(config))
        elif choice == "speed_accents_mode":
            set_screen(st, "speed_mode")
            await show_screen(query, st, "speed_mode")
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
            "📁 *Video clips*\n\nSend the Google Drive folder link containing your selected MP4 clips.",
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
            await update.message.reply_text("Please send a Google Drive folder link.")
            return
        st["video_link"] = text
        st["step"] = "awaiting_audio_link"
        await update.message.reply_text("🎵 Video folder accepted. Now send the Google Drive link for your MP3 track.")
    elif st.get("step") == "awaiting_audio_link":
        if "drive.google.com" not in text:
            await update.message.reply_text("Please send a Google Drive audio file link.")
            return
        st["audio_link"] = text
        st["step"] = "processing"
        await launch_render_job(update, uid)
    else:
        await update.message.reply_text("Send /start to create a new montage.")


async def launch_render_job(update: Update, uid: int):
    st = state(uid)
    if uid in active_jobs:
        await update.message.reply_text("A render job is already active. Use /status or /cancel before starting another.")
        return
    message = await update.message.reply_text("🚀 Sending your montage job to the renderer...")
    if not CLOUD_RUN_URL:
        await message.edit_text("CLOUD_RUN_URL is not configured.")
        return
    payload = {
        "style": st["style"],
        "effects_config": st["effects_config"],
        "effects_intensity": st["effects_intensity"],
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
                    active_jobs[uid] = {
                        "job_id": result.get("job_id", "unknown"),
                        "status_url": result.get("status_url"),
                        "cancel_url": result.get("cancel_url"),
                    }
                    await message.edit_text(
                        f"0% Job accepted.\nJob ID: `{result.get('job_id', 'unknown')}`",
                        parse_mode="Markdown",
                    )
                else:
                    await message.edit_text(f"Renderer returned an error: {response.status}")
    except Exception as exc:
        logger.error("Cloud Run error: %s", exc, exc_info=True)
        await message.edit_text(f"Cannot contact the rendering service: {str(exc)[:200]}")
    st["step"] = "done"


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🎬 *VIDEO MONTAGE BOT*\n\n"
        "*/start* — create a new montage\n\n"
        "Choose a style, real render effects, a visualizer overlay and montage rhythm, then send Drive links.",
        parse_mode="Markdown",
    )


def main():
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("status", status_cmd))
    app.add_handler(CommandHandler("cancel", cancel_cmd))
    app.add_handler(CallbackQueryHandler(cb))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    logger.info("Video Bot started")
    app.run_polling()


if __name__ == "__main__":
    main()
