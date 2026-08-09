# -*- coding: utf-8 -*-
"""
MELSEC MC Protocol (3E Frame, Binary, TCP) Client
--------------------------------------------------
미쓰비시 MELSEC Q / L / iQ-R 시리즈용 MC 프로토콜 클라이언트.
외부 라이브러리 없이 표준 socket 만 사용합니다.

PLC 측 사전 설정 (GX Works2/3):
  - 내장 Ethernet 포트 > 오픈 설정
      프로토콜   : TCP
      오픈 방식   : MC 프로토콜
      자국 포트번호: 5007 (예시, 임의 지정 가능)
      교신 데이터 코드: 바이너리
  - 설정 후 PLC 리셋 필요

사용 예:
    with MCProtocolClient("192.168.0.10", 5007) as plc:
        print(plc.read_words("D100", 10))
        print(plc.read_bits("M0", 16))
        plc.write_words("D200", [1, 2, 3])
        plc.write_bits("M100", [1, 0, 1])
"""

from __future__ import annotations

import socket
import struct
import threading
import time
from typing import List, Sequence, Tuple

# ---------------------------------------------------------------------------
# 디바이스 코드 정의
# ---------------------------------------------------------------------------

# Q / L 시리즈: 디바이스 코드 1바이트, 디바이스 번호 3바이트
DEVICE_CODES = {
    "SM": 0x91, "SD": 0xA9,
    "X": 0x9C, "Y": 0x9D, "M": 0x90, "L": 0x92, "F": 0x93, "V": 0x94,
    "B": 0xA0, "D": 0xA8, "W": 0xB4,
    "TS": 0xC1, "TC": 0xC0, "TN": 0xC2,
    "SS": 0xC7, "SC": 0xC6, "SN": 0xC8,
    "CS": 0xC4, "CC": 0xC3, "CN": 0xC5,
    "SB": 0xA1, "SW": 0xB5, "S": 0x98,
    "DX": 0xA2, "DY": 0xA3, "Z": 0xCC,
    "R": 0xAF, "ZR": 0xB0,
}

# 디바이스 번호를 16진수로 표기하는 디바이스들 (X, Y, B, W 등)
HEX_DEVICES = {"X", "Y", "B", "W", "SB", "SW", "DX", "DY"}

# 긴 이름부터 매칭해야 함 (SD 를 S + D 로 오인하지 않도록)
_DEVICE_NAMES_SORTED = sorted(DEVICE_CODES.keys(), key=len, reverse=True)

# 워드 단위로만 접근 가능한 디바이스 (비트 접근 불가)
WORD_ONLY_DEVICES = {"D", "W", "R", "ZR", "SD", "TN", "CN", "SN", "Z"}


# ---------------------------------------------------------------------------
# 예외
# ---------------------------------------------------------------------------

class MCProtocolError(Exception):
    """MC 프로토콜 통신/응답 오류"""


class MCConnectionError(MCProtocolError):
    """소켓 연결 오류"""


class MCResponseError(MCProtocolError):
    """PLC 가 에러 종료코드를 반환한 경우"""

    def __init__(self, end_code: int, detail: bytes = b""):
        self.end_code = end_code
        self.detail = detail
        super().__init__(
            f"PLC 응답 오류 - 종료코드 0x{end_code:04X}"
            f"{' / 상세 ' + detail.hex().upper() if detail else ''}"
        )


# 자주 만나는 종료코드 설명
END_CODE_HINTS = {
    0x0055: "온라인 변경 불가 설정",
    0xC050: "ASCII/바이너리 코드 설정 불일치",
    0xC051: "읽기/쓰기 점수가 허용 범위를 초과",
    0xC056: "요청 주소가 디바이스 범위를 초과",
    0xC058: "요청 데이터 길이 불일치",
    0xC059: "지원하지 않는 커맨드/서브커맨드",
    0xC05B: "지정한 디바이스에 접근 불가",
    0xC05C: "요청 내용에 오류 (비트 디바이스에 워드 지정 등)",
    0xC060: "비트 디바이스 데이터 지정 오류",
    0xC061: "요청 데이터 길이가 실제와 다름",
    0xC0B5: "지정 불가한 데이터를 지정",
}


