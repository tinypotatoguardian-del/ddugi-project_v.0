"""
ddugi Project v.0 — 지구 종말 방지 프로젝트

- FastAPI + SQLite(파일 기반)로 씨앗 데이터를 저장합니다.
- 프론트엔드(static/index.html)는 /api/... 엔드포인트를 호출합니다.

실행:
    pip install -r requirements.txt
    python main.py
    -> http://localhost:8000 접속

계정 (마스터 · 관리자):
    사번 + 비밀번호로 로그인합니다. 최초 실행 때 마스터 계정 1개가
    환경변수 MASTER_EMP_ID / MASTER_CODE (없으면 "master" / "1234")로 만들어집니다.
    마스터는 화면의 "계정 관리"에서 다른 사번을 관리자로 추가하거나 뺄 수 있고,
    누구나 화면의 "비밀번호 변경"에서 자기 비밀번호를 바꿉니다.
    같은 사번으로 5회 연속 틀리면 그 사번은 5분간 잠깁니다 (IP가 아니라 사번 기준이라,
    같은 사무실 IP를 여럿이 써도 한 사람의 실패가 남을 잠그지 않습니다).
"""

import datetime
import hashlib
import zoneinfo
KST = zoneinfo.ZoneInfo("Asia/Seoul")
import hmac
import json
import os
import secrets
import sqlite3
import time
import urllib.request as _urllib_req

# ── Discord 가입 알람 ──────────────────────────────────────────
_DISCORD_BOT_TOKEN   = os.environ.get("DISCORD_BOT_TOKEN", "")
_DISCORD_NOTIFY_CH   = os.environ.get("DISCORD_NOTIFY_CHANNEL", "")

def _notify_discord(msg: str):
    """회원가입 등 이벤트 발생 시 Discord 채널에 알람 전송."""
    if not _DISCORD_BOT_TOKEN or not _DISCORD_NOTIFY_CH:
        return
    try:
        data = json.dumps({"content": msg}).encode()
        req = _urllib_req.Request(
            f"https://discord.com/api/v10/channels/{_DISCORD_NOTIFY_CH}/messages",
            data=data,
            headers={
                "Authorization": f"Bot {_DISCORD_BOT_TOKEN}",
                "Content-Type": "application/json",
                "User-Agent": "DiscordBot (https://discord.com, 10)",
            },
            method="POST",
        )
        _urllib_req.urlopen(req, timeout=5)
    except Exception as e:
        print(f"[Discord notify] 오류: {e}")
from typing import Any, Dict, Optional

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

# JWT
JWT_SECRET = os.environ.get("JWT_SECRET", secrets.token_hex(32))
JWT_ALGO = "HS256"
JWT_EXPIRE_DAYS = 30

try:
    from jose import jwt as jose_jwt, JWTError
    HAS_JOSE = True
except ImportError:
    HAS_JOSE = False

def make_token(user_id: str, email: str, plan: str = "free") -> str:
    if not HAS_JOSE:
        return secrets.token_hex(32)
    exp = datetime.datetime.utcnow() + datetime.timedelta(days=JWT_EXPIRE_DAYS)
    return jose_jwt.encode({"sub": user_id, "email": email, "plan": plan, "exp": exp}, JWT_SECRET, algorithm=JWT_ALGO)

def decode_token(token: str) -> dict:
    if not HAS_JOSE:
        raise HTTPException(status_code=401, detail="JWT 라이브러리 없음")
    try:
        return jose_jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGO])
    except JWTError:
        raise HTTPException(status_code=401, detail="토큰이 유효하지 않거나 만료됐어요.")

def require_user_token(x_token: str) -> dict:
    """X-Token 헤더에서 유저 정보 추출"""
    if not x_token:
        raise HTTPException(status_code=401, detail="로그인이 필요해요.")
    payload = decode_token(x_token)
    username = payload.get("email", "")
    if not username:
        raise HTTPException(status_code=401, detail="토큰이 유효하지 않아요.")
    return {
        "username": username,
        "user_id": payload.get("sub", ""),
        "plan": payload.get("plan", "free"),
    }

def get_current_user(authorization: str = "") -> dict:
    """Authorization: Bearer <token> 헤더에서 유저 정보 추출"""
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="로그인이 필요해요.")
    return decode_token(authorization[7:])

APP_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(APP_DIR, "data.db")
DATABASE_URL = os.environ.get("DATABASE_URL", "")  # PostgreSQL 연결 문자열 (없으면 SQLite)
USE_PG = DATABASE_URL.startswith("postgres")
if USE_PG:
    import psycopg2
    import psycopg2.extras
# 최초 실행 때만 쓰는 마스터 계정. 이후에는 화면에서 비밀번호를 바꾼다.
MASTER_EMP_ID = os.environ.get("MASTER_EMP_ID", "master")
MASTER_CODE = os.environ.get("MASTER_CODE", "1234")
MIN_CODE_LEN = 6
MAX_FAILS = 5          # 연속 실패 허용 횟수
LOCK_SECONDS = 300     # 초과 시 잠금 시간 (5분)

# 01·02에서 고르는 분류의 기본값 (관리자가 화면에서 바꾸기 전까지 쓰는 값). 프론트엔드(index.html)의
# 기존 CATEGORIES/TARGETS/WORK_TYPES/도구 목록과 같은 내용 — 하드코딩을 없애는 게 목적이라 그대로 옮겼다.
DEFAULT_TAXONOMY = {
    "categories": {
        "① 업무관리형": ["업무관리", "일정관리", "진행현황", "회의/Action Item 관리"],
        "② 정보검색·지식형": ["자료 검색", "사례 검색", "문헌 검색"],
        "③ 분석·판단지원형": ["데이터 분석", "원인분석", "이상판단", "비교/평가"],
        "④ 문서·보고 자동화형": ["보고서 작성", "주간보고", "회의자료"],
        "⑤ 업무 프로세스 자동화형": ["반복 입력", "자료 취합", "데이터 정리", "검토/분류"],
    },
    "targets": ["공통 (업무관리 등)", "기타"],
    "worktypes": ["개발", "관리", "분석", "기획", "운영", "기타"],
    "tools": ["사내 시스템/ERP", "Office", "BI 도구", "Python 스크립트", "생성형 AI", "기타"],
    # 00 시작하기 화면 안내문 (HTML). 프론트엔드에 하드코딩돼 있던 걸 그대로 옮겼고, master만 수정 가능
    "intro_html": "",
}


def get_db():
    if USE_PG:
        conn = psycopg2.connect(DATABASE_URL)
        conn.autocommit = False
        return conn
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def db_execute(conn, sql, params=None):
    """Execute SQL — adapts ? placeholders to %s for PostgreSQL."""
    if USE_PG:
        sql = sql.replace("?", "%s")
    cur = conn.cursor()
    cur.execute(sql, params or ())
    return cur


def db_fetchone(conn, sql, params=None):
    cur = db_execute(conn, sql, params)
    row = cur.fetchone()
    if row is None:
        return None
    if USE_PG:
        cols = [d[0] for d in cur.description]
        return dict(zip(cols, row))
    return row


def db_fetchall(conn, sql, params=None):
    cur = db_execute(conn, sql, params)
    if USE_PG:
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]
    return cur.fetchall()


