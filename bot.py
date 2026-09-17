from pathlib import Path
from datetime import datetime, timezone
import os
import sqlite3
import time

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
    PreCheckoutQueryHandler,
    MessageHandler,
    filters,
)

from PIL import Image, ImageDraw, ImageFont


# =========================================================
# CONFIG
# =========================================================

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", "888972823"))

CARD_TEMPLATE = Path("citizen_card_template.png")
DB_PATH = Path("vellar.db")

CITIZENSHIP_PRICE = 500

LAND_PACKAGES = {
    1: 200,
    2: 300,
    4: 580,
}

VEL_PER_HECTARE_PER_HOUR = 1.5


# =========================================================
# DATABASE
# =========================================================

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            telegram_id INTEGER PRIMARY KEY,
            username TEXT,
            full_name TEXT,

            citizen_id TEXT UNIQUE,
            citizen_date TEXT,

            hectares REAL NOT NULL DEFAULT 0,
            vel_balance REAL NOT NULL DEFAULT 0,
            last_accrual REAL NOT NULL DEFAULT 0,

            citizenship_payment_id TEXT UNIQUE,

            test_citizen_id TEXT,
            test_citizen_date TEXT,
            test_hectares REAL NOT NULL DEFAULT 0,
            test_vel_balance REAL NOT NULL DEFAULT 0,
            test_last_accrual REAL NOT NULL DEFAULT 0
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS payments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            telegram_id INTEGER,
            payment_id TEXT UNIQUE,
            payment_type TEXT,
            amount INTEGER,
            created_at TEXT
        )
    """)

    # -----------------------------------------------------
    # MIGRATION FOR OLD DATABASE
    # -----------------------------------------------------

    cur.execute("PRAGMA table_info(users)")
    columns = {row["name"] for row in cur.fetchall()}

    migrations = {
        "test_citizen_id": "ALTER TABLE users ADD COLUMN test_citizen_id TEXT",
        "test_citizen_date": "ALTER TABLE users ADD COLUMN test_citizen_date TEXT",
        "test_hectares": "ALTER TABLE users ADD COLUMN test_hectares REAL NOT NULL DEFAULT 0",
        "test_vel_balance": "ALTER TABLE users ADD COLUMN test_vel_balance REAL NOT NULL DEFAULT 0",
        "test_last_accrual": "ALTER TABLE users ADD COLUMN test_last_accrual REAL NOT NULL DEFAULT 0",
    }

    for column, sql in migrations.items():
        if column not in columns:
            cur.execute(sql)

    conn.commit()
    conn.close()


# =========================================================
# HELPERS
# =========================================================

def now_str():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def get_user(telegram_id):
    conn = get_db()
    cur = conn.cursor()

    cur.execute(
        "SELECT * FROM users WHERE telegram_id = ?",
        (telegram_id,)
    )

    user = cur.fetchone()
    conn.close()

    return user


def ensure_user(telegram_user):
    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        INSERT INTO users (
            telegram_id,
            username,
            full_name,
            last_accrual,
            test_last_accrual
        )
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(telegram_id)
        DO UPDATE SET
            username = excluded.username,
            full_name = excluded.full_name
    """, (
        telegram_user.id,
        telegram_user.username,
        telegram_user.full_name,
        time.time(),
        time.time(),
    ))

    conn.commit()
    conn.close()


# =========================================================
# CITIZENSHIP
# =========================================================

def get_next_citizen_id():
    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        SELECT citizen_id
        FROM users
        WHERE citizen_id IS NOT NULL
    """)

    rows = cur.fetchall()
    conn.close()

    max_id = 0

    for row in rows:
        try:
            value = str(row["citizen_id"]).replace("#", "")
            number = int(value)

            if number > max_id:
                max_id = number

        except (ValueError, TypeError):
            pass

    return f"#{max_id + 1:04d}"


def create_citizen(telegram_user, payment_id=None):
    ensure_user(telegram_user)

    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        SELECT citizen_id
        FROM users
        WHERE telegram_id = ?
    """, (telegram_user.id,))

    existing = cur.fetchone()

    if existing and existing["citizen_id"]:
        conn.close()
        return existing["citizen_id"]

    citizen_id = get_next_citizen_id()
    date = now_str()

    cur.execute("""
        UPDATE users
        SET
            citizen_id = ?,
            citizen_date = ?,
            citizenship_payment_id = ?
        WHERE telegram_id = ?
    """, (
        citizen_id,
        date,
        payment_id,
        telegram_user.id,
    ))

    conn.commit()
    conn.close()

    return citizen_id


