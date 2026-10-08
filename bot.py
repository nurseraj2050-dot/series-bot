import json
import os
from datetime import time, timedelta
from zoneinfo import ZoneInfo

from telegram import Update
from telegram.ext import (
    ApplicationBuilder, CommandHandler,
    MessageHandler, ContextTypes, filters,
)

import config

FILE = "episodes.json"


# ========== ذخیره‌سازی ==========
def default_data():
    return {
        "file_ids": [],
        "index": 0,
        "hour": config.POST_HOUR,
        "minute": config.POST_MINUTE,
        "series_name": "سریال",
        "finished_notified": False,
        "collecting": False,
        "teaser_video_id": None,
        "poster_id": None,
        "send_teaser": True,
        "send_poster": True,
    }


def load():
    if not os.path.exists(FILE):
        return default_data()
    with open(FILE, encoding="utf-8") as f:
        d = json.load(f)
    for k, v in default_data().items():
        d.setdefault(k, v)
    return d


def save(d):
    with open(FILE, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=2)


def is_admin(update: Update) -> bool:
    return update.effective_user and update.effective_user.id == config.ADMIN_ID


async def notify_admin(context, text):
    try:
        await context.bot.send_message(config.ADMIN_ID, text)
    except Exception as e:
        print("notify error:", e)


# ========== پیش‌نمایش ==========
async def send_preview(context: ContextTypes.DEFAULT_TYPE):
    d = load()
    ids = d["file_ids"]
    idx = d["index"]
    if not ids or idx >= len(ids):
        return
    if not d.get("send_poster"):
        return

    ep_num = idx + 1
    text = (
        f"🎬 «{d['series_name']}»\n"
        f"📺 قسمت {ep_num} از {len(ids)}\n"
        f"⏰ امشب ساعت {d['hour']:02d}:{d['minute']:02d}\n\n"
        f"#پیش_نمایش"
    )
    try:
        if d.get("poster_id"):
            await context.bot.send_photo(
                chat_id=config.CHANNEL_ID,
                photo=d["poster_id"],
                caption=text
            )
        else:
            await context.bot.send_message(config.CHANNEL_ID, text)
    except Exception as e:
        print("preview error:", e)


# ========== ارسال قسمت ==========
async def send_next(context: ContextTypes.DEFAULT_TYPE):
    d = load()
    ids = d["file_ids"]
    idx = d["index"]

    if not ids or idx >= len(ids):
        if ids and not d.get("finished_notified"):
            d["finished_notified"] = True
            save(d)
            await context.bot.send_message(
                config.CHANNEL_ID,
                f"🎬 پخش سریال «{d['series_name']}» به پایان رسید.\n"
                f"منتظر سریال جدید باشید…"
            )
            await notify_admin(
                context,
                f"✅ سریال «{d['series_name']}» تموم شد.\n"
                f"برای سریال جدید /newseries بزن."
            )
        return

    # ویدیو تیزر
    if d.get("send_teaser") and d.get("teaser_video_id"):
        try:
            await context.bot.send_video(
                chat_id=config.CHANNEL_ID,
                video=d["teaser_video_id"],
                caption=f"🎬 «{d['series_name']}»\n#پیش_نمایش"
            )
        except Exception as e:
            print("teaser error:", e)

    # قسمت اصلی
    file_id = ids[idx]
    caption = f"🎬 {d['series_name']} — قسمت {idx + 1} از {len(ids)}"
    try:
        await context.bot.send_video(
            chat_id=config.CHANNEL_ID,
            video=file_id,
            caption=caption,
        )
    except Exception as e:
        print("error:", e)
        await notify_admin(context, f"❌ خطا در قسمت {idx+1}: {e}")
        return

    d["index"] = idx + 1
    save(d)
    print(f"✅ قسمت {idx+1}/{len(ids)} ارسال شد.")

    if d["index"] >= len(ids) and not d.get("finished_notified"):
        d["finished_notified"] = True
        save(d)
        await context.bot.send_message(
            config.CHANNEL_ID,
            f"🎬 پخش سریال «{d['series_name']}» به پایان رسید.\n"
            f"منتظر سریال جدید باشید…"
        )
        await notify_admin(
            context,
            f"✅ سریال «{d['series_name']}» تموم شد.\n"
            f"برای سریال جدید /newseries بزن."
        )