def hash_code(code: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", code.encode(), salt, 200_000)
    return salt.hex() + "$" + digest.hex()


def init_db() -> None:
    conn = get_db()
    db_execute(conn,
        """
        CREATE TABLE IF NOT EXISTS submissions (
            doc_id TEXT PRIMARY KEY,
            team TEXT,
            name TEXT,
            fields TEXT,
            locked INTEGER DEFAULT 0,
            completed INTEGER DEFAULT 0,
            status TEXT,
            filled_count INTEGER DEFAULT 0,
            total_sections INTEGER DEFAULT 0,
            recommended_type TEXT,
            updated_at TEXT
        )
        """
    )
    conn.commit()  # 아래 마이그레이션 ALTER가 실패해서 rollback해도 이 CREATE TABLE은 지워지지 않도록
    # 관리자 Gate 확인 결과. 작성자 저장(PUT)으로는 바뀌지 않도록 fields와 따로 둔다
    if USE_PG:
        cols = [r["column_name"] for r in db_fetchall(conn,
            "SELECT column_name FROM information_schema.columns WHERE table_name='submissions'")]
    else:
        cols = [r["name"] for r in db_fetchall(conn, "PRAGMA table_info(submissions)")]
    if "gate_review" not in cols:
        try:
            db_execute(conn, "ALTER TABLE submissions ADD COLUMN gate_review TEXT")
        except Exception:
            if USE_PG:
                conn.rollback()  # PG requires rollback after failed DDL
    # ── 일반 유저 계정 (이메일 기반)
    if USE_PG:
        db_execute(conn, """
            CREATE TABLE IF NOT EXISTS users (
                id SERIAL PRIMARY KEY,
                username TEXT UNIQUE,
                email TEXT UNIQUE,
                password_hash TEXT NOT NULL,
                nickname TEXT,
                plan TEXT DEFAULT 'free',
                plan_expires_at TEXT,
                created_at TEXT,
                last_login_at TEXT
            )
        """)
        conn.commit()  # 아래 마이그레이션 ALTER가 실패해서 rollback해도 이 CREATE TABLE은 지워지지 않도록
        # 마이그레이션: username 컬럼 없으면 추가 (옛날 DB용. 이미 있으면 그냥 실패하고 넘어감)
        try:
            db_execute(conn, "ALTER TABLE users ADD COLUMN username TEXT")
            conn.commit()
        except Exception:
            conn.rollback()
    else:
        db_execute(conn, """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE,
                email TEXT,
                password_hash TEXT NOT NULL,
                nickname TEXT,
                plan TEXT DEFAULT 'free',
                plan_expires_at TEXT,
                created_at TEXT,
                last_login_at TEXT
            )
        """)
        conn.commit()
        # 마이그레이션: username 컬럼 없으면 추가
        try:
            db_execute(conn, "ALTER TABLE users ADD COLUMN username TEXT")
            conn.commit()
        except Exception:
            pass

    # 마이그레이션: role 컬럼 (새싹감자/l1/l2/l3/l4/l5/mentor)
    try:
        db_execute(conn, "ALTER TABLE users ADD COLUMN role TEXT DEFAULT 'seedling'")
        conn.commit()
    except Exception:
        if USE_PG:
            conn.rollback()

    # 마이그레이션: is_active 컬럼 (0=비활성, 1=활성)
    try:
        db_execute(conn, "ALTER TABLE users ADD COLUMN is_active INTEGER DEFAULT 1")
        conn.commit()
    except Exception:
        if USE_PG:
            conn.rollback()

    # 마이그레이션: discord_username (Discord 서버 닉네임)
    try:
        db_execute(conn, "ALTER TABLE users ADD COLUMN discord_username TEXT")
        conn.commit()
    except Exception:
        if USE_PG:
            conn.rollback()

    # 마이그레이션: discord_thread_id (마음의 방 Discord 스레드 ID)
    try:
        db_execute(conn, "ALTER TABLE users ADD COLUMN discord_thread_id TEXT")
        conn.commit()
    except Exception:
        if USE_PG:
            conn.rollback()

    # 마이그레이션: mindroom_completed_at (마음의 방 완성 시각)
    try:
        db_execute(conn, "ALTER TABLE users ADD COLUMN mindroom_completed_at TEXT")
        conn.commit()
    except Exception:
        if USE_PG:
            conn.rollback()

    # 마이그레이션: submissions.discord_thread_id (씨앗별 Discord 스레드)
    try:
        db_execute(conn, "ALTER TABLE submissions ADD COLUMN discord_thread_id TEXT")
        conn.commit()
    except Exception:
        if USE_PG:
            conn.rollback()

    # 마이그레이션: intro_data (마음의 방 서버 저장)
    try:
        db_execute(conn, "ALTER TABLE users ADD COLUMN intro_data TEXT")
        conn.commit()
    except Exception:
        if USE_PG:
            conn.rollback()

    # 마이그레이션: discover_data (심기 전 준비 판정 결과 저장)
    try:
        db_execute(conn, "ALTER TABLE users ADD COLUMN discover_data TEXT")
        conn.commit()
    except Exception:
        if USE_PG:
            conn.rollback()

    # 마이그레이션: 관리자가 직접 만들어준 계정(아이디=초기 비번)이 최초 로그인 시
    # 비번을 바꾸도록 강제하는 플래그
    try:
        db_execute(conn, "ALTER TABLE users ADD COLUMN must_change_password INTEGER DEFAULT 0")
        conn.commit()
    except Exception:
        if USE_PG:
            conn.rollback()

    # ── invite_codes 테이블
    if USE_PG:
        db_execute(conn, """
            CREATE TABLE IF NOT EXISTS invite_codes (
                code TEXT PRIMARY KEY,
                created_by TEXT,
                plan TEXT DEFAULT 'free',
                expires_at TEXT,
                used_at TEXT,
                used_by TEXT
            )
        """)
    else:
        db_execute(conn, """
            CREATE TABLE IF NOT EXISTS invite_codes (
                code TEXT PRIMARY KEY,
                created_by TEXT,
                plan TEXT DEFAULT 'free',
                expires_at TEXT,
                used_at TEXT,
                used_by TEXT
            )
        """)
    conn.commit()  # 아래 submissions 마이그레이션 ALTER가 실패해서 rollback해도 이 CREATE TABLE은 지워지지 않도록

    # ── settings 테이블 (관리자 설정값 — URL, Discord 초대링크 등)
    db_execute(conn, """
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT,
            updated_at TEXT
        )
    """)
    # 기본값 세팅
    now_str = datetime.datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S")
    for k, v in [
        ("gamja99_url", "https://gamja99.up.railway.app"),
        ("discord_invite", ""),
    ]:
        q_exist = "SELECT 1 FROM settings WHERE key=?" if not USE_PG else "SELECT 1 FROM settings WHERE key=%s"
        if not db_fetchone(conn, q_exist, (k,)):
            q_ins = "INSERT INTO settings (key,value,updated_at) VALUES (?,?,?)" if not USE_PG else \
                    "INSERT INTO settings (key,value,updated_at) VALUES (%s,%s,%s)"
            db_execute(conn, q_ins, (k, v, now_str))
    conn.commit()

    # ── admin_sessions 테이블 (서버 재시작해도 세션 유지)
    if USE_PG:
        db_execute(conn, """
            CREATE TABLE IF NOT EXISTS admin_sessions (
                token TEXT PRIMARY KEY,
                emp_id TEXT NOT NULL,
                role TEXT NOT NULL,
                created_at TEXT
            )
        """)
    else:
        db_execute(conn, """
            CREATE TABLE IF NOT EXISTS admin_sessions (
                token TEXT PRIMARY KEY,
                emp_id TEXT NOT NULL,
                role TEXT NOT NULL,
                created_at TEXT
            )
        """)
    conn.commit()
    # submissions에 user_id 컬럼 추가 (마이그레이션)
    try:
        if USE_PG:
            db_execute(conn, "ALTER TABLE submissions ADD COLUMN user_id TEXT")
        else:
            db_execute(conn, "ALTER TABLE submissions ADD COLUMN user_id TEXT")
        if USE_PG:
            conn.commit()
    except Exception:
        if USE_PG:
            conn.rollback()
    # submissions에 ip 컬럼 추가 (마이그레이션) — 씨앗목록에서 제출자를 구분하기 위해
    try:
        db_execute(conn, "ALTER TABLE submissions ADD COLUMN ip TEXT")
        if USE_PG:
            conn.commit()
    except Exception:
        if USE_PG:
            conn.rollback()
    # 마스터·관리자 계정 (사번 + 비밀번호 해시 + 역할)
    db_execute(conn,
        """
        CREATE TABLE IF NOT EXISTS accounts (
            emp_id TEXT PRIMARY KEY,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL,
            name TEXT,
            created_at TEXT
        )
        """
    )
    if not db_fetchone(conn, "SELECT 1 FROM accounts WHERE role='master'"):
        db_execute(conn,
            "INSERT INTO accounts (emp_id, password_hash, role, name, created_at) VALUES (?,?,?,?,?)",
            (MASTER_EMP_ID, hash_code(MASTER_CODE), "master", "master", datetime.datetime.utcnow().isoformat()),
        )
    # 01·02에서 고르는 분류 목록 (카테고리·대상·업무 유형·도구). 하드코딩 대신 관리자가 화면에서 바꿀 수 있게 DB로 뺐다.
    db_execute(conn, "CREATE TABLE IF NOT EXISTS taxonomy (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
    for key, default in DEFAULT_TAXONOMY.items():
        if not db_fetchone(conn, "SELECT 1 FROM taxonomy WHERE key=?", (key,)):
            db_execute(conn, "INSERT INTO taxonomy (key, value) VALUES (?,?)", (key, json.dumps(default, ensure_ascii=False)))
    # 감자밭 (feedback)
    if USE_PG:
        db_execute(conn,
            """
            CREATE TABLE IF NOT EXISTS feedback (
                id SERIAL PRIMARY KEY,
                nickname TEXT,
                message TEXT NOT NULL,
                status TEXT DEFAULT 'planted',
                admin_note TEXT,
                created_at TEXT,
                reviewed_at TEXT
            )
            """
        )
    else:
        db_execute(conn,
            """
            CREATE TABLE IF NOT EXISTS feedback (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                nickname TEXT,
                message TEXT NOT NULL,
                status TEXT DEFAULT 'planted',
                admin_note TEXT,
                created_at TEXT,
                reviewed_at TEXT
            )
            """
        )
    # 방문 기록
    if USE_PG:
        db_execute(conn,
            """
            CREATE TABLE IF NOT EXISTS guestbook (
                id SERIAL PRIMARY KEY,
                nickname TEXT,
                message TEXT NOT NULL,
                created_at TEXT
            )
            """
        )
    else:
        db_execute(conn,
            """
            CREATE TABLE IF NOT EXISTS guestbook (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                nickname TEXT,
                message TEXT NOT NULL,
                created_at TEXT
            )
            """
        )
    # 방문 기록
    if USE_PG:
        db_execute(conn,
            """
            CREATE TABLE IF NOT EXISTS visits (
                id SERIAL PRIMARY KEY,
                ip TEXT,
                user_agent TEXT,
                path TEXT,
                visited_at TEXT
            )
            """
        )
    else:
        db_execute(conn,
            """
            CREATE TABLE IF NOT EXISTS visits (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ip TEXT,
                user_agent TEXT,
                path TEXT,
                visited_at TEXT
            )
            """
        )
    # 가입 대기 신청 (초대제라 가입 폼 대신 "카톡 아이디 남기기"로 받는 신청)
    if USE_PG:
        db_execute(conn,
            """
            CREATE TABLE IF NOT EXISTS signup_requests (
                id SERIAL PRIMARY KEY,
                contact TEXT NOT NULL,
                note TEXT,
                created_at TEXT
            )
            """
        )
    else:
        db_execute(conn,
            """
            CREATE TABLE IF NOT EXISTS signup_requests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                contact TEXT NOT NULL,
                note TEXT,
                created_at TEXT
            )
            """
        )
    conn.commit()
    # signup_requests에 contact_type 컬럼 추가 (마이그레이션) — 카톡/전화 구분용
    try:
        db_execute(conn, "ALTER TABLE signup_requests ADD COLUMN contact_type TEXT")
        conn.commit()
    except Exception:
        if USE_PG:
            conn.rollback()
    # signup_requests에 created_username 컬럼 추가 (마이그레이션) — 이 사람에게 만들어준 계정 아이디 기록용
    try:
        db_execute(conn, "ALTER TABLE signup_requests ADD COLUMN created_username TEXT")
        conn.commit()
    except Exception:
        if USE_PG:
            conn.rollback()
    # signup_requests에 희망 아이디·감자명 컬럼 추가 (마이그레이션)
    try:
        db_execute(conn, "ALTER TABLE signup_requests ADD COLUMN desired_username TEXT")
        conn.commit()
    except Exception:
        if USE_PG:
            conn.rollback()
    try:
        db_execute(conn, "ALTER TABLE signup_requests ADD COLUMN nickname TEXT")
        conn.commit()
    except Exception:
        if USE_PG:
            conn.rollback()
    if MASTER_EMP_ID == "master" and MASTER_CODE == "1234":
        print("[경고] 마스터 계정이 기본값(사번 master / 비밀번호 1234)입니다. 로그인 후 비밀번호를 바꾸세요.")
    conn.close()


def check_account(conn, emp_id: str, code: str) -> bool:
    row = db_fetchone(conn, "SELECT password_hash FROM accounts WHERE emp_id=?", (emp_id,))
    if not row:
        return False
    salt_hex, digest_hex = row["password_hash"].split("$")
    digest = hashlib.pbkdf2_hmac("sha256", (code or "").encode(), bytes.fromhex(salt_hex), 200_000)
    return hmac.compare_digest(digest.hex(), digest_hex)


def get_role(conn, emp_id: str) -> Optional[str]:
    row = db_fetchone(conn, "SELECT role FROM accounts WHERE emp_id=?", (emp_id,))
    return row["role"] if row else None


# 사번별 연속 실패 횟수와 잠금 해제 시각 (IP가 아니라 사번 기준)
# ponytail: 메모리 보관이라 서버를 다시 켜면 초기화됨. 사내 SSO 연동 시 이 방식은 대체
FAILS: Dict[str, list] = {}

# 관리자 로그인 세션 — DB에 저장해서 서버 재시작해도 유지
ADMIN_SESSIONS: Dict[str, dict] = {}  # 캐시용 (DB 조회 최소화)


def make_admin_session(emp_id: str, role: str) -> str:
    token = secrets.token_hex(32)
    now = datetime.datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S")
    conn = get_db()
    if USE_PG:
        db_execute(conn, "INSERT INTO admin_sessions (token,emp_id,role,created_at) VALUES (%s,%s,%s,%s)", (token, emp_id, role, now))
        conn.commit()
    else:
        db_execute(conn, "INSERT INTO admin_sessions (token,emp_id,role,created_at) VALUES (?,?,?,?)", (token, emp_id, role, now))
    conn.close()
    ADMIN_SESSIONS[token] = {"emp_id": emp_id, "role": role}
    return token


def revoke_admin_sessions(emp_id: str):
    conn = get_db()
    if USE_PG:
        db_execute(conn, "DELETE FROM admin_sessions WHERE emp_id=%s", (emp_id,))
        conn.commit()
    else:
        db_execute(conn, "DELETE FROM admin_sessions WHERE emp_id=?", (emp_id,))
    conn.close()
    for t in [t for t, s in ADMIN_SESSIONS.items() if s["emp_id"] == emp_id]:
        ADMIN_SESSIONS.pop(t, None)


def require_admin_token(token: str, allowed: set) -> dict:
    # 캐시 먼저
    sess = ADMIN_SESSIONS.get(token or "")
    if not sess:
        # DB에서 조회 (서버 재시작 후 캐시 없을 때)
        conn = get_db()
        if USE_PG:
            row = db_fetchone(conn, "SELECT emp_id,role FROM admin_sessions WHERE token=%s", (token or "",))
        else:
            row = db_fetchone(conn, "SELECT emp_id,role FROM admin_sessions WHERE token=?", (token or "",))
        conn.close()
        if row:
            sess = {"emp_id": row["emp_id"], "role": row["role"]}
            ADMIN_SESSIONS[token] = sess  # 캐시에 올려두기
        else:
            raise HTTPException(status_code=403, detail="로그인이 필요해요. 다시 로그인해주세요.")
    if sess["role"] not in allowed:
        raise HTTPException(status_code=403, detail="이 계정은 이 화면을 볼 권한이 없습니다.")
    return sess


def require_role(emp_id: str, code: str, allowed: set) -> str:
    """사번+비밀번호를 확인하고 역할을 돌려준다.
    비밀번호가 틀리면 403(남은 횟수)/429(잠김)이고 실패 횟수에 들어간다.
    비밀번호는 맞지만 역할이 allowed에 없으면 403(권한 없음)이고, 이건 실패 횟수에 넣지 않는다
    (권한이 부족한 사람이 잘못 시도했다고 잠기면 안 되니까).
    """
    emp_id = (emp_id or "").strip()
    rec = FAILS.get(emp_id)
    if rec and rec[1] > time.time():
        raise HTTPException(status_code=429, detail={"locked_seconds": int(rec[1] - time.time()) + 1})
    conn = get_db()
    ok = check_account(conn, emp_id, code)
    role = get_role(conn, emp_id) if ok else None
    conn.close()
    if not ok:
        rec = FAILS.setdefault(emp_id, [0, 0.0])
        rec[0] += 1
        if rec[0] >= MAX_FAILS:
            rec[0], rec[1] = 0, time.time() + LOCK_SECONDS
            raise HTTPException(status_code=429, detail={"locked_seconds": LOCK_SECONDS})
        raise HTTPException(status_code=403, detail={"remaining": MAX_FAILS - rec[0]})
    FAILS.pop(emp_id, None)
    if role not in allowed:
        raise HTTPException(status_code=403, detail="이 사번은 이 화면을 볼 권한이 없습니다.")
    return role


init_db()

# ── 감자밭 봇 시작 ──────────────────────────────────────────────
from contextlib import asynccontextmanager
from gamjabat_bot import launch_bot_thread, stop_bot, notify_registered, notify_url_change

@asynccontextmanager
async def lifespan(app):
    launch_bot_thread()   # 봇 백그라운드 시작
    yield
    await stop_bot()      # 서버 종료 시 봇도 종료

app = FastAPI(title="ddugi Project", lifespan=lifespan)


def get_client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for", "")
    return forwarded.split(",")[0].strip() if forwarded else (request.client.host if request.client else "unknown")


@app.middleware("http")
async def log_visit(request: Request, call_next):
    """Log page visits to DB (skip API calls and static assets)."""
    path = request.url.path
    skip_prefixes = ("/api/",)
    static_exts = (".js", ".css", ".png", ".jpg", ".jpeg", ".gif", ".svg", ".ico", ".woff", ".woff2", ".ttf", ".map")
    # 운영자 IP — 방문 기록 제외
    SKIP_IPS = {"211.37.81.27"}
    should_log = (
        not any(path.startswith(p) for p in skip_prefixes)
        and not any(path.endswith(ext) for ext in static_exts)
        and (path == "/" or "." not in path.split("/")[-1])
    )
    if should_log:
        try:
            ip = get_client_ip(request)  # Railway 리버스 프록시 뒤에서 실제 IP 가져오기
            if ip in SKIP_IPS:
                should_log = False
            if should_log:
                ua = request.headers.get("user-agent", "")
                now = datetime.datetime.utcnow().isoformat()
                conn = get_db()
                db_execute(conn, "INSERT INTO visits (ip, user_agent, path, visited_at) VALUES (?,?,?,?)",
                           (ip, ua, path, now))
                conn.commit()
                conn.close()
        except Exception:
            pass  # 방문 기록 실패가 요청을 막지 않도록
    response = await call_next(request)
    return response


@app.middleware("http")
async def no_cache(request: Request, call_next):
    # 개발 중 화면(static/index.html)을 자주 바꾸는데, 브라우저가 캐시해서 옛날 버전을 계속 보여주는 문제가
    # 있었다. 내부 소규모 도구라 캐시 이득보다 "새로고침해도 항상 최신"이 더 중요해서 캐시를 아예 끈다.
    response = await call_next(request)
    response.headers["Cache-Control"] = "no-store"
    return response


class SubmissionIn(BaseModel):
    team: str = ""
    name: str = ""
    fields: Dict[str, Any] = {}
    locked: bool = False
    completed: bool = False
    status: str = "작성중"
    filledCount: int = 0
    totalSections: int = 0
    recommendedType: Optional[str] = None


def row_to_summary(row) -> Dict[str, Any]:
    return {
        "docId": row["doc_id"],
        "team": row["team"],
        "name": row["name"],
        "ip": row["ip"],
        "locked": bool(row["locked"]),
        "completed": bool(row["completed"]),
        "status": row["status"],
        "filledCount": row["filled_count"],
        "totalSections": row["total_sections"],
        "recommendedType": row["recommended_type"],
        "updatedAt": row["updated_at"],
        "gateReview": json.loads(row["gate_review"]) if row["gate_review"] else None,
    }


@app.get("/api/submissions")
def list_submissions(x_admin_token: str = Header(default="")):
    # 전체 현황(팀 역량 포함)은 관리자·마스터 계정만 조회
    require_admin_token(x_admin_token, {"admin", "master"})
    conn = get_db()
    rows = db_fetchall(conn,
        "SELECT * FROM submissions ORDER BY updated_at DESC"
    )
    # user_id가 있는 것들만 모아서 username을 한 번에 조회 (로그인한 적 있는 제출만 계정이 붙음 —
    # 지금 익명으로 들어온 것들은 아직 username이 없고, 나중에 그 사람이 계정을 만들어서
    # 같은 브라우저로 로그인하면 user_id가 자동으로 붙어서 여기도 채워진다)
    uids = sorted({r["user_id"] for r in rows if r["user_id"]})
    username_by_uid = {}
    if uids:
        if USE_PG:
            urows = db_fetchall(conn, "SELECT id,username FROM users WHERE id = ANY(%s)", (uids,))
        else:
            qmarks = ",".join("?" * len(uids))
            urows = db_fetchall(conn, f"SELECT id,username FROM users WHERE id IN ({qmarks})", tuple(uids))
        username_by_uid = {str(u["id"]): u["username"] for u in urows}
    conn.close()
    # 한 사람이 씨앗을 여러 개 만들 수 있어서, 여기선 doc_id 하나당 한 줄 그대로 내려준다.
    # (이름/IP로 같은 사람 것끼리 묶어서 보여주는 건 화면 쪽 dedupeByAuthor()가 한다)
    out = []
    for r in rows:
        item = row_to_summary(r)
        item["userId"] = r["user_id"]
        item["username"] = username_by_uid.get(r["user_id"]) if r["user_id"] else None
        f = json.loads(r["fields"] or "{}")
        item["gate"] = {
            "level": f.get("g_level", ""),
            "task": f.get("s1_name", ""),
            "evidence": f.get("g_evidence", ""),
            "aiResult": f.get("g_ai_result", ""),
        }
        item["lpDone"] = f.get("lp_done", [])
        item["task"] = {
            "seedName": f.get("s1_name", ""),
            "cat": f.get("s1_cat", ""),
            "target": f.get("s1_target", []),
            "hasVerify": bool(str(f.get("verify_result", "")).strip()),
            "hasRedefine": bool(str(f.get("re_core", "")).strip()),
            "hasDiag": bool(str(f.get("diag_result", "")).strip()),
        }
        out.append(item)
    return out


@app.delete("/api/admin/submissions/empty")
def delete_empty_submissions(x_admin_token: str = Header(default="")):
    """아무 항목도 안 채운(filled_count=0) 씨앗을 한 번에 지운다. (빈 테스트/이탈 기록 정리용)"""
    require_admin_token(x_admin_token, {"admin", "master"})
    conn = get_db()
    cur = db_execute(conn, "DELETE FROM submissions WHERE filled_count=0 OR filled_count IS NULL")
    conn.commit()
    conn.close()
    return {"ok": True, "deleted": cur.rowcount}


@app.delete("/api/submissions/{doc_id}")
def delete_submission(doc_id: str, x_admin_token: str = Header(default="")):
    require_admin_token(x_admin_token, {"admin", "master"})
    conn = get_db()
    q = "DELETE FROM submissions WHERE doc_id=%s" if USE_PG else "DELETE FROM submissions WHERE doc_id=?"
    cur = db_execute(conn, q, (doc_id,))
    conn.commit()
    conn.close()
    if not cur.rowcount:
        raise HTTPException(status_code=404, detail="not found")
    return {"ok": True}


@app.get("/api/submissions/{doc_id}")
def get_submission(doc_id: str):
    conn = get_db()
    row = db_fetchone(conn,
        "SELECT * FROM submissions WHERE doc_id = ?", (doc_id,)
    )
    conn.close()
    if not row:
        raise HTTPException(status_code=404, detail="not found")
    out = row_to_summary(row)
    out["fields"] = json.loads(row["fields"] or "{}")
    return out


@app.put("/api/submissions/{doc_id}")
def put_submission(doc_id: str, body: SubmissionIn, request: Request):
    conn = get_db()
    now = datetime.datetime.utcnow().isoformat()
    db_execute(conn,
        """
        INSERT INTO submissions
            (doc_id, team, name, fields, locked, completed, status,
             filled_count, total_sections, recommended_type, updated_at, ip)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(doc_id) DO UPDATE SET
            team=excluded.team,
            name=excluded.name,
            fields=excluded.fields,
            locked=excluded.locked,
            completed=excluded.completed,
            status=excluded.status,
            filled_count=excluded.filled_count,
            total_sections=excluded.total_sections,
            recommended_type=excluded.recommended_type,
            updated_at=excluded.updated_at,
            ip=excluded.ip
        """,
        (
            doc_id,
            body.team,
            body.name,
            json.dumps(body.fields, ensure_ascii=False),
            int(body.locked),
            int(body.completed),
            body.status,
            body.filledCount,
            body.totalSections,
            body.recommendedType,
            now,
            get_client_ip(request),
        ),
    )
    conn.commit()
    conn.close()
    return {"ok": True, "updatedAt": now}


class LoginIn(BaseModel):
    empId: str
    code: str


@app.post("/api/auth/login")
def login(body: LoginIn):
    role = require_role(body.empId, body.code, {"master", "admin"})
    token = make_admin_session(body.empId, role)
    return {"role": role, "token": token}


@app.post("/api/auth/logout")
def logout(x_admin_token: str = Header(default="")):
    ADMIN_SESSIONS.pop(x_admin_token or "", None)
    return {"ok": True}


def account_out(row) -> Dict[str, Any]:
    return {"empId": row["emp_id"], "role": row["role"], "name": row["name"], "createdAt": row["created_at"]}


@app.get("/api/master/accounts")
def list_accounts(x_admin_token: str = Header(default="")):
    require_admin_token(x_admin_token, {"master"})
    conn = get_db()
    rows = db_fetchall(conn, "SELECT * FROM accounts ORDER BY created_at")
    conn.close()
    return [account_out(r) for r in rows]


class AccountIn(BaseModel):
    empId: str
    code: str
    name: str = ""


@app.post("/api/master/accounts")
def add_account(body: AccountIn, x_admin_token: str = Header(default="")):
    # 마스터가 관리자 계정을 직접 만들어준다 (자유 가입이 아니라 마스터의 권한 부여)
    require_admin_token(x_admin_token, {"master"})
    emp_id = body.empId.strip()
    if not emp_id:
        raise HTTPException(status_code=400, detail="사번을 입력하세요.")
    if len(body.code) < MIN_CODE_LEN:
        raise HTTPException(status_code=400, detail=f"비밀번호는 {MIN_CODE_LEN}자 이상이어야 합니다.")
    conn = get_db()
    if db_fetchone(conn, "SELECT 1 FROM accounts WHERE emp_id=?", (emp_id,)):
        conn.close()
        raise HTTPException(status_code=400, detail="이미 있는 사번입니다.")
    db_execute(conn,
        "INSERT INTO accounts (emp_id, password_hash, role, name, created_at) VALUES (?,?,?,?,?)",
        (emp_id, hash_code(body.code), "admin", body.name, datetime.datetime.utcnow().isoformat()),
    )
    conn.commit()
    conn.close()
    return {"ok": True}


@app.delete("/api/master/accounts/{emp_id}")
def remove_account(emp_id: str, x_admin_token: str = Header(default="")):
    sess = require_admin_token(x_admin_token, {"master"})
    if emp_id == sess["emp_id"]:
        raise HTTPException(status_code=400, detail="자기 자신(마스터) 계정은 지울 수 없습니다.")
    conn = get_db()
    cur = db_execute(conn, "DELETE FROM accounts WHERE emp_id=? AND role='admin'", (emp_id,))
    conn.commit()
    conn.close()
    if not cur.rowcount:
        raise HTTPException(status_code=404, detail="관리자 계정을 찾을 수 없습니다.")
    revoke_admin_sessions(emp_id)
    return {"ok": True}


class GateReviewIn(BaseModel):
    level: str
    decision: str
    note: str = ""


@app.post("/api/admin/gate/{doc_id}")
def review_gate(doc_id: str, body: GateReviewIn, x_admin_token: str = Header(default="")):
    # 레벨 인정은 관리자·마스터만 (AI 판정은 1차 참고)
    require_admin_token(x_admin_token, {"admin", "master"})
    if body.decision not in ("인정", "보완 요청"):
        raise HTTPException(status_code=400, detail="decision은 '인정' 또는 '보완 요청'")
    review = {"level": body.level, "decision": body.decision, "note": body.note[:500],
              "at": datetime.datetime.utcnow().isoformat()}
    conn = get_db()
    cur = db_execute(conn, "UPDATE submissions SET gate_review=? WHERE doc_id=?",
                       (json.dumps(review, ensure_ascii=False), doc_id))
    conn.commit()
    conn.close()
    if not cur.rowcount:
        raise HTTPException(status_code=404, detail="not found")
    return review


class PasswordChangeIn(BaseModel):
    old: str
    new: str


@app.post("/api/account/password")
def change_password(body: PasswordChangeIn, x_admin_token: str = Header(default="")):
    # 마스터든 관리자든 자기 비밀번호는 스스로 바꾼다
    sess = require_admin_token(x_admin_token, {"master", "admin"})
    emp_id = sess["emp_id"]
    require_role(emp_id, body.old, {"master", "admin"})
    if len(body.new) < MIN_CODE_LEN:
        raise HTTPException(status_code=400, detail=f"새 비밀번호는 {MIN_CODE_LEN}자 이상이어야 합니다.")
    if body.new == body.old:
        raise HTTPException(status_code=400, detail="새 비밀번호가 기존 비밀번호와 같습니다.")
    conn = get_db()
    db_execute(conn, "UPDATE accounts SET password_hash=? WHERE emp_id=?", (hash_code(body.new), emp_id))
    conn.commit()
    conn.close()
    # 비밀번호를 바꿨으니 기존 토큰은 전부 무효화하고, 새 토큰을 하나 내려준다
    revoke_admin_sessions(emp_id)
    new_token = make_admin_session(emp_id, sess["role"])
    return {"ok": True, "token": new_token}


TAXONOMY_KEYS = set(DEFAULT_TAXONOMY.keys())


@app.get("/api/taxonomy")
def get_taxonomy():
    # 01·02 화면을 그리는 데 누구나 필요해서 로그인 없이 조회 가능
    conn = get_db()
    rows = db_fetchall(conn, "SELECT key, value FROM taxonomy")
    conn.close()
    out = dict(DEFAULT_TAXONOMY)
    for r in rows:
        out[r["key"]] = json.loads(r["value"])
    return out


class TaxonomyIn(BaseModel):
    value: Any


@app.put("/api/admin/taxonomy/{key}")
def put_taxonomy(key: str, body: TaxonomyIn, x_admin_token: str = Header(default="")):
    role = require_admin_token(x_admin_token, {"admin", "master"})["role"]
    if key not in TAXONOMY_KEYS:
        raise HTTPException(status_code=400, detail="알 수 없는 분류입니다.")
    if key == "intro_html":
        if role != "master":
            raise HTTPException(status_code=403, detail="이 항목은 마스터만 수정할 수 있습니다.")
        if not isinstance(body.value, str):
            raise HTTPException(status_code=400, detail="문자열이어야 합니다.")
    elif key == "categories":
        if not isinstance(body.value, dict) or not body.value or not all(
            isinstance(k, str) and k.strip() and isinstance(v, list) for k, v in body.value.items()
        ):
            raise HTTPException(status_code=400, detail="카테고리는 최소 1개, '이름: 세부목적' 형식이어야 합니다.")
    else:
        if not isinstance(body.value, list) or not body.value or not all(isinstance(x, str) and x.strip() for x in body.value):
            raise HTTPException(status_code=400, detail="최소 1개 이상의 항목이 있어야 합니다.")
    conn = get_db()
    db_execute(conn,
        "INSERT INTO taxonomy (key, value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, json.dumps(body.value, ensure_ascii=False)),
    )
    conn.commit()
    conn.close()
    return {"ok": True}


# ── 감자밭 (feedback) ──────────────────────────────────────────────


class FeedbackIn(BaseModel):
    nickname: str = ""
    message: str


class FeedbackUpdateIn(BaseModel):
    status: str
    admin_note: str = ""


@app.post("/api/feedback")
def create_feedback(body: FeedbackIn):
    if not (body.message or "").strip():
        raise HTTPException(status_code=400, detail="메시지를 입력하세요.")
    conn = get_db()
    now = datetime.datetime.utcnow().isoformat()
    cur = db_execute(conn,
        "INSERT INTO feedback (nickname, message, status, created_at) VALUES (?,?,?,?)",
        (body.nickname.strip() or "익명 감자", body.message.strip(), "planted", now),
    )
    if USE_PG:
        new_id = db_fetchone(conn, "SELECT lastval() AS id")["id"]
    else:
        new_id = cur.lastrowid
    conn.commit()
    conn.close()
    return {"ok": True, "id": new_id}


@app.get("/api/feedback")
def list_feedback():
    conn = get_db()
    rows = db_fetchall(conn,
        "SELECT * FROM feedback WHERE status IN ('planted','growing') ORDER BY created_at DESC"
    )
    conn.close()
    return [dict(r) for r in rows]


@app.get("/api/feedback/all")
def list_all_feedback(x_admin_token: str = Header(default="")):
    require_admin_token(x_admin_token, {"admin", "master"})
    conn = get_db()
    rows = db_fetchall(conn, "SELECT * FROM feedback ORDER BY created_at DESC")
    conn.close()
    return [dict(r) for r in rows]


@app.put("/api/feedback/{fb_id}")
def update_feedback(fb_id: int, body: FeedbackUpdateIn, x_admin_token: str = Header(default="")):
    require_admin_token(x_admin_token, {"admin", "master"})
    if body.status not in ("planted", "growing", "harvested"):
        raise HTTPException(status_code=400, detail="status는 planted/growing/harvested 중 하나여야 합니다.")
    conn = get_db()
    row = db_fetchone(conn, "SELECT * FROM feedback WHERE id=?", (fb_id,))
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="피드백을 찾을 수 없습니다.")
    reviewed_at = datetime.datetime.utcnow().isoformat() if body.status == "harvested" else row["reviewed_at"]
    db_execute(conn,
        "UPDATE feedback SET status=?, admin_note=?, reviewed_at=? WHERE id=?",
        (body.status, body.admin_note.strip(), reviewed_at, fb_id),
    )
    conn.commit()
    conn.close()
    return {"ok": True}


# ── 방문 기록 (visits) ──────────────────────────────────────────────


@app.get("/api/visits/public")
def visit_stats_public():
    """인증 없이 오늘·전체 방문 수 + 순방문자 수 반환 (UI 카운터용)"""
    conn = get_db()
    today = datetime.datetime.now(KST).strftime("%Y-%m-%d")
    total = db_fetchone(conn, "SELECT COUNT(*) AS cnt FROM visits")
    today_row = db_fetchone(conn, "SELECT COUNT(*) AS cnt FROM visits WHERE visited_at >= ?", (today,))
    uniq = db_fetchone(conn, "SELECT COUNT(DISTINCT ip) AS cnt FROM visits")
    today_uniq = db_fetchone(conn, "SELECT COUNT(DISTINCT ip) AS cnt FROM visits WHERE visited_at >= ?", (today,))
    return {
        "today": today_row["cnt"] if today_row else 0,
        "total": total["cnt"] if total else 0,
        "unique_total": uniq["cnt"] if uniq else 0,
        "unique_today": today_uniq["cnt"] if today_uniq else 0,
    }

@app.get("/api/visits/stats")
def visit_stats(x_admin_token: str = Header(default="")):
    require_admin_token(x_admin_token, {"master"})
    conn = get_db()
    today = datetime.datetime.now(KST).strftime("%Y-%m-%d")
    total = db_fetchone(conn, "SELECT COUNT(*) AS cnt FROM visits")
    total_visits = total["cnt"] if total else 0
    uniq = db_fetchone(conn, "SELECT COUNT(DISTINCT ip) AS cnt FROM visits")
    unique_ips = uniq["cnt"] if uniq else 0
    today_total = db_fetchone(conn, "SELECT COUNT(*) AS cnt FROM visits WHERE visited_at >= ?", (today,))
    today_visits = today_total["cnt"] if today_total else 0
    today_uniq = db_fetchone(conn, "SELECT COUNT(DISTINCT ip) AS cnt FROM visits WHERE visited_at >= ?", (today,))
    today_unique = today_uniq["cnt"] if today_uniq else 0
    recent_rows = db_fetchall(conn,
        "SELECT ip, user_agent, path, visited_at FROM visits ORDER BY visited_at DESC LIMIT 50"
    )
    recent = [dict(r) for r in recent_rows]
    # IP별 방문 이력 묶기
    ip_rows = db_fetchall(conn,
        "SELECT ip, COUNT(*) AS visits, MAX(visited_at) AS last_seen, MIN(visited_at) AS first_seen FROM visits GROUP BY ip ORDER BY last_seen DESC"
    )
    by_ip = [dict(r) for r in ip_rows]
    # 날짜별 방문 수 (최근 30일)
    thirty_days_ago = (datetime.datetime.utcnow() - datetime.timedelta(days=30)).strftime("%Y-%m-%d")
    if USE_PG:
        by_date_rows = db_fetchall(conn,
            "SELECT SUBSTRING(visited_at FROM 1 FOR 10) AS date, COUNT(*) AS cnt FROM visits "
            "WHERE visited_at >= ? GROUP BY SUBSTRING(visited_at FROM 1 FOR 10) ORDER BY date",
            (thirty_days_ago,)
        )
    else:
        by_date_rows = db_fetchall(conn,
            "SELECT SUBSTR(visited_at, 1, 10) AS date, COUNT(*) AS cnt FROM visits "
            "WHERE visited_at >= ? GROUP BY SUBSTR(visited_at, 1, 10) ORDER BY date",
            (thirty_days_ago,)
        )
    by_date = [dict(r) for r in by_date_rows]
    conn.close()
    return {
        "total_visits": total_visits,
        "unique_ips": unique_ips,
        "today_visits": today_visits,
        "today_unique": today_unique,
        "recent": recent,
        "by_ip": by_ip,
        "by_date": by_date,
    }


# ── 일반 유저 (이메일 기반 로그인) ──────────────────────────────────────────────

class UserRegisterIn(BaseModel):
    username: str
    password: str
    nickname: str = ""   # 비우면 서버가 감자명 자동 배정

# ── 감자명 랜덤 생성 (조합형 무한 생성) ─────────────────────────
_GAMJA_COLOR   = ["빨간","노란","초록","파란","보라","주황","하얀","까만","분홍","금빛","은빛","투명한","무지개","파릇한","누런","연두"]
_GAMJA_STATE   = ["바삭","포실","뜨끈","차가운","촉촉","고소한","달콤한","쫄깃","보들","짭짤한","매운","담백한","포근한","부드러운","탄","삶은","구운","튀긴","날"]
_GAMJA_MOOD    = ["졸린","신난","설레는","화난","멍한","지친","배고픈","뿌듯한","당황한","진지한","느긋한","조용한","활발한","엉뚱한","꼼꼼한","대담한"]
_GAMJA_SHAPE   = ["동그란","통통한","작은","큰","반쪽","쪼그란","납작한","뾰족한","길쭉한","퉁퉁한"]
_GAMJA_ACTION  = ["굴러온","솟아난","숨은","늦은","빠른","걸어온","날아온","떠내려온","심긴","캐낸"]
_GAMJA_SEASON  = ["새벽","아침","봄날","여름","가을","겨울","비오는날","맑은날","안개낀","눈오는날"]
_GAMJA_EXTRA   = ["우주","바다속","산꼭대기","지하","옥상","골목","창가","이불속","서랍속","주머니속"]

def _random_gamja_name() -> str:
    import random
    patterns = [
        lambda: random.choice(_GAMJA_COLOR) + random.choice(_GAMJA_STATE) + "감자",
        lambda: random.choice(_GAMJA_STATE) + random.choice(_GAMJA_MOOD) + "감자",
        lambda: random.choice(_GAMJA_MOOD) + "감자",
        lambda: random.choice(_GAMJA_ACTION) + "감자",
        lambda: random.choice(_GAMJA_SEASON) + random.choice(_GAMJA_STATE) + "감자",
        lambda: random.choice(_GAMJA_SHAPE) + random.choice(_GAMJA_COLOR) + "감자",
        lambda: random.choice(_GAMJA_EXTRA) + "감자",
        lambda: random.choice(_GAMJA_COLOR) + random.choice(_GAMJA_MOOD) + "감자",
        lambda: random.choice(_GAMJA_STATE) + random.choice(_GAMJA_SHAPE) + "감자",
        lambda: random.choice(_GAMJA_ACTION) + random.choice(_GAMJA_STATE) + "감자",
    ]
    return random.choice(patterns)()

def _assign_gamja_name(conn) -> str:
    """중복 없는 감자명 생성. 조합형으로 사실상 무한."""
    import random
    q = "SELECT nickname FROM users WHERE nickname=%s" if USE_PG else "SELECT nickname FROM users WHERE nickname=?"
    for _ in range(50):
        name = _random_gamja_name()
        if not db_fetchone(conn, q, (name,)):
            return name
    # 50번 충돌 시 타임스탬프 붙여서 반환
    return f"감자{int(time.time()) % 100000}"

class UserLoginIn(BaseModel):
    username: str
    password: str

class UserPasswordIn(BaseModel):
    old_password: str
    new_password: str
    nickname: str = ""

import secrets
import string

def _make_invite_code() -> str:
    chars = string.ascii_uppercase + string.digits
    return "GAMJA-" + "".join(secrets.choice(chars) for _ in range(4))

def _user_by_username(conn, username: str):
    q = "SELECT * FROM users WHERE username=%s" if USE_PG else "SELECT * FROM users WHERE username=?"
    return db_fetchone(conn, q, (username,))

def _user_by_id(conn, uid: str):
    q = "SELECT * FROM users WHERE id=%s" if USE_PG else "SELECT * FROM users WHERE id=?"
    return db_fetchone(conn, q, (uid,))

def _check_pw(row, password: str) -> bool:
    ph = row["password_hash"] if isinstance(row, dict) else row[3]
    try:
        salt_hex, digest_hex = ph.split("$")
        salt = bytes.fromhex(salt_hex)
        expected = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 200_000)
        return hmac.compare_digest(expected, bytes.fromhex(digest_hex))
    except Exception:
        return False

