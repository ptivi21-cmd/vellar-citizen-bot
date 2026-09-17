from pathlib import Path
from datetime import datetime, timezone
import os
import sqlite3
import time

from telegram import (
    Update,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    LabeledPrice,
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


# ============================================================
# CONFIG
# ============================================================

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", "1768107641"))

CARD_TEMPLATE = Path("citizen_card_template.png")
DB_PATH = Path("vellar.db")

CITIZENSHIP_PRICE = 500
LAND_PACKAGES = {
    "land_1": {"hectares": 1, "price": 200, "title": "1 hectare"},
    "land_2": {"hectares": 2, "price": 300, "title": "2 hectares"},
    "land_4": {"hectares": 4, "price": 580, "title": "4 hectares"},
}

VEL_PER_HECTARE_PER_HOUR = 1.5


# ============================================================
# DATABASE
# ============================================================

def db():
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    return connection


def init_db():
    with db() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                telegram_id INTEGER PRIMARY KEY,
                username TEXT,
                full_name TEXT,
                citizen_id TEXT UNIQUE,
                citizen_date TEXT,
                hectares REAL NOT NULL DEFAULT 0,
                vel_balance REAL NOT NULL DEFAULT 0,
                last_accrual REAL NOT NULL,
                citizenship_payment_id TEXT UNIQUE
            )
            """
        )

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS payments (
                payment_id TEXT PRIMARY KEY,
                telegram_id INTEGER NOT NULL,
                payload TEXT NOT NULL,
                amount INTEGER NOT NULL,
                created_at REAL NOT NULL
            )
            """
        )

        # Helps if the bot is upgraded from an earlier version.
        columns = {
            row["name"]
            for row in conn.execute("PRAGMA table_info(users)").fetchall()
        }
        if "last_accrual" not in columns:
            conn.execute(
                "ALTER TABLE users ADD COLUMN last_accrual REAL NOT NULL DEFAULT 0"
            )


def get_user(telegram_id):
    with db() as conn:
        return conn.execute(
            "SELECT * FROM users WHERE telegram_id = ?",
            (telegram_id,),
        ).fetchone()


def ensure_user(tg_user):
    now = time.time()
    with db() as conn:
        existing = conn.execute(
            "SELECT telegram_id FROM users WHERE telegram_id = ?",
            (tg_user.id,),
        ).fetchone()

        if existing:
            conn.execute(
                """
                UPDATE users
                SET username = ?, full_name = ?
                WHERE telegram_id = ?
                """,
                (
                    tg_user.username,
                    tg_user.full_name,
                    tg_user.id,
                ),
            )
        else:
            conn.execute(
                """
                INSERT INTO users (
                    telegram_id,
                    username,
                    full_name,
                    last_accrual
                )
                VALUES (?, ?, ?, ?)
                """,
                (
                    tg_user.id,
                    tg_user.username,
                    tg_user.full_name,
                    now,
                ),
            )


def settle_vel(telegram_id):
    """
    Converts elapsed time into VEL and stores it in vel_balance.
    Yield = 1.5 VEL per hectare per hour.
    """
    now = time.time()

    with db() as conn:
        user = conn.execute(
            "SELECT hectares, vel_balance, last_accrual FROM users WHERE telegram_id = ?",
            (telegram_id,),
        ).fetchone()

        if not user:
            return 0.0, 0.0

        elapsed = max(0.0, now - float(user["last_accrual"]))
        rate_per_hour = float(user["hectares"]) * VEL_PER_HECTARE_PER_HOUR
        earned = elapsed / 3600.0 * rate_per_hour

        new_balance = float(user["vel_balance"]) + earned

        conn.execute(
            """
            UPDATE users
            SET vel_balance = ?, last_accrual = ?
            WHERE telegram_id = ?
            """,
            (new_balance, now, telegram_id),
        )

        return earned, new_balance


def next_citizen_number():
    with db() as conn:
        row = conn.execute(
            """
            SELECT citizen_id
            FROM users
            WHERE citizen_id IS NOT NULL
            ORDER BY rowid DESC
            LIMIT 1
            """
        ).fetchone()

    if not row or not row["citizen_id"]:
        return 0

    try:
        return int(row["citizen_id"].replace("#", ""))
    except ValueError:
        return 0


