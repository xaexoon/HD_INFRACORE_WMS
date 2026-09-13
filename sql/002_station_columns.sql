-- ═══════════════════════════════════════════════════════════
-- 키팅 스테이션 컬럼
--   ACS 가 지정해 주는 값을 그대로 담는다 (스펙 1-1 / 1-2).
--     station_no    숫자   1, 2, 3 ...
--     station_name  문자   "KIT-01", "AH01-A010" ...
--
--   STATION_NO 는 지금 varchar(20) 인데 60건 전부 NULL 이고
--   걸린 인덱스도 없어 그대로 타입을 바꿔도 된다.
-- ═══════════════════════════════════════════════════════════

ALTER TABLE kit_table ALTER COLUMN STATION_NO int NULL;

ALTER TABLE kit_table ADD STATION_NAME varchar(50) NULL;