@app.post("/api/user/register")
def user_register(body: UserRegisterIn):
    import re as _re
    username = body.username.strip().lower()
    if not username or len(username) < 2:
        raise HTTPException(status_code=400, detail="아이디는 2자 이상이어야 해요.")
    if not _re.match(r"^[a-z0-9_]+$", username):
        raise HTTPException(status_code=400, detail="아이디는 영문 소문자, 숫자, _ 만 사용 가능해요.")
    if len(body.password) < 8:
        raise HTTPException(status_code=400, detail="비밀번호는 8자 이상이어야 해요.")
    if not any(c.isalpha() for c in body.password):
        raise HTTPException(status_code=400, detail="비밀번호에 영문자를 포함해야 해요.")
    if not any(c.isdigit() for c in body.password):
        raise HTTPException(status_code=400, detail="비밀번호에 숫자를 포함해야 해요.")
    conn = get_db()
    now = datetime.datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S")
    # 아이디 중복 확인
    if _user_by_username(conn, username):
        conn.close()
        raise HTTPException(status_code=409, detail="이미 사용 중인 아이디예요.")
    ph = hash_code(body.password)
    nick = body.nickname.strip() or _assign_gamja_name(conn)
    # 닉네임 끝이 "감자"로 끝나지 않으면 자동 추가
    if nick and not nick.endswith("감자"):
        nick = nick + "감자"
    # "감자"만 단독으로 쓰면 랜덤 배정
    if nick == "감자":
        nick = _assign_gamja_name(conn)
    plan = "free"
    placeholder_email = username + "@noemail.local"
    if USE_PG:
        cur = db_execute(conn, "INSERT INTO users (username,email,password_hash,nickname,plan,created_at,last_login_at) VALUES (%s,%s,%s,%s,%s,%s,%s) RETURNING id", (username,placeholder_email,ph,nick,plan,now,now))
        uid = str(cur.fetchone()[0])
        conn.commit()
    else:
        cur = db_execute(conn, "INSERT INTO users (username,email,password_hash,nickname,plan,created_at,last_login_at) VALUES (?,?,?,?,?,?,?)", (username,placeholder_email,ph,nick,plan,now,now))
        uid = str(cur.lastrowid)
        conn.commit()
    conn.close()
    token = make_token(uid, username, plan)
    # Discord 가입 알람 (방장 채널) + 당사자 DM
    _notify_discord(
        f"🥔 새 감자 가입!\n"
        f"**닉네임:** {nick}  |  **아이디:** `{username}`\n"
        f"*{now}*"
    )
    notify_registered(nick)
    return {"token": token, "userId": uid, "username": username, "nickname": nick, "plan": plan}