def create_citizen(telegram_user, payment_id=None, test=False):
    ensure_user(telegram_user)

    existing = get_user(telegram_user.id)
    if existing and existing["citizen_id"]:
        return existing["citizen_id"], False

    if test:
        citizen_id = "#TEST"
        date = datetime.now().strftime("%d.%m.%Y")
    else:
        number = next_citizen_number() + 1
        citizen_id = f"#{number:04d}"
        date = datetime.now().strftime("%d.%m.%Y")

    with db() as conn:
        conn.execute(
            """
            UPDATE users
            SET citizen_id = ?,
                citizen_date = ?,
                citizenship_payment_id = ?
            WHERE telegram_id = ?
            """,
            (
                citizen_id,
                date,
                payment_id,
                telegram_user.id,
            ),
        )

    return citizen_id, True


def add_land(telegram_id, hectares, payment_id=None):
    ensure_user_id(telegram_id)

    with db() as conn:
        conn.execute(
            """
            UPDATE users
            SET hectares = hectares + ?
            WHERE telegram_id = ?
            """,
            (hectares, telegram_id),
        )


def ensure_user_id(telegram_id):
    if get_user(telegram_id) is None:
        now = time.time()
        with db() as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO users (
                    telegram_id,
                    username,
                    full_name,
                    last_accrual
                )
                VALUES (?, ?, ?, ?)
                """,
                (telegram_id, None, None, now),
            )


def payment_exists(payment_id):
    with db() as conn:
        return conn.execute(
            "SELECT 1 FROM payments WHERE payment_id = ?",
            (payment_id,),
        ).fetchone() is not None


def save_payment(payment_id, telegram_id, payload, amount):
    with db() as conn:
        conn.execute(
            """
            INSERT OR IGNORE INTO payments (
                payment_id,
                telegram_id,
                payload,
                amount,
                created_at
            )
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                payment_id,
                telegram_id,
                payload,
                amount,
                time.time(),
            ),
        )


# ============================================================
# CARD GENERATION
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


def draw_big_text(
    base_image,
    text,
    center_x,
    center_y,
    font_path,
    font_size,
    max_width=None,
    fill=(255, 255, 255),
):
    """
    Draw text centered at (center_x, center_y).

    The requested font_size is treated as the starting/max size.
    If max_width is provided, the font is reduced only as much as
    necessary to fit. The rendered text is never resized afterwards,
    so increasing font_size actually makes the text larger.
    """
    font_size = int(font_size)
    min_font_size = 20

    while font_size > min_font_size:
        font = ImageFont.truetype(font_path, font_size)
        bbox = font.getbbox(str(text))
        text_width = bbox[2] - bbox[0]
        if max_width is None or text_width <= max_width:
            break
        font_size -= 2

    font = ImageFont.truetype(font_path, max(font_size, min_font_size))

    bbox = font.getbbox(str(text))
    text_width = bbox[2] - bbox[0]
    text_height = bbox[3] - bbox[1]

    draw = ImageDraw.Draw(base_image)
    draw.text(
        (
            center_x - text_width / 2 - bbox[0],
            center_y - text_height / 2 - bbox[1],
        ),
        str(text),
        font=font,
        fill=fill,
    )
def create_citizen_card(citizen_id, username, date, suffix="", telegram_user_id=None):
    if not CARD_TEMPLATE.exists():
        raise FileNotFoundError(
            "citizen_card_template.png not found in the project."
        )

    image = Image.open(CARD_TEMPLATE).convert("RGB")

    # These coordinates match the current Vellar card template.
    draw_big_text(
        image=image,
        text=citizen_id,
        x=100,
        y=450,
        max_width=500,
        font_size=420,
    )

    # Username instead of the old full-name field.
    display_username = (
        f"@{username}" if username
        else f"ID {telegram_user_id}"
    )

    draw_big_text(
        image=image,
        text=display_username,
        x=100,
        y=595,
        max_width=600,
        font_size=300,
    )

    draw_big_text(
        image=image,
        text=date,
        x=785,
        y=595,
        max_width=500,
        font_size=360,
    )

    filename = (
        f"citizen_{str(citizen_id).replace('#', '')}"
        f"{suffix}.png"
    )

    output_path = Path(filename)
    image.save(output_path, quality=95)
    return output_path


# ============================================================
# KEYBOARDS
# ============================================================

