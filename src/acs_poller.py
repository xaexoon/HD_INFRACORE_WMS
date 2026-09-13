# -*- coding: utf-8 -*-
"""ACS 폴링 프로세스.

WMS 가 ACS 에 주기적으로 물어보고, 결과에 따라 다음 요청을 낸다.
ACS 관련해서 바뀌는 것은 이 파일과 services/acs_service.py 에서만 손본다.

    1초마다  GET  /wms/get_station_status        (1-1) 스테이션 상태
        빈 스테이션(status=0)이 있고 배정 대기 K-LPN 이 있으면
             POST /wms/req_kit_st_no            (1-2) 스테이션 지정 요청
             -> 받은 번호를 kit_table 에 저장

웹 프로세스와 따로 두는 이유
    · 폴링이 웹 응답 시간에 영향을 주지 않는다
    · uvicorn 워커를 늘려도 폴링이 중복으로 돌지 않는다
    · 폴링이 죽어도 웹은 계속 뜬다

※ 이 프로세스도 DB 를 쓰므로 init_db 를 각자 호출한다(프로세스별 각자 연결 원칙).
"""

from __future__ import annotations

import time

from src.db.connection import init_db, query, execute
from src.logger.logger import get_logger
from src.queries import kit_query
from src.services import acs_service

logger = get_logger("svc.acspoll")


# 직전에 본 상태. 바뀌었을 때만 로그를 남긴다.
#   1초 주기를 그대로 남기면 하루 86,400 줄이 되어 다른 로그가 전부 묻힌다.
_last_seen: str | None = None
_down: bool = False


def _log_status(rows: list[dict]) -> None:
    global _last_seen
    snapshot = str([(r.get("station_no"), r.get("status"), r.get("lpn_code"))
                    for r in rows])
    if snapshot == _last_seen:
        return
    _last_seen = snapshot

    empty = acs_service.empty_stations(rows)
    logger.info("스테이션 %s개 (빈 자리 %s개) - %s",
                len(rows), len(empty),
                ", ".join(f"{r.get('station_name')}:{r.get('status')}" for r in rows))


def _note_down(err) -> None:
    """무응답 진입. 처음 한 번만 남긴다."""
    global _down, _last_seen
    if _down:
        return
    _down = True
    _last_seen = None       # 복구되면 현재 상태를 다시 한 줄 남기도록
    logger.warning("ACS 무응답 - %s", err)


def _note_up() -> None:
    global _down
    if _down:
        _down = False
        logger.info("ACS 응답 확인")


# 주기 루프 안에서 같은 경고가 매초 나오면 로그가 못 쓰게 된다.
# 같은 키로는 한 번만 남기고, 해소되면 다시 남길 수 있게 푼다.
_warned: set = set()


def _warn_once(key, msg, *args) -> None:
    if key in _warned:
        return
    _warned.add(key)
    logger.warning(msg, *args)


def _clear_warn(key) -> None:
    _warned.discard(key)


def poll_once() -> None:
    """한 주기 처리. 예외를 올리지 않는다."""
    try:
        rows = acs_service.get_station_status()
    except acs_service.AcsError as e:
        _note_down(e)
        return

    _note_up()
    _log_status(rows)

    if acs_service.empty_stations(rows):
        _assign_station(rows)


def _assign_station(rows: list[dict]) -> None:
    """빈 스테이션이 있을 때, 배정 대기 K-LPN 한 건에 번호를 받아 채운다.

    가장 오래 기다린 것부터 한 건씩 처리한다(SELECT_KLPN_NO_STATION 이 TOP 1).
    스테이션은 한정 자원이라 한꺼번에 요청하면 늦게 만들어진 K-LPN 이
    먼저 자리를 차지할 수 있다.
    """
    waiting = query(kit_query.SELECT_KLPN_NO_STATION)
    if not waiting:
        return                      # 빈 자리가 있어도 기다리는 게 없으면 부를 일 없다

    code = waiting[0]["k_lpn_code"]

    try:
        station_no = acs_service.req_kit_station(code)
    except acs_service.AcsError as e:
        # 가용 스테이션이 없다는 등의 거절. 다음 주기에 다시 시도한다.
        _warn_once(("assign", code), "스테이션 배정 거절 - %s (%s)", code, e)
        return

    station_name = acs_service.station_name_of(rows, station_no)

    affected = execute(kit_query.ASSIGN_STATION_BY_LPN,
                       (station_no, station_name, code))
    if affected == 0:
        # 이미 배정된 뒤다(중복 응답 등). 오류는 아니다.
        return

    _clear_warn(("assign", code))
    logger.info("스테이션 배정 - %s -> %s (%s)", code, station_no, station_name)


def run_acs_poller(acs_conf: dict, db_conf: dict, stop_event) -> None:
    """프로세스 진입점 (main.py 의 Process target)."""
    init_db(
        address=db_conf["address"],
        database=db_conf["database"],
        user=db_conf["user"],
        password=db_conf["password"],
    )
    acs_service.init_acs(acs_conf["url"], acs_conf["timeout"])

    interval = acs_conf["interval"]
    logger.info("ACS 폴링 시작 (%s초 주기)", interval)

    # try/except 는 while '안쪽' 에 둔다. 바깥에 두면 한 번의 예외로
    # 루프가 통째로 죽고 재기동 전까지 폴링이 멈춘다.
    while not stop_event.is_set():
        try:
            poll_once()
        except Exception:
            logger.exception("폴링 처리 실패")

        # 종료 신호에 빨리 반응하도록 잘게 나눠 잔다
        waited = 0.0
        while waited < interval and not stop_event.is_set():
            time.sleep(min(0.2, interval - waited))
            waited += 0.2

    acs_service.close_acs()
    logger.info("ACS 폴링 종료")
