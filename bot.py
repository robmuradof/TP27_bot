import os
import json
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)
from telegram.error import BadRequest
import gspread
from google.oauth2.service_account import Credentials
from flask import Flask, request
import asyncio

# ================= НАСТРОЙКИ =================
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_PASSWORD = "1452"
DATA_FILE = "partituras.json"

RASPI_SANIE_URL = "https://docs.google.com/spreadsheets/d/1FzS710QDmTO7HGoqWjk6BqTTsY6gHQfAkRBm9i_QxAY/edit"
YANDEX_DISK_URL = "https://disk.yandex.ru/d/E5AOPqehJcxCGQ"
X32_DISK_URL = "https://disk.yandex.ru/d/BQS3lXD8BFxIFw"

SERVICE_ACCOUNT_EMAIL = (
    "telegram-sheets-reader@telegram-sheets-bot-483114.iam.gserviceaccount.com"
)

# ================= GOOGLE SHEETS =================
SCOPE = ["https://www.googleapis.com/auth/spreadsheets.readonly"]
CREDS = Credentials.from_service_account_file("credentials.json", scopes=SCOPE)
GS_CLIENT = gspread.authorize(CREDS)

# ================= ХРАНЕНИЕ =================
def load_partituras():
    if not os.path.exists(DATA_FILE):
        return {}
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print("[DEBUG] JSON read error:", e)
        return {}

def save_partituras(data):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

partituras = load_partituras()

# ================= МЕНЮ =================
async def main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📅 Расписание", url=RASPI_SANIE_URL)],
        [InlineKeyboardButton("📁 Qlab проекты", url=YANDEX_DISK_URL)],
        [InlineKeyboardButton("🎛 X32 сцены", url=X32_DISK_URL)],
        [InlineKeyboardButton("🎼 Партитуры", callback_data="partituras")],
    ])

    try:
        if update.callback_query:
            await update.callback_query.edit_message_text(
                "Выберите действие:", reply_markup=keyboard
            )
        else:
            await update.message.reply_text(
                "Выберите действие:", reply_markup=keyboard
            )
    except BadRequest:
        pass

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await main_menu(update, context)

# ================= КНОПКИ =================
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    try:
        await query.answer()
    except BadRequest:
        pass

    data = query.data

    if data == "partituras":
        if not partituras:
            try:
                await query.edit_message_text(
                    "Партитур пока нет.\nДобавьте через /addtab",
                    reply_markup=InlineKeyboardMarkup(
                        [[InlineKeyboardButton("⬅ [Назад]", callback_data="back")]]
                    ),
                )
            except BadRequest:
                pass
            return

        items = list(partituras.items())
        buttons = []

        for i in range(0, len(items), 2):
            row = []
            for title, url in items[i:i + 2]:
                row.append(InlineKeyboardButton(title, url=url))
            buttons.append(row)

        buttons.append([InlineKeyboardButton("⬅ [Назад]", callback_data="back")])

        try:
            await query.edit_message_text(
                "🎼 Партитуры:",
                reply_markup=InlineKeyboardMarkup(buttons),
            )
        except BadRequest:
            pass
        return

    if data == "retry_add":
        url = context.user_data.get("retry_url")
        if not url:
            return

        try:
            sheet = GS_CLIENT.open_by_url(url)
            title = sheet.title
            partituras[title] = url
            save_partituras(partituras)
            await query.edit_message_text(f"✅ Партитура «{title}» добавлена")
        except Exception:
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("🔄 Попробовать снова", callback_data="retry_add")]
            ])
            await query.edit_message_text(
                "❌ Не удалось открыть таблицу.\n"
                "Проверьте ссылку и убедитесь, что сервисный аккаунт имеет доступ на чтение.\n"
                "Чтобы разрешить доступ:\n"
                "1️⃣ Откройте Google таблицу.\n"
                "2️⃣ Нажмите 'Поделиться' → 'Добавить людей и группы'.\n"
                "3️⃣ Введите email сервисного аккаунта:\n"
                f"   {SERVICE_ACCOUNT_EMAIL}\n"
                "4️⃣ Выберите доступ 'Чтение' и сохраните.\n"
                "После этого нажмите кнопку ниже, чтобы попробовать снова:",
                reply_markup=keyboard,
            )
        return

    if data == "back":
        await main_menu(update, context)

    if data.startswith("del:"):
        name = data.replace("del:", "")
        if name in partituras:
            del partituras[name]
            save_partituras(partituras)
            await query.edit_message_text(f"🗑 «{name}» удалена")

