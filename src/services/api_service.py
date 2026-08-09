from src.db.connection import query, transaction
from src.logger.logger import get_logger
from src.queries import lpn_query, item_query
from enum import Enum

logger = get_logger("API Service")

class LpnType(str, Enum):
    RAW  = "R"   # 원자재 (메인랙 상주, 반복 사용)
    WASH = "W"   # 세척 필요
    DRY  = "D"   # 비세척
    KIT  = "K"   # 키팅 완료

def make_lpn_code(conn, lpn_type: str) -> str:
    with conn.cursor() as cur:
        cur.execute(
            "DECLARE @c VARCHAR(12); "
            "EXEC dbo.usp_make_lpn_code ?, @c OUTPUT; "
            "SELECT @c;", lpn_type)
        return cur.fetchone()[0]


def get_all_items():
    return query(item_query.SELECT_ALL)

def search_items(keyword: str) -> list[dict]:
    """자재코드/자재명 부분 검색 (QR PC 검색창용)"""
    like = f"%{keyword}%"
    return query(item_query.SEARCH, (like, like))

def get_item_by_code(item_code: str) -> list[dict]:
    return query(item_query.SELECT_BY_CODE,(item_code,))

def insert_gr_lpn(item_code: str, received_qty: int, received_date: str,
                  device_id: str, worker_id: str, lpn_code:str | None = None ) -> dict:
    """입고 등록 + LPN 발행 (문서 입고 1~3단계).

    처리 순서:
      1) 자재마스터 확인 (2단계: 속성 매핑)
      2) [트랜잭션] LPN 채번 → master → detail → txn(GR) INSERT
      3) 라벨 출력용 정보 반환
    실패 시: 트랜잭션 전체 롤백, 예외는 라우터로 전파
    """
    # ── 1) 자재마스터 확인 ──────────────────────────────
    items = query(item_query.SELECT_BY_CODE, (item_code,))
    if not items:
        raise ValueError(f"자재마스터에 없는 자재코드: {item_code}")
    item = items[0]

    # ── 2) master + detail + txn 을 하나의 트랜잭션으로 ──
    with transaction() as cur:
        # LPN 채번 (예: 2026-07-23 + 42번째 → LPN2607230042)
        cur.execute(lpn_query.NEXT_LPN_NO)
        seq_no = cur.fetchone()[0]

        # lpn_master INSERT + 생성된 seq 회수
        cur.execute(lpn_query.INSERT_MASTER, (lpn_code,))
        lpn_master_seq = cur.fetchone()[0]

        # lpn_detail INSERT (최초수량 = 현재수량)
        cur.execute(lpn_query.INSERT_DETAIL,
                    (lpn_master_seq, item["seq"], received_qty, received_qty))

        # lpn_txn INSERT (입고 이력)
        cur.execute(lpn_query.INSERT_TXN_GR,
                    (lpn_master_seq, item["seq"], received_qty,
                     device_id, worker_id, received_date))
    # with 블록 정상 종료 → commit / 예외 발생 → rollback 후 전파

    logger.info(f"LPN 발행: {lpn_code} / {item_code} {received_qty}{item['uom']} "
                f"/ {device_id} {worker_id or '-'}")

    # ── 3) 라벨 출력용 정보 반환 (LPN + 자재 + 세척Flag) ──
    return {
        "lpn_code": lpn_code,
        "item_code": item["item_code"],
        "item_name": item["item_name"],
        "qty": received_qty,
        "uom": item["uom"],
        "washing_yn": item["washing_yn"],
    }

def update_to_print(lpn_code: str):
    return None

def get_all_lpn() -> list[dict]:
    """활성 LPN 전체 조회"""
    return query(lpn_query.SELECT_ACTIVE_LPN)


def get_lpn(lpn_code: str) -> list[dict]:
    """LPN 단건 조회. 없으면 빈 리스트 반환"""
    return query(lpn_query.SELECT_BY_CODE_LPN, (lpn_code,))


def get_items() -> list[dict]:
    return query("SELECT item_code, item_name, uom, washing_yn, kitting_grp FROM item_master")