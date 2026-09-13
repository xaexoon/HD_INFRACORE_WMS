-- ═══════════════════════════════════════════════════════════
-- AMR 호출 상태값 추가 (ACS 연동 스펙 1-3 / 2-1)
--
--   CREATED      K-LPN 생성          WMS   (이미 허용값에 있음)
--   CALLED       AMR 호출 성공       WMS
--   CALL_FAILED  AMR 호출 실패       ACS
--   ACCEPTED     AMR 배차 성공       ACS
--   RUNNING      AMR 동작 중         ACS
--   COMPLETED    공정 도착 완료      ACS
--   CANCELED     취소                —
--
--   ※ kit_table.STATUS 의 'CANCEL' 과 철자가 다르다(CANCELED).
--     다른 테이블의 다른 개념이므로 섞어 쓰지 말 것.
-- ═══════════════════════════════════════════════════════════

ALTER TABLE lpn_master DROP CONSTRAINT CK_LPN_PSTAT;

ALTER TABLE lpn_master ADD CONSTRAINT CK_LPN_PSTAT
    CHECK (process_status IN (
        -- 기존
        'CREATED', 'PRINTED', 'AVAILABLE', 'ALLOCATED', 'PICK_COMP',
        'WASH_WAIT', 'WASH_COMP', 'KIT_COMP', 'CONSUMED', 'VOID',
        -- AMR 호출
        'CALLED', 'CALL_FAILED', 'ACCEPTED', 'RUNNING', 'COMPLETED', 'CANCELED'));


-- K-LPN 은 이제 CREATED 로 만들어진다.
--   기존 건은 KIT_COMP 로 남아 있어 호출 대상에 잡히지 않는다.
UPDATE lpn_master
   SET process_status = 'CREATED',
       updated_date   = sysdatetime()
 WHERE lpn_type = 'K'
   AND process_status = 'KIT_COMP'
   AND lifecycle_status = 'ACTIVE';
