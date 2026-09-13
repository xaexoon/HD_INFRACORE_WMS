# -*- coding: utf-8 -*-
"""로그 설정.

    [2026-08-26 14:03:11] INFO  [API][pick] - 확정 요청 pick_no=P260826001
    [2026-08-26 14:03:15] INFO  [BATCH][if] - I/F 가공 총 12 (성공 11 / 스킵 1)

로거 이름을 "채널.도메인" 으로 지으면 포매터가 두 칸으로 나눠 찍는다.
    get_logger("api.pick")  ->  [API][pick]
    get_logger("db")        ->  [DB]
    채널이 아닌 이름(uvicorn 등)은 전부 [LIB] 로 간다.

    ※ 메시지 본문에 [pick] 같은 태그를 손으로 붙이지 말 것. 두 번 찍힌다.

파일은 프로세스마다 따로 쓴다 (logs/web.log, scheduler.log, main.log).
여러 프로세스가 한 파일에 동시에 쓰면 줄이 유실되기 때문이다.
어느 파일에 쓸지는 프로세스 이름으로 정하므로, main.py 의 Process(name=...)
와 _PROCESS_FILE 의 키가 짝이 맞아야 한다.

보관
    매일 자정에 web.log -> web.log.2026-09-08 로 넘어간다.
    KEEP_DAYS 가 지난 것은 월별 zip 으로 묶어 logs/archive 로 옮긴다.
"""

import os
import logging
import zipfile
import datetime
import multiprocessing as mp
from logging.handlers import TimedRotatingFileHandler

LOG_DIR = "logs"
ARCHIVE_DIR = os.path.join(LOG_DIR, "archive")
KEEP_DAYS = 30                 # 이 기간이 지나면 zip 으로 묶는다

# 채널. get_logger 이름의 첫 마디로 쓴다.
_CHANNELS = ("api", "ws", "socket", "batch", "svc", "db", "sys", "lib")

# main.py 의 Process(name=...) -> 로그 파일명
_PROCESS_FILE = {
    "MainProcess": "main",
    "web server":  "web",
    "scheduler":   "scheduler",
    "acs":         "acs",
}

# WARNING 을 WARN 으로 줄여야 칸이 맞는다.
_LEVEL_SHORT = {logging.WARNING: "WARN", logging.CRITICAL: "CRIT"}

# 표시용 이름 정리.
#   uvicorn 은 access 가 아닌 모든 로그를 'uvicorn.error' 로 보낸다.
#   오류라는 뜻이 아닌데 error 가 찍혀 눈에 걸리므로 떼어낸다.
_LIB_RENAME = {"uvicorn.error": "uvicorn"}

# 외부 라이브러리 로그 레벨.
#   apscheduler 는 잡을 돌릴 때마다 INFO 한 줄을 남긴다. I/F 폴링이 5초 주기라
#   하루 17,000 줄이 이것만으로 쌓인다. 정상 실행은 남길 실익이 없다.
#   WARNING 으로 올려도 '밀려서 건너뜀' 과 '예외' 는 그대로 남는다.
_LIB_LEVELS = {
    "uvicorn":     logging.INFO,
    "apscheduler": logging.WARNING,
}

_FORMAT = "[%(asctime)s] %(levelshort)-5s %(tags)s - %(message)s"
_DATEFMT = "%Y-%m-%d %H:%M:%S"

_configured = False


class _TagFormatter(logging.Formatter):
    """로거 이름을 [채널][도메인] 두 칸으로 나눠 찍는다."""

    def format(self, record: logging.LogRecord) -> str:
        channel, _, domain = record.name.partition(".")

        if channel.lower() not in _CHANNELS:
            # 우리가 지은 이름이 아니다. 어느 라이브러리인지 남겨야 하므로
            # 이름 전체를 도메인 칸에 넣는다.
            domain = _LIB_RENAME.get(record.name, record.name)
            channel = "lib"

        record.tags = f"[{channel.upper()}][{domain}]" if domain else f"[{channel.upper()}]"
        record.levelshort = _LEVEL_SHORT.get(record.levelno, record.levelname)
        return super().format(record)