@app.post("/api/user/login")
def user_login(body: UserLoginIn):
    username = body.username.strip().lower()

    # 로그인 실패 잠금 체크 (admin과 동일 로직, 메모리 캐시)
    lock_key = f"user:{username}"
    now_ts = time.time()
    rec = _fail_cache.get(lock_key)
    if rec:
        fails, until = rec
        if until and now_ts < until:
            raise HTTPException(status_code=429, detail={"locked_seconds": int(until - now_ts) + 1})

    conn = get_db()
    row = _user_by_username(conn, username)
    if not row or not _check_pw(row, body.password):
        conn.close()
        # 실패 횟수 누적
        fails = (rec[0] if rec else 0) + 1
        if fails >= MAX_FAILS:
            _fail_cache[lock_key] = (fails, now_ts + LOCK_SECONDS)
            raise HTTPException(status_code=429, detail={"locked_seconds": LOCK_SECONDS})
        _fail_cache[lock_key] = (fails, None)
        raise HTTPException(status_code=401, detail=f"아이디 또는 비밀번호가 틀렸어요. (남은 시도 {MAX_FAILS - fails}회)")
    # 로그인 성공 → 잠금 초기화
    _fail_cache.pop(lock_key, None)
    # 비활성 계정 차단
    is_active = row["is_active"] if isinstance(row, dict) and "is_active" in row.keys() else 1
    if is_active == 0:
        conn.close()
        raise HTTPException(status_code=403, detail="접근이 제한된 계정이에요. 관리자에게 문의하세요.")
    uid = str(row["id"] if isinstance(row, dict) else row[0])
    plan = row["plan"] if isinstance(row, dict) else "free"
    nick = row["nickname"] if isinstance(row, dict) else username
    now = datetime.datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S")
    q = "UPDATE users SET last_login_at=%s WHERE id=%s" if USE_PG else "UPDATE users SET last_login_at=? WHERE id=?"
    db_execute(conn, q, (now, uid))
    if USE_PG: conn.commit()
    conn.close()
    token = make_token(uid, username, plan or "free")
    must_change = bool(row["must_change_password"]) if "must_change_password" in row.keys() else False
    return {"token": token, "userId": uid, "username": username, "nickname": nick or username, "plan": plan or "free", "mustChangePassword": must_change}

