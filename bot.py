from pathlib import Path
from datetime import datetime
import json
import os

from telegram import (
    Update,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)
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


BOT_TOKEN = os.getenv("BOT_TOKEN")
CARD_TEMPLATE = Path("citizen_card_template.png")


# ============================================================
# ШРИФТ
# ============================================================

def get_font(size):
    font_paths = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf",
        "/usr/share/fonts/truetype/liberation2/LiberationSerif-Bold.ttf",
        "/usr/share/fonts/truetype/liberation2/LiberationSerif-Regular.ttf",
    ]

    for path in font_paths:
        if Path(path).exists():
            return ImageFont.truetype(path, size)

    return ImageFont.load_default()


# ============================================================
# ПОДБОР РАЗМЕРА ШРИФТА
# ============================================================

def fit_font(text, max_width, start_size, min_size):

    size = start_size

    while size >= min_size:

        font = get_font(size)

        bbox = font.getbbox(text)

        width = bbox[2] - bbox[0]

        if width <= max_width:
            return font

        size -= 2

    return get_font(min_size)


# ============================================================
# СОЗДАНИЕ КАРТОЧКИ
# ============================================================

def create_citizen_card(citizen_id, name, date):

    image = Image.open(CARD_TEMPLATE).convert("RGB")
    draw = ImageDraw.Draw(image)

    # ========================================================
    # ОБЛАСТИ ДЛЯ ДИНАМИЧЕСКОГО ТЕКСТА
    # ========================================================

    # Citizen Number
    ID_X = 100
    ID_Y = 455
    ID_WIDTH = 285

    # Name
    NAME_X = 100
    NAME_Y = 600
    NAME_WIDTH = 310

    # Established / Date
    DATE_X = 785
    DATE_Y = 600
    DATE_WIDTH = 300

    # ========================================================
    # РАЗМЕРЫ ШРИФТОВ
    # ========================================================

    id_font = fit_font(
        citizen_id,
        ID_WIDTH,
        92,
        45
    )

    name_font = fit_font(
        name,
        NAME_WIDTH,
        82,
        38
    )

    date_font = fit_font(
        date,
        DATE_WIDTH,
        65,
        38
    )

    # ========================================================
    # ЦВЕТ
    # ========================================================

    text_color = (235, 235, 235)

    # ========================================================
    # НОМЕР
    # ========================================================

    draw.text(
        (ID_X, ID_Y),
        citizen_id,
        font=id_font,
        fill=text_color
    )

    # ========================================================
    # ИМЯ
    # ========================================================

    draw.text(
        (NAME_X, NAME_Y),
        name,
        font=name_font,
        fill=text_color
    )

    # ========================================================
    # ДАТА
    # ========================================================

    draw.text(
        (DATE_X, DATE_Y),
        date,
        font=date_font,
        fill=text_color
    )

    # ========================================================
    # СОХРАНЕНИЕ
    # ========================================================

    filename = f"citizen_{citizen_id.replace('#', '')}.png"

    output_path = Path(filename)

    image.save(output_path)

    return output_path


