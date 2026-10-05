"""
gamjabat_bot — Discord 자동 응답 봇
- gate1-자기소개에 새 글 올라오면 → 새싹감자 역할 자동 부여 + 환영 메시지
"""

import os
import discord
from discord.ext import commands

TOKEN = os.getenv("DISCORD_BOT_TOKEN", "")
GUILD_ID = int(os.getenv("DISCORD_GUILD_ID", "1555788463247466566"))
GATE1_CHANNEL_ID = int(os.getenv("DISCORD_GATE1_CHANNEL_ID", "1555810377554591757"))
SEEDLING_ROLE_ID = int(os.getenv("DISCORD_SEEDLING_ROLE_ID", "1555811319477964871"))

intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.guilds = True

bot = commands.Bot(command_prefix="!", intents=intents)


@bot.event
async def on_ready():
    print(f"✅ gamjabat_bot 시작: {bot.user}")
    guild = bot.get_guild(GUILD_ID)
    if guild:
        print(f"   서버: {guild.name} ({guild.member_count}명)")


@bot.event
async def on_thread_create(thread: discord.Thread):
    """포럼 채널에 새 포스트(스레드) 생성 시"""

    # gate1-자기소개 채널에 올라온 것만
    if thread.parent_id != GATE1_CHANNEL_ID:
        return

    guild = thread.guild
    author = thread.owner

    if not author:
        return

    # 새싹감자 역할 부여
    seedling_role = guild.get_role(SEEDLING_ROLE_ID)
    already_has_role = seedling_role and seedling_role in author.roles

    if seedling_role and not already_has_role:
        try:
            await author.add_roles(seedling_role, reason="gate1-자기소개 작성 완료")
            print(f"✅ 새싹감자 역할 부여: {author.display_name}")
        except discord.Forbidden:
            print(f"❌ 역할 부여 권한 없음: {author.display_name}")

    # 환영 메시지
    welcome = (
        f"🌱 **{author.display_name}님, 감자밭에 오신 걸 환영해요!**\n\n"
    )

    if not already_has_role:
        welcome += "새싹감자 역할이 부여됐어요.\n\n"

    welcome += (
        "**다음 단계:**\n"
        "→ AI 공부를 시작하고 싶다면: gamja99.up.railway.app\n"
        "→ 레벨 판정을 받고 싶다면: gate2-레벨판정\n"
        "→ 자유롭게 얘기하고 싶다면: 자유잡담\n\n"
        "궁금한 거 있으면 질문방에 편하게 올려줘요 🥔"
    )

    try:
        await thread.send(welcome)
        print(f"✅ 환영 메시지 전송: {author.display_name}")
    except Exception as e:
        print(f"❌ 메시지 전송 실패: {e}")


if __name__ == "__main__":
    if not TOKEN:
        print("❌ DISCORD_BOT_TOKEN 없음")
    else:
        bot.run(TOKEN)
