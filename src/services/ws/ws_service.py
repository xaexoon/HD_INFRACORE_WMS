"""핸디형 RFID 리더 2대에 ISSUED K-LPN 목록을 실시간 전달한다.

흐름
    K-LPN 발행 → kit_table 저장
    → broadcast_loop 가 주기적으로 rfid_yn=0 인 ISSUED K-LPN 을 조회
    → 접속 중인 핸디 전부에 목록 전송
    → 핸디가 태그 쓰기 완료 시 RFID_DONE 회신
    → rfid_yn=1 → 다음 주기부터 목록에서 빠짐

핸디가 2대라 같은 K-LPN 이 양쪽에 다 보인다. 중복 쓰기는 MARK_RFID_DONE 의
rfid_yn=0 조건으로 걸러지며, 두 번째 회신은 rowcount=0 으로 무시된다.
"""

import asyncio
import json
from typing import Any

from fastapi import WebSocket

from src.db.connection import get_conn          # ★ 확인 필요 (아래 주석 참조)
from src.queries import kit_query               # ★ 확인 필요
from src.logger.logger import get_logger

logger = get_logger("ws")

# 조회 주기(초). 짧게 잡을 이유가 없다. K-LPN 발행은 초 단위 연사가 아니다.
POLL_SEC = 2.0

# 접속 중인 핸디들
_clients: set[WebSocket] = set()

# 직전에 보낸 목록의 스냅샷. 바뀌었을 때만 전송해 트래픽과 로그를 줄인다.
_last_snapshot: str | None = None


# ─────────────────────────────────────────────
# DB (동기) — 이벤트 루프에서 직접 호출하지 말 것
# ─────────────────────────────────────────────
# pyodbc 는 블로킹이다. 이 함수들을 코루틴에서 그냥 부르면 쿼리가 도는 동안
# 이벤트 루프 전체가 멈추고, :8000 의 모든 HTTP 요청이 같이 멈춘다.
# 반드시 asyncio.to_thread 로 감싸서 호출한다.

def _fetch_klpn_rows() -> list[dict[str, Any]]:
    """rfid_yn=0 인 ISSUED K-LPN 목록."""
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(kit_query.SELECT_KLPN_FOR_RFID)
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]


def _mark_rfid_done(k_lpn_code: str) -> int:
    """태그 쓰기 완료 반영. 이미 처리된 건이면 0 을 돌려준다."""
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(kit_query.MARK_RFID_DONE, (k_lpn_code,))
        affected = cur.rowcount
        conn.commit()
        return affected


# ─────────────────────────────────────────────
# 접속 관리
# ─────────────────────────────────────────────
async def register(ws: WebSocket) -> int:
    """핸디 등록. 접속 대수를 돌려준다.

    accept() 는 라우터가 이미 호출한 뒤다. 여기서 또 부르면 RuntimeError.
    """
    _clients.add(ws)

    try:
        rows = await asyncio.to_thread(_fetch_klpn_rows)
        await ws.send_text(_pack(rows))
    except Exception:
        # 초기 전송이 실패해도 등록은 유지한다. 다음 주기에 다시 나간다.
        logger.exception("초기 목록 전송 실패")

    return len(_clients)


async def unregister(ws: WebSocket) -> int:
    _clients.discard(ws)
    return len(_clients)


# ─────────────────────────────────────────────
# 수신
# ─────────────────────────────────────────────
async def on_receive(ws: WebSocket, raw: str) -> None:
    """핸디 → 서버 메시지 처리.

    지금은 RFID_DONE / PING 둘뿐이다. 규격이 확정되면 여기서 분기를 늘린다.
    """
    try:
        msg = json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("JSON 파싱 실패: %.200s", raw)
        await _safe_send(ws, {"type": "ERROR", "msg": "invalid json"})
        return

    msg_type = msg.get("type")

    if msg_type == "PING":
        await _safe_send(ws, {"type": "PONG"})
        return

    if msg_type == "RFID_DONE":
        code = msg.get("k_lpn_code")
        if not code:
            await _safe_send(ws, {"type": "ERROR", "msg": "k_lpn_code required"})
            return

        try:
            affected = await asyncio.to_thread(_mark_rfid_done, code)
        except Exception:
            logger.exception("RFID_DONE 반영 실패 (%s)", code)
            await _safe_send(ws, {"type": "ERROR", "msg": "db error",
                                  "k_lpn_code": code})
            return

        if affected:
            logger.info("태그 쓰기 완료 %s", code)
        else:
            # 다른 핸디가 먼저 처리했거나, 이미 끝난 건. 오류는 아니다.
            logger.info("태그 쓰기 중복/무효 %s", code)

        await _safe_send(ws, {"type": "RFID_DONE_ACK",
                              "k_lpn_code": code,
                              "applied": bool(affected)})
        # 목록이 줄었으니 다음 주기를 기다리지 말고 바로 반영한다
        await _push_now()
        return

    logger.warning("알 수 없는 메시지 타입: %s", msg_type)


# ─────────────────────────────────────────────
# 송신
# ─────────────────────────────────────────────
def _pack(rows: list[dict[str, Any]]) -> str:
    return json.dumps({"type": "KLPN_LIST", "count": len(rows), "items": rows},
                      ensure_ascii=False, default=str)


async def _safe_send(ws: WebSocket, payload: dict) -> bool:
    try:
        await ws.send_text(json.dumps(payload, ensure_ascii=False, default=str))
        return True
    except Exception:
        return False


async def broadcast(rows: list[dict[str, Any]]) -> None:
    """접속 중인 전부에 전송.

    전송 실패한 소켓을 순회 도중 _clients 에서 지우면 RuntimeError 가 난다.
    따로 모았다가 순회가 끝난 뒤 제거한다.
    """
    if not _clients:
        return

    text = _pack(rows)
    dead: list[WebSocket] = []

    for ws in list(_clients):
        try:
            await ws.send_text(text)
        except Exception:
            dead.append(ws)

    for ws in dead:
        _clients.discard(ws)
    if dead:
        logger.info("끊긴 핸디 %d대 정리 (현재 %d대)", len(dead), len(_clients))


async def _push_now() -> None:
    """스냅샷 무시하고 즉시 한 번 밀어낸다."""
    global _last_snapshot
    try:
        rows = await asyncio.to_thread(_fetch_klpn_rows)
    except Exception:
        logger.exception("즉시 전송용 조회 실패")
        return
    _last_snapshot = _pack(rows)
    await broadcast(rows)


# ─────────────────────────────────────────────
# 주기 루프 (web_server lifespan 에서 기동)
# ─────────────────────────────────────────────
async def broadcast_loop() -> None:
    global _last_snapshot

    # try/except 는 반드시 while '안쪽'에 둔다. 바깥에 두면 DB 가 한 번
    # 끊길 때 루프가 통째로 죽고, 재기동 전까지 RFID 전송이 영영 안 된다.
    while True:
        try:
            if _clients:
                rows = await asyncio.to_thread(_fetch_klpn_rows)
                snapshot = _pack(rows)
                if snapshot != _last_snapshot:
                    _last_snapshot = snapshot
                    await broadcast(rows)
                    logger.info("목록 전송 %d건 → %d대", len(rows), len(_clients))
        except asyncio.CancelledError:
            # 서버 종료. 조용히 빠져나간다.
            raise
        except Exception:
            logger.exception("목록 조회/전송 실패")

        await asyncio.sleep(POLL_SEC)