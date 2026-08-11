import os
import threading
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
                "Любое отправленное сюда сообщение приведет к **муту на 12 часов** и удалению сообщений во всех каналах!"
            )
            await warning_msg.pin()

@bot.event
async def on_message(message):
    # Игнорируем бота и сообщения вне канала-ловушки
    if message.author.bot or message.channel.id != TARGET_CHANNEL_ID:
        return

    # Игнорируем администраторов
    if message.author.guild_permissions.administrator:
        return

    user = message.author
    guild = message.guild

    # 1. Мгновенно удаляем сообщение из канала-ловушки
    try:
        await message.delete()
    except Exception as e:
        print(f"Не удалось удалить сообщение: {e}")

    # 2. Выдаем пользователю таймаут на 12 часов
    try:
        await user.timeout(timedelta(hours=12), reason="Сообщение в заблокированном канале")
    except Exception as e:
        print(f"Ошибка при выдаче таймаута: {e}")

    # 3. Проходим по ВСЕМ текстовым каналам сервера и чистим сообщения нарушителя за последние 5 минут
    five_minutes_ago = datetime.now(timezone.utc) - timedelta(minutes=5)
    
    def is_user_recent_message(m):
        return m.author.id == user.id and m.created_at >= five_minutes_ago

    for text_channel in guild.text_channels:
        try:
            # Проверяем права бота в конкретном канале перед очисткой
            permissions = text_channel.permissions_for(guild.me)
            if permissions.manage_messages and permissions.read_message_history:
                await text_channel.purge(limit=100, check=is_user_recent_message)
        except Exception as e:
            print(f"Не удалось очистить канал {text_channel.name}: {e}")

TOKEN = os.environ.get("DISCORD_TOKEN")
bot.run(TOKEN)
