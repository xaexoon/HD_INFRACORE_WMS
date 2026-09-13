from src.queries import common_query
from src.logger.logger import get_logger

logger = get_logger("svc.common")

def make_lpn_code(cur, lpn_type: str) -> str:
    """LPN 코드 채번. 반드시 트랜잭션 커서를 받는다."""
    cur.execute(common_query.NEXT_LPN_NO, (lpn_type, lpn_type, lpn_type))
    row = cur.fetchone()

    if row is None:
        raise RuntimeError(f"LPN 채번 실패: {lpn_type}")

    lpn_code, seq_no = row[0], row[1]

    if seq_no > 99999:
        raise RuntimeError(f"일련번호 소진: {lpn_type} (99999 초과)")

    logger.info(f"LPN 채번 - {lpn_code}")
    return lpn_code

def make_doc_no(cur, doc_type: str) -> str:
    """지시번호 채번. 반드시 트랜잭션 커서를 받는다.

    PIK : ERP 수신 가공 시 [오더 + 공정] 단위로 부여
    KIT : 피킹 확정 시 부여
    """
    if doc_type not in ("PIK", "KIT", "URG", "MAN", "SPL"):
        raise ValueError(f"지원하지 않는 문서 유형: {doc_type}")

    cur.execute(common_query.NEXT_DOC_NO, (doc_type, doc_type, doc_type))
    row = cur.fetchone()
    if row is None:
        raise RuntimeError(f"지시번호 채번 실패: {doc_type}")

    doc_no, seq_no = row[0], row[1]
    if seq_no > 9999:
        raise RuntimeError(f"일련번호 소진: {doc_type} (9999 초과)")

    return doc_no

def log_status(cur, table_name: str, row_seq: int,
               to_status: str,
               from_status: str | None = None,
               doc_no: str | None = None,
               worker_id: str | None = None,
               device_id: str | None = None,
               remark: str | None = None) -> None:
    """상태 전이 이력 기록. 반드시 트랜잭션 커서를 받는다.

    상태를 바꾸는 모든 지점에서 호출한다.
    호출을 빠뜨리면 그 전이는 이력에 남지 않으므로
    가급적 update_status() 헬퍼를 통해 호출할 것.
    """
    cur.execute(common_query.INSERT_STATUS_LOG,
                (table_name, row_seq, doc_no, from_status, to_status,
                 worker_id, device_id, remark))


def update_status(cur, sql, params,
                  table_name: str, row_seq: int,
                  to_status: str,
                  from_status: str | None = None,
                  doc_no: str | None = None,
                  worker_id: str | None = None,
                  device_id: str | None = None,
                  remark: str | None = None) -> bool:
    """상태 전이 UPDATE + 이력 기록을 한 번에.

    UPDATE 가 0건이면(조건 불일치) 이력도 남기지 않는다.
    상태 변경 지점에서 이 함수만 쓰면 이력 누락을 막을 수 있다.
    반환값 : 실제로 변경되었는가
    """
    cur.execute(sql, params)
    if not cur.rowcount:
        return False

    log_status(cur, table_name, row_seq, to_status, from_status,
               doc_no, worker_id, device_id, remark)
    return True