# ============================================================
# START
# ============================================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):

    text = (
        "🇻🇪 REPUBLIC OF VELLAR\n\n"
        "Welcome to Vellar.\n\n"
        "Become a digital citizen and receive your "
        "Vellar Digital Citizen ID Card."
    )

    keyboard = [
        [
            InlineKeyboardButton(
                "🇻🇪 BECOME A CITIZEN",
                callback_data="citizenship"
            )
        ]
    ]

    await update.message.reply_text(
        text,
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


# ============================================================
# CITIZENSHIP
# ============================================================

async def citizenship(update: Update, context: ContextTypes.DEFAULT_TYPE):

    query = update.callback_query
    await query.answer()

    keyboard = [
        [
            InlineKeyboardButton(
                "⭐ BUY FOR 500 STARS",
                callback_data="buy"
            )
        ]
    ]

    await query.message.reply_text(
        "🇻🇪 FOUNDER CITIZENSHIP\n\n"
        "Status: Founder Citizen\n"
        "Digital Citizen ID Card included\n"
        "Permanent digital membership\n\n"
        "Price: ⭐ 500 Telegram Stars",

        reply_markup=InlineKeyboardMarkup(keyboard)
    )


# ============================================================
# BUY
# ============================================================

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


# ============================================================
# PRECHECKOUT
# ============================================================

async def precheckout(update: Update, context: ContextTypes.DEFAULT_TYPE):

    query = update.pre_checkout_query

    if query.invoice_payload == "vellar_founder_citizenship":

        await query.answer(ok=True)

    else:

        await query.answer(
            ok=False,
            error_message="Invalid payment."
        )


# ============================================================
# УСПЕШНАЯ ОПЛАТА
# ============================================================

async def successful_payment(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    payment = update.message.successful_payment
    user = update.effective_user

    file_path = Path("citizens.json")

    # --------------------------------------------------------
    # ЗАГРУЖАЕМ РЕЕСТР
    # --------------------------------------------------------

    if file_path.exists():

        with open(
            file_path,
            "r",
            encoding="utf-8"
        ) as f:

            data = json.load(f)

    else:

        data = {
            "next_id": 2,
            "citizens": []
        }

    # --------------------------------------------------------
    # СОЗДАЁМ ID
    # --------------------------------------------------------

    citizen_number = data["next_id"]

    citizen_id = f"#{citizen_number:04d}"

    data["next_id"] += 1

    # --------------------------------------------------------
    # ДАННЫЕ ГРАЖДАНИНА
    # --------------------------------------------------------

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

    # --------------------------------------------------------
    # СОХРАНЯЕМ РЕЕСТР
    # --------------------------------------------------------

    with open(
        file_path,
        "w",
        encoding="utf-8"
    ) as f:

        json.dump(
            data,
            f,
            ensure_ascii=False,
            indent=2
        )

    # --------------------------------------------------------
    # СОЗДАЁМ КАРТОЧКУ
    # --------------------------------------------------------

    card_path = create_citizen_card(
        citizen_id,
        name,
        date
    )

    # --------------------------------------------------------
    # ОТПРАВЛЯЕМ КАРТОЧКУ
    # --------------------------------------------------------

    with open(
        card_path,
        "rb"
    ) as photo:

        await update.message.reply_photo(
            photo=photo,
            caption=(
                "🇻🇪 WELCOME TO THE REPUBLIC OF VELLAR\n\n"
                f"Citizen ID: {citizen_id}\n"
                "Status: Founder Citizen\n\n"
                "Your Digital Citizen ID Card is attached."
            )
        )


# ============================================================
# ТЕСТОВАЯ КАРТОЧКА
# ============================================================

async def testcard(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    user = update.effective_user

    name = user.full_name

    date = datetime.now().strftime("%d.%m.%Y")

    card_path = create_citizen_card(
        "#TEST",
        name,
        date
    )

    with open(
        card_path,
        "rb"
    ) as photo:

        await update.message.reply_photo(
            photo=photo,
            caption=(
                "🪪 VELLAR DIGITAL CITIZEN ID\n\n"
                "TEST CARD — PREVIEW ONLY"
            )
        )


# ============================================================
# TERMS
# ============================================================

async def terms(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    await update.message.reply_text(
        "Vellar is a fictional digital community.\n\n"
        "Vellar citizenship is a digital membership/status "
        "and does not constitute legal citizenship, nationality, "
        "residency, land ownership or government-issued status."
    )


# ============================================================
# SUPPORT
# ============================================================

async def support(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    await update.message.reply_text(
        "Vellar Support\n\n"
        "For questions about your digital membership, "
        "please contact the Vellar administration."
    )


# ============================================================
# MAIN
# ============================================================

def main():

    application = (
        Application
        .builder()
        .token(BOT_TOKEN)
        .build()
    )

    # COMMANDS

    application.add_handler(
        CommandHandler("start", start)
    )

    application.add_handler(
        CommandHandler("terms", terms)
    )

    application.add_handler(
        CommandHandler("support", support)
    )

    application.add_handler(
        CommandHandler("testcard", testcard)
    )

    # BUTTONS

    application.add_handler(
        CallbackQueryHandler(
            citizenship,
            pattern="^citizenship$"
        )
    )

    application.add_handler(
        CallbackQueryHandler(
            buy,
            pattern="^buy$"
        )
    )

    # PAYMENT

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