def main_keyboard(user):
    citizen = get_user(user.id)

    buttons = [
        [
            InlineKeyboardButton(
                "🇻🇪 Гражданство — ⭐ 500",
                callback_data="citizenship",
            )
        ],
        [
            InlineKeyboardButton(
                "🌍 Земельные участки",
                callback_data="land",
            ),
            InlineKeyboardButton(
                "📊 Мои активы",
                callback_data="assets",
            ),
        ],
        [
            InlineKeyboardButton(
                "ℹ️ Как работает Vellar",
                callback_data="terms",
            ),
            InlineKeyboardButton(
                "🆘 Поддержка",
                callback_data="support",
            ),
        ],
    ]

    if citizen and citizen["citizen_id"]:
        buttons[0][0] = InlineKeyboardButton(
            "🪪 Моё гражданство",
            callback_data="citizenship",
        )

    return InlineKeyboardMarkup(buttons)


def citizenship_keyboard():
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "⭐ Купить гражданство — 500",
                    callback_data="buy_citizenship",
                )
            ],
            [
                InlineKeyboardButton(
                    "◀️ Главное меню",
                    callback_data="menu",
                )
            ],
        ]
    )


def land_keyboard(locked=False):
    if locked:
        return InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        "🇻🇪 Получить гражданство",
                        callback_data="citizenship",
                    )
                ],
                [
                    InlineKeyboardButton(
                        "◀️ Главное меню",
                        callback_data="menu",
                    )
                ],
            ]
        )

    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "🌱 1 гектар — ⭐ 200",
                    callback_data="buy_land_1",
                )
            ],
            [
                InlineKeyboardButton(
                    "🌱 2 гектара — ⭐ 300",
                    callback_data="buy_land_2",
                )
            ],
            [
                InlineKeyboardButton(
                    "🌱 4 гектара — ⭐ 580",
                    callback_data="buy_land_4",
                )
            ],
            [
                InlineKeyboardButton(
                    "📊 Мои активы",
                    callback_data="assets",
                )
            ],
            [
                InlineKeyboardButton(
                    "◀️ Главное меню",
                    callback_data="menu",
                )
            ],
        ]
    )


def assets_keyboard():
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "🔄 Обновить",
                    callback_data="assets",
                )
            ],
            [
                InlineKeyboardButton(
                    "🌍 Купить участок",
                    callback_data="land",
                )
            ],
            [
                InlineKeyboardButton(
                    "◀️ Главное меню",
                    callback_data="menu",
                )
            ],
        ]
    )


# ============================================================
# TEXT
# ============================================================

def citizenship_text(user):
    citizen = get_user(user.id)

    if citizen and citizen["citizen_id"]:
        return (
            "🇻🇪 ВЫ ГРАЖДАНИН VELLAR\n\n"
            f"Citizen ID: {citizen['citizen_id']}\n"
            "Status: Founder Citizen\n"
            f"Date: {citizen['citizen_date']}\n\n"
            "Гражданство уже оформлено."
        )

    return (
        "🇻🇪 ГРАЖДАНСТВО VELLAR\n\n"
        "Цифровое гражданство Республики Vellar.\n\n"
        "После оплаты вы получите:\n"
        "• уникальный Citizen ID\n"
        "• цифровую Citizen Card\n"
        "• доступ к покупке земельных участков\n"
        "• доступ к системе VEL\n\n"
        "Цена: ⭐ 500 Telegram Stars"
    )


def land_text(user):
    citizen = get_user(user.id)

    if not citizen or not citizen["citizen_id"]:
        return (
            "🔒 ЗЕМЕЛЬНЫЕ УЧАСТКИ\n\n"
            "Покупка земельных участков доступна "
            "только гражданам Vellar.\n\n"
            "Сначала получите гражданство."
        )

    return (
        "🌍 ЗЕМЕЛЬНЫЕ УЧАСТКИ VELLAR\n\n"
        "Каждый гектар генерирует 1.5 VEL в час.\n\n"
        "Доступные пакеты:\n"
        "🌱 1 гектар — ⭐ 200\n"
        "🌱 2 гектара — ⭐ 300\n"
        "🌱 4 гектара — ⭐ 580\n\n"
        "Покупка добавляет выбранную площадь "
        "к вашим активам."
    )


