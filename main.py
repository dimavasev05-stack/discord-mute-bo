import os
import threading
import requests
import asyncio
import time
import discord
from discord.ext import commands
from discord.ui import Button, View
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

threading.Thread(target=run_web, daemon=True).start()


# === НАСТРОЙКА И КОД ДИСКОРД БОТА ===
intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)

# ID канала-ловушки
TARGET_CHANNEL_ID = 1536698437758623824 
# Название закрытого канала-лога в Discord
LOG_CHANNEL_NAME = "лог-ловушка"

# Данные Telegram из переменных окружения
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")


# === ИНТЕРАКТИВНАЯ КНОПКА РАЗМУТА В DISCORD ===
class UnmuteButtonView(View):
    def __init__(self, target_user_id):
        super().__init__(timeout=None) # Бесконечная кнопка
        self.target_user_id = target_user_id

    @discord.ui.button(label="🔓 Снять мут", style=discord.ButtonStyle.green, custom_id="discord_unmute_btn")
    async def unmute_button_callback(self, interaction: discord.Interaction, button: Button):
        # Проверяем, есть ли у нажавшего права на управление мутами
        if not interaction.user.guild_permissions.moderate_members and not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("⛔ У вас нет прав для снятия таймаута!", ephemeral=True)
            return

        guild = interaction.guild
        member = guild.get_member(self.target_user_id) or await guild.fetch_member(self.target_user_id)

        if member:
            try:
                await member.timeout(None, reason=f"Мут снят модератором {interaction.user}")
                
                # Меняем кнопку на деактивированную
                button.disabled = True
                button.label = f"✅ Мут снят ({interaction.user.display_name})"
                button.style = discord.ButtonStyle.secondary
                
                await interaction.response.edit_message(view=self)
                await interaction.followup.send(f"✅ Таймаут с пользователя **{member}** успешно снят!", ephemeral=True)
            except Exception as e:
                await interaction.response.send_message(f"❌ Ошибка при снятии мута: {e}", ephemeral=True)
        else:
            await interaction.response.send_message("❌ Пользователь не найден на сервере.", ephemeral=True)


def send_telegram_notification(username, user_id, content, attachments):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print("Telegram token или Chat ID не настроены.")
        return

    caption_text = (
        f"🚨 **Нарушение в канале-ловушке!**\n\n"
        f"👤 **Пользователь:** {username} (ID: `{user_id}`)\n"
        f"💬 **Текст:** {content if content else '_[без текста]_'}"
    )

    reply_markup = {
        "inline_keyboard": [
            [{"text": "🔓 Снять мут (Unmute)", "callback_data": f"unmute_{user_id}"}]
        ]
    }

    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        payload = {
            "chat_id": TELEGRAM_CHAT_ID,
            "text": caption_text,
            "parse_mode": "Markdown",
            "reply_markup": reply_markup
        }
        res = requests.post(url, json=payload, timeout=5)
        if not res.ok:
            print(f"[ОШИБКА TELEGRAM API] {res.status_code}: {res.text}")
        else:
            print("Уведомление в Telegram успешно отправлено!")
    except Exception as e:
        print(f"[ОШИБКА ОТПРАВКИ В TELEGRAM] {e}")


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
                        from_user_id = str(cq.get("from", {}).get("id"))
                        
                        if TELEGRAM_CHAT_ID and from_user_id != str(TELEGRAM_CHAT_ID):
                            answer_url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/answerCallbackQuery"
                            requests.post(answer_url, json={
                                "callback_query_id": cq.get("id"),
                                "text": "⛔ У вас нет доступа к управлению этим ботом!",
                                "show_alert": True
                            })
                            continue

                        data = cq.get("data", "")
                        callback_id = cq.get("id")
                        
                        if data.startswith("unmute_"):
                            user_id = int(data.split("_")[1])
                            
                            future = asyncio.run_coroutine_threadsafe(unmute_discord_user(user_id), bot.loop)
                            try:
                                success, user_name = future.result(timeout=10)
                            except Exception as e:
                                success, user_name = False, ""
                            
                            answer_url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/answerCallbackQuery"
                            if success:
                                msg_text = f"✅ Таймаут с пользователя {user_name} успешно снят!"
                            else:
                                msg_text = f"❌ Не удалось снять таймаут."
                            
                            requests.post(answer_url, json={"callback_query_id": callback_id, "text": msg_text, "show_alert": True})
                            
                            if success and "message" in cq:
                                chat_id = cq["message"]["chat"]["id"]
                                msg_id = cq["message"]["message_id"]
                                edit_url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/editMessageReplyMarkup"
                                requests.post(edit_url, json={"chat_id": chat_id, "message_id": msg_id, "reply_markup": {"inline_keyboard": []}})
        except Exception as e:
            pass
        time.sleep(2)

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


