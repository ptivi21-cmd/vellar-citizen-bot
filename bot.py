import os import json from pathlib import Path
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, LabeledPrice from telegram.ext import ( Application, CommandHandler, CallbackQueryHandler, PreCheckoutQueryHandler, MessageHandler, ContextTypes, filters, )
TOKEN = os.environ["BOT_TOKEN"] PRICE_STARS = 500 DATA_FILE = Path("citizens.json")
def load_data(): if DATA_FILE.exists(): try: return json.loads(DATA_FILE.read_text(encoding="utf-8")) except Exception: pass
return {
    "next_id": 2,
    "citizens": []
}
def save_data(data): DATA_FILE.write_text( json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8" )
data = load_data()
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE): keyboard = [ [ InlineKeyboardButton( "🇻🇪 BECOME A CITIZEN", callback_data="citizenship" ) ] ]
await update.message.reply_text(
    "🇻🇪 REPUBLIC OF VELLAR\n\n"
    "A digital nation built by its citizens.\n\n"
    "Become one of the first 1,000 Founder Citizens.",
    reply_markup=InlineKeyboardMarkup(keyboard)
)
async def citizenship(update: Update, context: ContextTypes.DEFAULT_TYPE): query = update.callback_query await query.answer()
keyboard = [
    [
        InlineKeyboardButton(
            "⭐ BECOME A CITIZEN — 500 ⭐",
            callback_data="buy"
        )
    ]
]

await query.edit_message_text(
    "🇻🇪 FOUNDER CITIZENSHIP\n\n"
    "Become one of the first citizens of the Republic of Vellar.\n\n"
    f"Price: {PRICE_STARS} ⭐\n"
    "Status: Founder Citizen\n"
    "Founder limit: 1,000 citizens",
    reply_markup=InlineKeyboardMarkup(keyboard)
)
async def buy(update: Update, context: ContextTypes.DEFAULT_TYPE): query = update.callback_query await query.answer()
prices = [
    LabeledPrice(
        "Founder Citizenship",
        PRICE_STARS
    )
]

await context.bot.send_invoice(
    chat_id=query.message.chat_id,
    title="Republic of Vellar — Founder Citizenship",
    description="Digital citizenship in the Republic of Vellar.",
    payload="vellar_founder_citizenship",
    currency="XTR",
    prices=prices,
    provider_token=""
)
async def precheckout( update: Update, context: ContextTypes.DEFAULT_TYPE ): query = update.pre_checkout_query
if query.invoice_payload != "vellar_founder_citizenship":
    await query.answer(
        ok=False,
        error_message="Invalid payment."
    )
    return

await query.answer(ok=True)
async def successful_payment( update: Update, context: ContextTypes.DEFAULT_TYPE ): payment = update.message.successful_payment
if payment.invoice_payload != "vellar_founder_citizenship":
    return

global data

citizen_id = data["next_id"]
data["next_id"] += 1

user = update.effective_user

citizen = {
    "id": f"#{citizen_id:04d}",
    "telegram_id": user.id,
    "username": user.username,
    "first_name": user.first_name,
    "status": "Founder Citizen",
    "payment_id": payment.telegram_payment_charge_id
}

data["citizens"].append(citizen)
save_data(data)

await update.message.reply_text(
    "🇻🇪 WELCOME TO VELLAR\n\n"
    f"Citizen ID: {citizen['id']}\n"
    "Status: Founder Citizen\n\n"
    "Your identity has been registered in the Republic.\n\n"
    "Welcome to the beginning."
)
async def terms(update: Update, context: ContextTypes.DEFAULT_TYPE): await update.message.reply_text( "VELLAR TERMS\n\n" "Vellar is a fictional digital nation and community.\n\n" "Vellar citizenship is a digital membership/status " "and does not constitute legal citizenship, nationality, " "residency, land ownership or any government-issued status.\n\n" "Payments are for digital goods/services." )
async def support(update: Update, context: ContextTypes.DEFAULT_TYPE): await update.message.reply_text( "VELLAR SUPPORT\n\n" "For payment or citizenship issues, " "contact the Vellar administration." )
def main(): app = Application.builder().token(TOKEN).build()
app.add_handler(CommandHandler("start", start))
app.add_handler(CommandHandler("terms", terms))
app.add_handler(CommandHandler("support", support))

app.add_handler(
    CallbackQueryHandler(
        citizenship,
        pattern="^citizenship$"
    )
)

app.add_handler(
    CallbackQueryHandler(
        buy,
        pattern="^buy$"
    )
)

app.add_handler(
    PreCheckoutQueryHandler(precheckout)
)

app.add_handler(
    MessageHandler(
        filters.SUCCESSFUL_PAYMENT,
        successful_payment
    )
)

print("Vellar bot is running...")
app.run_polling()
if name == "main": main() 
