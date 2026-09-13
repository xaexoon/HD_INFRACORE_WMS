import os
import time
from multiprocessing import Process
import multiprocessing as mp
from src.logger.logger import get_logger
from src.common.config_loader import get_base_dir, load_config
from src.web_server import run_web
from src.scheduler import run_scheduler
from src.acs_poller import run_acs_poller


if __name__ == "__main__":
    logger = get_logger("sys.main")
    opt = load_config()
    base_dir = get_base_dir()
    stop_event = mp.Event()


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

    # ACS (REST). WMS 가 클라이언트로 주기 폴링한다.
    acs_conf = {
        "url": opt.get("acs_url", "http://127.0.0.1:8080"),
        "timeout": opt.getfloat("acs_timeout", fallback=0.5),
        "interval": opt.getfloat("acs_interval", fallback=1.0),
    }

    plc_conf = {
         "host": opt.get("plc_host", "127.0.0.1"),
        "port": opt.getint("plc_port", fallback=5007),
        # "plc_type": opt.get("plc_type", "Q"),
        "timeout": opt.getfloat("plc_timeout", fallback=3.0),
        "poll_interval_sec": opt.getfloat("plc_poll_interval_sec", fallback=1.0),
    }

    plc_enable = opt.getboolean("plc_enable", fallback=True)
    scheduler_enable = opt.getboolean("scheduler_enable", fallback=True)
    acs_enable = opt.getboolean("acs_enable", fallback=True)
    procs: list[Process] = []

    # ── 웹 프로세스 시작  ──────────────
    web_process = Process(target=run_web, name="web server",
                          args=(db_conf, web_conf))
    web_process.start()
    procs.append(web_process)
    logger.info(f"웹 서버 프로세스 시작 (pid={web_process.pid})")


    # 스케줄러 — ERP I/F 폴링
    if scheduler_enable:
        scheduler_process = Process(target=run_scheduler, name="scheduler",
                                    args=(db_conf,))
        scheduler_process.start()
        procs.append(scheduler_process)
        logger.info(f"스케줄러 프로세스 시작 (pid={scheduler_process.pid})")
    else:
        logger.info("scheduler_enable=false — 스케줄러 미기동")

    # ── ACS 폴링 프로세스 ──────────────
    if acs_enable:
        acs_process = Process(target=run_acs_poller, name="acs",
                              args=(acs_conf, db_conf, stop_event))
        acs_process.start()
        procs.append(acs_process)
        logger.info(f"ACS 폴링 프로세스 시작 (pid={acs_process.pid}) "
                    f"— {acs_conf['url']} {acs_conf['interval']}초 주기")
    else:
        logger.info("acs_enable=false — ACS 폴링 미기동")

    # TODO: PLC 통신 프로세스
    # if plc_enable:
    #     plc_process = Process(target="", name="plc", args=(db_conf, plc_conf))
    #     plc_process.start()
    #     procs.append(plc_process)
    #     logger.info(f"PLC 프로세스 시작 (pid={plc_process.pid})")
    # else:
    #     logger.info("plc_enable=false — PLC 프로세스 미기동")


    try:
        while True:
            dead = [p for p in procs if not p.is_alive()]
            if dead:
                for p in dead:
                    logger.error(
                        f"프로세스 종료 감지: {p.name} "
                        f"(pid={p.pid}, exitcode={p.exitcode})"
                    )
                break
            time.sleep(1.0)
    except KeyboardInterrupt:
        logger.info("중단 요청")

        # ── 종료 처리 ──────────────
    stop_event.set()  # ★① 스스로 정리하라고 신호
    deadline = time.time() + 5  # 전체 대기 상한 5초
    for p in procs:
        p.join(timeout=max(0.1, deadline - time.time()))

    for p in procs:  # ② 안 나간 놈만 종료 요청
        if p.is_alive():
            logger.info(f"{p.name} 종료 요청")
            p.terminate()
    for p in procs:
        p.join(timeout=5)
        if p.is_alive():  # ③ 그래도 버티면 강제 종료
            logger.warning(f"{p.name} 강제 종료")
            p.kill()

    logger.info("종료 완료")