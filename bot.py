from pathlib import Path
from datetime import datetime

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    PreCheckoutQueryHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

from PIL import Image, ImageDraw, ImageFont


BOT_TOKEN = __import__("os").getenv("BOT_TOKEN")

CARD_TEMPLATE = Path("citizen_card_template.png")


# =========================
# СОЗДАНИЕ КАРТОЧКИ
# =========================

def create_citizen_card(citizen_id, name, date):
    image = Image.open(CARD_TEMPLATE).convert("RGB")
    draw = ImageDraw.Draw(image)

    font_path = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"

    try:
        font_id = ImageFont.truetype(font_path, 32)
        font_name = ImageFont.truetype(font_path, 32)
        font_date = ImageFont.truetype(font_path, 28)
    except:
        font_id = ImageFont.load_default()
        font_name = ImageFont.load_default()
        font_date = ImageFont.load_default()

    # Номер гражданина
    draw.text(
        (100, 468),
        str(citizen_id),
        font=font_id,
        fill=(230, 230, 230)
    )

    # Имя
    draw.text(
        (100, 620),
        str(name),
        font=font_name,
        fill=(230, 230, 230)
    )

    # Дата
    draw.text(
        (785, 620),
        str(date),
        font=font_date,
        fill=(230, 230, 230)
    )

    output_path = Path(f"citizen_{str(citizen_id).replace('#', '')}.png")
    image.save(output_path)

    return output_path


# =========================
# START
# =========================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "🇻🇪 REPUBLIC OF VELLAR\n\n"
        "Welcome to Vellar.\n\n"
        "Become a digital citizen and receive your official "
        "Vellar Citizen ID Card.\n\n"
        "This is a digital membership in the Vellar community."
    )

    await update.message.reply_text(
        text,
        reply_markup={
            "inline_keyboard": [
                [
                    {
                        "text": "🇻🇪 BECOME A CITIZEN",
                        "callback_data": "citizenship"
                    }
                ]
            ]
        }
    )


# =========================
# ГРАЖДАНСТВО
# =========================

async def citizenship(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    await query.message.reply_text(
        "🇻🇪 FOUNDER CITIZENSHIP\n\n"
        "Status: Founder Citizen\n"
        "Digital Citizen ID Card included\n"
        "Permanent digital membership\n\n"
        "Price: ⭐ 500 Telegram Stars",
        reply_markup={
            "inline_keyboard": [
                [
                    {
                        "text": "⭐ BUY FOR 500 STARS",
                        "callback_data": "buy"
                    }
                ]
            ]
        }
    )


# =========================
# ОПЛАТА
# =========================

async def buy(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    await context.bot.send_invoice(
        chat_id=query.message.chat_id,
        title="Vellar Founder Citizenship",
        description="Digital membership in the Republic of Vellar.",
        payload="vellar_founder_citizenship",
        currency="XTR",
        prices=[],
        provider_token=""
    )


# =========================
# PRE-CHECKOUT
# =========================

async def precheckout(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.pre_checkout_query

    if query.invoice_payload == "vellar_founder_citizenship":
        await query.answer(ok=True)
    else:
        await query.answer(
            ok=False,
            error_message="Invalid payment."
        )


# =========================
# УСПЕШНАЯ ОПЛАТА
# =========================

async def successful_payment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    payment = update.message.successful_payment
    user = update.effective_user

    file_path = Path("citizens.json")

    if file_path.exists():
        import json

        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    else:
        data = {
            "next_id": 2,
            "citizens": []
        }

    citizen_number = data["next_id"]
    citizen_id = f"#{citizen_number:04d}"

    data["next_id"] += 1

    name = user.full_name
    date = datetime.now().strftime("%d.%m.%Y")

    citizen = {
        "id": citizen_id,
        "telegram_id": user.id,
        "username": user.username,
        "name": name,
        "status": "Founder Citizen",
        "country": "Vellar",
        "date": date,
        "stars": 500,
        "payment_id": payment.telegram_payment_charge_id
    }

    data["citizens"].append(citizen)

    import json

    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    # Создаём персональную карточку
    card_path = create_citizen_card(
        citizen_id,
        name,
        date
    )

    # Отправляем карточку
    with open(card_path, "rb") as photo:
        await update.message.reply_photo(
            photo=photo,
            caption=(
                "🇻🇪 WELCOME TO THE REPUBLIC OF VELLAR\n\n"
                f"Citizen ID: {citizen_id}\n"
                "Status: Founder Citizen\n\n"
                "Your digital citizen card is attached."
            )
        )


# =========================
# TEST CARD
# =========================

async def testcard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user

    date = datetime.now().strftime("%d.%m.%Y")

    card_path = create_citizen_card(
        "#TEST",
        user.full_name,
        date
    )

    with open(card_path, "rb") as photo:
        await update.message.reply_photo(
            photo=photo,
            caption=(
                "🪪 TEST CITIZEN CARD\n\n"
                "This is a preview only."
            )
        )


# =========================
# TERMS
# =========================

async def terms(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Vellar is a fictional digital community.\n\n"
        "Vellar citizenship is a digital membership/status "
        "and does not constitute legal citizenship, nationality, "
        "residency, land ownership or government-issued status."
    )


# =========================
# SUPPORT
# =========================

async def support(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Vellar Support\n\n"
        "For questions about your digital membership, "
        "please contact the Vellar administration."
    )


# =========================
# MAIN
# =========================

def main():
    application = Application.builder().token(BOT_TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("terms", terms))
    application.add_handler(CommandHandler("support", support))

    # ТЕСТОВАЯ КОМАНДА
    application.add_handler(CommandHandler("testcard", testcard))

    application.add_handler(
        CallbackQueryHandler(citizenship, pattern="^citizenship$")
    )

    application.add_handler(
        CallbackQueryHandler(buy, pattern="^buy$")
    )

    application.add_handler(
        PreCheckoutQueryHandler(precheckout)
    )

    application.add_handler(
        MessageHandler(
            filters.SUCCESSFUL_PAYMENT,
            successful_payment
        )
    )

    print("Vellar bot is running...")

    application.run_polling()


if __name__ == "__main__":
    main()