@app.put("/api/user/password")
def user_change_password(body: UserPasswordIn, authorization: str = Header(default="")):
    payload = get_current_user(authorization)
    uid = payload["sub"]
    conn = get_db()
    row = _user_by_id(conn, uid)
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="유저를 찾을 수 없어요.")
    if not _check_pw(row, body.old_password):
        conn.close()
        raise HTTPException(status_code=401, detail="현재 비밀번호가 틀렸어요.")
    if len(body.new_password) < 8 or not any(c.isalpha() for c in body.new_password) or not any(c.isdigit() for c in body.new_password):
        conn.close()
        raise HTTPException(status_code=400, detail="새 비밀번호: 8자 이상, 영문+숫자 포함해야 해요.")
    ph = hash_code(body.new_password)
    new_nick = body.nickname.strip()[:20]
    if new_nick:
        q = "UPDATE users SET password_hash=%s, nickname=%s, must_change_password=0 WHERE id=%s" if USE_PG else "UPDATE users SET password_hash=?, nickname=?, must_change_password=0 WHERE id=?"
        db_execute(conn, q, (ph, new_nick, uid))
    else:
        q = "UPDATE users SET password_hash=%s, must_change_password=0 WHERE id=%s" if USE_PG else "UPDATE users SET password_hash=?, must_change_password=0 WHERE id=?"
        db_execute(conn, q, (ph, uid))
    if USE_PG: conn.commit()
    conn.close()
    return {"ok": True, "nickname": new_nick or row["nickname"]}

class SignupRequestIn(BaseModel):
    contact: str
    contact_type: str = "kakao"  # "kakao" | "phone"
    desired_username: str
    nickname: str = ""
    note: str = ""


@app.post("/api/signup-request")
def create_signup_request(body: SignupRequestIn):
    import re as _re
    contact = body.contact.strip()[:100]
    contact_type = body.contact_type if body.contact_type in ("kakao", "phone") else "kakao"
    desired_username = body.desired_username.strip().lower()[:20]
    if not contact:
        raise HTTPException(status_code=400, detail="연락처를 입력해주세요.")
    if not desired_username or len(desired_username) < 2 or not _re.match(r"^[a-z0-9_]+$", desired_username):
        raise HTTPException(status_code=400, detail="원하는 아이디는 영문 소문자/숫자/_ 2자 이상이어야 해요.")
    conn = get_db()
    now = datetime.datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S")
    db_execute(conn, "INSERT INTO signup_requests (contact, contact_type, desired_username, nickname, note, created_at) VALUES (?,?,?,?,?,?)",
               (contact, contact_type, desired_username, body.nickname.strip()[:20], body.note.strip()[:500], now))
    conn.commit()
    conn.close()
    return {"ok": True}


@app.get("/api/admin/signup-requests")
def list_signup_requests(x_admin_token: str = Header(default="")):
    require_admin_token(x_admin_token, {"master", "admin"})
    conn = get_db()
    rows = db_fetchall(conn, "SELECT * FROM signup_requests ORDER BY created_at DESC")
    conn.close()
    return [dict(r) for r in rows]


class SignupRequestLinkIn(BaseModel):
    username: str = ""  # 빈 문자열이면 연결 해제


import random, string as _string

def _make_temp_password(length=10):
    chars = _string.ascii_letters + _string.digits
    return ''.join(random.choices(chars, k=length))


@app.put("/api/admin/signup-requests/{req_id}")
def link_signup_request(req_id: int, body: SignupRequestLinkIn, x_admin_token: str = Header(default="")):
    """연결: 가입신청자에게 실제 계정 생성. 해제(username 빈칸): 계정 비활성화."""
    require_admin_token(x_admin_token, {"master", "admin"})
    conn = get_db()

    # 신청 정보 가져오기
    req = db_fetchone(conn, "SELECT * FROM signup_requests WHERE id=?" if not USE_PG else "SELECT * FROM signup_requests WHERE id=%s", (req_id,))
    if not req:
        conn.close()
        raise HTTPException(status_code=404, detail="가입 신청을 찾을 수 없어요.")

    # 해제: 계정 비활성화
    if not body.username.strip():
        old_username = req["created_username"] if isinstance(req, dict) else req[req.keys().index("created_username") if hasattr(req, "keys") else 6]
        if old_username:
            q_deact = "UPDATE users SET is_active=0 WHERE username=%s" if USE_PG else "UPDATE users SET is_active=0 WHERE username=?"
            db_execute(conn, q_deact, (old_username,))
        q_unlink = "UPDATE signup_requests SET created_username=NULL WHERE id=%s" if USE_PG else "UPDATE signup_requests SET created_username=NULL WHERE id=?"
        db_execute(conn, q_unlink, (req_id,))
        conn.commit()
        conn.close()
        return {"ok": True, "action": "unlinked"}

    # 연결: 계정 생성
    import re as _re
    username = body.username.strip().lower()[:20]
    if not username or len(username) < 2 or not _re.match(r"^[a-z0-9_]+$", username):
        conn.close()
        raise HTTPException(status_code=400, detail="아이디는 영문 소문자/숫자/_ 2자 이상이어야 해요.")

    # 아이디 중복 확인
    q_dup = "SELECT 1 FROM users WHERE username=%s" if USE_PG else "SELECT 1 FROM users WHERE username=?"
    if db_fetchone(conn, q_dup, (username,)):
        conn.close()
        raise HTTPException(status_code=409, detail="이미 사용 중인 아이디예요.")

    req_dict = dict(req)
    nickname = req_dict.get("nickname") or username
    temp_pw = username  # 초기 비밀번호 = 아이디와 동일
    ph = hash_code(temp_pw)
    now = datetime.datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S")
    placeholder_email = username + "@noemail.local"

    if USE_PG:
        cur = db_execute(conn, "INSERT INTO users (username,email,password_hash,nickname,plan,role,is_active,must_change_password,created_at,last_login_at) VALUES (%s,%s,%s,%s,'free','seedling',1,1,%s,%s) RETURNING id",
                         (username, placeholder_email, ph, nickname, now, now))
        conn.commit()
    else:
        db_execute(conn, "INSERT INTO users (username,email,password_hash,nickname,plan,role,is_active,must_change_password,created_at,last_login_at) VALUES (?,?,?,?,'free','seedling',1,1,?,?)",
                   (username, placeholder_email, ph, nickname, now, now))

    # signup_requests에 기록
    q_link = "UPDATE signup_requests SET created_username=%s WHERE id=%s" if USE_PG else "UPDATE signup_requests SET created_username=? WHERE id=?"
    db_execute(conn, q_link, (username, req_id))
    conn.commit()
    conn.close()
    return {"ok": True, "action": "created", "username": username, "temp_password": temp_pw}


# ── 사용자 권한(role) 설정 API
VALID_ROLES = {"seedling", "l1", "l2", "l3", "l4", "l5", "mentor"}
ROLE_LABELS = {
    "seedling": "🌱 새싹감자",
    "l1": "🍊 L1 AI User",
    "l2": "🌿 L2 AI Operator",
    "l3": "🔧 L3 AI Builder",
    "l4": "⚙️ L4 AI System Builder",
    "l5": "🏗️ L5 AX Architect",
    "mentor": "⭐ 멘토",
}

class UserRoleIn(BaseModel):
    role: str

@app.put("/api/master/users/{username}/role")
def set_user_role(username: str, body: UserRoleIn, x_admin_token: str = Header(default="")):
    """사용자 권한(레벨) 설정"""
    require_admin_token(x_admin_token, {"master", "admin"})
    if body.role not in VALID_ROLES:
        raise HTTPException(status_code=400, detail=f"유효한 역할: {', '.join(VALID_ROLES)}")
    conn = get_db()
    q = "UPDATE users SET role=%s WHERE username=%s" if USE_PG else "UPDATE users SET role=? WHERE username=?"
    cur = db_execute(conn, q, (body.role, username))
    if USE_PG:
        conn.commit()
    conn.close()
    return {"ok": True, "username": username, "role": body.role, "label": ROLE_LABELS[body.role]}


@app.put("/api/master/users/{username}/reset-password")
def reset_user_password(username: str, x_admin_token: str = Header(default="")):
    """사용자 비밀번호를 아이디와 동일하게 초기화"""
    require_admin_token(x_admin_token, {"master", "admin"})
    conn = get_db()
    ph = hash_code(username)
    q = "UPDATE users SET password_hash=%s, must_change_password=1 WHERE username=%s" if USE_PG else "UPDATE users SET password_hash=?, must_change_password=1 WHERE username=?"
    db_execute(conn, q, (ph, username))
    if USE_PG: conn.commit()
    conn.close()
    return {"ok": True, "username": username, "message": "비밀번호가 아이디와 동일하게 초기화됐어요."}