def assets_text(user):
    citizen = get_user(user.id)

    if not citizen or not citizen["citizen_id"]:
        return (
            "📊 МОИ АКТИВЫ\n\n"
            "У вас пока нет активов Vellar.\n\n"
            "Получите гражданство, чтобы открыть "
            "доступ к земельным участкам."
        )

    settle_vel(user.id)
    citizen = get_user(user.id)

    hectares = float(citizen["hectares"])
    balance = float(citizen["vel_balance"])
    rate = hectares * VEL_PER_HECTARE_PER_HOUR

    return (
        "📊 МОИ АКТИВЫ\n\n"
        f"🪪 Citizen ID: {citizen['citizen_id']}\n"
        f"🌱 Земля: {hectares:g} га\n"
        f"⚡ Скорость добычи: {rate:g} VEL/час\n"
        f"💎 Баланс VEL: {balance:.4f}\n\n"
        "Доход начисляется автоматически "
        "с момента покупки каждого участка."
    )


# ============================================================
# START
# ============================================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    ensure_user(update.effective_user)

    await update.message.reply_text(
        "🇻🇪 REPUBLIC OF VELLAR\n\n"
        "Добро пожаловать в Vellar.\n\n"
        "Цифровое гражданство, территория и "
        "внутренняя экономика VEL.",
        reply_markup=main_keyboard(update.effective_user),
    )


# ============================================================
# CALLBACKS
# ============================================================

async def callbacks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user = update.effective_user
    ensure_user(user)

    data = query.data

    if data == "menu":
        await query.edit_message_text(
            "🇻🇪 REPUBLIC OF VELLAR\n\n"
            "Выберите действие:",
            reply_markup=main_keyboard(user),
        )
        return

    if data == "citizenship":
        await query.edit_message_text(
            citizenship_text(user),
            reply_markup=citizenship_keyboard(),
        )
        return

    if data == "land":
        citizen = get_user(user.id)

        if not citizen or not citizen["citizen_id"]:
            await query.edit_message_text(
                land_text(user),
                reply_markup=land_keyboard(locked=True),
            )
            return

        await query.edit_message_text(
            land_text(user),
            reply_markup=land_keyboard(),
        )
        return

    if data == "assets":
        await query.edit_message_text(
            assets_text(user),
            reply_markup=assets_keyboard(),
        )
        return

    if data == "terms":
        await query.edit_message_text(
            "ℹ️ КАК РАБОТАЕТ VELLAR\n\n"
            "1. Получите цифровое гражданство.\n"
            "2. После этого откроется покупка земли.\n"
            "3. Каждый гектар генерирует 1.5 VEL/час.\n"
            "4. В разделе «Мои активы» отображаются "
            "земля, скорость добычи и накопленный VEL.\n\n"
            "Vellar — цифровое сообщество. Это не "
            "юридическое гражданство, государственная "
            "регистрация или право собственности на "
            "реальную недвижимость.",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("◀️ Главное меню", callback_data="menu")]]
            ),
        )
        return

    if data == "support":
        await query.edit_message_text(
            "🆘 VELLAR SUPPORT\n\n"
            "По вопросам цифрового гражданства, "
            "активов и платежей обратитесь к администрации Vellar.",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("◀️ Главное меню", callback_data="menu")]]
            ),
        )
        return

    if data == "buy_citizenship":
        citizen = get_user(user.id)

        if citizen and citizen["citizen_id"]:
            await query.edit_message_text(
                citizenship_text(user),
                reply_markup=citizenship_keyboard(),
            )
            return

        await send_invoice(
            context,
            chat_id=query.message.chat_id,
            title="Vellar Citizenship",
            description="Digital citizenship in the Republic of Vellar.",
            payload="citizenship",
            price=CITIZENSHIP_PRICE,
        )
        return

    if data.startswith("buy_land_"):
        citizen = get_user(user.id)

        if not citizen or not citizen["citizen_id"]:
            await query.edit_message_text(
                land_text(user),
                reply_markup=land_keyboard(locked=True),
            )
            return

        package_key = data.replace("buy_", "")
        package = LAND_PACKAGES.get(package_key)

        if not package:
            await query.message.reply_text("Ошибка пакета земли.")
            return

        await send_invoice(
            context,
            chat_id=query.message.chat_id,
            title=f"Vellar Land: {package['title']}",
            description=(
                f"{package['hectares']} hectare(s) of digital Vellar territory."
            ),
            payload=package_key,
            price=package["price"],
        )
        return


# ============================================================
# INVOICES / TELEGRAM STARS
# ============================================================

async def send_invoice(context, chat_id, title, description, payload, price):
    await context.bot.send_invoice(
        chat_id=chat_id,
        title=title,
        description=description,
        payload=payload,
        currency="XTR",
        prices=[LabeledPrice(title, price)],
        provider_token="",
    )


