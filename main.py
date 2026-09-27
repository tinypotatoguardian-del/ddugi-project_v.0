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
    conn.commit()
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
def list_submissions(x_emp_id: str = Header(default=""), x_emp_code: str = Header(default="")):
    # 전체 현황(팀 역량 포함)은 관리자·마스터 계정만 조회
    require_role(x_emp_id, x_emp_code, {"admin", "master"})
    conn = get_db()
    rows = db_fetchall(conn,
        "SELECT * FROM submissions ORDER BY updated_at DESC"
    )
    conn.close()
    out = []
    for r in rows:
        item = row_to_summary(r)
        f = json.loads(r["fields"] or "{}")
        # 13 효과 확인의 Gate 신청 내용 (관리자 확인용)
        item["gate"] = {
            "level": f.get("g_level", ""),
            "task": f.get("s1_name", ""),
            "evidence": f.get("g_evidence", ""),
            "aiResult": f.get("g_ai_result", ""),
        }
        item["lpDone"] = f.get("lp_done", [])
        # 과제 목록 화면용: 진행 단계는 프런트에서 계산 (실제로 채워졌는지 bool만 넘김)
        item["task"] = {
            "name": f.get("s1_name", ""),
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
def put_submission(doc_id: str, body: SubmissionIn):
    conn = get_db()
    now = datetime.datetime.utcnow().isoformat()
    db_execute(conn,
        """
        INSERT INTO submissions
            (doc_id, team, name, fields, locked, completed, status,
             filled_count, total_sections, recommended_type, updated_at)
        VALUES (?,?,?,?,?,?,?,?,?,?,?)
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
            updated_at=excluded.updated_at
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
    return {"role": role}


def account_out(row) -> Dict[str, Any]:
    return {"empId": row["emp_id"], "role": row["role"], "name": row["name"], "createdAt": row["created_at"]}


@app.get("/api/master/accounts")
def list_accounts(x_emp_id: str = Header(default=""), x_emp_code: str = Header(default="")):
    require_role(x_emp_id, x_emp_code, {"master"})
    conn = get_db()
    rows = db_fetchall(conn, "SELECT * FROM accounts ORDER BY created_at")
    conn.close()
    return [account_out(r) for r in rows]


class AccountIn(BaseModel):
    empId: str
    code: str
    name: str = ""


@app.post("/api/master/accounts")
def add_account(body: AccountIn, x_emp_id: str = Header(default=""), x_emp_code: str = Header(default="")):
    # 마스터가 관리자 계정을 직접 만들어준다 (자유 가입이 아니라 마스터의 권한 부여)
    require_role(x_emp_id, x_emp_code, {"master"})
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
def remove_account(emp_id: str, x_emp_id: str = Header(default=""), x_emp_code: str = Header(default="")):
    require_role(x_emp_id, x_emp_code, {"master"})
    if emp_id == x_emp_id:
        raise HTTPException(status_code=400, detail="자기 자신(마스터) 계정은 지울 수 없습니다.")
    conn = get_db()
    cur = db_execute(conn, "DELETE FROM accounts WHERE emp_id=? AND role='admin'", (emp_id,))
    conn.commit()
    conn.close()
    if not cur.rowcount:
        raise HTTPException(status_code=404, detail="관리자 계정을 찾을 수 없습니다.")
    return {"ok": True}


class GateReviewIn(BaseModel):
    level: str
    decision: str
    note: str = ""


@app.post("/api/admin/gate/{doc_id}")
def review_gate(doc_id: str, body: GateReviewIn, x_emp_id: str = Header(default=""), x_emp_code: str = Header(default="")):
    # 레벨 인정은 관리자·마스터만 (AI 판정은 1차 참고)
    require_role(x_emp_id, x_emp_code, {"admin", "master"})
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
    empId: str
    old: str
    new: str


@app.post("/api/account/password")
def change_password(body: PasswordChangeIn):
    # 마스터든 관리자든 자기 비밀번호는 스스로 바꾼다
    require_role(body.empId, body.old, {"master", "admin"})
    if len(body.new) < MIN_CODE_LEN:
        raise HTTPException(status_code=400, detail=f"새 비밀번호는 {MIN_CODE_LEN}자 이상이어야 합니다.")
    if body.new == body.old:
        raise HTTPException(status_code=400, detail="새 비밀번호가 기존 비밀번호와 같습니다.")
    conn = get_db()
    db_execute(conn, "UPDATE accounts SET password_hash=? WHERE emp_id=?", (hash_code(body.new), body.empId))
    conn.commit()
    conn.close()
    return {"ok": True}


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
def put_taxonomy(key: str, body: TaxonomyIn, x_emp_id: str = Header(default=""), x_emp_code: str = Header(default="")):
    role = require_role(x_emp_id, x_emp_code, {"admin", "master"})
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


# 정적 프론트엔드 서빙 (반드시 API 라우트들 다음에 mount)
app.mount("/", StaticFiles(directory=os.path.join(APP_DIR, "static"), html=True), name="static")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