async def get_or_create_log_channel(guild):
    """Находит или создаёт приватный канал логов только для бота и роли owner/владельца"""
    log_channel = discord.utils.get(guild.text_channels, name=LOG_CHANNEL_NAME)
    if log_channel:
        return log_channel

    try:
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(read_messages=False),
            guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True)
        }
        
        owner_role = discord.utils.get(guild.roles, name="owner") or discord.utils.get(guild.roles, name="Owner")
        if owner_role:
            overwrites[owner_role] = discord.PermissionOverwrite(read_messages=True, send_messages=False)

        if guild.owner:
            overwrites[guild.owner] = discord.PermissionOverwrite(read_messages=True, send_messages=False)

        log_channel = await guild.create_text_channel(
            name=LOG_CHANNEL_NAME,
            overwrites=overwrites,
            reason="Автоматический канал для логов ловушки"
        )
        print(f"Создан приватный логирующий канал: {log_channel.name}")
        return log_channel
    except Exception as e:
        print(f"[ОШИБКА СОЗДАНИЯ ЛОГ-КАНАЛА] {e}")
        return None


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
        print(f"Сообщение от {message.author} проигнорировано (администратор).")
        return

    user = message.author
    guild = message.guild

    # 1. Отправляем логи в приватный канал Discord с интерактивной кнопкой Unmute
    try:
        log_channel = await get_or_create_log_channel(guild)
        if log_channel:
            safe_content = message.content.replace("@everyone", "@‌everyone").replace("@here", "@‌here") if message.content else "_[без текста]_"
            
            embed = discord.Embed(
                title="🚨 Нарушение в канале-ловушке!",
                color=discord.Color.red(),
                timestamp=datetime.now(timezone.utc)
            )
            embed.add_field(name="Пользователь", value=f"{user.mention} (`{user.id}`)", inline=True)
            embed.add_field(name="Сообщение", value=safe_content, inline=False)
            embed.set_footer(text="Автоматический лог системы безопасности")

            # Прикрепляем View с интерактивной кнопкой размута
            view = UnmuteButtonView(target_user_id=user.id)

            await log_channel.send(embed=embed, view=view, allowed_mentions=discord.AllowedMentions.none())
    except Exception as e:
        print(f"[ОШИБКА ЛОГА В DISCORD] {e}")

    # 2. Отправляем уведомление в Telegram
    try:
        send_telegram_notification(
            username=str(user),
            user_id=user.id,
            content=message.content,
            attachments=message.attachments
        )
    except Exception as e:
        print(f"[ТЕЛЕГРАМ ОШИБКА] {e}")

    # 3. Мгновенно удаляем сообщение из ловушки
    try:
        await message.delete()
        print(f"Удалено сообщение от {user} из ловушки.")
    except Exception as e:
        print(f"[ОШИБКА УДАЛЕНИЯ СООБЩЕНИЯ] {e}")

    # 4. Выдаем таймаут на 12 часов
    try:
        await user.timeout(timedelta(hours=12), reason="Сообщение в заблокированном канале")
        print(f"Выдан таймаут пользователю {user}.")
    except Exception as e:
        print(f"[ОШИБКА ТАЙМАУТА] {e}")

    # 5. Чистим сообщения за последние 5 минут во всех каналах сервера
    five_minutes_ago = datetime.now(timezone.utc) - timedelta(minutes=5)
    
    def is_user_recent_message(m):
        return m.author.id == user.id and m.created_at >= five_minutes_ago

    all_channels = (
        guild.text_channels + 
        guild.voice_channels + 
        getattr(guild, 'stage_channels', []) + 
        getattr(guild, 'forum_channels', [])
    )

    for ch in all_channels:
        try:
            permissions = ch.permissions_for(guild.me)
            if permissions.manage_messages and permissions.read_message_history:
                deleted = await ch.purge(limit=100, check=is_user_recent_message)
                if deleted:
                    print(f"Удалено {len(deleted)} сообщений у {user} в канале {ch.name}.")
        except Exception as e:
            print(f"[ОШИБКА ЧИСТКИ В КАНАЛЕ {ch.name}] {e}")

TOKEN = os.environ.get("DISCORD_TOKEN")
bot.run(TOKEN)
