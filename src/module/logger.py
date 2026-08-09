import logging
import datetime
import os
import shutil
import threading
import time
import traceback
import zipfile
import logging.handlers
import multiprocessing as mp


# 로거 대신 Print
class LoggerPrint:
    def __init__(self, program_name='logger'):
        self.program_name = program_name
    def info(self, msg):
        print(f'[INFO] [{datetime.datetime.now()}] [{self.program_name}] {msg}')

    def warn(self, msg):
        print(f'[WARN] [{datetime.datetime.now()}] [{self.program_name}] {msg}')

    def warning(self, msg):
        print(f'[WARN] [{datetime.datetime.now()}] [{self.program_name}] {msg}')

    def error(self, msg):
        print(f'[ERROR] [{datetime.datetime.now()}] [{self.program_name}] {msg}')


# 로깅 설정
def get_logger(program_name, stop_event: mp.Event = None, logger=None, console_flag=True, duplicate_flag=False):
    if logger is None:
        logger = logging.getLogger(program_name)
        if len(logger.handlers) > 0:  # 로거가 이미 존재하는 경우
            return logger
        logger.setLevel(logging.INFO)

    # log를 console에 출력
    formatter = logging.Formatter(f'[%(asctime)s] [{program_name}] [%(levelname)s] %(message)s')
    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)
    if console_flag is True:
        logger.addHandler(stream_handler)

    # log를 파일에 출력
    # os.makedirs("./log/temp", exist_ok=True)
    # file_handler = logging.FileHandler(f"./log/temp/{program_name}.log", encoding="utf-8")
    # file_handler.setFormatter(formatter)
    # logger.addHandler(file_handler)

    os.makedirs("./log/temp", exist_ok=True)
    timedfilehandler = logging.handlers.TimedRotatingFileHandler(filename=f"./log/temp/{program_name}.log",
                                                                 when='midnight',
                                                                 interval=1,
                                                                 encoding='utf-8')
    timedfilehandler.setFormatter(formatter)
    timedfilehandler.suffix = "%Y-%m-%d"
    logger.addHandler(timedfilehandler)


    if stop_event is None:
        stop_event = mp.Event()
    logger.info(f"=====================================")
    if duplicate_flag is False:
        logger.info(f"[{program_name}] 프로그램 시작")
        logger.info(f"=====================================")
    threading.Thread(target=midnight_log, args=(logger, program_name, duplicate_flag, stop_event)).start()

    return logger


# 로그 자정 확인 (로그 미생성 방지)
def midnight_log(logger, program_name, duplicate_flag, stop_event):
    pre_day = datetime.datetime.now().day
    while not stop_event.is_set():
        now_day = datetime.datetime.now().day
        if pre_day != now_day:
            logger.info(f"=====================================")
            if duplicate_flag is False:
                logger.info(f"로그 초기화")
                logger.info(f"=====================================")
            pre_day = now_day
        time.sleep(1)
    logger.info(f"=====================================")
    if duplicate_flag is False:
        logger.info(f"[{program_name}] 프로그램 종료")
        logger.info(f"=====================================")


# 로그 압축파일 저장
def saveLogZip():
    threading.Timer(60, logZipProcess).start()


# 로그 압축파일 생성
def logZipProcess():
    now_dir = os.getcwd()
    log_dir = os.path.join(now_dir, "log")
    temp_dir = os.path.join(log_dir, "temp")

    yesterday = datetime.datetime.now() - datetime.timedelta(1)
    yesterday_date = yesterday.strftime("%Y-%m-%d")

    for file_name in os.listdir(temp_dir):
        file_path = os.path.join(temp_dir, file_name)
        file_base_name, file_extension = os.path.splitext(file_name)

        if os.path.isdir(file_path) is True or file_extension == ".log":
            # 오늘 날짜의 로그 또는 디렉토리라면 무시
            continue

        log_date = file_extension[-10:]
        move_path = os.path.join(temp_dir, log_date)
        os.makedirs(move_path, exist_ok=True)
        shutil.move(file_path, os.path.join(move_path, file_base_name))

    # 로그 폴더 있는지 확인
    try:
        # 로그 폴더 확인 및 만들기
        log_path: str = f"./log/temp/{yesterday_date}"
        log_zip_path: str = f"./log/zip/{yesterday_date}.zip"
        os.makedirs(f"./log/zip", exist_ok=True)

        if not os.path.isdir(log_path) or os.path.exists(log_zip_path):
            # 압축 파일 경로에 폴더가 없거나 압축 파일이 있으면 종료
            return

        # 어제 일자 압축하기
        log_zips: zipfile.ZipFile = zipfile.ZipFile(log_zip_path, 'w')

        for folder, subfolders, files in os.walk(log_path):
            for file in files:
                log_zips.write(
                    os.path.join(folder, file),
                    os.path.relpath(os.path.join(folder, file), log_path),
                    compress_type=zipfile.ZIP_DEFLATED)
        log_zips.close()

        # 기존 폴더 삭제
        if os.path.exists(log_path):
            shutil.rmtree(log_path)

        # 30일 지난 파일 삭제
        delete_old_files(path_target=f'./log/temp', days_elapsed=30)
        delete_old_files(path_target=f'./log/zip', days_elapsed=30)
    except Exception:
        print(traceback.format_exc())
        return


# 링크: https://m.blog.naver.com/wideeyed/221797721352
def delete_old_files(path_target, days_elapsed):
    """path_target:삭제할 파일이 있는 디렉토리, days_elapsed:경과일수"""
    for f in os.listdir(path_target):  # 디렉토리를 조회한다
        f = os.path.join(path_target, f)
        timestamp_now = datetime.datetime.now().timestamp()  # 타임스탬프(단위:초)
        # st_mtime(마지막으로 수정된 시간)기준 X일 경과 여부
        is_old = os.stat(f).st_mtime < timestamp_now - (days_elapsed * 24 * 60 * 60)
        if is_old:  # X일 경과했다면
            try:
                if os.path.isfile(f):  # 파일이면
                    os.remove(f)  # 파일을 지운다
                else:
                    shutil.rmtree(f)
                print(f, 'is deleted')  # 삭제완료 로깅
            except OSError:  # Device or resource busy (다른 프로세스가 사용 중)등의 이유
                print(f, 'can not delete')  # 삭제불가 로깅