# -*- coding: utf-8 -*-
"""
tcp_socket_module.py
====================
소켓 프로세스(tcp_socket.py) <-> 메인 로직 사이를 잇는 계층.

구조
  TcpSocketModule : 소켓 프로세스를 mp.Process 로 띄우고, 내부 큐로 주고받는 저수준 관리자.
                    - socket_send_queue     : Module -> 소켓 프로세스 (전송/제어)
                    - socket_received_queue : 소켓 프로세스 -> Module (상태/수신)
                    수신 데이터를 data_buffer 에 쌓고, 연결 상태를 관리한다.

  TcpSocketFrame  : 사용자가 상속해서 쓰는 추상 클래스.
                    - 바깥(메인 로직)과는 send_queue / recv_queue 로 통신
                    - 안쪽 TcpSocketModule 을 통해 실제 소켓과 연결
                    - async task 2개(recv_process / send_process) +
                      상태처리 스레드 1개(socket_data_process)

  [2겹 큐 그림]
    메인로직 ──send_queue/recv_queue──> TcpSocketFrame
                                          └ TcpSocketModule
                                              └ socket_send_queue/socket_received_queue
                                                  └ 소켓 프로세스(tcp_socket.py)

제어 명령은 tcp_socket.ControlCommand 상수를, 상태 타입은 tcp_socket.StateType 상수를 공유한다.
"""

import time
import asyncio
import logging
import datetime
import threading
import traceback
import multiprocessing as mp
from abc import ABCMeta, abstractmethod
from collections import deque
from logging import Logger

from src.module.logger import LoggerPrint
from src.module.thread_with_exception import ThreadWithException
from src.socket_module.tcp_socket import (
    socket_server_start, socket_client_start, ControlCommand, StateType,
)


