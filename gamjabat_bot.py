"""
감자밭 Discord 봇
① gate1-자기소개 새 스레드 → 자동 안내 댓글
② 새 멤버 서버 입장 → 자동 DM
③ 방장이 자기소개에 ✅ 이모지 → 작성자에게 자동 DM
④ gamja99 가입 완료 시 → 감자명으로 멤버 찾아 DM
"""
import asyncio, os, threading
import discord

GUILD_ID         = int(os.environ.get("DISCORD_GUILD_ID",  "1555788463247466566"))
FORUM_CHANNEL_ID = int(os.environ.get("DISCORD_FORUM_CHANNEL", "1555810377554591757"))
BOT_TOKEN        = os.environ.get("DISCORD_BOT_TOKEN", "")

MSG_THREAD_COMMENT = """\
자기소개 잘 봤어 🥔

새싹감자 역할이 부여됐어!

이제 여기 들어와서 회원가입 해봐!
👉 gamja99.up.railway.app

아이디 + 비밀번호만 입력하면 되고,
감자명은 Discord 닉네임 그대로 쓰면 돼!

가입하면 **마음의 방**에서 씨앗 찾기 시작해봐.
씨앗 다 작성하면 판정 요청까지 해줘야 완성이야 🌱"""

MSG_WELCOME_DM = """\
감자밭에 온 걸 환영해 🥔

먼저 **#gate1-자기소개** 채널에 소개글 올려줘!
채널 들어가면 양식 있어.
작성하면 다음 단계 안내해줄게 😊"""

MSG_APPROVED_DM = """\
자기소개 확인됐어 ✅

이제 여기서 회원가입 해봐!
👉 gamja99.up.railway.app

아이디 + 비밀번호만 입력하면 되고,
감자명은 Discord 닉네임 그대로 쓰면 돼!

가입하면 **마음의 방**에서 씨앗 찾기 시작해봐 🌱"""

MSG_REGISTERED_DM = """\
gamja99 가입 확인됐어 🥔

**마음의 방** 탭 들어가서 씨앗 찾기 시작해봐!
씨앗 다 작성하면 판정 요청까지 해줘야 완성이야.
모르는 거 있으면 언제든 물어봐 😊"""

intents = discord.Intents.default()
intents.guilds    = True
intents.members   = True
intents.reactions = True
bot = discord.Client(intents=intents)

@bot.event
async def on_ready():
    print(f"[감자밭봇] 연결됨: {bot.user}")

# ① 자기소개 새 스레드 → 품질 체크 후 역할 부여 or 재작성 안내
SEEDLING_ROLE_ID = int(os.environ.get("DISCORD_SEEDLING_ROLE_ID", "1555811319477964871"))

MIN_LENGTH = 50
QUESTIONS = ["1.", "2.", "3.", "4.", "5."]
MIN_QUESTIONS = 4
MIN_ANSWER_LEN = 8  # 각 답변 최소 길이

def _extract_answers(text: str) -> dict:
    """번호별 답변 내용 추출"""
    answers = {}
    for i, q in enumerate(QUESTIONS):
        next_q = QUESTIONS[i+1] if i+1 < len(QUESTIONS) else None
        start = text.find(q)
        if start == -1:
            continue
        end = text.find(next_q, start+2) if next_q else len(text)
        answer = text[start+2:end].strip()
        answers[q] = answer
    return answers

VAGUE = ["모름", "모르겠", "없음", "없어", "아직", "모르겠다", "몰라", "기타", "없다", "?", "ㅎ", "ㄱ", "ㅋ"]

def check_quality(text: str) -> tuple[bool, str]:
    """자기소개 품질 체크. (통과 여부, 피드백) 반환"""
    text = text.strip()

    if len(text) < MIN_LENGTH:
        return False, f"내용이 너무 짧아요 ({len(text)}자). 아래 질문들에 맞게 답해줘요!"

    answered = sum(1 for q in QUESTIONS if q in text)
    if answered < MIN_QUESTIONS:
        missing = [q for q in QUESTIONS if q not in text]
        return False, f"**{', '.join(missing)} 번 질문**에 답이 없어요. ({answered}/5개)"

    # 각 답변 품질 체크
    answers = _extract_answers(text)
    too_short = []
    too_vague = []
    for q, ans in answers.items():
        num = q.rstrip('.')
        if len(ans) < MIN_ANSWER_LEN:
            too_short.append(num)
        elif any(v in ans for v in VAGUE) and len(ans) < 15:
            too_vague.append(num)

    if too_short:
        return False, f"**{', '.join(too_short)}번** 답변이 너무 짧아요. 조금 더 구체적으로 써줘요!"
    if too_vague:
        return False, f"**{', '.join(too_vague)}번** 답변이 너무 막연해요. 실제 상황이나 예시를 넣어줘요!"

    return True, "통과"