async def precheckout(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.pre_checkout_query

    valid_payloads = {"citizenship", *LAND_PACKAGES.keys()}

    if query.invoice_payload not in valid_payloads:
        await query.answer(
            ok=False,
            error_message="Invalid Vellar payment.",
        )
        return

    await query.answer(ok=True)


async def successful_payment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    payment = update.message.successful_payment
    user = update.effective_user

    ensure_user(user)

    payment_id = payment.telegram_payment_charge_id
    payload = payment.invoice_payload

    if payment_exists(payment_id):
        return

    save_payment(
        payment_id=payment_id,
        telegram_id=user.id,
        payload=payload,
        amount=payment.total_amount,
    )

    if payload == "citizenship":
        citizen_id, created = create_citizen(
            user,
            payment_id=payment_id,
            test=False,
        )

        if not created:
            await update.message.reply_text(
                "Гражданство уже оформлено ранее.",
                reply_markup=main_keyboard(user),
            )
            return

        date = get_user(user.id)["citizen_date"]
        username = user.username

        card_path = create_citizen_card(
            citizen_id,
            username,
            date,
            telegram_user_id=user.id,
        )

        with open(card_path, "rb") as photo:
            await update.message.reply_photo(
                photo=photo,
                caption=(
                    "🇻🇪 ДОБРО ПОЖАЛОВАТЬ В VELLAR\n\n"
                    f"Citizen ID: {citizen_id}\n"
                    "Status: Founder Citizen\n"
                    f"Date: {date}\n\n"
                    "Ваша цифровая Citizen Card готова."
                ),
            )

        await update.message.reply_text(
            "Открыты земельные активы Vellar.",
            reply_markup=main_keyboard(user),
        )
        return

    if payload in LAND_PACKAGES:
        package = LAND_PACKAGES[payload]

        # Accrue income up to the exact moment of purchase,
        # then add the new land. New hectares start earning now.
        settle_vel(user.id)
        add_land(
            telegram_id=user.id,
            hectares=package["hectares"],
            payment_id=payment_id,
        )

        citizen = get_user(user.id)

        await update.message.reply_text(
            "✅ ЗЕМЕЛЬНЫЙ АКТИВ ПРИОБРЕТЁН\n\n"
            f"Добавлено: {package['hectares']} га\n"
            f"Оплата: ⭐ {package['price']}\n"
            f"Всего земли: {float(citizen['hectares']):g} га\n"
            f"Новая скорость: "
            f"{float(citizen['hectares']) * VEL_PER_HECTARE_PER_HOUR:g} VEL/час",
            reply_markup=main_keyboard(user),
        )


# ============================================================
# TEST MODE
# ============================================================

def is_admin(user_id):
    return ADMIN_ID != 0 and user_id == ADMIN_ID


async def test_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("Команда доступна только ADMIN_ID.")
        return

    keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "🧪 TEST: гражданство",
                    callback_data="test_citizenship",
                )
            ],
            [
                InlineKeyboardButton(
                    "🧪 TEST: +1 га",
                    callback_data="test_land_1",
                ),
                InlineKeyboardButton(
                    "🧪 TEST: +2 га",
                    callback_data="test_land_2",
                ),
            ],
            [
                InlineKeyboardButton(
                    "🧪 TEST: +4 га",
                    callback_data="test_land_4",
                )
            ],
            [
                InlineKeyboardButton(
                    "🧪 TEST: активы",
                    callback_data="test_assets",
                )
            ],
            [
                InlineKeyboardButton(
                    "🧹 TEST: сбросить аккаунт",
                    callback_data="test_reset",
                )
            ],
        ]
    )

    await update.message.reply_text(
        "🧪 VELLAR DEVELOPER TEST MENU\n\n"
        "Тестовые кнопки не списывают Telegram Stars.",
        reply_markup=keyboard,
    )