# ================= ADDTAB =================
ADD_PASSWORD, ADD_URL = range(2)

async def addtab_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Введите пароль:")
    return ADD_PASSWORD

async def addtab_password(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text.strip() != ADMIN_PASSWORD:
        await update.message.reply_text("❌ Пароль неверный.")
        return ConversationHandler.END
    await update.message.reply_text("Отправьте ссылку на Google таблицу:")
    return ADD_URL

async def addtab_url(update: Update, context: ContextTypes.DEFAULT_TYPE):
    url = update.message.text.strip()
    context.user_data["retry_url"] = url
    try:
        sheet = GS_CLIENT.open_by_url(url)
        title = sheet.title
        partituras[title] = url
        save_partituras(partituras)
        await update.message.reply_text(f"✅ Партитура «{title}» добавлена")
    except Exception:
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔄 Попробовать снова", callback_data="retry_add")]
        ])
        await update.message.reply_text(
            "❌ Не удалось открыть таблицу.\n"
            "Проверьте ссылку и убедитесь, что сервисный аккаунт имеет доступ на чтение.\n"
            "Чтобы разрешить доступ:\n"
            "1️⃣ Откройте Google таблицу.\n"
            "2️⃣ Нажмите 'Поделиться' → 'Добавить людей и группы'.\n"
            "3️⃣ Введите email сервисного аккаунта:\n"
            f"   {SERVICE_ACCOUNT_EMAIL}\n"
            "4️⃣ Выберите доступ 'Чтение' и сохраните.\n"
            "После этого нажмите кнопку ниже, чтобы попробовать снова:",
            reply_markup=keyboard,
        )
    return ConversationHandler.END

# ================= DELTAB =================
DEL_PASSWORD = range(1)

async def deltab_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Введите пароль:")
    return DEL_PASSWORD

async def deltab_password(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text.strip() != ADMIN_PASSWORD:
        await update.message.reply_text("❌ Пароль неверный.")
        return ConversationHandler.END

    buttons = [
        [InlineKeyboardButton(name, callback_data=f"del:{name}")]
        for name in partituras
    ]

    await update.message.reply_text(
        "Выберите таблицу для удаления:",
        reply_markup=InlineKeyboardMarkup(buttons),
    )
    return ConversationHandler.END

# ================= APP =================
app = ApplicationBuilder().token(BOT_TOKEN).build()

app.add_handler(CommandHandler("start", start))
app.add_handler(CallbackQueryHandler(button_handler))

app.add_handler(
    ConversationHandler(
        entry_points=[CommandHandler("addtab", addtab_start)],
        states={
            ADD_PASSWORD: [MessageHandler(filters.TEXT & ~filters.COMMAND, addtab_password)],
            ADD_URL: [MessageHandler(filters.TEXT & ~filters.COMMAND, addtab_url)],
        },
        fallbacks=[],
    )
)

app.add_handler(
    ConversationHandler(
        entry_points=[CommandHandler("deltab", deltab_start)],
        states={
            DEL_PASSWORD: [MessageHandler(filters.TEXT & ~filters.COMMAND, deltab_password)],
        },
        fallbacks=[],
    )
)

# ================= WEBHOOK =================
flask_app = Flask(__name__)

@flask_app.route("/", methods=["POST"])
def telegram_webhook():
    update = Update.de_json(request.json, app.bot)
    asyncio.run(app.process_update(update))
    return "ok"

async def setup_webhook():
    webhook_url = os.getenv("WEBHOOK_URL")
    await app.bot.set_webhook(webhook_url)

asyncio.run(setup_webhook())
