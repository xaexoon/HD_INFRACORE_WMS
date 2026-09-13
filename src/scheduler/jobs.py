# -*- coding: utf-8 -*-
"""스케줄 작업 정의.

잡을 추가할 때는 register() 에 add_job 한 줄만 넣는다.
  max_instances=1 : 이전 실행이 안 끝났는데 다음 주기가 오는 것을 막는다
  coalesce=True   : 밀린 실행을 하나로 합친다
"""
from apscheduler.schedulers.base import BaseScheduler

from src.services.batch import interface_service
from src.logger.logger import get_logger

logger = get_logger("batch.if")


# ── ERP I/F 폴링 ───────────────────────────────────────────
#   ERP 는 ORDER_H / ORDER_D 에 push 만 하고 알림을 주지 않는다.
#   WMS 가 WMS_PROC_STAT = 'R' 인 건을 주기적으로 확인해 가공한다.
def sync_orders_job() -> None:
    try:
        interface_service.sync_orders()
    except Exception as e:
        logger.error(f"I/F 폴링 오류 - {e}")


def register(scheduler: BaseScheduler) -> None:
    scheduler.add_job(
        sync_orders_job,
        trigger="interval",
        seconds=5,
        id="if_sync",
        name="ERP I/F 폴링",
        max_instances=1,
        coalesce=True,
    )

    # 스테이션 배정은 주기 잡으로 돌리지 않는다.
    #   K-LPN 발행(3중 검증 통과) 시점에 1회만 ACS 에 요청한다.
    #   실패해 배차 대기로 남은 건은 kit_service.assign_pending_stations() 를
    #   화면에서 불러 다시 요청한다(사람이 판단해서 누른다).

    # TODO: 재고 실사 / 마감 배치 등 추가 시 여기에