@app.delete("/api/master/users/{username}")
def delete_user(username: str, x_admin_token: str = Header(default="")):
    """유저 계정 완전 삭제 (마스터 전용)"""
    require_admin_token(x_admin_token, {"master"})
    conn = get_db()
    q = "DELETE FROM users WHERE username=%s" if USE_PG else "DELETE FROM users WHERE username=?"
    cur = db_execute(conn, q, (username,))
    if USE_PG: conn.commit()
    deleted = cur.rowcount if cur else 0
    conn.close()
    if not deleted:
        raise HTTPException(status_code=404, detail="유저를 찾을 수 없어요.")
    return {"ok": True, "deleted": username}


@app.put("/api/master/users/{username}/status")
def set_user_status(username: str, body: dict, x_admin_token: str = Header(default="")):
    """유저 활성/비활성 전환 (마스터/어드민)"""
    require_admin_token(x_admin_token, {"master", "admin"})
    is_active = 1 if body.get("is_active") else 0
    conn = get_db()
    q = "UPDATE users SET is_active=%s WHERE username=%s" if USE_PG else "UPDATE users SET is_active=? WHERE username=?"
    db_execute(conn, q, (is_active, username))
    if USE_PG: conn.commit()
    conn.close()
    return {"ok": True}


@app.delete("/api/admin/signup-requests/{req_id}")
def delete_signup_request(req_id: int, x_admin_token: str = Header(default="")):
    """가입 신청 거절/삭제"""
    require_admin_token(x_admin_token, {"master", "admin"})
    conn = get_db()
    q = "DELETE FROM signup_requests WHERE id=%s" if USE_PG else "DELETE FROM signup_requests WHERE id=?"
    db_execute(conn, q, (req_id,))
    if USE_PG: conn.commit()
    conn.close()
    return {"ok": True}

@app.get("/api/master/users")
def list_users(x_admin_token: str = Header(default="")):
    """전체 일반 유저 목록 (마스터/어드민 전용)"""
    require_admin_token(x_admin_token, {"master", "admin"})
    conn = get_db()
    rows = db_fetchall(conn, "SELECT id,username,nickname,plan,role,is_active,created_at,last_login_at,discord_username,discord_thread_id FROM users ORDER BY created_at DESC")
    conn.close()
    return [dict(r) for r in rows]


class DiscordUsernameIn(BaseModel):
    discord_username: str

@app.put("/api/master/users/{username}/discord")
def set_discord_username(username: str, body: DiscordUsernameIn, x_admin_token: str = Header(default="")):
    """Discord 닉네임 연결 (마스터/어드민 전용)"""
    require_admin_token(x_admin_token, {"master", "admin"})
    conn = get_db()
    q = "UPDATE users SET discord_username=%s WHERE username=%s" if USE_PG else "UPDATE users SET discord_username=? WHERE username=?"
    db_execute(conn, q, (body.discord_username.strip(), username))
    if USE_PG: conn.commit()
    conn.close()
    return {"ok": True}


# ── 초대코드 관리 (마스터 전용)
@app.post("/api/admin/invite")
def create_invite(x_admin_token: str = Header(default="")):
    sess = require_admin_token(x_admin_token, {"master", "admin"})
    conn = get_db()
    # 고유 코드 생성
    for _ in range(10):
        code = _make_invite_code()
        q = "SELECT 1 FROM invite_codes WHERE code=%s" if USE_PG else "SELECT 1 FROM invite_codes WHERE code=?"
        if not db_fetchone(conn, q, (code,)):
            break
    expires_at = (datetime.datetime.now(KST) + datetime.timedelta(hours=24)).strftime("%Y-%m-%d %H:%M:%S")
    q2 = "INSERT INTO invite_codes (code,created_by,plan,expires_at) VALUES (%s,%s,'free',%s)" if USE_PG else          "INSERT INTO invite_codes (code,created_by,plan,expires_at) VALUES (?,?,'free',?)"
    db_execute(conn, q2, (code, sess["emp_id"], expires_at))
    if USE_PG: conn.commit()
    conn.close()
    return {"code": code, "expires_at": expires_at}

@app.get("/api/admin/invites")
def list_invites(x_admin_token: str = Header(default="")):
    require_admin_token(x_admin_token, {"master", "admin"})
    conn = get_db()
    rows = db_fetchall(conn, "SELECT * FROM invite_codes ORDER BY expires_at DESC")
    conn.close()
    now = datetime.datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S")
    return [{"code": r["code"], "plan": r["plan"], "expires_at": r["expires_at"],
             "used_at": r["used_at"], "used_by": r["used_by"],
             "status": "사용됨" if r["used_at"] else ("만료" if r["expires_at"] and r["expires_at"] < now else "유효")}
            for r in rows]


# ── 설정값 (URL, Discord 초대링크)
@app.get("/api/admin/settings")
def get_settings(x_admin_token: str = Header(default="")):
    require_admin_token(x_admin_token, {"master", "admin"})
    conn = get_db()
    rows = db_fetchall(conn, "SELECT key, value FROM settings")
    conn.close()
    return {r["key"]: r["value"] for r in rows}

class SettingsUpdate(BaseModel):
    gamja99_url: Optional[str] = None
    discord_invite: Optional[str] = None

@app.put("/api/admin/settings")
def update_settings(body: SettingsUpdate, x_admin_token: str = Header(default="")):
    require_admin_token(x_admin_token, {"master", "admin"})
    conn = get_db()
    now_str = datetime.datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S")
    updates = {k: v for k, v in body.dict().items() if v is not None}
    for k, v in updates.items():
        q = "INSERT OR REPLACE INTO settings (key,value,updated_at) VALUES (?,?,?)" if not USE_PG else \
            "INSERT INTO settings (key,value,updated_at) VALUES (%s,%s,%s) ON CONFLICT (key) DO UPDATE SET value=EXCLUDED.value, updated_at=EXCLUDED.updated_at"
        db_execute(conn, q, (k, v, now_str))
    if USE_PG:
        conn.commit()
    conn.close()
    # 사이트 URL 바뀌면 Discord 공지
    if "gamja99_url" in updates:
        new_url = updates["gamja99_url"]
        _notify_discord(f"📢 **사이트 주소가 변경됐어!**\n새 주소: {new_url}")
        notify_url_change(new_url)
    return {"ok": True, "updated": list(updates.keys())}

# ── 초대 패키지 생성 (초대코드 + 설정값 한 번에)
@app.post("/api/admin/invite-package")
def create_invite_package(x_admin_token: str = Header(default="")):
    sess = require_admin_token(x_admin_token, {"master", "admin"})
    conn = get_db()
    # 초대코드 생성
    for _ in range(10):
        code = _make_invite_code()
        q = "SELECT 1 FROM invite_codes WHERE code=?" if not USE_PG else "SELECT 1 FROM invite_codes WHERE code=%s"
        if not db_fetchone(conn, q, (code,)):
            break
    expires_at = (datetime.datetime.now(KST) + datetime.timedelta(hours=24)).strftime("%Y-%m-%d %H:%M:%S")
    q2 = "INSERT INTO invite_codes (code,created_by,plan,expires_at) VALUES (?,?,'free',?)" if not USE_PG else \
         "INSERT INTO invite_codes (code,created_by,plan,expires_at) VALUES (%s,%s,'free',%s)"
    db_execute(conn, q2, (code, sess["emp_id"], expires_at))
    if USE_PG:
        conn.commit()
    # 설정값 조회
    rows = db_fetchall(conn, "SELECT key, value FROM settings")
    conn.close()
    cfg = {r["key"]: r["value"] for r in rows}
    gamja99_url = cfg.get("gamja99_url", "https://gamja99.up.railway.app")
    discord_invite = cfg.get("discord_invite", "")
    return {
        "code": code,
        "expires_at": expires_at,
        "gamja99_url": gamja99_url,
        "discord_invite": discord_invite,
    }

@app.get("/api/user/me")
def user_me(authorization: str = Header(default="")):
    payload = get_current_user(authorization)
    conn = get_db()
    uid = payload["sub"]
    row = _user_by_id(conn, uid)
    conn.close()
    if not row:
        raise HTTPException(status_code=404, detail="유저를 찾을 수 없어요.")
    return {
        "userId": str(row["id"]),
        "username": row["username"] or "",
        "nickname": row["nickname"] or row["username"] or "",
        "plan": row["plan"] or "free",
        "planExpiresAt": row["plan_expires_at"] if "plan_expires_at" in row.keys() else None,
        "mindroom_completed_at": row["mindroom_completed_at"] if "mindroom_completed_at" in row.keys() else None,
        "discord_username": row["discord_username"] if "discord_username" in row.keys() else None,
    }

# 내 씨앗 목록 (로그인 유저용)
@app.get("/api/user/submissions")
def user_submissions(authorization: str = Header(default="")):
    payload = get_current_user(authorization)
    uid = payload["sub"]
    conn = get_db()
    if USE_PG:
        rows = db_fetchall(conn, "SELECT * FROM submissions WHERE user_id=%s ORDER BY updated_at DESC", (uid,))
    else:
        rows = db_fetchall(conn, "SELECT * FROM submissions WHERE user_id=? ORDER BY updated_at DESC", (uid,))
    out = []
    for r in rows:
        item = row_to_summary(r)
        item["seedName"] = json.loads(r["fields"] or "{}").get("s1_name", "")
        out.append(item)
    return out

# 씨앗 저장 시 user_id 연결 (기존 PUT에 user_id 추가)
# → 기존 /api/submissions/{doc_id} PUT에서 토큰 있으면 user_id 저장
@app.put("/api/user/submissions/{doc_id}")
def put_user_submission(doc_id: str, body: "SubmissionIn", request: Request, authorization: str = Header(default="")):
    """로그인 유저의 씨앗 저장 — user_id 자동 연결"""
    payload = get_current_user(authorization)
    uid = payload["sub"]
    ip = get_client_ip(request)
    conn = get_db()
    now = datetime.datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S")
    fields_json = json.dumps(body.fields, ensure_ascii=False)
    if USE_PG:
        db_execute(conn, """
            INSERT INTO submissions (doc_id,team,name,fields,locked,completed,status,filled_count,total_sections,recommended_type,updated_at,user_id,ip)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT(doc_id) DO UPDATE SET
                team=EXCLUDED.team, name=EXCLUDED.name, fields=EXCLUDED.fields,
                locked=EXCLUDED.locked, completed=EXCLUDED.completed, status=EXCLUDED.status,
                filled_count=EXCLUDED.filled_count, total_sections=EXCLUDED.total_sections,
                recommended_type=EXCLUDED.recommended_type, updated_at=EXCLUDED.updated_at,
                user_id=EXCLUDED.user_id, ip=EXCLUDED.ip
        """, (doc_id, body.team, body.name, fields_json, body.locked, body.completed, body.status,
              body.filledCount, body.totalSections, body.recommendedType, now, uid, ip))
        conn.commit()
    else:
        db_execute(conn, """
            INSERT INTO submissions (doc_id,team,name,fields,locked,completed,status,filled_count,total_sections,recommended_type,updated_at,user_id,ip)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(doc_id) DO UPDATE SET
                team=excluded.team, name=excluded.name, fields=excluded.fields,
                locked=excluded.locked, completed=excluded.completed, status=excluded.status,
                filled_count=excluded.filled_count, total_sections=excluded.total_sections,
                recommended_type=excluded.recommended_type, updated_at=excluded.updated_at,
                user_id=excluded.user_id, ip=excluded.ip
        """, (doc_id, body.team, body.name, fields_json, body.locked, body.completed, body.status,
              body.filledCount, body.totalSections, body.recommendedType, now, uid, ip))
    return {"ok": True}

# 관리자: 유저 목록 + 씨앗 현황
@app.get("/api/admin/users")
def admin_users(x_admin_token: str = Header(default="")):
    require_admin_token(x_admin_token, {"admin", "master"})
    conn = get_db()
    users = db_fetchall(conn, "SELECT id,username,email,nickname,plan,plan_expires_at,created_at,last_login_at,must_change_password FROM users ORDER BY created_at DESC")
    result = []
    for u in users:
        uid = str(u["id"])
        if USE_PG:
            seeds = db_fetchall(conn, "SELECT doc_id,status,filled_count,completed,updated_at FROM submissions WHERE user_id=%s", (uid,))
        else:
            seeds = db_fetchall(conn, "SELECT doc_id,status,filled_count,completed,updated_at FROM submissions WHERE user_id=?", (uid,))
        result.append({
            "id": uid, "username": u["username"], "email": u["email"], "nickname": u["nickname"],
            "plan": u["plan"], "planExpiresAt": u["plan_expires_at"],
            "createdAt": u["created_at"], "lastLoginAt": u["last_login_at"],
            "mustChangePassword": bool(u["must_change_password"]),
            "seedCount": len(seeds),
            "seeds": [{"docId": s["doc_id"], "status": s["status"], "filledCount": s["filled_count"], "completed": bool(s["completed"]), "updatedAt": s["updated_at"]} for s in seeds]
        })
    return result


class AdminCreateUserIn(BaseModel):
    username: str
    nickname: str = ""