async def test_callbacks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query

    if not is_admin(update.effective_user.id):
        await query.answer("Только для ADMIN_ID.", show_alert=True)
        return

    await query.answer()
    user = update.effective_user

    if query.data == "test_citizenship":
        citizen_id, created = create_citizen(
            user,
            payment_id=None,
            test=True,
        )

        date = get_user(user.id)["citizen_date"]

        card_path = create_citizen_card(
            citizen_id,
            user.username,
            date,
            suffix="_test",
            telegram_user_id=user.id,
        )

        with open(card_path, "rb") as photo:
            await query.message.reply_photo(
                photo=photo,
                caption=(
                    "🧪 TEST CITIZENSHIP\n\n"
                    f"Citizen ID: {citizen_id}\n"
                    f"Username: @{user.username if user.username else 'none'}\n"
                    f"Date: {date}\n\n"
                    "Telegram Stars НЕ списаны."
                ),
            )
        return

    if query.data.startswith("test_land_"):
        citizen = get_user(user.id)

        if not citizen or not citizen["citizen_id"]:
            await query.message.reply_text(
                "Сначала нажмите TEST: гражданство."
            )
            return

        hectares = int(query.data.replace("test_land_", ""))
        settle_vel(user.id)
        add_land(user.id, hectares)

        citizen = get_user(user.id)

        await query.message.reply_text(
            "🧪 TEST LAND PURCHASE\n\n"
            f"Добавлено: {hectares} га\n"
            f"Всего: {float(citizen['hectares']):g} га\n"
            f"Скорость: "
            f"{float(citizen['hectares']) * VEL_PER_HECTARE_PER_HOUR:g} VEL/час"
        )
        return

    if query.data == "test_assets":
        if not get_user(user.id) or not get_user(user.id)["citizen_id"]:
            await query.message.reply_text(
                "Сначала нажмите TEST: гражданство."
            )
            return

        await query.message.reply_text(
            "🧪 TEST ASSETS\n\n" + assets_text(user)
        )
        return

    if query.data == "test_reset":
        with db() as conn:
            conn.execute(
                "DELETE FROM payments WHERE telegram_id = ?",
                (user.id,),
            )
            conn.execute(
                "DELETE FROM users WHERE telegram_id = ?",
                (user.id,),
            )

        await query.message.reply_text(
            "🧹 Тестовый аккаунт сброшен."
        )
        return


# ============================================================
# EXTRA COMMANDS
# ============================================================

async def myid(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        f"Ваш Telegram ID: {update.effective_user.id}\n\n"
        "Используйте этот ID как ADMIN_ID в настройках деплоя."
    )


async def assets_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    ensure_user(update.effective_user)

    await update.message.reply_text(
        assets_text(update.effective_user),
        reply_markup=assets_keyboard(),
    )


async def land_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    ensure_user(update.effective_user)
    citizen = get_user(update.effective_user.id)

    await update.message.reply_text(
        land_text(update.effective_user),
        reply_markup=land_keyboard(
            locked=not citizen or not citizen["citizen_id"]
        ),
    )


async def citizenship_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    ensure_user(update.effective_user)

    await update.message.reply_text(
        citizenship_text(update.effective_user),
        reply_markup=citizenship_keyboard(),
    )


async def terms_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Vellar — цифровое сообщество.\n\n"
        "Гражданство и земельные участки в этом боте "
        "являются цифровыми внутриигровыми/социальными активами "
        "и не являются юридическим гражданством, "
        "государственной регистрацией или правом собственности "
        "на реальную землю."
    )


async def support_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🆘 Vellar Support\n\n"
        "По вопросам гражданства, платежей и активов "
        "обратитесь к администрации проекта."
    )


# ============================================================
# MAIN
# ============================================================

def main():
    if not BOT_TOKEN:
        raise RuntimeError(
            "BOT_TOKEN is not set. Add your Telegram bot token to environment variables."
        )

    init_db()

    application = (
        Application.builder()
        .token(BOT_TOKEN)
        .build()
    )

    # Commands
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("citizenship", citizenship_command))
    application.add_handler(CommandHandler("land", land_command))
    application.add_handler(CommandHandler("assets", assets_command))
    application.add_handler(CommandHandler("terms", terms_command))
    application.add_handler(CommandHandler("support", support_command))
    application.add_handler(CommandHandler("myid", myid))
    application.add_handler(CommandHandler("test", test_menu))

    # Normal buttons
    application.add_handler(
        CallbackQueryHandler(
            callbacks,
            pattern=r"^(menu|citizenship|land|assets|terms|support|buy_citizenship|buy_land_[124])$",
        )
    )

    # Developer test buttons
    application.add_handler(
        CallbackQueryHandler(
            test_callbacks,
            pattern=r"^test_",
        )
    )

    # Telegram Stars
    application.add_handler(
        PreCheckoutQueryHandler(precheckout)
    )

    application.add_handler(
        MessageHandler(
            filters.SUCCESSFUL_PAYMENT,
            successful_payment,
        )
    )

    print("Vellar Citizen Bot is running...")
    application.run_polling()


if __name__ == "__main__":
    main()
