import os
import json
from pathlib import Path
from datetime import datetime

from PIL import Image, ImageDraw, ImageFont

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, LabeledPrice
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    PreCheckoutQueryHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

TOKEN = os.environ["BOT_TOKEN"]

PRICE_STARS = 500

DATA_FILE = Path("citizens.json")
CARD_TEMPLATE = Path("citizen_card_template.png")


def load_data():
    if DATA_FILE.exists():
        try:
            return json.loads(
                DATA_FILE.read_text(encoding="utf-8")
            )
        except Exception:
            pass

    return {
        "next_id": 2,
        "citizens": []
    }


def save_data(data):
    DATA_FILE.write_text(
        json.dumps(
            data,
            ensure_ascii=False,
            indent=2
        ),
        encoding="utf-8"
    )


data = load_data()


def create_citizen_card(citizen_id, name, date):
    image = Image.open(CARD_TEMPLATE).convert("RGB")
    draw = ImageDraw.Draw(image)

    font_regular = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
    font_bold = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"

    id_font = ImageFont.truetype(font_regular, 48)
    name_font = ImageFont.truetype(font_regular, 34)
    date_font = ImageFont.truetype(font_regular, 32)

    # Citizen number
    draw.text(
        (100, 468),
        citizen_id,
        font=id_font,
        fill=(235, 235, 235)
    )

    # Name
    draw.text(
        (100, 620),
        name.upper(),
        font=name_font,
        fill=(235, 235, 235)
    )

    # Date
    draw.text(
        (785, 620),
        date,
        font=date_font,
        fill=(235, 235, 235)
    )

    output = Path(f"citizen_{citizen_id.replace('#', '')}.png")

    image.save(
        output,
        format="PNG",
        optimize=True
    )

    return output


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):

    keyboard = [
        [
            InlineKeyboardButton(
                "🇻🇪 BECOME A CITIZEN",
                callback_data="citizenship"
            )
        ]
    ]

    await update.message.reply_text(
        "🇻🇪 REPUBLIC OF VELLAR\n\n"
        "A digital nation built by its citizens.\n\n"
        "Become a Founder Citizen of Vellar.",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def citizenship(update: Update, context: ContextTypes.DEFAULT_TYPE):

    query = update.callback_query
    await query.answer()

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
        "Become one of the founding citizens of the Republic of Vellar.\n\n"
        "Status: Founder Citizen\n"
        "Price: 500 ⭐",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def buy(update: Update, context: ContextTypes.DEFAULT_TYPE):

    query = update.callback_query
    await query.answer()

    prices = [
        LabeledPrice(
            "Founder Citizenship",
            PRICE_STARS
        )
    ]

    await context.bot.send_invoice(
        chat_id=query.message.chat_id,
        title="Republic of Vellar — Founder Citizenship",
        description="Digital membership in the Republic of Vellar.",
        payload="vellar_founder_citizenship",
        currency="XTR",
        prices=prices,
        provider_token=""
    )


async def precheckout(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    query = update.pre_checkout_query

    if query.invoice_payload != "vellar_founder_citizenship":

        await query.answer(
            ok=False,
            error_message="Invalid payment."
        )

        return

    await query.answer(ok=True)


async def successful_payment(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    global data

    payment = update.message.successful_payment

    if payment.invoice_payload != "vellar_founder_citizenship":
        return

    citizen_number = data["next_id"]

    data["next_id"] += 1

    user = update.effective_user

    citizen_id = f"#{citizen_number:04d}"

    name = user.first_name or "Citizen"

    if user.last_name:
        name += f" {user.last_name}"

    date = datetime.now().strftime("%d.%m.%Y")

    citizen = {
        "id": citizen_id,
        "telegram_id": user.id,
        "username": user.username,
        "name": name,
        "status": "Founder Citizen",
        "date": date,
        "stars": PRICE_STARS,
        "payment_id": payment.telegram_payment_charge_id
    }

    data["citizens"].append(citizen)

    save_data(data)

    # Create personalized card
    card = create_citizen_card(
        citizen_id,
        name,
        date
    )

    # Send card
    with open(card, "rb") as photo:

        await update.message.reply_photo(
            photo=photo,
            caption=(
                "🇻🇪 REPUBLIC OF VELLAR\n\n"
                f"Citizen ID: {citizen_id}\n"
                f"Name: {name}\n"
                "Status: Founder Citizen\n"
                f"Joined: {date}\n\n"
                "Welcome to Vellar."
            )
        )


async def terms(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    await update.message.reply_text(
        "VELLAR TERMS\n\n"
        "Vellar is a fictional digital nation and community.\n\n"
        "Vellar citizenship is a digital membership/status "
        "and does not constitute legal citizenship, nationality, "
        "residency, land ownership or government-issued status."
    )


async def support(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    await update.message.reply_text(
        "VELLAR SUPPORT\n\n"
        "For payment or citizenship issues, "
        "contact the Vellar administration."
    )


def main():

    app = Application.builder().token(TOKEN).build()

    app.add_handler(
        CommandHandler("start", start)
    )

    app.add_handler(
        CommandHandler("terms", terms)
    )

    app.add_handler(
        CommandHandler("support", support)
    )

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


if __name__ == "__main__":
    main()
