# -*- coding: utf-8 -*-
"""
tcp_socket.py
=============
저수준 소켓 통신 계층 (별도 프로세스에서 동작).

구조
  ControlCommand : 소켓 프로세스로 보내는 제어 명령 상수 (예전 bytes(0~3) 대체)
  StateType      : received_queue 로 올려보내는 상태 데이터의 type 상수
  SocketFrame    : 추상 부모 클래스 (연결 관리 / 송신 / 수신 공통 로직)
                   - connect_socket / close_socket 이 자식이 채우는 추상 메서드
  SocketClient   : connect_socket -> connect
  SocketServer   : connect_socket -> bind / listen / accept
  socket_client_start / socket_server_start : 프로세스 진입 함수

동작 개요
  __init__ 끝에서 asyncio.run(self.socket_process()) 로 진입하고,
  그 안에서 연결관리(init_process)와 송신(send_process)을 async task 로 돌린다.
  수신만 ThreadWithException 스레드(recv_process)로 분리한다.
  바깥(SocketModule)과는 send_queue / received_queue 두 개의 mp.Queue 로 통신한다.
"""

import time
import socket
import asyncio
import datetime
import traceback
import multiprocessing as mp
from abc import ABCMeta, abstractmethod

from src.module.thread_with_exception import ThreadWithException


class ControlCommand:
    """소켓 프로세스 제어 명령 (예전 bytes(0~3) 매직값 대체).

    send_queue 로 이 값들을 넣으면 데이터 전송이 아니라 제어 동작으로 처리된다.
    bytes 객체로 둔 이유는 기존 큐 프로토콜(bytes 전송)과 충돌하지 않게 하기 위함.
    """
    RESTART = b"\x00__CTRL_RESTART__"   # 재접속
    STOP    = b"\x00__CTRL_STOP__"      # 완전 종료
    DISABLE = b"\x00__CTRL_DISABLE__"   # 비활성화 (연결 끊고 대기)
    ENABLE  = b"\x00__CTRL_ENABLE__"    # 비활성화 해제

    ALL = (RESTART, STOP, DISABLE, ENABLE)


class StateType:
    """received_queue 로 올려보내는 상태 데이터의 type 값.

    값 자체는 기존 문자열('info'/'connect'/'error'/'receive')을 그대로 유지해
    받는 쪽(SocketModule)을 깨지 않는다. 나중에 받는 쪽도 이 상수를 쓰도록 통일하면 됨.
    """
    INFO    = "info"      # 일반 메시지
    CONNECT = "connect"   # 연결 여부 (data=True/False)
    ERROR   = "error"     # 에러 메시지
    RECEIVE = "receive"   # 수신 데이터 (data=bytes)


