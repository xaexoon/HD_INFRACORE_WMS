from src.queries import pick_query
from src.logger.logger import get_logger
from src.db.connection import query, transaction

logger = get_logger("Pick Service")

def get_all_picking_list():
    return query(pick_query.SELECT_ALL)

def get_pick_list_grp_kit() -> dict:
    rows = query(pick_query.SELECT_ALL_GROUP_KIT)

    kits = {}
    for r in rows:
        k = r["kit_seq"]
        if k not in kits:
            kits[k] = {
                "kit_seq": k,
                "order_no": r["order_no"],
                "mes_seq_no": r["mes_seq_no"],
                "engine_no": r["engine_no"],
                "proc_code": r["proc_code"],
                "work_center_nm": r["work_center_nm"],
                "delivery_seq": r["delivery_seq"],
                "kit_status": r["kit_status"],
                "hold_yn": bool(r["hold_yn"]),
                "items": [],
            }
        kits[k]["items"].append({
            "seq": r["seq"],
            "item_code": r["item_code"],
            "item_name": r["item_name"],
            "req_qty": r["req_qty"],
            "picked_qty": r["picked_qty"],
            "uom": r["uom"],
            "lpn_type": r["lpn_type"],
            "status": r["status"],
        })

    return {"pick_lists": list(kits.values()), "total": len(kits)}

def insert_w_lpn():
    return None