# ========== زمان‌بندی ==========
def schedule_jobs(app):
    d = load()
    tz = ZoneInfo(config.TIMEZONE)
    for j in app.job_queue.get_jobs_by_name("daily"):
        j.schedule_removal()
    for j in app.job_queue.get_jobs_by_name("preview"):
        j.schedule_removal()

    app.job_queue.run_daily(
        send_next,
        time=time(d["hour"], d["minute"], tzinfo=tz),
        name="daily"
    )

    total = (d["hour"] * 60 + d["minute"] - config.PREVIEW_MINUTES_BEFORE) % (24 * 60)
    ph, pm = total // 60, total % 60
    app.job_queue.run_daily(
        send_preview,
        time=time(ph, pm, tzinfo=tz),
        name="preview"
    )


# ========== دستورات ==========
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        return
    await update.message.reply_text(
        "🤖 ربات پخش سریال\n\n"
        "🚀 شروع:\n"
        "/newseries — سریال جدید\n"
        "→ ویدیوها رو فوروارد کن\n"
        "/done — پایان دریافت\n\n"
        "🎬 پیش‌نمایش:\n"
        "/setteaser — ارسال ویدیو تیزر\n"
        "/setposter — ارسال عکس پوستر\n"
        "/teaser on|off — روشن/خاموش تیزر\n"
        "/poster on|off — روشن/خاموش پوستر\n\n"
        "⚙️ مدیریت:\n"
        "/status /list /settime HH:MM\n"
        "/postnow /skip /rename نام /clear"
    )


