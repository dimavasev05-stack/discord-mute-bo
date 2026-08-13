import os
import threading
import requests
import asyncio
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

    caption_text = (
        f"🚨 **Нарушение в канале-ловушке!**\n\n"
        f"👤 **Пользователь:** {username} (ID: `{user_id}`)\n"
        f"💬 **Текст:** {content if content else '_[без текста]_'}"
    )

    # Инлайн-кнопка для Telegram
    reply_markup = {
        "inline_keyboard": [
            [{"text": "🔓 Снять мут (Unmute)", "callback_data": f"unmute_{user_id}"}]
        ]
    }

    if attachments:
        images = [att for att in attachments if att.content_type and att.content_type.startswith('image/')]
        other_files = [att for att in attachments if att not in images]

        if images:
            if len(images) == 1:
                url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendPhoto"
                payload = {
                    "chat_id": TELEGRAM_CHAT_ID,
                    "photo": images[0].url,
                    "caption": caption_text,
                    "parse_mode": "Markdown",
                    "reply_markup": reply_markup
                }
                try:
                    requests.post(url, json=payload, timeout=10)
                except Exception as e:
                    print(f"Ошибка отправки фото в Telegram: {e}")
            else:
                url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMediaGroup"
                media = []
                for i, img in enumerate(images):
                    item = {"type": "photo", "media": img.url}
                    if i == 0:
                        item["caption"] = caption_text
                        item["parse_mode"] = "Markdown"
                    media.append(item)
                
                try:
                    requests.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "media": media}, timeout=10)
                    # Кнопку отправляем отдельным сообщением после альбома
                    url_msg = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
                    requests.post(url_msg, json={
                        "chat_id": TELEGRAM_CHAT_ID,
                        "text": f"Управление мутом для `{username}`:",
                        "parse_mode": "Markdown",
                        "reply_markup": reply_markup
                    }, timeout=5)
                except Exception as e:
                    print(f"Ошибка отправки альбома в Telegram: {e}")

        for file in other_files:
            url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendDocument"
            file_caption = caption_text if not images else f"📎 Файл от {username}"
            payload = {
                "chat_id": TELEGRAM_CHAT_ID,
                "document": file.url,
                "caption": file_caption,
                "parse_mode": "Markdown",
                "reply_markup": reply_markup
            }
            try:
                requests.post(url, json=payload, timeout=10)
            except Exception as e:
                print(f"Ошибка отправки документа в Telegram: {e}")

    else:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        payload = {
            "chat_id": TELEGRAM_CHAT_ID,
            "text": caption_text,
            "parse_mode": "Markdown",
            "reply_markup": reply_markup
        }
        try:
            requests.post(url, json=payload, timeout=5)
        except Exception as e:
            print(f"Ошибка отправки сообщения в Telegram: {e}")


# === СЛУШАТЕЛЬ НАЖАТИЙ КНОПОК В TELEGRAM ===
def telegram_polling():
    if not TELEGRAM_TOKEN:
        return
    
    offset = 0
    while True:
        try:
            url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates?offset={offset}&timeout=10"
            res = requests.get(url, timeout=15).json()
            
            if res.get("ok"):
                for update in res.get("result", []):
                    offset = update["update_id"] + 1
                    
                    if "callback_query" in update:
                        cq = update["callback_query"]
                        data = cq.get("data", "")
                        callback_id = cq.get("id")
                        
                        if data.startswith("unmute_"):
                            user_id = int(data.split("_")[1])
                            
                            # Передаем задачу на размут в основной поток Discord
                            future = asyncio.run_coroutine_threadsafe(unmute_discord_user(user_id), bot.loop)
                            success, user_name = future.result(timeout=10)
                            
                            # Ответ всплывающим уведомлением в Telegram
                            answer_url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/answerCallbackQuery"
                            if success:
                                msg_text = f"✅ Таймаут с пользователя {user_name} успешно снят!"
                            else:
                                msg_text = f"❌ Не удалось снять таймаут (пользователь не найден или снят вручную)."
                            
                            requests.post(answer_url, json={"callback_query_id": callback_id, "text": msg_text, "show_alert": True})
                            
                            # Обновляем сообщение в Telegram, убирая кнопку
                            if success and "message" in cq:
                                chat_id = cq["message"]["chat"]["id"]
                                msg_id = cq["message"]["message_id"]
                                edit_url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/editMessageReplyMarkup"
                                requests.post(edit_url, json={"chat_id": chat_id, "message_id": msg_id, "reply_markup": {"inline_keyboard": []}})
        except Exception as e:
            pass
        asyncio.run(asyncio.sleep(2))

threading.Thread(target=telegram_polling, daemon=True).start()


async def unmute_discord_user(user_id):
    try:
        channel = bot.get_channel(TARGET_CHANNEL_ID)
        if not channel:
            return False, ""
        
        guild = channel.guild
        member = guild.get_member(user_id) or await guild.fetch_member(user_id)
        
        if member:
            await member.timeout(None, reason="Мут снят вручную через Telegram")
            return True, str(member)
    except Exception as e:
        print(f"Ошибка снятия мута: {e}")
    return False, ""


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

    # 1. Отправляем уведомление в Telegram перед удалением из Discord
    send_telegram_notification(
        username=str(user),
        user_id=user.id,
        content=message.content,
        attachments=message.attachments
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