def create_test_citizenship(telegram_user):
    ensure_user(telegram_user)

    conn = get_db()
    cur = conn.cursor()

    test_id = "#TEST"
    date = now_str()

    cur.execute("""
        UPDATE users
        SET
            test_citizen_id = ?,
            test_citizen_date = ?
        WHERE telegram_id = ?
    """, (
        test_id,
        date,
        telegram_user.id,
    ))

    conn.commit()
    conn.close()

    return test_id


# =========================================================
# CITIZEN CARD
# =========================================================

def load_font(size):
    font_candidates = [
        "DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf",
    ]

    for path in font_candidates:
        try:
            return ImageFont.truetype(path, size)
        except Exception:
            pass

    return ImageFont.load_default()


def draw_big_text(
    base_image,
    text,
    center_x,
    center_y,
    font_size,
    max_width=None,
    fill=(255, 255, 255)
):
    draw = ImageDraw.Draw(base_image)

    size = font_size

    while size > 10:
        font = load_font(size)

        bbox = draw.textbbox((0, 0), str(text), font=font)

        width = bbox[2] - bbox[0]
        height = bbox[3] - bbox[1]

        if max_width is None or width <= max_width:
            break

        size -= 5

    x = center_x - width / 2
    y = center_y - height / 2

    draw.text(
        (x, y),
        str(text),
        font=font,
        fill=fill,
    )


def create_citizen_card(
    citizen_id,
    username,
    date,
    suffix="",
    telegram_user_id=None
):
    if not CARD_TEMPLATE.exists():
        raise FileNotFoundError(
            "Файл citizen_card_template.png не найден."
        )

    image = Image.open(CARD_TEMPLATE).convert("RGB")

    draw_big_text(
        base_image=image,
        text=citizen_id,
        center_x=350,
        center_y=450,
        max_width=600,
        font_size=180,
    )

    display_username = (
        f"@{username}"
        if username
        else f"ID {telegram_user_id}"
    )

    draw_big_text(
        base_image=image,
        text=display_username,
        center_x=350,
        center_y=600,
        max_width=600,
        font_size=100,
    )

    draw_big_text(
        base_image=image,
        text=date,
        center_x=800,
        center_y=600,
        max_width=500,
        font_size=90,
    )

    filename = (
        f"citizen_"
        f"{str(citizen_id).replace('#', '')}"
        f"{suffix}.png"
    )

    output_path = Path(filename)

    image.save(
        output_path,
        quality=95,
    )

    return output_path


# =========================================================
# VEL ACCRUAL
# =========================================================

def update_vel_balance(telegram_id):
    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        SELECT hectares, vel_balance, last_accrual
        FROM users
        WHERE telegram_id = ?
    """, (telegram_id,))

    user = cur.fetchone()

    if not user:
        conn.close()
        return

    current_time = time.time()
    last_accrual = user["last_accrual"] or current_time

    hours_passed = (
        current_time - last_accrual
    ) / 3600

    if hours_passed <= 0:
        conn.close()
        return

    earned = (
        user["hectares"]
        * VEL_PER_HECTARE_PER_HOUR
        * hours_passed
    )

    new_balance = user["vel_balance"] + earned

    cur.execute("""
        UPDATE users
        SET
            vel_balance = ?,
            last_accrual = ?
        WHERE telegram_id = ?
    """, (
        new_balance,
        current_time,
        telegram_id,
    ))

    conn.commit()
    conn.close()


def update_test_vel_balance(telegram_id):
    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        SELECT
            test_hectares,
            test_vel_balance,
            test_last_accrual
        FROM users
        WHERE telegram_id = ?
    """, (telegram_id,))

    user = cur.fetchone()

    if not user:
        conn.close()
        return

    current_time = time.time()

    last_accrual = (
        user["test_last_accrual"]
        or current_time
    )

    hours_passed = (
        current_time - last_accrual
    ) / 3600

    if hours_passed <= 0:
        conn.close()
        return

    earned = (
        user["test_hectares"]
        * VEL_PER_HECTARE_PER_HOUR
        * hours_passed
    )

    new_balance = user["test_vel_balance"] + earned

    cur.execute("""
        UPDATE users
        SET
            test_vel_balance = ?,
            test_last_accrual = ?
        WHERE telegram_id = ?
    """, (
        new_balance,
        current_time,
        telegram_id,
    ))

    conn.commit()
    conn.close()


