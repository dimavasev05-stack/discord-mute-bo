import os
import threading
import discord
from discord.ext import commands
from datetime import datetime, timedelta, timezone
from flask import Flask

# === ФЕЙКОВЫЙ ВЕБ-СЕРВЕР ДЛЯ БЕСПЛАТНОГО ТАРИФА RENDER ===
app = Flask('')

@app.route('/')
def home():
    return "Bot is alive!"

def run_web():
    # Render передает порт через переменную PORT
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)

# Запускаем веб-сервер в отдельном потоке
threading.Thread(target=run_web).start()


# === КОД ДИСКОРД БОТА ===
intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)

TARGET_CHANNEL_ID = 1536698437758623824 

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
    channel = message.channel

    try:
        await user.timeout(timedelta(hours=12), reason="Сообщение в заблокированном канале")
    except Exception as e:
        print(f"Ошибка таймаута: {e}")

    ten_minutes_ago = datetime.now(timezone.utc) - timedelta(minutes=10)
    
    def is_user_recent_message(m):
        return m.author.id == user.id and not m.author.bot and m.created_at >= ten_minutes_ago

    try:
        await channel.purge(limit=100, check=is_user_recent_message)
    except Exception as e:
        print(f"Ошибка очистки: {e}")

TOKEN = os.environ.get("DISCORD_TOKEN")
bot.run(TOKEN)