# ---------------------------------------------------------------------------
# 클라이언트
# ---------------------------------------------------------------------------

class MCProtocolClient:
    """
    MC 프로토콜 3E 프레임 바이너리 클라이언트 (TCP)

    Args:
        host:        PLC IP 주소
        port:        MC 프로토콜 오픈 설정 포트 (기본 5007)
        plc_type:    "Q" (Q/L/QnA 시리즈) 또는 "R" (iQ-R 시리즈)
        timeout:     소켓 타임아웃(초)
        network_no:  네트워크 번호 (자국은 0x00)
        pc_no:       PC 번호 (자국은 0xFF)
        auto_reconnect: 통신 실패 시 1회 재접속 후 재시도
    """

    # 커맨드
    _CMD_BATCH_READ = 0x0401
    _CMD_BATCH_WRITE = 0x1401

    def __init__(
        self,
        host: str,
        port: int = 5007,
        plc_type: str = "Q",
        timeout: float = 3.0,
        network_no: int = 0x00,
        pc_no: int = 0xFF,
        auto_reconnect: bool = True,
    ):
        plc_type = plc_type.upper()
        if plc_type not in ("Q", "R"):
            raise ValueError("plc_type 은 'Q' 또는 'R' 이어야 합니다")

        self.host = host
        self.port = port
        self.plc_type = plc_type
        self.timeout = timeout
        self.network_no = network_no
        self.pc_no = pc_no
        self.auto_reconnect = auto_reconnect

        # 감시 타이머: 250ms 단위. 0x0010 = 4초
        self.monitoring_timer = 0x0010

        self._sock: socket.socket | None = None
        self._lock = threading.RLock()

    # -- 연결 관리 ---------------------------------------------------------

    @property
    def is_connected(self) -> bool:
        return self._sock is not None

    def connect(self) -> None:
        with self._lock:
            self.close()
            try:
                self._sock = socket.create_connection(
                    (self.host, self.port), timeout=self.timeout
                )
                self._sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            except OSError as e:
                self._sock = None
                raise MCConnectionError(
                    f"PLC 연결 실패 {self.host}:{self.port} - {e}"
                ) from e

    def close(self) -> None:
        with self._lock:
            if self._sock is not None:
                try:
                    self._sock.close()
                except OSError:
                    pass
                self._sock = None

    def __enter__(self) -> "MCProtocolClient":
        self.connect()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    # -- 디바이스 파싱 -----------------------------------------------------

    @staticmethod
    def parse_device(device: str) -> Tuple[str, int]:
        """'D100' -> ('D', 100),  'X1A' -> ('X', 26)"""
        device = device.strip().upper().replace(" ", "")
        for name in _DEVICE_NAMES_SORTED:
            if device.startswith(name):
                num_part = device[len(name):]
                if not num_part:
                    raise ValueError(f"디바이스 번호가 없습니다: {device}")
                base = 16 if name in HEX_DEVICES else 10
                try:
                    return name, int(num_part, base)
                except ValueError:
                    raise ValueError(
                        f"디바이스 번호 형식 오류: {device} "
                        f"({name} 는 {base}진수)"
                    ) from None
        raise ValueError(f"지원하지 않는 디바이스: {device}")

    def _build_device_spec(self, dev_name: str, dev_num: int, count: int) -> bytes:
        code = DEVICE_CODES[dev_name]
        if self.plc_type == "R":
            # iQ-R: 디바이스 번호 4바이트 + 디바이스 코드 2바이트
            spec = struct.pack("<IH", dev_num, code)
        else:
            # Q/L: 디바이스 번호 3바이트 + 디바이스 코드 1바이트
            spec = struct.pack("<I", dev_num)[:3] + bytes([code])
        return spec + struct.pack("<H", count)

    def _subcommand(self, bit_unit: bool) -> int:
        if self.plc_type == "R":
            return 0x0003 if bit_unit else 0x0002
        return 0x0001 if bit_unit else 0x0000

    # -- 프레임 송수신 -----------------------------------------------------

    def _build_frame(self, command: int, subcommand: int, payload: bytes) -> bytes:
        body = struct.pack("<HHH", self.monitoring_timer, command, subcommand) + payload
        header = struct.pack(
            "<HBBHB",
            0x0050,           # 서브헤더 (요청) 50 00
            self.network_no,  # 네트워크 번호
            self.pc_no,       # PC 번호
            0x03FF,           # 요구처 유닛 I/O 번호
            0x00,             # 요구처 유닛 국번호
        )
        return header + struct.pack("<H", len(body)) + body

    def _recv_exact(self, size: int) -> bytes:
        buf = bytearray()
        while len(buf) < size:
            try:
                chunk = self._sock.recv(size - len(buf))
            except socket.timeout as e:
                raise MCConnectionError(f"응답 타임아웃 ({self.timeout}s)") from e
            except OSError as e:
                raise MCConnectionError(f"수신 오류: {e}") from e
            if not chunk:
                raise MCConnectionError("PLC 가 연결을 끊었습니다")
            buf.extend(chunk)
        return bytes(buf)

    def _transact(self, command: int, subcommand: int, payload: bytes) -> bytes:
        """요청 전송 후 응답 데이터부(종료코드 제외)를 반환"""
        frame = self._build_frame(command, subcommand, payload)

        with self._lock:
            for attempt in (1, 2):
                try:
                    if self._sock is None:
                        self.connect()
                    self._sock.sendall(frame)

                    # 응답 헤더 9바이트 = 서브헤더2 + 네트워크1 + PC1 + I/O2 + 국번1 + 길이2
                    head = self._recv_exact(9)
                    if head[0:2] != b"\xD0\x00":
                        raise MCProtocolError(
                            f"예상치 못한 응답 서브헤더: {head[0:2].hex().upper()}"
                        )
                    (data_len,) = struct.unpack("<H", head[7:9])
                    body = self._recv_exact(data_len)

                except MCConnectionError:
                    self.close()
                    if attempt == 1 and self.auto_reconnect:
                        time.sleep(0.1)
                        continue
                    raise
                break

        (end_code,) = struct.unpack("<H", body[0:2])
        if end_code != 0x0000:
            hint = END_CODE_HINTS.get(end_code)
            err = MCResponseError(end_code, body[2:])
            if hint:
                err.args = (f"{err.args[0]} ({hint})",)
            raise err

        return body[2:]

    # -- 워드 단위 읽기/쓰기 -----------------------------------------------

    def read_words(self, device: str, count: int = 1, signed: bool = False) -> List[int]:
        """워드(16bit) 일괄 읽기. 예: read_words('D100', 10)"""
        if count < 1:
            raise ValueError("count 는 1 이상이어야 합니다")
        name, num = self.parse_device(device)
        spec = self._build_device_spec(name, num, count)
        data = self._transact(self._CMD_BATCH_READ, self._subcommand(False), spec)

        expected = count * 2
        if len(data) < expected:
            raise MCProtocolError(
                f"응답 데이터 부족: {len(data)}바이트 (기대 {expected})"
            )
        fmt = f"<{count}{'h' if signed else 'H'}"
        return list(struct.unpack(fmt, data[:expected]))

    def write_words(self, device: str, values: Sequence[int]) -> None:
        """워드 일괄 쓰기. 예: write_words('D200', [1, 2, 3])"""
        if not values:
            raise ValueError("values 가 비어 있습니다")
        name, num = self.parse_device(device)
        spec = self._build_device_spec(name, num, len(values))
        payload = spec + b"".join(
            struct.pack("<h" if v < 0 else "<H", v) for v in values
        )
        self._transact(self._CMD_BATCH_WRITE, self._subcommand(False), payload)

    # -- 비트 단위 읽기/쓰기 -----------------------------------------------

    def read_bits(self, device: str, count: int = 1) -> List[int]:
        """비트 일괄 읽기. 0/1 리스트 반환. 예: read_bits('M0', 16)"""
        if count < 1:
            raise ValueError("count 는 1 이상이어야 합니다")
        name, num = self.parse_device(device)
        if name in WORD_ONLY_DEVICES:
            raise ValueError(f"{name} 는 워드 디바이스라 비트 접근할 수 없습니다")

        spec = self._build_device_spec(name, num, count)
        data = self._transact(self._CMD_BATCH_READ, self._subcommand(True), spec)

        # 1바이트에 2점: 상위 니블 = 앞 점, 하위 니블 = 뒤 점
        bits: List[int] = []
        for byte in data:
            bits.append((byte >> 4) & 0x01)
            bits.append(byte & 0x01)
        return bits[:count]

    def write_bits(self, device: str, values: Sequence[int]) -> None:
        """비트 일괄 쓰기. 예: write_bits('M100', [1, 0, 1])"""
        if not values:
            raise ValueError("values 가 비어 있습니다")
        name, num = self.parse_device(device)
        if name in WORD_ONLY_DEVICES:
            raise ValueError(f"{name} 는 워드 디바이스라 비트 접근할 수 없습니다")

        bits = [1 if v else 0 for v in values]
        if len(bits) % 2:
            bits.append(0)  # 홀수면 패딩

        packed = bytes(
            ((bits[i] & 0x01) << 4) | (bits[i + 1] & 0x01)
            for i in range(0, len(bits), 2)
        )
        spec = self._build_device_spec(name, num, len(values))
        self._transact(self._CMD_BATCH_WRITE, self._subcommand(True), spec + packed)

    # -- 단일 접근 편의 메서드 ---------------------------------------------

    def read_word(self, device: str, signed: bool = False) -> int:
        return self.read_words(device, 1, signed=signed)[0]

    def write_word(self, device: str, value: int) -> None:
        self.write_words(device, [value])

    def read_bit(self, device: str) -> int:
        return self.read_bits(device, 1)[0]

    def write_bit(self, device: str, value: int) -> None:
        self.write_bits(device, [value])

    # -- 확장 데이터 타입 --------------------------------------------------

    def read_int32(self, device: str, count: int = 1, signed: bool = True) -> List[int]:
        """32bit 정수 읽기 (하위워드 우선)"""
        words = self.read_words(device, count * 2)
        raw = struct.pack(f"<{len(words)}H", *words)
        return list(struct.unpack(f"<{count}{'i' if signed else 'I'}", raw))

    def write_int32(self, device: str, values: Sequence[int]) -> None:
        raw = b"".join(struct.pack("<i" if v < 0 else "<I", v) for v in values)
        words = struct.unpack(f"<{len(raw) // 2}H", raw)
        self.write_words(device, list(words))

    def read_float32(self, device: str, count: int = 1) -> List[float]:
        """32bit 실수(FLOAT) 읽기"""
        words = self.read_words(device, count * 2)
        raw = struct.pack(f"<{len(words)}H", *words)
        return list(struct.unpack(f"<{count}f", raw))

    def write_float32(self, device: str, values: Sequence[float]) -> None:
        raw = b"".join(struct.pack("<f", v) for v in values)
        words = struct.unpack(f"<{len(raw) // 2}H", raw)
        self.write_words(device, list(words))

    def read_string(self, device: str, length: int) -> str:
        """문자열 읽기 (1워드 = 2문자, 하위바이트 우선)"""
        word_count = (length + 1) // 2
        words = self.read_words(device, word_count)
        raw = struct.pack(f"<{word_count}H", *words)
        return raw[:length].split(b"\x00")[0].decode("ascii", errors="ignore")

    def write_string(self, device: str, text: str, length: int) -> None:
        raw = text.encode("ascii")[:length].ljust(
            length + (length % 2), b"\x00"
        )
        words = struct.unpack(f"<{len(raw) // 2}H", raw)
        self.write_words(device, list(words))


# ---------------------------------------------------------------------------
# 동작 확인용
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    PLC_IP = "192.168.0.10"
    PLC_PORT = 5007

    try:
        with MCProtocolClient(PLC_IP, PLC_PORT, plc_type="Q") as plc:
            print("연결 성공")

            print("D100~D109 :", plc.read_words("D100", 10))
            print("M0~M15    :", plc.read_bits("M0", 16))
            print("X0~X0F    :", plc.read_bits("X0", 16))

            plc.write_word("D200", 1234)
            print("D200 확인 :", plc.read_word("D200"))

            plc.write_bit("M100", 1)
            print("M100 확인 :", plc.read_bit("M100"))

    except MCProtocolError as e:
        print(f"오류: {e}")