# =========================================================
# KEYBOARDS
# =========================================================

def main_keyboard(user=None):
    buttons = []

    if user and user["citizen_id"]:
        buttons.append([
            InlineKeyboardButton(
                "🪪 Моё гражданство",
                callback_data="citizenship"
            )
        ])
    else:
        buttons.append([
            InlineKeyboardButton(
                "🪪 Стать гражданином",
                callback_data="citizenship"
            )
        ])

    buttons.extend([
        [
            InlineKeyboardButton(
                "🗺 Цифровая территория",
                callback_data="land"
            )
        ],
        [
            InlineKeyboardButton(
                "💎 Мои активы",
                callback_data="assets"
            )
        ],
        [
            InlineKeyboardButton(
                "📜 Условия",
                callback_data="terms"
            ),
            InlineKeyboardButton(
                "🆘 Поддержка",
                callback_data="support"
            ),
        ],
    ])

    return InlineKeyboardMarkup(buttons)


def test_keyboard():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "🪪 TEST гражданство",
                callback_data="test_citizenship"
            )
        ],
        [
            InlineKeyboardButton(
                "➕ TEST +1 га",
                callback_data="test_land_1"
            ),
            InlineKeyboardButton(
                "➕ TEST +2 га",
                callback_data="test_land_2"
            ),
        ],
        [
            InlineKeyboardButton(
                "➕ TEST +4 га",
                callback_data="test_land_4"
            )
        ],
        [
            InlineKeyboardButton(
                "💎 TEST активы",
                callback_data="test_assets"
            )
        ],
        [
            InlineKeyboardButton(
                "♻️ TEST сброс",
                callback_data="test_reset"
            )
        ],
    ])


# =========================================================
# TEXTS
# =========================================================

def start_text(user):
    if user and user["citizen_id"]:
        return (
            "🏛 <b>Добро пожаловать в Vellar.</b>\n\n"
            f"Ваш статус: <b>Citizen</b>\n"
            f"Ваш ID: <b>{user['citizen_id']}</b>\n\n"
            "Управляйте своим цифровым статусом, "
            "территорией и активами."
        )

    return (
        "🏛 <b>Добро пожаловать в Vellar.</b>\n\n"
        "Vellar — цифровая республика, "
        "в которой гражданство, территория "
        "и внутренние активы существуют "
        "в единой системе.\n\n"
        "Первый шаг — получить гражданство."
    )


def citizenship_text(user):
    if user and user["citizen_id"]:
        return (
            "🪪 <b>Ваше гражданство Vellar</b>\n\n"
            f"ID: <b>{user['citizen_id']}</b>\n"
            f"Дата: <b>{user['citizen_date']}</b>\n\n"
            "Статус: <b>Citizen</b>"
        )

    return (
        "🪪 <b>Гражданство Vellar</b>\n\n"
        "Станьте одним из первых граждан "
        "цифровой республики.\n\n"
        f"Стоимость: <b>{CITIZENSHIP_PRICE} ⭐</b>"
    )


def land_text(user):
    if not user or not user["citizen_id"]:
        return (
            "🗺 <b>Цифровая территория</b>\n\n"
            "Для приобретения территории "
            "необходимо сначала получить гражданство."
        )

    hectares = user["hectares"]

    return (
        "🗺 <b>Цифровая территория Vellar</b>\n\n"
        f"Ваша территория: <b>{hectares:g} га</b>\n\n"
        "Выберите пакет:"
    )