async def new_series(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        return
    d = load()
    d.update({
        "file_ids": [], "index": 0,
        "finished_notified": False, "collecting": True,
    })
    save(d)
    await update.message.reply_text(
        "🆕 حالت دریافت فعال شد.\nویدیوها رو به ترتیب فوروارد کن و بعد /done بزن."
    )


async def done(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        return
    d = load()
    if not d["file_ids"]:
        return await update.message.reply_text("📭 هیچ قسمتی ثبت نشده.")
    d["collecting"] = False
    save(d)
    await update.message.reply_text(
        f"✅ آماده‌ست!\n«{d['series_name']}» — {len(d['file_ids'])} قسمت\n"
        f"⏰ پخش: {d['hour']:02d}:{d['minute']:02d}"
    )


async def set_teaser(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        return
    context.user_data["awaiting"] = "teaser"
    await update.message.reply_text("🎬 ویدیو تیزر رو بفرست.")


async def set_poster(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        return
    context.user_data["awaiting"] = "poster"
    await update.message.reply_text("🖼 عکس پوستر رو بفرست.")


async def toggle_teaser(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        return
    if not context.args or context.args[0].lower() not in ("on", "off"):
        return await update.message.reply_text("مثال: /teaser on")
    d = load()
    d["send_teaser"] = context.args[0].lower() == "on"
    save(d)
    await update.message.reply_text(f"✅ تیزر: {'روشن' if d['send_teaser'] else 'خاموش'}")


async def toggle_poster(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        return
    if not context.args or context.args[0].lower() not in ("on", "off"):
        return await update.message.reply_text("مثال: /poster on")
    d = load()
    d["send_poster"] = context.args[0].lower() == "on"
    save(d)
    await update.message.reply_text(f"✅ پوستر: {'روشن' if d['send_poster'] else 'خاموش'}")


async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        return
    d = load()
    n, idx = len(d["file_ids"]), d["index"]
    await update.message.reply_text(
        f"📊 «{d['series_name']}»\n"
        f"قسمت‌ها: {n} | ارسال‌شده: {idx} | باقی: {max(0, n-idx)}\n"
        f"⏰ پخش: {d['hour']:02d}:{d['minute']:02d}\n"
        f"🎬 تیزر: {'✅' if d['teaser_video_id'] else '❌'} ({'روشن' if d['send_teaser'] else 'خاموش'})\n"
        f"🖼 پوستر: {'✅' if d['poster_id'] else '❌'} ({'روشن' if d['send_poster'] else 'خاموش'})"
    )


async def list_eps(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        return
    d = load()
    if not d["file_ids"]:
        return await update.message.reply_text("📭 خالیه.")
    lines = [f"{'✅' if i < d['index'] else ('👉' if i == d['index'] else '⏳')} قسمت {i+1}"
             for i in range(len(d["file_ids"]))]
    await update.message.reply_text(f"📋 «{d['series_name']}»\n\n" + "\n".join(lines))


async def set_time(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        return
    if not context.args:
        return await update.message.reply_text("مثال: /settime 20:30")
    try:
        h, m = map(int, context.args[0].split(":"))
        assert 0 <= h < 24 and 0 <= m < 60
    except Exception:
        return await update.message.reply_text("❗ فرمت اشتباه.")
    d = load()
    d["hour"], d["minute"] = h, m
    save(d)
    schedule_jobs(context.application)
    await update.message.reply_text(f"✅ ساعت پخش: {h:02d}:{m:02d}")


async def post_now(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        return
    await update.message.reply_text("📤 ارسال...")
    await send_next(context)


async def skip(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        return
    d = load()
    if d["index"] < len(d["file_ids"]):
        d["index"] += 1
        d["finished_notified"] = False
        save(d)
        await update.message.reply_text(f"⏭ قسمت بعدی: {d['index']+1}")
    else:
        await update.message.reply_text("سریال تموم شده.")


async def rename(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        return
    if not context.args:
        return await update.message.reply_text("مثال: /rename Breaking Bad")
    d = load()
    d["series_name"] = " ".join(context.args)
    save(d)
    await update.message.reply_text(f"✅ نام: {d['series_name']}")


async def clear(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        return
    save(default_data())
    schedule_jobs(context.application)
    await update.message.reply_text("🗑 همه چیز پاک شد.")


# ========== دریافت مدیا ==========
async def handle_media(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        return

    msg = update.message
    awaiting = context.user_data.get("awaiting")
    d = load()

    if awaiting == "teaser":
        fid = None
        if msg.video:
            fid = msg.video.file_id
        elif msg.document and (msg.document.mime_type or "").startswith("video"):
            fid = msg.document.file_id
        if not fid:
            return await msg.reply_text("❗ ویدیو بفرست.")
        d["teaser_video_id"] = fid
        save(d)
        context.user_data["awaiting"] = None
        return await msg.reply_text("✅ تیزر ثبت شد.")

    if awaiting == "poster":
        if not msg.photo:
            return await msg.reply_text("❗ عکس بفرست.")
        d["poster_id"] = msg.photo[-1].file_id
        save(d)
        context.user_data["awaiting"] = None
        return await msg.reply_text("✅ پوستر ثبت شد.")

    fid = None
    if msg.video:
        fid = msg.video.file_id
    elif msg.document and (msg.document.mime_type or "").startswith("video"):
        fid = msg.document.file_id
    if not fid:
        return

    if not d.get("collecting") and d["file_ids"] and d["index"] < len(d["file_ids"]):
        return await msg.reply_text(
            "⚠️ سریال فعلی در حال پخشه!\nاول /newseries بزن."
        )

    d["file_ids"].append(fid)
    save(d)
    await msg.reply_text(f"✅ قسمت {len(d['file_ids'])} ثبت شد.")


# ========== اجرا ==========
def main():
    app = ApplicationBuilder().token(config.BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("newseries", new_series))
    app.add_handler(CommandHandler("done", done))
    app.add_handler(CommandHandler("status", status))
    app.add_handler(CommandHandler("list", list_eps))
    app.add_handler(CommandHandler("settime", set_time))
    app.add_handler(CommandHandler("postnow", post_now))
    app.add_handler(CommandHandler("skip", skip))
    app.add_handler(CommandHandler("rename", rename))
    app.add_handler(CommandHandler("clear", clear))
    app.add_handler(CommandHandler("setteaser", set_teaser))
    app.add_handler(CommandHandler("setposter", set_poster))
    app.add_handler(CommandHandler("teaser", toggle_teaser))
    app.add_handler(CommandHandler("poster", toggle_poster))

    app.add_handler(MessageHandler(
        (filters.VIDEO | filters.Document.VIDEO | filters.PHOTO) & filters.ChatType.PRIVATE,
        handle_media
    ))

    schedule_jobs(app)
    print("🤖 ربات روشن شد...")
    app.run_polling()


if __name__ == "__main__":
    main()