class SocketFrame(metaclass=ABCMeta):
    """소켓 통신 공통 틀 (추상 클래스).

    Parameters
    ----------
    host : 서버 주소
    port : 서버 포트
    socket_type : 소켓 타입 식별자 (예: 'acs_client')
    received_queue : 수신/상태 데이터를 바깥으로 올려보내는 큐
    send_queue : 바깥에서 보낼 데이터를 받는 큐
    timeout : 소켓 타임아웃 (None=무제한)
    bind_ip : 송신 측 네트워크 바인딩 IP
    """

    # ---- 튜닝 상수 (필요하면 인자로 빼서 조정) ----
    RECV_BUFFER_SIZE   = 1024   # recv 한 번에 읽는 바이트
    EMPTY_DATA_LIMIT   = 50     # 빈 데이터가 이만큼 연속되면 끊김으로 판단
    RECV_LOOP_DELAY    = 0.01   # 수신 루프 간격(초)
    SEND_LOOP_DELAY    = 0.01   # 송신 루프 간격(초)
    RECONNECT_DELAY    = 1.0    # 재접속 시도 간격(초)

    def __init__(self, host: str, port: int, socket_type: str,
                 received_queue: mp.Queue, send_queue: mp.Queue,
                 timeout=None, bind_ip=None):
        self.host = host
        self.port = port
        self.socket_type = socket_type
        self.received_queue = received_queue
        self.send_queue = send_queue
        self.timeout = timeout
        self.bind_ip = bind_ip

        self.server_socket: socket.socket = None    # 서버 리슨 소켓
        self.client_socket: socket.socket = None    # 실제 통신 소켓

        self.socket_start = True       # 전체 루프 가동 여부 (False면 종료)
        self.init_log_flag = False     # 연결 실패 로그 1회만 찍기용
        self.client_connect = False    # 통신 소켓 연결 여부
        self.disable_flag = False      # 비활성화 여부

        self.recv_thread: ThreadWithException = None

        asyncio.run(self.socket_process())

    def __del__(self):
        self.close_socket()

    # ------------------------------------------------------------------ #
    # 메인 프로세스: 연결관리 + 송신을 async task 로 동시 실행
    # ------------------------------------------------------------------ #
    async def socket_process(self):
        init_task = asyncio.create_task(self.init_process())
        send_task = asyncio.create_task(self.send_process())
        await init_task
        await send_task

    # ------------------------------------------------------------------ #
    # 추상 메서드 (client/server 가 각자 구현)
    # ------------------------------------------------------------------ #
    @abstractmethod
    def connect_socket(self) -> bool:
        """소켓을 생성하고 연결한다. 성공하면 True."""
        pass

    @abstractmethod
    def close_socket(self):
        """소켓을 닫고 연결 상태를 False 로 만든다."""
        pass

    # ------------------------------------------------------------------ #
    # 연결 관리: 끊겨 있으면 재접속, 성공하면 수신 스레드 시작
    # ------------------------------------------------------------------ #
    async def init_process(self):
        while self.socket_start is True:
            if self.client_connect is False and self.disable_flag is False:
                if self.connect_socket() is True:
                    self.client_connect = True
                    self._start_recv_thread()
                    self.send_state(True, StateType.CONNECT)
            await asyncio.sleep(self.RECONNECT_DELAY)

    def _start_recv_thread(self):
        """기존 수신 스레드가 살아있으면 정리하고 새로 시작."""
        try:
            if self.recv_thread is not None and self.recv_thread.run_flag is True:
                self.recv_thread.raise_exception()
        except Exception:
            print(traceback.format_exc())
        finally:
            self.recv_thread = None

        self.recv_thread = ThreadWithException(self.recv_process)
        self.recv_thread.start()

    def restart(self):
        """현재 연결을 끊고 재접속을 유도한다 (init_process 가 다시 붙음)."""
        self.send_state("재시작하기 위해 종료합니다.", StateType.INFO)
        self.close_socket()
        self.init_log_flag = False

    # ------------------------------------------------------------------ #
    # 수신 프로세스 (별도 스레드)
    #   빈 데이터가 EMPTY_DATA_LIMIT 만큼 연속되면 끊김으로 판단해 재접속
    #   예외 발생 시에도 재접속
    # ------------------------------------------------------------------ #
    def recv_process(self):
        empty_count = 0
        self.send_state("수신 프로세스 시작", StateType.INFO)

        while self.client_connect is True:
            try:
                received_data = self.client_socket.recv(self.RECV_BUFFER_SIZE)
                if not received_data:
                    if empty_count >= self.EMPTY_DATA_LIMIT:
                        empty_count = 0
                        raise Exception("빈 데이터가 연속으로 들어옴")
                    empty_count += 1
                else:
                    empty_count = 0
                    self.send_state(received_data, StateType.RECEIVE)
            except Exception:
                if self.socket_start is True and self.client_connect is True:
                    self.send_state(
                        "데이터 수신 도중 예외가 발생하여 재시작합니다. 예외 메시지: "
                        + str(traceback.format_exc()),
                        StateType.ERROR,
                    )
                    self.restart()
            time.sleep(self.RECV_LOOP_DELAY)

        self.send_state("수신 프로세스 종료", StateType.INFO)

    # ------------------------------------------------------------------ #
    # 송신 프로세스 (async task)
    #   큐에서 꺼낸 값이 제어 명령이면 _handle_control 로, 아니면 그대로 전송
    # ------------------------------------------------------------------ #
    async def send_process(self):
        while self.socket_start is True:
            while self.send_queue.qsize() > 0:
                try:
                    send_data = self.send_queue.get()

                    if send_data in ControlCommand.ALL:
                        keep_running = self._handle_control(send_data)
                        if keep_running is False:
                            return   # STOP: 송신 루프 종료
                        continue

                    if self.client_connect is True:
                        self.client_socket.sendall(send_data)

                except Exception as e:
                    print(traceback.format_exc())
                    self.send_state("예외가 발생했습니다. 예외 메시지: " + str(e),
                                    StateType.ERROR)
                await asyncio.sleep(self.SEND_LOOP_DELAY)
            await asyncio.sleep(self.SEND_LOOP_DELAY)

    def _handle_control(self, command: bytes) -> bool:
        """제어 명령 처리. 계속 돌면 True, STOP이면 False 반환."""
        if command == ControlCommand.RESTART:
            self.send_state("재시작 명령이 들어와 재시작 합니다.", StateType.INFO)
            self.restart()
            return True

        if command == ControlCommand.STOP:
            self.socket_start = False
            self.close_socket()
            return False

        if command == ControlCommand.DISABLE:
            self.disable_flag = True
            self.send_state("비활성화 명령이 들어왔습니다", StateType.INFO)
            self.close_socket()
            return True

        if command == ControlCommand.ENABLE:
            self.send_state("비활성화 해제 명령이 들어왔습니다", StateType.INFO)
            self.disable_flag = False
            self.init_log_flag = False
            return True

        return True

    # ------------------------------------------------------------------ #
    # 상태 데이터 전송
    # ------------------------------------------------------------------ #
    def send_state(self, data, state_type: str):
        self.received_queue.put({
            "type": state_type,
            "time": datetime.datetime.now(),
            "socket_type": self.socket_type,
            "data": data,
        })