class TcpSocketModule:
    """소켓 프로세스를 띄우고 내부 큐로 통신하는 저수준 관리자."""

    DATA_PROCESS_DELAY = 0.01   # 상태처리 루프 간격(초)

    def __init__(self, socket_name: str, ip_address: str, port: int,
                 socket_timeout: int = None, receive_timeout: int = 0,
                 server_flag: bool = False, buffer_bytes_flag: bool = False,
                 bind_ip: str = None, logger: Logger = None):
        self.logger = logger if logger is not None else LoggerPrint(socket_name)

        # 소켓 설정
        self.socket_name = socket_name
        self.ip_address = ip_address
        self.port = port
        self.socket_timeout = socket_timeout
        self.receive_timeout = receive_timeout
        self.server_flag = server_flag
        self.bind_ip = bind_ip

        # 소켓 프로세스와 주고받는 내부 큐
        self.socket_send_queue = mp.Queue()       # Module -> 소켓 프로세스
        self.socket_received_queue = mp.Queue()   # 소켓 프로세스 -> Module
        self.socket_process: mp.Process = None

        # 수신 버퍼 / 상태
        # 버퍼는 상태처리 스레드(socket_data_process)가 쌓고,
        # recv_process(다른 스레드)가 꺼내가므로 락으로 보호한다.
        self.buffer_bytes_flag = buffer_bytes_flag
        self.data_buffer = bytes() if buffer_bytes_flag else deque()
        self._buffer_lock = threading.Lock()
        self.received_time = datetime.datetime.now()
        self.received_connect = False     # 실제 데이터를 받은 적 있는지
        self.connect_flag = False         # 소켓 연결 여부

        self.start_socket()

    def __del__(self):
        self.final_close()

    # ------------------------------------------------------------------ #
    # 소켓 프로세스 시작
    # ------------------------------------------------------------------ #
    def start_socket(self):
        entry_func = socket_server_start if self.server_flag else socket_client_start
        self.socket_process = mp.Process(
            target=entry_func, name=self.socket_name,
            args=(self.ip_address, self.port, self.socket_name,
                  self.socket_received_queue, self.socket_send_queue,
                  self.socket_timeout, self.bind_ip),
        )
        self.socket_process.start()

    # ------------------------------------------------------------------ #
    # 소켓 프로세스가 올려보낸 상태 데이터 처리
    #   루프: 큐를 비우면서 타입별 처리 -> 수신 타임아웃 검사
    # ------------------------------------------------------------------ #
    def socket_data_process(self):
        while self.socket_received_queue.qsize() > 0:
            state = self.socket_received_queue.get()
            self._handle_state(state)

        self._check_receive_timeout()

    def _handle_state(self, state: dict):
        """상태 데이터 하나를 타입에 따라 처리."""
        data_type = state["type"]
        data = state["data"]

        try:
            if data_type == StateType.ERROR:
                raise Exception(data)

            elif data_type == StateType.RECEIVE:
                self._append_recv_buffer(data)
                self.received_time = datetime.datetime.now()
                self.received_connect = True

            elif data_type == StateType.INFO:
                self.logger.info(data)

            elif data_type == StateType.CONNECT:
                self._handle_connect_state(data)

            else:
                raise Exception("소켓 데이터의 타입을 알 수 없습니다.")
        except Exception:
            self.logger.warning(f"Socket Data Error: {traceback.format_exc()}")

    def _append_recv_buffer(self, data):
        """수신 데이터를 버퍼에 누적 (bytes 모드 / deque 모드)."""
        with self._buffer_lock:
            if self.buffer_bytes_flag:
                self.data_buffer += data
            else:
                self.data_buffer.append(data)

    def pop_recv_buffer(self):
        """수신 버퍼에서 처리할 데이터를 꺼낸다. 꺼낸 만큼 버퍼에서 제거된다.

        - bytes 모드 : 지금까지 쌓인 스트림 전체를 반환하고 버퍼를 비운다.
        - deque 모드 : 가장 먼저 들어온 전문 1개를 꺼낸다.
        버퍼가 비어 있으면 None 을 반환한다.
        """
        with self._buffer_lock:
            if not self.data_buffer:
                return None
            if self.buffer_bytes_flag:
                data = self.data_buffer
                self.data_buffer = bytes()
                return data
            return self.data_buffer.popleft()

    def _handle_connect_state(self, connected: bool):
        """연결 상태 변경 처리. 새로 연결되면 버퍼를 비우고 상태를 초기화."""
        self.connect_flag = connected
        if connected is True:
            self.received_time = datetime.datetime.now()
            self.received_connect = False
            self._clear_recv_buffer()

    def _clear_recv_buffer(self):
        with self._buffer_lock:
            if self.buffer_bytes_flag:
                self.data_buffer = bytes()
            else:
                self.data_buffer.clear()

    def _check_receive_timeout(self):
        """연결돼 있는데 일정 시간 데이터가 안 오면 강제 재접속."""
        if self.connect_flag is not True:
            return
        if self.receive_timeout == 0:
            return

        try:
            time_diff = datetime.datetime.now() - self.received_time
            if time_diff >= datetime.timedelta(seconds=self.receive_timeout):
                self.logger.warning(f"[{self.socket_name}] failed to receive data")
                self.reconnect()
        except Exception as e:
            self.logger.warning(f"[{self.socket_name}] Exception: {e}\n{traceback.format_exc()}")

    # ------------------------------------------------------------------ #
    # 제어 명령 (소켓 프로세스로 ControlCommand 전송)
    # ------------------------------------------------------------------ #
    def reconnect(self):
        """현재 연결을 끊고 재접속 유도."""
        self.connect_flag = False
        self.socket_send_queue.put(ControlCommand.RESTART)

    def final_close(self):
        """소켓 프로세스를 완전히 종료."""
        self.logger.info("프로그램 종료 요청")
        self.socket_send_queue.put(ControlCommand.STOP)
        self.socket_process.join(timeout=1)
        if self.socket_process.is_alive() is True:
            self.socket_process.kill()
        self.logger.info("프로그램 종료 완료")


