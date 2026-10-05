"""
감자밭 Discord 봇
- gate1-자기소개 포럼에 새 스레드 생성 시 자동 안내 댓글
- FastAPI lifespan에서 백그라운드 스레드로 실행
"""
import asyncio
import os
import threading

import discord

FORUM_CHANNEL_ID = int(os.environ.get("DISCORD_FORUM_CHANNEL", "1555810377554591757"))
BOT_TOKEN        = os.environ.get("DISCORD_BOT_TOKEN", "")

WELCOME_COMMENT = """\
자기소개 잘 봤어 🥔

이제 여기 들어와서 회원가입 해봐!
👉 gamja99.up.railway.app

아이디 + 비밀번호만 입력하면 되고,
감자명은 Discord 닉네임 그대로 쓰면 돼!

가입하면 **마음의 방**에서 씨앗 찾기 시작해봐.
씨앗 다 작성하면 판정 요청까지 해줘야 완성이야 🌱\
"""

# ── 봇 클라이언트 ──────────────────────────────────────────────
intents = discord.Intents.default()
intents.guilds = True

bot = discord.Client(intents=intents)

@bot.event
async def on_ready():
    print(f"[감자밭봇] 연결됨: {bot.user}")

@bot.event
async def on_thread_create(thread: discord.Thread):
    """포럼에 새 자기소개 스레드 생성 시 자동 댓글"""
    if thread.parent_id != FORUM_CHANNEL_ID:
        return
    # 글 올라오는 시간 잠깐 대기
    await asyncio.sleep(3)
    try:
        await thread.send(WELCOME_COMMENT)
        print(f"[감자밭봇] 댓글 완료: {thread.name}")
    except Exception as e:
        print(f"[감자밭봇] 댓글 오류: {e}")

# ── FastAPI 에서 호출하는 시작/종료 함수 ──────────────────────
_bot_thread: threading.Thread | None = None
_bot_loop:   asyncio.AbstractEventLoop | None = None

def start_bot():
    """백그라운드 스레드에서 봇 이벤트 루프 실행"""
    global _bot_loop
    if not BOT_TOKEN:
        print("[감자밭봇] DISCORD_BOT_TOKEN 없음 — 봇 비활성화")
        return

    _bot_loop = asyncio.new_event_loop()
    asyncio.set_event_loop(_bot_loop)
    _bot_loop.run_until_complete(bot.start(BOT_TOKEN))

def launch_bot_thread():
    global _bot_thread
    _bot_thread = threading.Thread(target=start_bot, daemon=True, name="gamjabat-bot")
    _bot_thread.start()

async def stop_bot():
    if not bot.is_closed():
        await bot.close()
