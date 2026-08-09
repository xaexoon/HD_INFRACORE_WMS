# -*- coding: utf-8 -*-
"""
ACS(AGV 제어 시스템) REST API 클라이언트
------------------------------------------
WMS = client, ACS = server. 통신은 WMS -> ACS 단방향이다.
PLC 센서가 스테이션 점유를 감지하면 여기를 통해 AGV 배차를 요청한다.

사용:
    init_acs("http://192.168.1.50:8080")          # 기동 시 1회
    call_agv("ST-01", "LPN2607280001")            # 센서 감지 시
"""

from __future__ import annotations

import httpx

from src.logger.logger import get_logger

logger = get_logger("acs service")


class AcsError(Exception):
    """ACS 요청 실패"""


class AcsNoResponseError(AcsError):
    """ACS 무응답 (서버 다운 / 주소 오류 / 네트워크 단절 / 타임아웃).

    상태코드조차 못 받아 요청이 ACS 에 닿았는지 알 수 없다.
    AGV 가 이미 배차됐을 수 있으므로 함부로 재전송하면 안 된다.
    """


_client: httpx.Client | None = None


def init_acs(base_url: str, timeout: float = 5.0) -> None:
    """기동 시 1회 호출. 커넥션을 재사용하도록 Client 를 하나 유지한다."""
    global _client
    _client = httpx.Client(base_url=base_url.rstrip("/"), timeout=timeout)
    logger.info(f"ACS 클라이언트 초기화 - {base_url} (timeout={timeout}s)")


def close_acs() -> None:
    global _client
    if _client is not None:
        _client.close()
        _client = None


# TODO: ACS 스펙 확정 후 경로/필드명을 실제 스펙에 맞춰 교체.
def call_agv(station_code: str, lpn_code: str) -> dict:
    """스테이션의 제품을 가져가도록 AGV 배차를 요청한다."""
    if _client is None:
        raise RuntimeError("ACS 클라이언트 미초기화. init_acs() 를 먼저 호출하세요.")

    payload = {"stationCode": station_code, "lpnCode": lpn_code}
    logger.info(f"ACS 요청 {payload}")

    try:
        resp = _client.post("/api/agv/call", json=payload)
    except httpx.TransportError as e:
        logger.error(f"ACS 무응답 - {e}")
        raise AcsNoResponseError(f"ACS 무응답 - {e}") from e

    logger.info(f"ACS 응답 HTTP {resp.status_code} {resp.text[:200]}")
    if resp.status_code >= 400:
        raise AcsError(f"ACS 오류 HTTP {resp.status_code} - {resp.text[:200]}")

    return resp.json()
