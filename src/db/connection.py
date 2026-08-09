"""src/db/connection.py — DB 연결 전담 (MSSQL / pyodbc)

프로세스 시작 시 init_db(주소, DB명, 계정, 비밀번호)를 호출하면
접속 문자열을 구성하고 접속 확인까지 수행한다.
"""
import pyodbc

from src.logger.logger import get_logger
from contextlib import contextmanager

logger = get_logger("db")

_conn_str: str | None = None


def init_db(address: str, database: str, user: str, password: str):
    """접속 정보를 파라미터로 받아 접속 문자열 구성 + 접속 테스트.
    실패 시 예외를 던져 프로세스가 기동 단계에서 죽게 한다(fail fast)."""
    global _conn_str

    _conn_str = (
        "DRIVER={ODBC Driver 17 for SQL Server};"
        f"SERVER={address};"
        f"DATABASE={database};"
        f"UID={user};"
        f"PWD={password};"
        "TrustServerCertificate=yes;"
    )

    query("SELECT 1 AS ok")  # 접속 확인
    logger.info(f"DB 접속 확인 완료 (server={address}, db={database})")


def get_conn():
    if _conn_str is None:
        raise RuntimeError("DB 미초기화. 프로세스 시작 시 init_db()를 먼저 호출하세요.")
    return pyodbc.connect(_conn_str)


def query(sql, params=()):
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute(sql, params)
        columns = [col[0] for col in cur.description]
        return [dict(zip(columns, row)) for row in cur.fetchall()]
    finally:
        conn.close()


def execute(sql, params=()):
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute(sql, params)
        conn.commit()
        return cur.rowcount
    finally:
        conn.close()

def insert_returning(sql, params=()):
    """INSERT ... OUTPUT INSERTED.xxx 처럼 결과를 돌려주는 DML.

    execute()는 rowcount만 반환하고, query()는 commit이 없어서
    생성된 seq를 받아야 하는 INSERT에는 둘 다 쓸 수 없다.
    """
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute(sql, params)
        columns = [col[0] for col in cur.description]
        rows = [dict(zip(columns, row)) for row in cur.fetchall()]
        conn.commit()
        return rows
    finally:
        conn.close()

@contextmanager
def transaction():
    """with transaction() as cur: 블록이 정상 종료하면 commit, 예외면 rollback"""
    conn = get_conn()
    try:
        yield conn.cursor()
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()