def assets_text(user):
    if not user or not user["citizen_id"]:
        return (
            "💎 <b>Активы Vellar</b>\n\n"
            "Раздел доступен гражданам Vellar."
        )

    return (
        "💎 <b>Мои активы</b>\n\n"
        f"🪪 Citizenship: <b>{user['citizen_id']}</b>\n"
        f"🗺 Territory: <b>{user['hectares']:g} га</b>\n"
        f"💎 VEL: <b>{user['vel_balance']:.2f}</b>"
    )


# =========================================================
# START
# =========================================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    telegram_user = update.effective_user

    ensure_user(telegram_user)

    user = get_user(telegram_user.id)

    await update.message.reply_text(
        start_text(user),
        parse_mode="HTML",
        reply_markup=main_keyboard(user),
    )


# =========================================================
# TEST COMMAND
# =========================================================

async def test_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return

    await update.message.reply_text(
        "🧪 <b>TEST MODE</b>\n\n"
        "Тестовые данные полностью отделены "
        "от реальных данных пользователя.\n\n"
        "Сброс теста НЕ удаляет настоящее гражданство.",
        parse_mode="HTML",
        reply_markup=test_keyboard(),
    )


# =========================================================
# CALLBACKS
# =========================================================

async def callbacks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    telegram_user = query.from_user
    ensure_user(telegram_user)

    user = get_user(telegram_user.id)
    data = query.data

    if data == "citizenship":
        await query.edit_message_text(
            citizenship_text(user),
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(
                        "⭐ Получить гражданство",
                        callback_data="buy_citizenship"
                    )
                ],
                [
                    InlineKeyboardButton(
                        "⬅️ Назад",
                        callback_data="menu"
                    )
                ],
            ]) if not user["citizen_id"] else
            InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(
                        "⬅️ Назад",
                        callback_data="menu"
                    )
                ]
            ])
        )

    elif data == "land":
        await query.edit_message_text(
            land_text(user),
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(
                        "1 га — 200 ⭐",
                        callback_data="buy_land_1"
                    )
                ],
                [
                    InlineKeyboardButton(
                        "2 га — 300 ⭐",
                        callback_data="buy_land_2"
                    )
                ],
                [
                    InlineKeyboardButton(
                        "4 га — 580 ⭐",
                        callback_data="buy_land_4"
                    )
                ],
                [
                    InlineKeyboardButton(
                        "⬅️ Назад",
                        callback_data="menu"
                    )
                ],
            ]) if user["citizen_id"] else
            InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(
                        "⬅️ Назад",
                        callback_data="menu"
                    )
                ]
            ])
        )

    elif data == "assets":
        update_vel_balance(telegram_user.id)

        user = get_user(telegram_user.id)

        await query.edit_message_text(
            assets_text(user),
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(
                        "⬅️ Назад",
                        callback_data="menu"
                    )
                ]
            ])
        )

    elif data == "terms":
        await query.edit_message_text(
            "📜 <b>Условия Vellar</b>\n\n"
            "Vellar является цифровым проектом. "
            "Гражданство и территория существуют "
            "внутри экосистемы Vellar.",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(
                        "⬅️ Назад",
                        callback_data="menu"
                    )
                ]
            ])
        )

    elif data == "support":
        await query.edit_message_text(
            "🆘 <b>Поддержка</b>\n\n"
            "По вопросам работы Vellar "
            "обратитесь к администратору.",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(
                        "⬅️ Назад",
                        callback_data="menu"
                    )
                ]
            ])
        )

    elif data == "menu":
        user = get_user(telegram_user.id)

        await query.edit_message_text(
            start_text(user),
            parse_mode="HTML",
            reply_markup=main_keyboard(user),
        )


# =========================================================
# BUY CITIZENSHIP
# =========================================================

async def buy_citizenship(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user = get_user(query.from_user.id)

    if user and user["citizen_id"]:
        await query.edit_message_text(
            "У вас уже есть гражданство Vellar.",
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(
                        "⬅️ Назад",
                        callback_data="menu"
                    )
                ]
            ])
        )
        return

    await context.bot.send_invoice(
        chat_id=query.from_user.id,
        title="Vellar Citizenship",
        description="Гражданство цифровой республики Vellar",
        payload="citizenship",
        currency="XTR",
        prices=[],
    )


