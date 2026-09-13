from src.db.connection import query, execute, insert_returning
from src.queries.master import item_master_query as q
from src.schemas import item_schema


def get_item_master_list():
    return query(q.SELECT_ITEM_LIST)


def get_item_master(item_seq: int):
    rows = query(q.SELECT_ITEM_BY_SEQ, (item_seq,))
    return rows[0] if rows else None


def search_item_master(keyword: str):
    like = f"%{keyword}%"
    return query(q.SELECT_ITEM_SEARCH, (like, like))


def get_size_types():
    """크기 구분 셀렉트박스용. S(소물) / M(중물) / L(대물)"""
    return query(q.SELECT_SIZE_TYPES)


def get_item_no_size():
    """크기 구분 미입력 자재. 수기 입력 대상 확인용."""
    return query(q.SELECT_ITEM_NO_SIZE)


def insert_item_master(body: item_schema.ItemInsert) -> int:
    if query(q.COUNT_ITEM_CODE, (body.item_code,))[0]["cnt"] > 0:
        raise ValueError(f"이미 등록된 자재 코드입니다: {body.item_code}")

    rows = insert_returning(q.INSERT_ITEM, (
        body.item_code,
        body.item_name,
        body.uom,
        body.washing_yn,
        body.mixed_allow,
        body.kitting_grp,
        body.size_type,
    ))
    return rows[0]["seq"]

def update_item_master(body: item_schema.ItemUpdate) -> int:
    if body.use_yn is False:
        r = query(q.COUNT_ITEM_USED, (body.seq, body.seq))[0]
        if r["stock_cnt"]:
            raise ValueError("재고가 남아 있어 사용중지할 수 없습니다")
        if r["pick_cnt"]:
            raise ValueError("진행 중인 피킹 지시가 있어 사용중지할 수 없습니다")

    return execute(q.UPDATE_ITEM, (
        body.item_name,
        body.uom,
        body.washing_yn,
        body.mixed_allow,
        body.kitting_grp,
        body.size_type,
        body.use_yn,
        body.seq,
    ))


def delete_item_master(item_seq: int) -> int:
    """물리 삭제. 사용여부가 N 인 자재만."""
    return execute(q.DELETE_ITEM_HARD, (item_seq,))