import os
import threading
import asyncio
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


# === ИНТЕРАКТИВНАЯ КНОПКА РАЗМУТА В DISCORD ===
class UnmuteButtonView(View):
    def __init__(self, target_user_id):
        super().__init__(timeout=None)  # Бесконечная кнопка
        self.target_user_id = target_user_id

    @discord.ui.button(label="🔓 Снять мут", style=discord.ButtonStyle.green, custom_id="discord_unmute_btn")
    async def unmute_button_callback(self, interaction: discord.Interaction, button: Button):
        # Проверка прав: снимать мут могут модераторы или администраторы
        if not interaction.user.guild_permissions.moderate_members and not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("⛔ У вас нет прав для снятия таймаута!", ephemeral=True)
            return

        guild = interaction.guild
        member = guild.get_member(self.target_user_id) or await guild.fetch_member(self.target_user_id)

        if member:
            try:
                await member.timeout(None, reason=f"Мут снят через логи пользователем {interaction.user}")
                
                # Обновляем вид кнопки
                button.disabled = True
                button.label = f"✅ Мут снят ({interaction.user.display_name})"
                button.style = discord.ButtonStyle.secondary
                
                await interaction.response.edit_message(view=self)
                await interaction.followup.send(f"✅ Таймаут с пользователя **{member}** успешно снят!", ephemeral=True)
            except Exception as e:
                await interaction.response.send_message(f"❌ Ошибка при снятии мута: {e}", ephemeral=True)
        else:
            await interaction.response.send_message("❌ Пользователь не найден на сервере.", ephemeral=True)


async def get_or_create_log_channel(guild):
    """Находит или создаёт приватный канал логов только для бота и владельцев/owner"""
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

    # 1. Отправляем логи в закрытый Discord-канал (экранируем теги + добавляем кнопку размута)
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
            embed.set_footer(text="Система автоматической модерации")

            view = UnmuteButtonView(target_user_id=user.id)

            await log_channel.send(embed=embed, view=view, allowed_mentions=discord.AllowedMentions.none())
    except Exception as e:
        print(f"[ОШИБКА ЛОГА В DISCORD] {e}")

    # 2. Мгновенно удаляем сообщение из ловушки
    try:
        await message.delete()
        print(f"Удалено сообщение от {user} из ловушки.")
    except Exception as e:
        print(f"[ОШИБКА УДАЛЕНИЯ СООБЩЕНИЯ] {e}")

    # 3. Выдаем таймаут на 12 часов
    try:
        await user.timeout(timedelta(hours=12), reason="Сообщение в заблокированном канале")
        print(f"Выдан таймаут пользователю {user}.")
    except Exception as e:
        print(f"[ОШИБКА ТАЙМАУТА] {e}")

    # 4. Чистим сообщения за последние 5 минут абсолютно во всех каналах
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
