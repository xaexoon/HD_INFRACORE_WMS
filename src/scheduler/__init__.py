# -*- coding: utf-8 -*-
"""스케줄러 프로세스.

main.py 에서 별도 Process 로 기동한다.
웹서버와 생명주기를 분리해야 하는 이유:
  - 웹서버 재시작 시 배치가 같이 죽으면 안 됨
  - uvicorn 워커를 늘리면 잡이 워커 수만큼 중복 실행됨
"""
import time

from apscheduler.schedulers.background import BackgroundScheduler

from src.logger.logger import get_logger


# ---------------------------------------------------------------------- #
# 트리거 표기
#
# APScheduler 의 str(trigger) 는 interval[0:00:05] / cron[hour='3', minute='0']
# 처럼 나와 한눈에 안 들어온다. 읽히는 말로 바꿔 남긴다.
# ---------------------------------------------------------------------- #
def _every_text(delta) -> str:
    """timedelta -> '5초마다' / '10분마다' / '2시간마다'."""
    total = int(delta.total_seconds())
    if total <= 0:
        return "즉시"
    if total % 3600 == 0:
        return f"{total // 3600}시간마다"
    if total % 60 == 0:
        return f"{total // 60}분마다"
    return f"{total}초마다"


def _trigger_text(trigger) -> str:
    """트리거를 짧게 읽히는 말로 바꾼다.

    트리거 클래스를 import 해서 isinstance 로 가르지 않고 속성으로 가른다.
    APScheduler 판이 올라가며 클래스 위치가 바뀌어도 그대로 돌게 하려는 것이다.
    모르는 트리거가 오면 원래 표기를 그대로 쓴다(정보를 잃지 않는다).
    """
    interval = getattr(trigger, "interval", None)
    if interval is not None:                       # IntervalTrigger
        return _every_text(interval)

    run_date = getattr(trigger, "run_date", None)
    if run_date is not None:                       # DateTrigger
        return f"{run_date:%Y-%m-%d %H:%M:%S} 1회"

    fields = getattr(trigger, "fields", None)
    if fields is not None:                         # CronTrigger
        # 지정하지 않은 칸(*)은 빼고 실제로 정한 것만 보여준다
        named = {f.name: str(f) for f in fields if not f.is_default}
        # 마감 배치처럼 시/분만 정한 흔한 경우는 더 짧게
        if set(named) <= {"hour", "minute"} and "hour" in named:
            return f"매일 {int(named['hour']):02d}:{int(named.get('minute', 0)):02d}"
        return "cron " + " ".join(f"{k}={v}" for k, v in named.items()) if named else "cron"

    return str(trigger)


def run_scheduler(db_conf: dict) -> None:
    """스케줄러 프로세스 진입점."""
    logger = get_logger("batch.sched")

    # 자식 프로세스이므로 DB 커넥션을 새로 초기화한다 (run_web 과 동일)
    from src.db.connection import init_db
    init_db(
        address=db_conf["address"],
        database=db_conf["database"],
        user=db_conf["user"],
        password=db_conf["password"],
    )

    from src.scheduler import jobs

    sched = BackgroundScheduler(timezone="Asia/Seoul")
    jobs.register(sched)
    sched.start()

    for job in sched.get_jobs():
        logger.info("등록: %s — %s (%s)", job.id, job.name, _trigger_text(job.trigger))
    logger.info("시작 — 잡 %s개", len(sched.get_jobs()))

    try:
        while True:
            time.sleep(1.0)
    except KeyboardInterrupt:
        logger.info("중단 요청")
    finally:
        sched.shutdown(wait=False)
        logger.info("종료")