class TcpSocketFrame(metaclass=ABCMeta):
    """사용자가 상속해서 쓰는 통신 베이스 (추상 클래스)."""

    ALL_SEND_INTERVAL = 3       # 전체 송신 주기(초)
    SEND_LOOP_DELAY   = 0.01
    RECV_LOOP_DELAY   = 0.01
    RECV_ITEM_DELAY   = 0.001
    DATA_LOOP_DELAY   = 0.01

    def __init__(self, program_name: str, parameter: dict,
                 send_queue: mp.Queue, recv_queue: mp.Queue,
                 logger: logging.Logger | None, stop_event: mp.Event):
        self.socket_name = program_name
        self.logger = logger if logger is not None else LoggerPrint(program_name)

        # 바깥(메인 로직)과 통신하는 큐
        self.send_queue = send_queue
        self.recv_queue = recv_queue
        self.stop_event = stop_event

        # 상태 변수
        self.connect_flag: bool = None       # 바깥에 알린 연결 상태
        self.write_time = datetime.datetime.now()   # 마지막 전체 송신 시각
        self.task_list: list = []

        # 소켓 모듈 파라미터
        self.socket_module = TcpSocketModule(
            socket_name=program_name,
            ip_address=parameter.get("ip_address"),
            port=parameter.get("port"),
            socket_timeout=parameter.get("socket_timeout", None),
            receive_timeout=parameter.get("receive_timeout", 0),
            buffer_bytes_flag=parameter.get("buffer_bytes_flag", False),
            server_flag=parameter.get("server_flag"),
            bind_ip=parameter.get("bind_ip"),
            logger=logger,
        )

        # 소켓 모듈의 상태 처리를 별도 스레드로 가동
        self.socket_data_process_thread = ThreadWithException(self._run_data_process)
        self.socket_data_process_thread.start()

    def __del__(self):
        self.close()

    def close(self):
        self.socket_module.final_close()
        self.socket_data_process_thread.raise_exception()
        self.logger.info("프로그램 종료")

    # ------------------------------------------------------------------ #
    # 메인 진입: 수신/송신 async task 가동
    # ------------------------------------------------------------------ #
    async def run_process(self):
        self.task_list.append(asyncio.create_task(self.recv_process()))
        self.task_list.append(asyncio.create_task(self.send_process()))
        for task in self.task_list:
            await task

    def _run_data_process(self):
        """소켓 모듈의 상태 처리 루프 (별도 스레드)."""
        while not self.stop_event.is_set():
            self.socket_module.socket_data_process()
            time.sleep(self.DATA_LOOP_DELAY)

    # ------------------------------------------------------------------ #
    # 송신 처리
    #   바깥 send_queue 의 명령(send/disable/reconnect/exit)을 해석해 처리
    #   + 주기적 전체 송신 + 연결 상태 통지
    # ------------------------------------------------------------------ #
    async def send_process(self):
        while not self.stop_event.is_set():
            try:
                while self.send_queue.qsize() != 0:
                    self._handle_send_command(self.send_queue.get())

                self._tick_all_send()
                self.send_connect_state()
            except Exception as e:
                self.logger.warning(f"송신 처리 도중 예외 발생: {e}\n{traceback.format_exc()}")
            await asyncio.sleep(self.SEND_LOOP_DELAY)

    def _handle_send_command(self, command: dict):
        """바깥에서 들어온 송신 명령 하나를 처리."""
        try:
            cmd_type = command.get("type")

            if cmd_type == "send":
                if self.socket_module.connect_flag is True:
                    self.send_data_process(command.get("data"))

            elif cmd_type == "disable":
                if command.get("data") is True:
                    self.socket_module.socket_send_queue.put(ControlCommand.DISABLE)
                else:
                    self.socket_module.socket_send_queue.put(ControlCommand.ENABLE)

            elif cmd_type == "reconnect":
                self.socket_module.socket_send_queue.put(ControlCommand.RESTART)

            elif cmd_type == "exit":
                self.close()
        except Exception as e:
            self.logger.warning(f"Exception: {e}\n{traceback.format_exc()}")

    def _tick_all_send(self):
        """ALL_SEND_INTERVAL 초마다 전체 송신 실행."""
        now = datetime.datetime.now()
        if now - self.write_time >= datetime.timedelta(seconds=self.ALL_SEND_INTERVAL):
            self.all_send_data_process()
            self.write_time = now

    # ------------------------------------------------------------------ #
    # 수신 처리: 소켓 모듈 버퍼에 쌓인 데이터를 꺼내 recv_data_process 로
    # ------------------------------------------------------------------ #
    async def recv_process(self):
        while not self.stop_event.is_set():
            while len(self.socket_module.data_buffer) != 0:
                try:
                    recv_data = self._pop_recv_data()
                    if recv_data is None:
                        break   # 재접속 등으로 다른 스레드가 먼저 비운 경우
                    self.recv_data_process(recv_data)
                except Exception:
                    self.logger.warning(f"수신 처리 도중 예외 발생: {traceback.format_exc()}")
                await asyncio.sleep(self.RECV_ITEM_DELAY)
            await asyncio.sleep(self.RECV_LOOP_DELAY)

    def _pop_recv_data(self):
        """버퍼에서 수신 데이터를 꺼낸다. 비어 있으면 None."""
        return self.socket_module.pop_recv_buffer()

    # ------------------------------------------------------------------ #
    # 연결 상태 통지: 실제 연결 + 수신이 모두 True 일 때만 연결됨으로 본다
    # ------------------------------------------------------------------ #
    def send_connect_state(self):
        now_connect = (self.socket_module.connect_flag is True and
                       self.socket_module.received_connect is True)
        if self.connect_flag != now_connect:
            self.recv_queue.put({"type": StateType.CONNECT, "data": now_connect})
            self.connect_flag = now_connect

    # ------------------------------------------------------------------ #
    # 자식이 구현하는 추상 메서드
    # ------------------------------------------------------------------ #
    @abstractmethod
    def all_send_data_process(self):
        """주기적(ALL_SEND_INTERVAL초)으로 전체 데이터를 송신."""
        pass

    @abstractmethod
    def send_data_process(self, send_data):
        """보낼 데이터를 실제 전송 형태로 가공해 송신."""
        pass

    @abstractmethod
    def recv_data_process(self, recv_data):
        """받은 데이터를 해석해 recv_queue 로 올림."""
        pass