@bot.event
async def on_thread_create(thread: discord.Thread):
    if thread.parent_id != FORUM_CHANNEL_ID:
        return
    await asyncio.sleep(4)  # 글 작성 완료 대기

    # 첫 메시지 가져오기
    try:
        messages = [m async for m in thread.history(limit=1, oldest_first=True)]
        content = messages[0].content if messages else ""
    except Exception:
        content = thread.name  # 첫 메시지 못 가져오면 제목으로 대체

    passed, reason = check_quality(content)
    guild = bot.get_guild(GUILD_ID)
    author = thread.owner

    if passed:
        # 새싹감자 역할 부여
        try:
            if guild and author:
                role = guild.get_role(SEEDLING_ROLE_ID)
                if role and role not in author.roles:
                    await author.add_roles(role, reason="gate1-자기소개 품질 통과")
                    print(f"[감자밭봇] 새싹감자 부여: {author.display_name}")
        except Exception as e:
            print(f"[감자밭봇] 역할 부여 오류: {e}")

        # 환영 댓글
        try:
            await thread.send(MSG_THREAD_COMMENT)
        except Exception as e:
            print(f"[감자밭봇] 환영 댓글 오류: {e}")

    else:
        # 재작성 안내 — 어느 부분이 부족한지 구체적으로
        try:
            await thread.send(
                f"🥔 자기소개 잘 봤어! 조금만 더 채워주면 새싹감자 역할 드릴게요.\n\n"
                f"**{reason}**\n\n"
                f"아래 양식 참고해서 수정해줘요:\n"
                f"> **1.** 지금 주로 사용하는 AI\n"
                f"> **2.** AI 주로 사용하는 영역\n"
                f"> **3.** AI로 직접 만들거나 해결해본 것\n"
                f"> **4.** 가장 막히는 지점\n"
                f"> **5.** 지금 AI로 해결해보고 싶은 문제\n\n"
                f"수정하면 바로 확인할게요!"
            )
            print(f"[감자밭봇] 재작성 안내: {author.display_name if author else '?'} — {reason}")
        except Exception as e:
            print(f"[감자밭봇] 재작성 안내 오류: {e}")

# ② 새 멤버 입장 → 자동 DM
@bot.event
async def on_member_join(member: discord.Member):
    if member.guild.id != GUILD_ID:
        return
    try:
        await member.send(MSG_WELCOME_DM)
        print(f"[감자밭봇] 입장 DM: {member.display_name}")
    except discord.Forbidden:
        print(f"[감자밭봇] 입장 DM 실패 (DM 차단): {member.display_name}")

# ③ 방장 ✅ 이모지 → 자기소개 작성자 DM
@bot.event
async def on_raw_reaction_add(payload: discord.RawReactionActionEvent):
    if str(payload.emoji) != "✅":
        return
    channel = bot.get_channel(payload.channel_id)
    if not isinstance(channel, discord.Thread):
        return
    if channel.parent_id != FORUM_CHANNEL_ID:
        return
    try:
        msgs = [m async for m in channel.history(limit=1, oldest_first=True)]
        if not msgs or msgs[0].author.bot:
            return
        await msgs[0].author.send(MSG_APPROVED_DM)
        print(f"[감자밭봇] 승인 DM: {msgs[0].author.display_name}")
    except discord.Forbidden:
        print(f"[감자밭봇] 승인 DM 실패 (DM 차단)")
    except Exception as e:
        print(f"[감자밭봇] 승인 DM 오류: {e}")

# ④ gamja99 가입 완료 → 감자명으로 DM
async def _dm_by_nickname(nickname: str):
    guild = bot.get_guild(GUILD_ID)
    if not guild:
        return
    member = discord.utils.find(
        lambda m: m.display_name == nickname or m.name == nickname,
        guild.members
    )
    if not member:
        print(f"[감자밭봇] 멤버 못 찾음: {nickname}")
        return
    try:
        await member.send(MSG_REGISTERED_DM)
        print(f"[감자밭봇] 가입 완료 DM: {member.display_name}")
    except discord.Forbidden:
        print(f"[감자밭봇] 가입 완료 DM 실패: {nickname}")

def notify_registered(nickname: str):
    """main.py 동기 컨텍스트에서 호출"""
    if _bot_loop and not bot.is_closed():
        asyncio.run_coroutine_threadsafe(_dm_by_nickname(nickname), _bot_loop)

_bot_thread: threading.Thread | None = None
_bot_loop:   asyncio.AbstractEventLoop | None = None

def start_bot():
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

# ⑤ 사이트 URL 변경 시 → 공지 채널에 메시지
async def _announce_url_change(new_url: str):
    guild = bot.get_guild(GUILD_ID)
    if not guild:
        return
    # 공지(announcement) 또는 general 채널 찾기
    ch = discord.utils.find(
        lambda c: c.name in ("공지", "announcement", "general", "일반"),
        guild.text_channels
    )
    if not ch:
        # 없으면 notify 채널 ID 사용
        notify_ch_id = os.environ.get("DISCORD_NOTIFY_CHANNEL", "")
        if notify_ch_id:
            ch = bot.get_channel(int(notify_ch_id))
    if not ch:
        print(f"[감자밭봇] URL 공지 채널 못 찾음")
        return
    try:
        await ch.send(f"📢 **사이트 주소가 변경됐어!**\n새 주소: {new_url}")
        print(f"[감자밭봇] URL 변경 공지 완료: {new_url}")
    except Exception as e:
        print(f"[감자밭봇] URL 공지 오류: {e}")

def notify_url_change(new_url: str):
    """main.py 동기 컨텍스트에서 호출"""
    if _bot_loop and not bot.is_closed():
        asyncio.run_coroutine_threadsafe(_announce_url_change(new_url), _bot_loop)