# =========================================================
# BUY LAND
# =========================================================

async def buy_land(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user = get_user(query.from_user.id)

    if not user or not user["citizen_id"]:
        await query.edit_message_text(
            "Сначала необходимо получить гражданство Vellar."
        )
        return

    hectares = int(query.data.split("_")[-1])
    price = LAND_PACKAGES[hectares]

    await context.bot.send_invoice(
        chat_id=query.from_user.id,
        title=f"Vellar Territory — {hectares} га",
        description=f"Цифровая территория Vellar: {hectares} га",
        payload=f"land_{hectares}",
        currency="XTR",
        prices=[],
    )


# =========================================================
# PRECHECKOUT
# =========================================================

async def precheckout_callback(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    query = update.pre_checkout_query

    await query.answer(ok=True)


# =========================================================
# SUCCESSFUL PAYMENT
# =========================================================

async def successful_payment(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    payment = update.message.successful_payment
    telegram_user = update.effective_user

    payload = payment.invoice_payload
    payment_id = payment.telegram_payment_charge_id

    ensure_user(telegram_user)

    conn = get_db()
    cur = conn.cursor()

    try:
        cur.execute("""
            INSERT INTO payments (
                telegram_id,
                payment_id,
                payment_type,
                amount,
                created_at
            )
            VALUES (?, ?, ?, ?, ?)
        """, (
            telegram_user.id,
            payment_id,
            payload,
            payment.total_amount,
            datetime.now(timezone.utc).isoformat(),
        ))
    except sqlite3.IntegrityError:
        pass

    conn.commit()
    conn.close()

    if payload == "citizenship":
        citizen_id = create_citizen(
            telegram_user,
            payment_id=payment_id,
        )

        user = get_user(telegram_user.id)

        try:
            card_path = create_citizen_card(
                citizen_id=citizen_id,
                username=telegram_user.username,
                date=user["citizen_date"],
                telegram_user_id=telegram_user.id,
            )

            with open(card_path, "rb") as photo:
                await update.message.reply_photo(
                    photo=photo,
                    caption=(
                        "🏛 <b>Гражданство Vellar оформлено.</b>\n\n"
                        f"Ваш ID: <b>{citizen_id}</b>\n"
                        "Статус: <b>Citizen</b>"
                    ),
                    parse_mode="HTML",
                )

        except Exception:
            await update.message.reply_text(
                "🏛 <b>Гражданство Vellar оформлено.</b>\n\n"
                f"Ваш ID: <b>{citizen_id}</b>",
                parse_mode="HTML",
            )

    elif payload.startswith("land_"):
        hectares = int(payload.split("_")[1])

        conn = get_db()
        cur = conn.cursor()

        cur.execute("""
            UPDATE users
            SET hectares = hectares + ?
            WHERE telegram_id = ?
        """, (
            hectares,
            telegram_user.id,
        ))

        conn.commit()
        conn.close()

        await update.message.reply_text(
            "🗺 <b>Территория добавлена.</b>\n\n"
            f"Получено: <b>{hectares} га</b>",
            parse_mode="HTML",
        )


# =========================================================
# TEST CALLBACKS
# =========================================================

async def test_callbacks(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    query = update.callback_query
    await query.answer()

    telegram_user = query.from_user

    if telegram_user.id != ADMIN_ID:
        return

    ensure_user(telegram_user)

    data = query.data

    # -----------------------------------------------------
    # TEST CITIZENSHIP
    # -----------------------------------------------------

    if data == "test_citizenship":

        test_id = create_test_citizenship(
            telegram_user
        )

        user = get_user(telegram_user.id)

        try:
            card_path = create_citizen_card(
                citizen_id=test_id,
                username=telegram_user.username,
                date=user["test_citizen_date"],
                suffix="_test",
                telegram_user_id=telegram_user.id,
            )

            with open(card_path, "rb") as photo:
                await query.message.reply_photo(
                    photo=photo,
                    caption=(
                        "🧪 <b>TEST гражданство</b>\n\n"
                        "Это тестовая версия.\n"
                        "Реальное гражданство не изменено."
                    ),
                    parse_mode="HTML",
                )

        except Exception as e:
            await query.message.reply_text(
                f"Ошибка создания тестовой карты:\n{e}"
            )

    # -----------------------------------------------------
    # TEST LAND
    # -----------------------------------------------------

    elif data.startswith("test_land_"):

        hectares = int(data.split("_")[-1])

        conn = get_db()
        cur = conn.cursor()

        cur.execute("""
            UPDATE users
            SET
                test_hectares = test_hectares + ?,
                test_last_accrual = ?
            WHERE telegram_id = ?
        """, (
            hectares,
            time.time(),
            telegram_user.id,
        ))

        conn.commit()
        conn.close()

        user = get_user(telegram_user.id)

        await query.message.reply_text(
            "🧪 <b>TEST территория добавлена.</b>\n\n"
            f"Добавлено: <b>{hectares} га</b>\n"
            f"Всего TEST: <b>{user['test_hectares']:g} га</b>\n\n"
            "Реальная территория не изменена.",
            parse_mode="HTML",
        )

    # -----------------------------------------------------
    # TEST ASSETS
    # -----------------------------------------------------

    elif data == "test_assets":

        update_test_vel_balance(
            telegram_user.id
        )

        user = get_user(telegram_user.id)

        await query.message.reply_text(
            "🧪 <b>TEST АКТИВЫ</b>\n\n"
            f"🪪 Citizenship: "
            f"<b>{user['test_citizen_id'] or '—'}</b>\n"
            f"🗺 Territory: "
            f"<b>{user['test_hectares']:g} га</b>\n"
            f"💎 VEL: "
            f"<b>{user['test_vel_balance']:.2f}</b>\n\n"
            "Реальные активы пользователя "
            "не изменены.",
            parse_mode="HTML",
        )

    # -----------------------------------------------------
    # TEST RESET
    # -----------------------------------------------------

    elif data == "test_reset":

        conn = get_db()
        cur = conn.cursor()

        cur.execute("""
            UPDATE users
            SET
                test_citizen_id = NULL,
                test_citizen_date = NULL,
                test_hectares = 0,
                test_vel_balance = 0,
                test_last_accrual = ?
            WHERE telegram_id = ?
        """, (
            time.time(),
            telegram_user.id,
        ))

        conn.commit()
        conn.close()

        await query.message.reply_text(
            "♻️ <b>TEST данные сброшены.</b>\n\n"
            "Реальное гражданство, территория, "
            "VEL и история платежей НЕ затронуты.",
            parse_mode="HTML",
        )


# =========================================================
# ERROR HANDLER
# =========================================================

async def error_handler(
    update: object,
    context: ContextTypes.DEFAULT_TYPE
):
    print("ERROR:", context.error)


# =========================================================
# MAIN
# =========================================================

def main():

    if not BOT_TOKEN:
        raise RuntimeError(
            "BOT_TOKEN не найден в переменных окружения."
        )

    init_db()

    application = (
        Application.builder()
        .token(BOT_TOKEN)
        .build()
    )

    application.add_handler(
        CommandHandler("start", start)
    )

    application.add_handler(
        CommandHandler("test", test_command)
    )

    application.add_handler(
        CallbackQueryHandler(
            test_callbacks,
            pattern=r"^test_"
        )
    )

    application.add_handler(
        CallbackQueryHandler(
            buy_citizenship,
            pattern=r"^buy_citizenship$"
        )
    )

    application.add_handler(
        CallbackQueryHandler(
            buy_land,
            pattern=r"^buy_land_[124]$"
        )
    )

    application.add_handler(
        CallbackQueryHandler(
            callbacks,
            pattern=r"^(menu|citizenship|land|assets|terms|support)$"
        )
    )

    application.add_handler(
        PreCheckoutQueryHandler(
            precheckout_callback
        )
    )

    application.add_handler(
        MessageHandler(
            filters.SUCCESSFUL_PAYMENT,
            successful_payment
        )
    )

    application.add_error_handler(
        error_handler
    )

    print("Vellar bot started.")

    application.run_polling()


if __name__ == "__main__":
    main()
