# -*- coding: utf-8 -*-
"""
WMS PLC 통신 서비스
--------------------
공정 PORT 센서 신호를 주기 폴링으로 수집하고,
상태가 변한 경우에만 콜백을 호출한다. (PLC-01 / PLC-03)

src/services/plc_service.py 위치를 가정.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional

from src.plc.mc_protocol import MCProtocolClient, MCProtocolError
from src.logger.logger import get_logger

logger = get_logger("plc_service")


# ---------------------------------------------------------------------------
# 설정
# ---------------------------------------------------------------------------

@dataclass
class PortMapping:
    """공정 PORT 1개와 PLC 디바이스 주소의 매핑"""
    port_id: str            # 예: "PORT_A01"
    proc_code: str          # 공정 코드
    device: str             # 예: "M100" (점유 신호)
    description: str = ""


@dataclass
class PlcConfig:
    host: str
    port: int = 5007
    plc_type: str = "Q"
    timeout: float = 3.0
    poll_interval: float = 0.5      # 폴링 주기(초)
    reconnect_delay: float = 5.0    # 재접속 대기(초)
    ports: List[PortMapping] = field(default_factory=list)


# ---------------------------------------------------------------------------
# 서비스
# ---------------------------------------------------------------------------

class PlcService:
    """
    백그라운드 스레드로 PLC 를 폴링하며 PORT 상태를 관리한다.

    on_change(port_id, occupied) 콜백은 상태가 바뀔 때만 호출된다.
    """

    def __init__(
        self,
        config: PlcConfig,
        on_change: Optional[Callable[[str, bool], None]] = None,
    ):
        self.config = config
        self.on_change = on_change

        self._client = MCProtocolClient(
            host=config.host,
            port=config.port,
            plc_type=config.plc_type,
            timeout=config.timeout,
        )
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._state_lock = threading.RLock()

        # port_id -> 점유 여부
        self._port_state: Dict[str, bool] = {}
        self._connected = False
        self._last_error: Optional[str] = None

        # 연속된 디바이스를 한 번에 읽기 위한 그룹핑
        self._read_groups = self._build_read_groups(config.ports)

    # -- 읽기 그룹 최적화 ---------------------------------------------------

    @staticmethod
    def _build_read_groups(ports: List[PortMapping]) -> List[dict]:
        """
        연속된 비트 디바이스를 묶어 1회 요청으로 읽는다.
        M100, M101, M102 -> read_bits('M100', 3) 한 번.
        """
        parsed = []
        for p in ports:
            name, num = MCProtocolClient.parse_device(p.device)
            parsed.append((name, num, p))
        parsed.sort(key=lambda x: (x[0], x[1]))

        groups: List[dict] = []
        for name, num, port in parsed:
            if groups:
                g = groups[-1]
                if g["device_name"] == name and num == g["start"] + g["count"]:
                    g["count"] += 1
                    g["ports"].append(port)
                    continue
            groups.append(
                {"device_name": name, "start": num, "count": 1, "ports": [port]}
            )

        for g in groups:
            g["head"] = f"{g['device_name']}{g['start']:X}" \
                if g["device_name"] in {"X", "Y", "B", "W", "SB", "SW"} \
                else f"{g['device_name']}{g['start']}"
        return groups

    # -- 생명주기 ----------------------------------------------------------

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            logger.warning("PLC 폴링이 이미 실행 중입니다")
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._poll_loop, name="plc-poller", daemon=True
        )
        self._thread.start()
        logger.info(
            f"PLC 폴링 시작 - {self.config.host}:{self.config.port} "
            f"(PORT {len(self.config.ports)}개, {len(self._read_groups)}회 요청/주기)"
        )

    def stop(self, timeout: float = 5.0) -> None:
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=timeout)
        self._client.close()
        self._connected = False
        logger.info("PLC 폴링 중지")

    # -- 폴링 루프 ---------------------------------------------------------

    def _poll_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                if not self._client.is_connected:
                    self._client.connect()
                    self._connected = True
                    self._last_error = None
                    logger.info("PLC 연결됨")

                self._poll_once()
                self._stop_event.wait(self.config.poll_interval)

            except MCProtocolError as e:
                self._connected = False
                self._last_error = str(e)
                self._client.close()
                logger.error(f"PLC 통신 오류: {e}")
                self._stop_event.wait(self.config.reconnect_delay)

            except Exception as e:  # 예기치 못한 오류로 스레드가 죽지 않도록
                self._last_error = str(e)
                logger.exception(f"PLC 폴링 예외: {e}")
                self._stop_event.wait(self.config.reconnect_delay)

    def _poll_once(self) -> None:
        changes: List[tuple] = []

        for g in self._read_groups:
            bits = self._client.read_bits(g["head"], g["count"])
            with self._state_lock:
                for port, bit in zip(g["ports"], bits):
                    occupied = bool(bit)
                    prev = self._port_state.get(port.port_id)
                    if prev != occupied:
                        self._port_state[port.port_id] = occupied
                        changes.append((port, prev, occupied))

        for port, prev, occupied in changes:
            logger.info(
                f"PORT 상태 변경 [{port.port_id}] "
                f"{'점유' if prev else '공가' if prev is not None else '초기'}"
                f" -> {'점유' if occupied else '공가'}"
            )
            if self.on_change:
                try:
                    self.on_change(port.port_id, occupied)
                except Exception as e:
                    logger.exception(f"on_change 콜백 오류 [{port.port_id}]: {e}")

    # -- 조회 API ----------------------------------------------------------

    def is_port_available(self, port_id: str) -> bool:
        """보급 가능(공가) 여부. 상태 미수신이면 False."""
        with self._state_lock:
            state = self._port_state.get(port_id)
        return state is False

    def get_all_ports(self) -> Dict[str, Optional[str]]:
        with self._state_lock:
            return {
                pid: ("점유" if occ else "공가")
                for pid, occ in self._port_state.items()
            }

    def get_status(self) -> dict:
        return {
            "connected": self._connected,
            "host": f"{self.config.host}:{self.config.port}",
            "last_error": self._last_error,
            "ports": self.get_all_ports(),
        }

    # -- 쓰기 (설비 신호 송출용) -------------------------------------------

    def write_signal(self, device: str, value: int) -> None:
        """PLC 로 신호 출력. 예: write_signal('Y10', 1)"""
        try:
            self._client.write_bit(device, value)
            logger.info(f"PLC 신호 출력 {device} = {value}")
        except MCProtocolError as e:
            logger.error(f"PLC 신호 출력 실패 {device}: {e}")
            raise


# ---------------------------------------------------------------------------
# 싱글톤 (FastAPI lifespan 에서 사용)
# ---------------------------------------------------------------------------

_service: Optional[PlcService] = None


def init_plc_service(config: PlcConfig,
                     on_change: Optional[Callable[[str, bool], None]] = None
                     ) -> PlcService:
    global _service
    _service = PlcService(config, on_change)
    _service.start()
    return _service


def get_plc_service() -> PlcService:
    if _service is None:
        raise RuntimeError("PLC 서비스가 초기화되지 않았습니다")
    return _service


def shutdown_plc_service() -> None:
    if _service is not None:
        _service.stop()


# ---------------------------------------------------------------------------
# main.py 연동 예시
# ---------------------------------------------------------------------------
"""
from contextlib import asynccontextmanager
from fastapi import FastAPI
from src.services.plc_service import (
    PlcConfig, PortMapping, init_plc_service, shutdown_plc_service,
    get_plc_service,
)

PLC_CONFIG = PlcConfig(
    host="192.168.0.10",
    port=5007,
    poll_interval=0.5,
    ports=[
        PortMapping("PORT_A01", "PROC_A", "M100", "A공정 1번 포트"),
        PortMapping("PORT_A02", "PROC_A", "M101", "A공정 2번 포트"),
        PortMapping("PORT_B01", "PROC_B", "M102", "B공정 1번 포트"),
    ],
)

def on_port_change(port_id: str, occupied: bool):
    if not occupied:
        # 공가 감지 -> STAGING BUFFER 대기 K-LPN 확인 후 AMR Call
        from src.services.acs_service import try_dispatch_amr
        try_dispatch_amr(port_id)

@asynccontextmanager
async def lifespan(app: FastAPI):
    init_plc_service(PLC_CONFIG, on_change=on_port_change)
    yield
    shutdown_plc_service()

app = FastAPI(lifespan=lifespan)

@app.get("/api/plc/status")
def plc_status():
    return get_plc_service().get_status()
"""