# ---------------------------------------------------------------------- #
# 오래된 로그를 월별 zip 으로
# ---------------------------------------------------------------------- #
def archive_old_logs(keep_days: int = KEEP_DAYS) -> int:
    """KEEP_DAYS 가 지난 로그를 월별 zip 으로 묶고 원본을 지운다.

        logs/web.log.2026-08-03  ->  logs/archive/2026-08.zip 안으로

    같은 달 파일은 한 zip 에 모인다. 이미 있으면 덧붙인다.
    묶기 전에는 평문이라 그냥 열어볼 수 있다.

    메인 프로세스에서만 부른다. 여러 프로세스가 같은 zip 을 동시에 열면
    깨지기 때문이다.
    """
    if not os.path.isdir(LOG_DIR):
        return 0

    cutoff = datetime.date.today() - datetime.timedelta(days=keep_days)
    targets: dict[str, list[str]] = {}

    for name in os.listdir(LOG_DIR):
        # web.log.2026-08-03 형태만 본다. web.log(현재 파일)는 건드리지 않는다.
        head, _, datepart = name.rpartition(".")
        if not head.endswith(".log"):
            continue
        try:
            day = datetime.datetime.strptime(datepart, "%Y-%m-%d").date()
        except ValueError:
            continue
        if day >= cutoff:
            continue
        targets.setdefault(day.strftime("%Y-%m"), []).append(name)

    if not targets:
        return 0

    os.makedirs(ARCHIVE_DIR, exist_ok=True)
    moved = 0

    for month, names in targets.items():
        zip_path = os.path.join(ARCHIVE_DIR, f"{month}.zip")
        try:
            with zipfile.ZipFile(zip_path, "a", zipfile.ZIP_DEFLATED) as zf:
                existing = set(zf.namelist())
                for name in names:
                    src = os.path.join(LOG_DIR, name)
                    if name not in existing:
                        zf.write(src, arcname=name)
                    os.remove(src)
                    moved += 1
        except Exception:
            # 보관에 실패해도 로깅 자체는 계속돼야 한다. 원본은 남겨둔다.
            logging.getLogger("sys.log").exception("로그 보관 실패 - %s", zip_path)

    return moved


def _make_file_handler(stem: str, formatter: logging.Formatter):
    handler = TimedRotatingFileHandler(
        filename=os.path.join(LOG_DIR, f"{stem}.log"),
        when="midnight",
        interval=1,
        # 0 = 자동 삭제 안 함. 오래된 것은 archive_old_logs 가 zip 으로 묶는다.
        # 여기에 값을 주면 묶기도 전에 지워진다.
        backupCount=0,
        encoding="utf-8",
        delay=True,            # 실제로 쓸 때까지 파일을 만들지 않는다
    )
    handler.suffix = "%Y-%m-%d"          # web.log.2026-09-08
    handler.setFormatter(formatter)
    return handler


def _configure_root() -> None:
    """프로세스당 1회. root 로거에 콘솔 + 프로세스별 파일을 붙인다."""
    global _configured
    if _configured:
        return
    _configured = True          # 재진입 방지를 위해 먼저 세운다

    os.makedirs(LOG_DIR, exist_ok=True)
    formatter = _TagFormatter(_FORMAT, datefmt=_DATEFMT)

    root = logging.getLogger()

    # root 자체는 WARNING. 외부 라이브러리가 DEBUG 를 쏟아내는 것을 막는다.
    # 우리 로거는 get_logger 에서 DEBUG 로 따로 올린다.
    root.setLevel(logging.WARNING)

    console = logging.StreamHandler()
    console.setFormatter(formatter)
    root.addHandler(console)

    stem = _PROCESS_FILE.get(mp.current_process().name, "etc")
    root.addHandler(_make_file_handler(stem, formatter))

    # uvicorn 은 run() 에서 log_config=None 을 줘야 이 설정이 살아남는다.
    for lib_name, level in _LIB_LEVELS.items():
        logging.getLogger(lib_name).setLevel(level)

    # 보관은 메인 프로세스에서만. 기동할 때 한 번 돌린다.
    if mp.current_process().name == "MainProcess":
        archive_old_logs()


def get_logger(name: str) -> logging.Logger:
    """이름 붙은 로거를 돌려준다. 출력은 root 핸들러가 처리한다.

    name 은 "채널.도메인" 으로 짓는다.  예) get_logger("api.pick")
    채널을 틀리게 적으면 그 줄이 전부 [LIB] 로 빠져 눈에 안 띈다.
    """
    _configure_root()

    channel = name.partition(".")[0].lower()
    if channel not in _CHANNELS:
        raise ValueError(f"로거 채널이 잘못되었습니다: {name!r} "
                         f"(쓸 수 있는 채널: {', '.join(_CHANNELS)})")

    logger = logging.getLogger(name)
    logger.setLevel(logging.DEBUG)   # 우리 로그는 DEBUG 까지 남긴다
    return logger
