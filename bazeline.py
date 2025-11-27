import logging
import os
from io import BytesIO
from pathlib import Path

from dotenv import load_dotenv
from PIL import Image, ImageDraw, ImageFilter
import telebot

# ----------------- НАСТРОЙКИ -----------------

BASE_DIR = Path(__file__).resolve().parent
TEMPLATE_PATH = BASE_DIR / "template.png"  # фон с рамкой
INNER_MARGIN_X = 130  # отступы от краёв шаблона
INNER_MARGIN_Y = 140
CORNER_RADIUS = 60  # радиус скругления
SHADOW_OFFSET = (18, 18)  # смещение тени (по x, по y)
SHADOW_BLUR = 12  # радиус размытия тени (плавный распад)
SHADOW_ALPHA = 90  # непрозрачность тени (более мягкая)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)


# ----------------- ОБРАБОТКА КАРТИНОК -----------------


def process_image(user_image_bytes: BytesIO) -> BytesIO:
    """
    Берём картинку от пользователя, скругляем, добавляем тень и вставляем
    её поверх шаблона. Возвращаем готовый PNG в виде BytesIO.
    """
    if not TEMPLATE_PATH.exists():
        raise FileNotFoundError(f"Template not found: {TEMPLATE_PATH}")

    template = Image.open(TEMPLATE_PATH).convert("RGBA")
    t_w, t_h = template.size

    inner_w = t_w - 2 * INNER_MARGIN_X
    inner_h = t_h - 2 * INNER_MARGIN_Y

    src = Image.open(user_image_bytes).convert("RGBA")
    src.thumbnail((inner_w, inner_h), Image.LANCZOS)
    s_w, s_h = src.size

    offset_x = INNER_MARGIN_X + (inner_w - s_w) // 2
    offset_y = INNER_MARGIN_Y + (inner_h - s_h) // 2

    # Антиалиасинг углов: рисуем маску в большем разрешении и сжимаем
    AA = 4
    hi_mask = Image.new("L", (s_w * AA, s_h * AA), 0)
    hi_draw = ImageDraw.Draw(hi_mask)
    hi_draw.rounded_rectangle(
        (0, 0, s_w * AA, s_h * AA), radius=CORNER_RADIUS * AA, fill=255
    )
    mask = hi_mask.resize((s_w, s_h), Image.LANCZOS)
    rounded = Image.new("RGBA", (s_w, s_h), (0, 0, 0, 0))
    rounded.paste(src, (0, 0), mask=mask)

    # Тень с запасом под размытие, чтобы углы не обрезались (скруглённые углы сохраняются)
    shadow_pad = SHADOW_BLUR * 3  # больше отступа, чтобы блюр не обрезался
    shadow_w = s_w + shadow_pad
    shadow_h = s_h + shadow_pad

    hi_shadow_mask = Image.new("L", (shadow_w * AA, shadow_h * AA), 0)
    hi_shadow_draw = ImageDraw.Draw(hi_shadow_mask)
    hi_shadow_draw.rounded_rectangle(
        (
            SHADOW_BLUR * AA,
            SHADOW_BLUR * AA,
            SHADOW_BLUR * AA + s_w * AA,
            SHADOW_BLUR * AA + s_h * AA,
        ),
        radius=CORNER_RADIUS * AA,
        fill=255,
    )
    
    hi_shadow_mask = hi_shadow_mask.filter(ImageFilter.GaussianBlur(SHADOW_BLUR * AA))
    shadow_mask = hi_shadow_mask.resize((shadow_w, shadow_h), Image.LANCZOS)

    shadow = Image.new("RGBA", (shadow_w, shadow_h), (0, 0, 0, 0))
    shadow.paste((0, 0, 0, SHADOW_ALPHA), mask=shadow_mask)

    result = template.copy()
    result.alpha_composite(
        shadow,
        (
            offset_x + SHADOW_OFFSET[0] - SHADOW_BLUR,
            offset_y + SHADOW_OFFSET[1] - SHADOW_BLUR,
        ),
    )
    result.alpha_composite(rounded, (offset_x, offset_y))

    output = BytesIO()
    output.name = "cover.png"
    result.save(output, format="PNG")
    output.seek(0)
    return output


# ----------------- ХЕНДЛЕРЫ БОТА (telebot) -----------------


def create_bot() -> telebot.TeleBot:
    load_dotenv()
    token = os.getenv("BOT_TOKEN")
    if not token:
        raise RuntimeError("BOT_TOKEN не найден в .env")

    bot = telebot.TeleBot(token)

    @bot.message_handler(commands=["start"])
    def start(message):
        bot.reply_to(
            message, "Привет! Отправь мне картинку — я сделаю обложку для поста 🐯"
        )

    @bot.message_handler(content_types=["photo"])
    def handle_photo(message):
        try:
            photo = message.photo[-1]
            file_info = bot.get_file(photo.file_id)
            downloaded = bot.download_file(file_info.file_path)

            img_bytes = BytesIO(downloaded)
            processed = process_image(img_bytes)

            bot.send_photo(message.chat.id, processed)
        except Exception as e:
            logger.exception("Ошибка при обработке изображения: %s", e)
            bot.reply_to(
                message, "Что-то пошло не так при обработке картинки 😔 Попробуй снова."
            )

    return bot


# ----------------- ЗАПУСК -----------------


def main():
    bot = create_bot()
    logger.info("Bot is running with telebot polling")
    bot.infinity_polling()


if __name__ == "__main__":
    main()