@app.post("/api/admin/users/create")
def admin_create_user(body: AdminCreateUserIn, x_admin_token: str = Header(default="")):
    """관리자가 학생/구직자용 계정을 직접 만든다. 아이디=초기 비밀번호로 만들고,
    최초 로그인 시 비밀번호를 바꾸도록 강제한다 (카톡 등으로 아이디·비번을 전달하는 용도)."""
    require_admin_token(x_admin_token, {"admin", "master"})
    import re as _re
    username = body.username.strip().lower()
    if not username or len(username) < 2 or not _re.match(r"^[a-z0-9_]+$", username):
        raise HTTPException(status_code=400, detail="아이디는 영문 소문자/숫자/_ 2자 이상이어야 해요.")
    conn = get_db()
    if _user_by_username(conn, username):
        conn.close()
        raise HTTPException(status_code=409, detail="이미 사용 중인 아이디예요.")
    now = datetime.datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S")
    ph = hash_code(username)  # 초기 비번 = 아이디
    nick = body.nickname.strip() or username
    placeholder_email = username + "@noemail.local"  # email이 NOT NULL/UNIQUE인 옛 스키마 대비 — 실제 이메일 안 씀
    if USE_PG:
        cur = db_execute(conn, "INSERT INTO users (username,email,password_hash,nickname,plan,created_at,must_change_password) VALUES (%s,%s,%s,%s,'free',%s,1) RETURNING id", (username, placeholder_email, ph, nick, now))
        uid = str(cur.fetchone()[0])
        conn.commit()
    else:
        cur = db_execute(conn, "INSERT INTO users (username,email,password_hash,nickname,plan,created_at,must_change_password) VALUES (?,?,?,?,'free',?,1)", (username, placeholder_email, ph, nick, now))
        uid = str(cur.lastrowid)
        conn.commit()
    conn.close()
    return {"ok": True, "username": username, "password": username, "userId": uid}


class AdminDeleteUserIn(BaseModel):
    password: str  # 관리자 본인 비밀번호 재확인


@app.delete("/api/admin/users/{user_id}")
def admin_delete_user(user_id: str, body: AdminDeleteUserIn, x_admin_token: str = Header(default="")):
    """학생/구직자 계정 삭제. 되돌릴 수 없는 작업이라 관리자 본인 비밀번호를 다시 확인한다.
    (씨앗 데이터는 지우지 않고 남겨둔다 — user_id가 끊어질 뿐)"""
    sess = require_admin_token(x_admin_token, {"admin", "master"})
    require_role(sess["emp_id"], body.password, {"admin", "master"})  # 틀리면 여기서 403/429
    conn = get_db()
    q = "DELETE FROM users WHERE id=%s" if USE_PG else "DELETE FROM users WHERE id=?"
    cur = db_execute(conn, q, (user_id,))
    conn.commit()
    conn.close()
    if not cur.rowcount:
        raise HTTPException(status_code=404, detail="계정을 찾을 수 없습니다.")
    return {"ok": True}


# ── 방명록 (guestbook) ──────────────────────────────────────────────
class GuestbookIn(BaseModel):
    nickname: str = ""
    message: str

@app.post("/api/guestbook")
def create_guestbook(body: GuestbookIn):
    v = validate_text(body.message)
    if not v["ok"]: raise HTTPException(status_code=400, detail=v["msg"])
    now = datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S")
    conn = get_conn()
    if USE_PG:
        db_execute(conn, "INSERT INTO guestbook (nickname, message, created_at) VALUES (%s,%s,%s)",
                   (body.nickname.strip() or "익명", body.message.strip(), now))
    else:
        db_execute(conn, "INSERT INTO guestbook (nickname, message, created_at) VALUES (?,?,?)",
                   (body.nickname.strip() or "익명", body.message.strip(), now))
    return {"ok": True}

@app.get("/api/guestbook")
def list_guestbook():
    conn = get_conn()
    rows = db_fetchall(conn, "SELECT * FROM guestbook ORDER BY created_at DESC")
    return [dict(r) for r in rows]


# ── AI 적합성 자동 판정 ──────────────────────────────────────────

class JudgeIn(BaseModel):
    text: str          # 문제 설명 (씨앗이름 + 자유텍스트 등)
    api_key: str = ""  # 사용자 본인 Claude API 키 (없으면 키워드 판정)
    has_plan: bool = False  # 핵심 문제·해결 방향 가설이 이미 구조화되어 있는지

@app.post("/api/discover/judge")
def discover_judge(body: JudgeIn):
    """
    AI 적합성 자동 판정.
    api_key 있으면 Claude API 호출, 없으면 키워드 기반 판정.
    반환: {judgment: 'possible'|'redefine'|'unnecessary', reason: str, method: 'ai'|'keyword'}
    """
    text = (body.text or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="판정할 내용을 입력해줘요.")

    # ── Claude API 판정 ──────────────────────────────────────────
    if body.api_key.strip():
        try:
            import urllib.request as _urllib
            import json as _json
            plan_note = (
                "\n\n참고: 이 문제는 핵심 문제와 해결 방향 가설까지 이미 구체화되어 있어요. "
                "막연하다는 이유로 'redefine'을 주지 마세요." if body.has_plan else ""
            )
            prompt = (
                "아래 업무/문제가 AI 도구 활용에 적합한지 판단해줘.\n\n"
                f"문제: {text}{plan_note}\n\n"
                "아래 JSON 형식으로만 답해줘 (설명 없이):\n"
                '{"judgment": "possible" | "redefine" | "unnecessary", "reason": "2~3줄 이유"}\n\n'
                "판단 기준:\n"
                "- possible: AI가 실질적으로 도움 될 수 있음\n"
                "- redefine: 문제가 너무 막연하거나 더 명확히 해야 함\n"
                "- unnecessary: AI보다 더 나은 방법이 있거나 AI가 필요 없음"
            )
            payload = _json.dumps({
                "model": "claude-haiku-4-5",
                "max_tokens": 256,
                "messages": [{"role": "user", "content": prompt}]
            }).encode()
            req = _urllib.Request(
                "https://api.anthropic.com/v1/messages",
                data=payload,
                headers={
                    "x-api-key": body.api_key.strip(),
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json"
                }
            )
            with _urllib.urlopen(req, timeout=15) as res:
                data = _json.loads(res.read().decode())
            raw = data["content"][0]["text"].strip()
            # JSON 파싱
            start = raw.find("{")
            end = raw.rfind("}") + 1
            result = _json.loads(raw[start:end])
            judgment = result.get("judgment", "redefine")
            if judgment not in ("possible", "redefine", "unnecessary"):
                judgment = "redefine"
            return {"judgment": judgment, "reason": result.get("reason", ""), "method": "ai"}
        except Exception as e:
            # API 실패 시 키워드 판정으로 폴백
            pass

    # ── 키워드 기반 판정 ─────────────────────────────────────────
    t = text.lower()

    possible_kw = ["반복", "매번", "자동화", "자동", "주기", "시간이", "오래", "귀찮", "매일", "매주",
                   "엑셀", "취합", "정리", "분류", "요약", "번역", "초안", "작성", "검색", "분석",
                   "보고서", "자소서", "피드백", "코드", "수행평가", "아이디어"]
    redefine_kw = ["모르겠", "뭘해야", "막막", "어떻게", "뭔가", "잘 모", "어디서", "무엇을",
                   "뭐부터", "어떤걸", "막연", "뭐가", "처음"]
    unnecessary_kw = ["그냥", "간단", "쉬운", "쉽게", "직접", "말로", "전화", "대화", "회의",
                      "관계", "감정", "설득", "협의"]

    def score(kws):
        return sum(1 for k in kws if k in t)

    s_possible = score(possible_kw)
    s_redefine = score(redefine_kw)
    s_unnecessary = score(unnecessary_kw)

    if body.has_plan:
        # 핵심 문제·해결 방향 가설이 이미 구조화돼 있으면 "막연함" 키워드만으로 재정의를 요구하지 않음
        judgment = "possible"
        reason = "핵심 문제와 해결 방향까지 이미 구체화되어 있어요. 이대로 진행해도 돼요."
    elif s_redefine > s_possible and s_redefine > s_unnecessary:
        judgment = "redefine"
        reason = "문제가 아직 막연해요. 구체적으로 어떤 상황인지, 어떤 결과를 원하는지 더 적어줘요."
    elif s_unnecessary > s_possible:
        judgment = "unnecessary"
        reason = "AI보다 더 빠른 방법이 있을 수 있어요. 직접 대화나 간단한 도구로 해결되는지 먼저 확인해봐요."
    elif s_possible > 0:
        judgment = "possible"
        reason = "반복적이거나 정형화된 작업이 있어서 AI가 도움 될 수 있어요."
    else:
        judgment = "redefine"
        reason = "조금 더 구체적으로 어떤 문제를 해결하고 싶은지 적어줘요."

    return {"judgment": judgment, "reason": reason, "method": "keyword"}

# 정적 프론트엔드 서빙은 파일 맨 끝에 (API 라우트 모두 등록 후)
# 여기 있으면 아래에 정의된 API들을 StaticFiles가 가로챔 — 삭제 후 맨 끝으로 이동


def _run_discord_bot():
    """Discord 봇을 별도 스레드에서 실행"""
    token = os.getenv("DISCORD_BOT_TOKEN", "")
    if not token:
        print("[bot] DISCORD_BOT_TOKEN 없음 — 봇 비활성화")
        return
    try:
        import bot as discord_bot
        discord_bot.bot.run(token)
    except Exception as e:
        print(f"[bot] 실행 오류: {e}")




# ── 씨앗 Discord 공유 ──────────────────────────────────────────────────────
SEED_SHARE_CH = "1556104705304690768"  # 씨앗정의서-공유 포럼
GUILD_ID      = "1555788463247466566"  # 감자밭 서버
SEEDLING_ROLE = "1555811319477964871"  # 새싹감자 역할


