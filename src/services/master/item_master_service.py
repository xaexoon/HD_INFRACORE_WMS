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
    ))
    return rows[0]["seq"]


def update_item_master(body: item_schema.ItemUpdate) -> int:
    return execute(q.UPDATE_ITEM, (
        body.item_name,
        body.uom,
        body.washing_yn,
        body.mixed_allow,
        body.kitting_grp,
        body.seq,
    ))


# def delete_item_master(item_seq: int) -> int:
#     return execute(q.DELETE_ITEM, (item_seq,))

def delete_item_master(item_seq: int) -> int:
    return execute(q.DELETE_ITEM_HARD, (item_seq,))
