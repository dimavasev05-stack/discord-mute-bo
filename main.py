import os
import threading
import requests
import discord
from discord.ext import commands
from datetime import datetime, timedelta, timezone
from flask import Flask

# === ВЕБ-СЕРВЕР ДЛЯ RENDER И ВНЕШНЕГО ПИНГА ===
app = Flask('')

@app.route('/', methods=['GET', 'HEAD'])
def home():
    return "Bot is alive!"

def run_web():
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)

threading.Thread(target=run_web).start()


# === НАСТРОЙКА И КОД ДИСКОРД БОТА ===
intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)

# ID канала-ловушки
TARGET_CHANNEL_ID = 1536698437758623824 

# Данные Telegram из переменных окружения
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

def send_telegram_notification(username, user_id, content, attachments):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print("Telegram token или Chat ID не настроены.")
        return

    # Формируем текст уведомления
    text = (
        f"🚨 **Нарушение в канале-ловушке!**\n\n"
        f"👤 **Пользователь:** {username} (ID: `{user_id}`)\n"
        f"💬 **Текст:** {content if content else '_[без текста]_'}\n"
    )

    if attachments:
        text += "\n📎 **Вложения/Медиа:**\n"
        for url in attachments:
            text += f"• {url}\n"

    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "Markdown"
    }

    try:
        requests.post(url, json=payload, timeout=5)
    except Exception as e:
        print(f"Ошибка отправки в Telegram: {e}")


@bot.event
async def on_ready():
    print(f"Бот {bot.user} успешно запущен!")
    channel = bot.get_channel(TARGET_CHANNEL_ID)
    if channel:
        pins = await channel.pins()
        has_warning_pin = any(pin.author.id == bot.user.id for pin in pins)
        if not has_warning_pin:
            warning_msg = await channel.send(
                "⚠️ **ВНИМАНИЕ!** Этот канал заблокирован.\n"
                "Любое отправленное сюда сообщение приведет к **муту на 12 часов** и удалению сообщений!"
            )
            await warning_msg.pin()

@bot.event
async def on_message(message):
    if message.author.bot or message.channel.id != TARGET_CHANNEL_ID:
        return

    if message.author.guild_permissions.administrator:
        return

    user = message.author
    guild = message.guild

    # Собираем ссылки на медиафайлы/вложения
    attachment_urls = [att.url for att in message.attachments]

    # 1. Отправляем уведомление в Telegram перед удалением
    send_telegram_notification(
        username=str(user),
        user_id=user.id,
        content=message.content,
        attachments=attachment_urls
    )

    # 2. Мгновенно удаляем сообщение из канала-ловушки
    try:
        await message.delete()
    except Exception as e:
        print(f"Не удалось удалить сообщение: {e}")

    # 3. Выдаем таймаут на 12 часов
    try:
        await user.timeout(timedelta(hours=12), reason="Сообщение в заблокированном канале")
    except Exception as e:
        print(f"Ошибка при выдаче таймаута: {e}")

    # 4. Чистим сообщения нарушителя за последние 5 минут во всех каналах
    five_minutes_ago = datetime.now(timezone.utc) - timedelta(minutes=5)
    
    def is_user_recent_message(m):
        return m.author.id == user.id and m.created_at >= five_minutes_ago

    for text_channel in guild.text_channels:
        try:
            permissions = text_channel.permissions_for(guild.me)
            if permissions.manage_messages and permissions.read_message_history:
                await text_channel.purge(limit=100, check=is_user_recent_message)
        except Exception as e:
            print(f"Не удалось очистить канал {text_channel.name}: {e}")

TOKEN = os.environ.get("DISCORD_TOKEN")
bot.run(TOKEN)