def _discord_post(path: str, body: dict):
    """봇 토큰으로 Discord API POST"""
    import urllib.request, urllib.error
    token = os.environ.get("DISCORD_BOT_TOKEN", "")
    if not token:
        return None, "DISCORD_BOT_TOKEN 없음"
    url = f"https://discord.com/api/v10{path}"
    req = urllib.request.Request(url, data=json.dumps(body).encode(), headers={
        "Authorization": f"Bot {token}",
        "Content-Type": "application/json",
        "User-Agent": "DiscordBot (https://gamja99.up.railway.app, 1.0)"
    }, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.loads(r.read().decode()), None
    except urllib.error.HTTPError as e:
        return None, e.read().decode()


def _discord_patch(path: str, body: dict):
    """봇 토큰으로 Discord API PATCH"""
    import urllib.request, urllib.error
    token = os.environ.get("DISCORD_BOT_TOKEN", "")
    if not token:
        return None, "DISCORD_BOT_TOKEN 없음"
    url = f"https://discord.com/api/v10{path}"
    req = urllib.request.Request(url, data=json.dumps(body).encode(), headers={
        "Authorization": f"Bot {token}",
        "Content-Type": "application/json",
        "User-Agent": "DiscordBot (https://gamja99.up.railway.app, 1.0)"
    }, method="PATCH")
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.loads(r.read().decode()), None
    except urllib.error.HTTPError as e:
        return None, e.read().decode()


def _discord_give_role(discord_username: str, role_id: str) -> bool:
    """Discord 유저에게 역할 부여 (닉네임으로 멤버 검색 후 PUT)"""
    import urllib.request, urllib.error
    token = os.environ.get("DISCORD_BOT_TOKEN", "")
    if not token or not discord_username:
        return False
    # 서버 멤버 검색
    url = f"https://discord.com/api/v10/guilds/{GUILD_ID}/members/search?query={urllib.parse.quote(discord_username)}&limit=5"
    req = urllib.request.Request(url, headers={
        "Authorization": f"Bot {token}",
        "User-Agent": "DiscordBot (https://gamja99.up.railway.app, 1.0)"
    })
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            members = json.loads(r.read().decode())
    except Exception:
        return False
    # 닉네임 정확히 일치하는 멤버 찾기
    member = next((m for m in members
                   if (m.get("nick") or m.get("user",{}).get("global_name","") or m.get("user",{}).get("username","")).lower()
                      == discord_username.lower()), None)
    if not member:
        return False
    user_id = member["user"]["id"]
    # 역할 부여 PUT
    put_url = f"https://discord.com/api/v10/guilds/{GUILD_ID}/members/{user_id}/roles/{role_id}"
    put_req = urllib.request.Request(put_url, data=b"", headers={
        "Authorization": f"Bot {token}",
        "Content-Type": "application/json",
        "User-Agent": "DiscordBot (https://gamja99.up.railway.app, 1.0)"
    }, method="PUT")
    try:
        urllib.request.urlopen(put_req, timeout=10)
        return True
    except Exception:
        return False


def _discord_create_thread(forum_ch: str, title: str, content: str) -> tuple[str | None, str | None]:
    """포럼 채널에 새 스레드(포스트) 생성. (thread_id, error) 반환"""
    data, err = _discord_post(f"/channels/{forum_ch}/threads", {
        "name": title[:100],
        "message": {"content": content[:2000]},
        "auto_archive_duration": 10080  # 7일
    })
    if err:
        return None, err
    return data.get("id"), None


def _discord_add_comment(thread_id: str, content: str) -> bool:
    """스레드에 댓글(메시지) 추가"""
    _, err = _discord_post(f"/channels/{thread_id}/messages", {"content": content[:2000]})
    return err is None

class SeedShareIn(BaseModel):
    seed_name: str
    problem: str
    ai_goal: str
    blocker: str = ""


# ── 마음의 방 완성 ───────────────────────────────────────────────────────────
class MindroomCompleteIn(BaseModel):
    summary: str = ""   # 마음의 방 내용 요약 (Discord 게시용)

@app.post("/api/user/mindroom/complete")
def mindroom_complete(body: MindroomCompleteIn, x_token: str = Header(default="")):
    """마음의 방 완성 처리: LV1 달성 + Discord 새싹감자 부여 + 스레드 생성"""
    user = require_user_token(x_token)
    conn = get_db()
    row = db_fetchone(conn,
        "SELECT nickname, discord_username, discord_thread_id, mindroom_completed_at FROM users WHERE username=%s" if USE_PG
        else "SELECT nickname, discord_username, discord_thread_id, mindroom_completed_at FROM users WHERE username=?",
        (user["username"],))

    nick = (row["nickname"] if row else None) or user["username"]
    discord_uname = row["discord_username"] if row else None
    existing_thread = row["discord_thread_id"] if row else None
    already_done = bool(row["mindroom_completed_at"] if row else None)

    result = {"ok": True, "already_done": already_done, "role_given": False, "thread_id": existing_thread}

    # 완성 시각 기록
    now_str = datetime.datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S")
    q = "UPDATE users SET mindroom_completed_at=%s WHERE username=%s" if USE_PG \
        else "UPDATE users SET mindroom_completed_at=? WHERE username=?"
    db_execute(conn, q, (now_str, user["username"]))
    if USE_PG: conn.commit()

    # Discord 새싹감자 역할 부여 (연결돼 있으면)
    if discord_uname and not already_done:
        import threading
        def _give():
            ok = _discord_give_role(discord_uname, SEEDLING_ROLE)
            result["role_given"] = ok
        t = threading.Thread(target=_give, daemon=True)
        t.start()
        t.join(timeout=8)

    # Discord 스레드 생성 (아직 없으면)
    if not existing_thread and discord_uname:
        summary_text = body.summary[:500] if body.summary else "(내용 없음)"
        title = f"🏠 {nick}의 마음의 방"
        content = (
            f"**🏠 {nick}의 마음의 방 완성!**\n\n"
            f"{summary_text}\n\n"
            f"_이 스레드는 {nick}님의 성장 이력입니다. 씨앗 정의 → 진행 → 완료가 여기 쌓여요._"
        )
        thread_id, err = _discord_create_thread(SEED_SHARE_CH, title, content)
        if thread_id:
            q2 = "UPDATE users SET discord_thread_id=%s WHERE username=%s" if USE_PG \
                 else "UPDATE users SET discord_thread_id=? WHERE username=?"
            db_execute(conn, q2, (thread_id, user["username"]))
            if USE_PG: conn.commit()
            result["thread_id"] = thread_id
    elif existing_thread and not already_done:
        # 이미 스레드 있으면 완성 댓글만
        summary_text = body.summary[:500] if body.summary else ""
        msg = f"**🏠 마음의 방 완성** ({now_str[:10]})"
        if summary_text:
            msg += f"\n{summary_text}"
        _discord_add_comment(existing_thread, msg)

    conn.close()
    return result


# ── 씨앗 Discord 스레드 생성 (씨앗별 새 스레드) ─────────────────────────────
class SeedThreadIn(BaseModel):
    doc_id: str
    title: str           # 씨앗 제목 (짧게)
    problem: str         # 해결하고 싶은 문제
    ai_goal: str         # AI로 하고 싶은 것
    prompt: str = ""     # 자동생성 or 직접 입력 프롬프트
    blocker: str = ""

@app.post("/api/seed/thread")
def seed_create_thread(body: SeedThreadIn, x_token: str = Header(default="")):
    """씨앗 정의 완성 → Discord 새 스레드 생성"""
    user = require_user_token(x_token)
    conn = get_db()
    row = db_fetchone(conn,
        "SELECT nickname, discord_username FROM users WHERE username=%s" if USE_PG
        else "SELECT nickname, discord_username FROM users WHERE username=?",
        (user["username"],))
    nick = (row["nickname"] if row else None) or user["username"]
    discord_uname = row["discord_username"] if row else None

    if not discord_uname:
        conn.close()
        return {"ok": False, "reason": "Discord 계정이 연결되지 않았어요."}

    title = f"🌱 {nick} — {body.title[:40]}"
    content = (
        f"**🌱 {nick}의 씨앗 정의**\n\n"
        f"**문제:** {body.problem}\n"
        f"**AI 목표:** {body.ai_goal}\n"
    )
    if body.blocker:
        content += f"**막히는 것:** {body.blocker}\n"
    if body.prompt:
        content += f"\n**📋 프롬프트:**\n```\n{body.prompt[:800]}\n```"

    thread_id, err = _discord_create_thread(SEED_SHARE_CH, title, content)
    if err or not thread_id:
        conn.close()
        return {"ok": False, "reason": err or "스레드 생성 실패"}

    # submissions에 discord_thread_id 저장
    q = "UPDATE submissions SET discord_thread_id=%s WHERE doc_id=%s" if USE_PG \
        else "UPDATE submissions SET discord_thread_id=? WHERE doc_id=?"
    db_execute(conn, q, (thread_id, body.doc_id))
    if USE_PG: conn.commit()
    conn.close()
    return {"ok": True, "thread_id": thread_id}


# ── 씨앗 업데이트 / 완료 댓글 ────────────────────────────────────────────────
class SeedCommentIn(BaseModel):
    doc_id: str
    content: str
    update_type: str = "update"  # "update" | "complete"

@app.post("/api/seed/comment")
def seed_add_comment(body: SeedCommentIn, x_token: str = Header(default="")):
    """씨앗 스레드에 업데이트/완료 댓글 추가"""
    user = require_user_token(x_token)
    conn = get_db()
    row = db_fetchone(conn,
        "SELECT discord_thread_id FROM submissions WHERE doc_id=%s" if USE_PG
        else "SELECT discord_thread_id FROM submissions WHERE doc_id=?",
        (body.doc_id,))
    conn.close()

    if not row or not row["discord_thread_id"]:
        return {"ok": False, "reason": "Discord 스레드가 없어요. 씨앗을 먼저 공유해주세요."}

    prefix = "✅ **완료!**" if body.update_type == "complete" else "📝 **업데이트**"
    msg = f"{prefix}\n{body.content[:1500]}"
    ok = _discord_add_comment(row["discord_thread_id"], msg)
    return {"ok": ok}


# ── 마음의 방 서버 저장/불러오기 ──────────────────────────────
class IntroDataIn(BaseModel):
    data: dict  # {intro_freetext, intro_ai_result, intro_saved, ...}

@app.put("/api/user/intro")
def save_intro(body: IntroDataIn, x_token: str = Header(default="")):
    """마음의 방 데이터 서버 저장"""
    user = require_user_token(x_token)
    conn = get_db()
    q = "UPDATE users SET intro_data=%s WHERE username=%s" if USE_PG else "UPDATE users SET intro_data=? WHERE username=?"
    db_execute(conn, q, (json.dumps(body.data, ensure_ascii=False), user["username"]))
    if USE_PG: conn.commit()
    conn.close()
    return {"ok": True}

@app.get("/api/user/intro")
def load_intro(x_token: str = Header(default="")):
    """마음의 방 데이터 불러오기"""
    user = require_user_token(x_token)
    conn = get_db()
    row = db_fetchone(conn, "SELECT intro_data FROM users WHERE username=?" if not USE_PG
                     else "SELECT intro_data FROM users WHERE username=%s", (user["username"],))
    conn.close()
    if not row or not row["intro_data"]:
        return {"data": {}}
    return {"data": json.loads(row["intro_data"])}


# ── 심기 전 준비 저장/불러오기 ──────────────────────────────
@app.put("/api/user/discover")
def save_discover(body: IntroDataIn, x_token: str = Header(default="")):
    """심기 전 준비 판정 결과 서버 저장"""
    user = require_user_token(x_token)
    conn = get_db()
    q = "UPDATE users SET discover_data=%s WHERE username=%s" if USE_PG else "UPDATE users SET discover_data=? WHERE username=?"
    db_execute(conn, q, (json.dumps(body.data, ensure_ascii=False), user["username"]))
    if USE_PG: conn.commit()
    conn.close()
    return {"ok": True}

@app.get("/api/user/discover")
def load_discover(x_token: str = Header(default="")):
    """심기 전 준비 판정 결과 불러오기"""
    user = require_user_token(x_token)
    conn = get_db()
    row = db_fetchone(conn, "SELECT discover_data FROM users WHERE username=?" if not USE_PG
                     else "SELECT discover_data FROM users WHERE username=%s", (user["username"],))
    conn.close()
    if not row or not row["discover_data"]:
        return {"data": {}}
    return {"data": json.loads(row["discover_data"])}

class SeedUpdateIn(BaseModel):
    content: str
    update_type: str = "update"  # update | complete | new_seed

@app.post("/api/seed/share")
def seed_share(body: SeedShareIn, x_token: str = Header(default="")):
    """씨앗 첫 공유 — Discord 스레드 생성"""
    user = require_user_token(x_token)
    conn = get_db()
    row = db_fetchone(conn, "SELECT discord_username, discord_thread_id FROM users WHERE username=?" if not USE_PG
                     else "SELECT discord_username, discord_thread_id FROM users WHERE username=%s", (user["username"],))

    display_name = (row["discord_username"] or user["username"]) if row else user["username"]
    existing_thread = row["discord_thread_id"] if row else None

    if existing_thread:
        conn.close()
        return {"ok": True, "thread_id": existing_thread, "reused": True}

    from datetime import datetime
    today = datetime.now().strftime("%Y.%m.%d")
    content = (
        f"🌱 **{display_name}님의 감자밭 이력**\n\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"**[{today}] 씨앗 1호 시작**\n\n"
        f"**씨앗 이름:** {body.seed_name}\n"
        f"**해결하고 싶은 것:** {body.problem}\n"
        f"**AI로 하려는 것:** {body.ai_goal}\n"
        + (f"**막히는 지점:** {body.blocker}\n" if body.blocker else "") +
        f"\n👀 피드백 환영해요!"
    )
    data, err = _discord_post(f"/channels/{SEED_SHARE_CH}/threads", {
        "name": f"🌱 {display_name}님의 감자밭",
        "message": {"content": content}
    })
    if err or not data:
        conn.close()
        raise HTTPException(status_code=500, detail=f"Discord 오류: {err}")

    thread_id = data["id"]
    q = "UPDATE users SET discord_thread_id=%s WHERE username=%s" if USE_PG else "UPDATE users SET discord_thread_id=? WHERE username=?"
    db_execute(conn, q, (thread_id, user["username"]))
    if USE_PG: conn.commit()
    conn.close()
    return {"ok": True, "thread_id": thread_id, "reused": False}


@app.post("/api/seed/update")
def seed_update(body: SeedUpdateIn, x_token: str = Header(default="")):
    """씨앗 업데이트/완료/새 씨앗 댓글"""
    user = require_user_token(x_token)
    conn = get_db()
    row = db_fetchone(conn, "SELECT discord_thread_id FROM users WHERE username=?" if not USE_PG
                     else "SELECT discord_thread_id FROM users WHERE username=%s", (user["username"],))
    conn.close()

    if not row or not row["discord_thread_id"]:
        raise HTTPException(status_code=400, detail="먼저 씨앗 공유를 해주세요")

    thread_id = row["discord_thread_id"]
    from datetime import datetime
    today = datetime.now().strftime("%Y.%m.%d")

    icons = {"update": "🔄", "complete": "✅", "new_seed": "🌱"}
    labels = {"update": "업데이트", "complete": "완료!", "new_seed": "새 씨앗 시작"}
    icon = icons.get(body.update_type, "🔄")
    label = labels.get(body.update_type, "업데이트")

    content = f"**[{today}] {icon} {label}**\n\n{body.content}"
    _, err = _discord_post(f"/channels/{thread_id}/messages", {"content": content})
    if err:
        raise HTTPException(status_code=500, detail=f"Discord 오류: {err}")
    return {"ok": True}


if __name__ == "__main__":
    import uvicorn
    import threading

    # Discord 봇 백그라운드 실행
    bot_thread = threading.Thread(target=_run_discord_bot, daemon=True)
    bot_thread.start()
    print("[main] Discord 봇 스레드 시작됨")

    uvicorn.run(app, host="0.0.0.0", port=8000)

# ── 정적 프론트엔드 서빙 — 반드시 모든 API 라우트 정의 후 마지막에 ──
app.mount("/", StaticFiles(directory=os.path.join(APP_DIR, "static"), html=True), name="static")
