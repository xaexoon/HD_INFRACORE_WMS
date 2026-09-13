# -*- coding: utf-8 -*-
"""ACS REST 클라이언트.

WMS = client, ACS = server. WMS 가 주기적으로 물어보는 방식이다.

    init_acs("http://192.168.1.50:8080")   # 프로세스마다 기동 시 1회
    rows = get_station_status()            # 1초 주기 폴링

실패는 전부 AcsError 로 올린다. 부르는 쪽이 판단한다.
"""

from __future__ import annotations

import httpx

from src.logger.logger import get_logger

logger = get_logger("svc.acs")


class AcsError(Exception):
    """ACS 요청 실패."""


_client: httpx.Client | None = None


def init_acs(base_url: str, timeout: float = 0.5) -> None:
    """기동 시 1회. 커넥션을 재사용하도록 Client 를 하나 유지한다.

    timeout 은 폴링 주기보다 짧아야 한다. 주기보다 길면 ACS 가 느릴 때
    다음 요청이 앞 요청을 기다리다 폴링이 밀린다.
    """
    global _client
    _client = httpx.Client(base_url=base_url.rstrip("/"), timeout=timeout)
    logger.info("ACS 클라이언트 초기화 - %s (timeout=%ss)", base_url, timeout)


def close_acs() -> None:
    global _client
    if _client is not None:
        _client.close()
        _client = None


def is_ready() -> bool:
    """init_acs 가 불렸는가."""
    return _client is not None


def _get(path: str) -> dict:
    if _client is None:
        raise AcsError("ACS 클라이언트 미초기화. init_acs() 를 먼저 호출하세요")

    try:
        resp = _client.get(path)
    except httpx.HTTPError as e:
        raise AcsError(f"무응답 - {e}") from e

    if resp.status_code >= 400:
        raise AcsError(f"HTTP {resp.status_code} - {resp.text[:200]}")

    try:
        body = resp.json()
    except ValueError as e:
        raise AcsError(f"JSON 아님 - {resp.text[:200]}") from e

    if not body.get("flag"):
        raise AcsError(f"flag=false - {str(body)[:200]}")

    return body


def _post(path: str, payload: dict) -> dict:
    if _client is None:
        raise AcsError("ACS 클라이언트 미초기화. init_acs() 를 먼저 호출하세요")

    try:
        resp = _client.post(path, json=payload)
    except httpx.HTTPError as e:
        raise AcsError(f"무응답 - {e}") from e

    if resp.status_code >= 400:
        raise AcsError(f"HTTP {resp.status_code} - {resp.text[:200]}")

    try:
        body = resp.json()
    except ValueError as e:
        raise AcsError(f"JSON 아님 - {resp.text[:200]}") from e

    if not body.get("flag"):
        # 실패 응답은 msg 에 사유가 온다. 통신 오류와 구분해야 하므로
        # 사유를 그대로 올려 부르는 쪽이 판단하게 한다.
        raise AcsError(body.get("msg") or f"flag=false - {str(body)[:200]}")

    return body


# ---------------------------------------------------------------------- #
# 1-1. 대차 스테이션 상태
# ---------------------------------------------------------------------- #
def get_station_status() -> list[dict]:
    """스테이션 상태 목록.

        [{"station_no": 1, "status": 0, "station_name": "KIT-01",
          "product_detect": false, "lpn_code": ""}, ...]

        status 0 = 비어 있음(배정 가능) / 1 = 사용 중
    """
    data = _get("/wms/get_station_status").get("data")
    if not isinstance(data, list):
        raise AcsError(f"data 가 목록이 아님 - {str(data)[:200]}")
    return data


def empty_stations(rows: list[dict]) -> list[dict]:
    """비어 있는(status=0) 스테이션만 추린다."""
    return [r for r in rows if r.get("status") == 0]


# ---------------------------------------------------------------------- #
# 1-2. 키팅 스테이션 할당 요청
# ---------------------------------------------------------------------- #
def req_kit_station(lpn_code: str) -> int:
    """K-LPN 에 쓸 키팅 스테이션 번호를 받아온다.

        POST /wms/req_kit_st_no  {"lpn_code": "K25090700001"}
        ->   {"flag": true, "data": {"lpn_code": ..., "station_no": 1}}

    station_name 은 응답에 없다. 1-1 목록에서 station_no 로 찾아 쓴다.
    실패(flag=false)면 msg 를 담은 AcsError 를 올린다.
    """
    data = _post("/wms/req_kit_st_no", {"lpn_code": lpn_code}).get("data") or {}

    station_no = data.get("station_no")
    if station_no is None:
        raise AcsError(f"station_no 가 없다 - {str(data)[:200]}")

    # 응답이 다른 LPN 것이면 잘못 반영된다. 반드시 확인한다.
    if data.get("lpn_code") not in (None, "", lpn_code):
        raise AcsError(f"요청과 다른 lpn_code 응답 - 요청 {lpn_code} / 응답 {data.get('lpn_code')}")

    return int(station_no)


def station_name_of(rows: list[dict], station_no: int) -> str | None:
    """1-1 목록에서 station_no 에 해당하는 이름을 찾는다."""
    for r in rows:
        if r.get("station_no") == station_no:
            return r.get("station_name")
    return None
