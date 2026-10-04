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

# 관리자 로그인 세션 (토큰 -> {emp_id, role}). 비밀번호를 매 요청마다
# 보내지 않고, 로그인 1회로 만든 토큰만 보내게 하기 위한 저장소.
# 시간 만료는 없음 — 로그아웃, 비밀번호 변경, 계정 삭제로만 무효화된다.
# ponytail: 메모리 보관이라 서버를 다시 켜면 전부 로그아웃됨. 여러 서버로 늘리면 DB/Redis로 교체
ADMIN_SESSIONS: Dict[str, dict] = {}


def make_admin_session(emp_id: str, role: str) -> str:
    token = secrets.token_hex(32)
    ADMIN_SESSIONS[token] = {"emp_id": emp_id, "role": role}
    return token


def revoke_admin_sessions(emp_id: str):
    for t in [t for t, s in ADMIN_SESSIONS.items() if s["emp_id"] == emp_id]:
        ADMIN_SESSIONS.pop(t, None)


def require_admin_token(token: str, allowed: set) -> dict:
    sess = ADMIN_SESSIONS.get(token or "")
    if not sess:
        raise HTTPException(status_code=401, detail="로그인이 필요해요. 다시 로그인해주세요.")
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

app = FastAPI(title="ddugi Project")


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
    conn.close()
    # 한 사람이 씨앗을 여러 개 만들 수 있어서, 여기선 doc_id 하나당 한 줄 그대로 내려준다.
    # (이름/IP로 같은 사람 것끼리 묶어서 보여주는 건 화면 쪽 dedupeByAuthor()가 한다)
    out = []
    for r in rows:
        item = row_to_summary(r)
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
    nickname: str = ""
    invite_code: str = ""

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
    # 초대코드 검증
    invite_code = body.invite_code.strip().upper()
    if not invite_code:
        raise HTTPException(status_code=400, detail="초대코드를 입력해주세요.")
    conn = get_db()
    now = datetime.datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S")
    q = "SELECT * FROM invite_codes WHERE code=%s" if USE_PG else "SELECT * FROM invite_codes WHERE code=?"
    inv = db_fetchone(conn, q, (invite_code,))
    if not inv:
        conn.close()
        raise HTTPException(status_code=400, detail="유효하지 않은 초대코드예요.")
    if inv["used_at"]:
        conn.close()
        raise HTTPException(status_code=400, detail="이미 사용된 초대코드예요.")
    if inv["expires_at"] and inv["expires_at"] < now:
        conn.close()
        raise HTTPException(status_code=400, detail="만료된 초대코드예요. 새 코드를 요청해주세요.")
    # 아이디 중복 확인
    if _user_by_username(conn, username):
        conn.close()
        raise HTTPException(status_code=409, detail="이미 사용 중인 아이디예요.")
    ph = hash_code(body.password)
    nick = body.nickname.strip() or username
    plan = inv["plan"] if isinstance(inv, dict) else "free"
    if USE_PG:
        cur = db_execute(conn, "INSERT INTO users (username,password_hash,nickname,plan,created_at,last_login_at) VALUES (%s,%s,%s,%s,%s,%s) RETURNING id", (username,ph,nick,plan,now,now))
        uid = str(cur.fetchone()[0])
        conn.commit()
    else:
        cur = db_execute(conn, "INSERT INTO users (username,password_hash,nickname,plan,created_at,last_login_at) VALUES (?,?,?,?,?,?)", (username,ph,nick,plan,now,now))
        uid = str(cur.lastrowid)
    # 초대코드 사용 처리
    q2 = "UPDATE invite_codes SET used_at=%s,used_by=%s WHERE code=%s" if USE_PG else "UPDATE invite_codes SET used_at=?,used_by=? WHERE code=?"
    db_execute(conn, q2, (now, uid, invite_code))
    if USE_PG:
        conn.commit()
    else:
        conn.commit()
    conn.close()
    token = make_token(uid, username, plan)
    return {"token": token, "userId": uid, "username": username, "nickname": nick, "plan": plan}

@app.post("/api/user/login")
def user_login(body: UserLoginIn):
    username = body.username.strip().lower()
    conn = get_db()
    row = _user_by_username(conn, username)
    if not row or not _check_pw(row, body.password):
        conn.close()
        raise HTTPException(status_code=401, detail="아이디 또는 비밀번호가 틀렸어요.")
    uid = str(row["id"] if isinstance(row, dict) else row[0])
    plan = row["plan"] if isinstance(row, dict) else "free"
    nick = row["nickname"] if isinstance(row, dict) else username
    now = datetime.datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S")
    q = "UPDATE users SET last_login_at=%s WHERE id=%s" if USE_PG else "UPDATE users SET last_login_at=? WHERE id=?"
    db_execute(conn, q, (now, uid))
    if USE_PG: conn.commit()
    conn.close()
    token = make_token(uid, username, plan or "free")
    return {"token": token, "userId": uid, "username": username, "nickname": nick or username, "plan": plan or "free"}

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
        q = "UPDATE users SET password_hash=%s, nickname=%s WHERE id=%s" if USE_PG else "UPDATE users SET password_hash=?, nickname=? WHERE id=?"
        db_execute(conn, q, (ph, new_nick, uid))
    else:
        q = "UPDATE users SET password_hash=%s WHERE id=%s" if USE_PG else "UPDATE users SET password_hash=? WHERE id=?"
        db_execute(conn, q, (ph, uid))
    if USE_PG: conn.commit()
    conn.close()
    return {"ok": True, "nickname": new_nick or row["nickname"]}

class SignupRequestIn(BaseModel):
    contact: str
    contact_type: str = "kakao"  # "kakao" | "phone"
    note: str = ""


@app.post("/api/signup-request")
def create_signup_request(body: SignupRequestIn):
    contact = body.contact.strip()[:100]
    contact_type = body.contact_type if body.contact_type in ("kakao", "phone") else "kakao"
    if not contact:
        raise HTTPException(status_code=400, detail="연락처를 입력해주세요.")
    conn = get_db()
    now = datetime.datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S")
    db_execute(conn, "INSERT INTO signup_requests (contact, contact_type, note, created_at) VALUES (?,?,?,?)",
               (contact, contact_type, body.note.strip()[:500], now))
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
        "planExpiresAt": row["plan_expires_at"] if "plan_expires_at" in row.keys() else None
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
    users = db_fetchall(conn, "SELECT id,email,nickname,plan,plan_expires_at,created_at,last_login_at FROM users ORDER BY created_at DESC")
    result = []
    for u in users:
        uid = str(u["id"])
        if USE_PG:
            seeds = db_fetchall(conn, "SELECT doc_id,status,filled_count,completed,updated_at FROM submissions WHERE user_id=%s", (uid,))
        else:
            seeds = db_fetchall(conn, "SELECT doc_id,status,filled_count,completed,updated_at FROM submissions WHERE user_id=?", (uid,))
        result.append({
            "id": uid, "email": u["email"], "nickname": u["nickname"],
            "plan": u["plan"], "planExpiresAt": u["plan_expires_at"],
            "createdAt": u["created_at"], "lastLoginAt": u["last_login_at"],
            "seedCount": len(seeds),
            "seeds": [{"docId": s["doc_id"], "status": s["status"], "filledCount": s["filled_count"], "completed": bool(s["completed"]), "updatedAt": s["updated_at"]} for s in seeds]
        })
    return result

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

# 정적 프론트엔드 서빙 (반드시 API 라우트들 다음에 mount)
app.mount("/", StaticFiles(directory=os.path.join(APP_DIR, "static"), html=True), name="static")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
