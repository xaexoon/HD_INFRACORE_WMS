import os
import time
from multiprocessing import Process
import multiprocessing as mp
from src.logger.logger import get_logger
from src.common.config_loader import get_base_dir, load_config
from src.web_server import run_web


if __name__ == "__main__":
    logger = get_logger("main")
    opt = load_config()
    base_dir = get_base_dir()

    db_conf = {
        "address" : opt.get("db_address", "127.0.0.1"),
        "database": opt.get("db_database"),
        "user" : opt.get("db_user"),
        "password" : opt.get("db_password")

    }

    web_conf = {
        "host" : opt.get("web_server_host", "0.0.0.0"),
        "port" : opt.getint("web_server_port", fallback=8000)
    }

    plc_conf = {
         "host": opt.get("plc_host", "127.0.0.1"),
        "port": opt.getint("plc_port", fallback=5007),
        # "plc_type": opt.get("plc_type", "Q"),
        "timeout": opt.getfloat("plc_timeout", fallback=3.0),
        "poll_interval_sec": opt.getfloat("plc_poll_interval_sec", fallback=1.0),
    }

    plc_enable = opt.getboolean("plc_enable", fallback=True)
    procs: list[Process] = []

    # ── 프로세스 시작 (여기에 계속 추가) ──────────────
    web_process = Process(target=run_web, name="web server", args=(db_conf, web_conf))
    web_process.start()
    procs.append(web_process)
    logger.info(f"[main] 웹 서버 프로세스 시작 (pid={web_process.pid})")


    # TODO: PLC 통신 프로세스
    # if plc_enable:
    #     plc_process = Process(target="", name="plc", args=(db_conf, plc_conf))
    #     plc_process.start()
    #     procs.append(plc_process)
    #     logger.info(f"[main] PLC 프로세스 시작 (pid={plc_process.pid})")
    # else:
    #     logger.info("[main] plc_enable=false — PLC 프로세스 미기동")


    try:
        while True:
            dead = [p for p in procs if not p.is_alive()]
            if dead:
                for p in dead:
                    logger.error(
                        f"[main] 프로세스 종료 감지: {p.name} "
                        f"(pid={p.pid}, exitcode={p.exitcode})"
                    )
                break
            time.sleep(1.0)
    except KeyboardInterrupt:
        logger.info("[main] 중단 요청")

    for p in procs:
        if p.is_alive():
            logger.info(f"[main] {p.name} 종료 요청")
            p.terminate()
    for p in procs:
        p.join(timeout=5)
        if p.is_alive():
            logger.warning(f"[main] {p.name} 강제 종료")
            p.kill()

    # ── 대기 (start가 전부 끝난 뒤에만) ──────────────
    web_process.join()
