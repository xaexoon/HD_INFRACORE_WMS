import asyncio
import multiprocessing as mp

from src.socket_module.tcp_socket_module import TcpSocketFrame
from src.db.connection import init_db
from src.logger.logger import get_logger


class AcsSocket(TcpSocketFrame):
    """ACS와의 전문 송수신."""

    # ------------------------------------------------------------------ #
    # 주기 송신 (ALL_SEND_INTERVAL 초마다 프레임워크가 호출)
    # ------------------------------------------------------------------ #
    def all_send_data_process(self):
        # TODO: ACS 스펙에 하트비트/상태조회 전문이 있으면 여기서 전송
        # 예: self.socket_module.socket_send_queue.put(b"HEARTBEAT\r\n")
        pass

    # ------------------------------------------------------------------ #
    # 송신: 바깥(send_queue)에서 온 요청을 전문으로 가공해 전송
    # ------------------------------------------------------------------ #
    def send_data_process(self, send_data):
        # send_data 는 바깥에서 {"type": "send", "data": ...} 로 넣은 것의 data 부분.
        # TODO: 스펙 확정 후 전문 조립
        #   예: {"cmd": "AMR_CALL", "port": "SB-01", "lpn": "K-123"} 형태의 dict를
        #       받아서 ACS 전문(bytes)으로 변환
        payload = send_data if isinstance(send_data, bytes) else str(send_data).encode()
        self.socket_module.socket_send_queue.put(payload)
        self.logger.info(f"ACS 송신: {payload!r}")

    # ------------------------------------------------------------------ #
    # 수신: ACS 가 보낸 전문 해석
    # ------------------------------------------------------------------ #
    def recv_data_process(self, recv_data):
        # TODO: 스펙 확정 후 전문 파싱
        #   - AMR 이동 완료 보고 -> lpn_txn INSERT, lpn_master 위치 갱신
        #   - AMR 상태 통지     -> recv_queue 로 올려 화면(WebSocket) 반영 등
        self.logger.info(f"ACS 수신: {recv_data!r}")


# ---------------------------------------------------------------------- #
# 프로세스 진입 함수 (main.py 의 Process target)
# ---------------------------------------------------------------------- #
def run_acs(db_conf: dict, acs_conf: dict,
            send_queue: mp.Queue, recv_queue: mp.Queue, stop_event):
    logger = get_logger("acs")

    # 이 프로세스도 DB 사용 (수신 전문 -> DB 반영). 프로세스별 각자 연결 원칙.
    init_db(
        address=db_conf["address"],
        database=db_conf["database"],
        user=db_conf["user"],
        password=db_conf["password"],
    )

    acs = AcsSocket(
        program_name="acs",
        parameter={
            "ip_address": acs_conf["address"],
            "port": int(acs_conf["port"]),
            "server_flag": False,        # WMS = 클라이언트, ACS = 서버
            "socket_timeout": 5,         # 접속 시도 타임아웃(초)
            "receive_timeout": 0,        # 0 = 무수신 재접속 비활성 (스펙 보고 조정)
            "buffer_bytes_flag": False,  # 수신을 deque 로 (전문 단위 콜백)
        },
        send_queue=send_queue,
        recv_queue=recv_queue,
        logger=logger,
        stop_event=stop_event,
    )
    asyncio.run(acs.run_process())