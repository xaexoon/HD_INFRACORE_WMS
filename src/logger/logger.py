import logging
import os
from logging.handlers import TimedRotatingFileHandler
import gzip
import shutil

def get_logger(name: str = "wms"):
    os.makedirs("logs", exist_ok=True)

    logger = logging.getLogger(name)

    if logger.handlers:
        return logger

    logger.setLevel(logging.DEBUG)

    # 포맷
    formatter = logging.Formatter(
        "[%(asctime)s] %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )

    # 콘솔 출력
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)

    # 파일 출력 — 자정마다 새 파일 생성 + 압축
    file_handler = TimedRotatingFileHandler(
        filename="logs/wms.log",
        when="midnight",       # 자정마다 교체
        interval=1,            # 1일마다
        backupCount=30,        # 30일치 보관
        encoding="utf-8",
    )
    file_handler.suffix = "%Y-%m-%d"        # 파일명: wms.log.2024-01-15
    file_handler.namer = lambda name: name  # 파일명 그대로 유지
    file_handler.rotator = _gz_rotator      # 압축 함수 적용
    file_handler.setFormatter(formatter)

    logger.addHandler(console_handler)
    logger.addHandler(file_handler)

    return logger


def _gz_rotator(source, dest):
    try:
        with open(source, 'rb') as f_in:
            with gzip.open(dest, 'wb') as f_out:
                shutil.copyfileobj(f_in, f_out)
        try:
            os.remove(source)
        except PermissionError:
            pass  # 다른 프로세스가 사용 중이면 삭제 스킵
    except Exception:
        pass