class SocketClient(SocketFrame):
    """클라이언트: 서버에 connect."""

    def connect_socket(self) -> bool:
        try:
            if self.init_log_flag is False:
                self.send_state("클라이언트를 시작합니다.", StateType.INFO)
                self.send_state("서버에 연결을 시도합니다...", StateType.INFO)

            self.client_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.client_socket.settimeout(self.timeout)
            if self.bind_ip is not None:
                self.client_socket.bind((self.bind_ip, 0))
            self.client_socket.connect((self.host, self.port))

            self.send_state("서버에 연결되었습니다.", StateType.INFO)
            return True
        except Exception as e:
            if self.init_log_flag is False:
                self.send_state("서버에 연결 도중 예외가 발생하였습니다. 예외 메시지: " + str(e),
                                StateType.ERROR)
                self.init_log_flag = True
            self.close_socket()
        return False

    def close_socket(self):
        self.client_connect = False
        if self.client_socket is not None:
            try:
                self.client_socket.close()
            except Exception:
                pass
            self.client_socket = None
        self.send_state(False, StateType.CONNECT)


class SocketServer(SocketFrame):
    """서버: bind / listen / accept."""

    def connect_socket(self) -> bool:
        try:
            if self.init_log_flag is False:
                self.send_state("서버를 시작합니다.", StateType.INFO)
                self.send_state("서버를 설정합니다...", StateType.INFO)

            self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.server_socket.settimeout(self.timeout)
            self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.server_socket.bind((self.host, self.port))
            self.server_socket.listen()

            self.client_socket, connect_addr = self.server_socket.accept()
            self.send_state("클라이언트가 접속 했습니다. 클라이언트 주소 :" + str(connect_addr),
                            StateType.INFO)
            return True
        except Exception as e:
            if self.init_log_flag is False:
                self.send_state("서버 설정 도중 예외가 발생했습니다. 예외 메시지: " + str(e),
                                StateType.ERROR)
                self.init_log_flag = True
            self.close_socket()
        return False

    def close_socket(self):
        self.client_connect = False
        if self.client_socket is not None:
            try:
                self.client_socket.close()
            except Exception:
                pass
            self.client_socket = None
        if self.server_socket is not None:
            try:
                self.server_socket.close()
            except Exception:
                pass
            self.server_socket = None
        self.send_state(False, StateType.CONNECT)
        self.send_state("통신 프로그램 종료", StateType.INFO)


# ---------------------------------------------------------------------- #
# 프로세스 진입 함수
# ---------------------------------------------------------------------- #
def socket_server_start(host: str, port: int, socket_type: str,
                        received_queue: mp.Queue, send_queue: mp.Queue,
                        timeout=None, bind_ip=None):
    print("소켓 서버 실행")
    SocketServer(host, port, socket_type, received_queue, send_queue, timeout, bind_ip)


def socket_client_start(host: str, port: int, socket_type: str,
                        received_queue: mp.Queue, send_queue: mp.Queue,
                        timeout=None, bind_ip=None):
    print("소켓 클라이언트 실행")
    SocketClient(host, port, socket_type, received_queue, send_queue, timeout, bind_ip)