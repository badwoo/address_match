-- =============================================================================
-- 地址房号解析 PG 存储过程
-- =============================================================================
--
-- 包含两个对象：
--   1. extract_house_number(p_address TEXT)  —— 房号提取核心函数（IMMUTABLE）
--   2. batch_update_house_number(...)         —— 批量更新存储过程（大表优化）
--
-- 用法：
--   -- 单条测试
--   SELECT extract_house_number('广东省深圳市福田区华强北街道华航社区振兴路91-13号B101');
--   -- 返回: B101
--
--   -- 批量更新
--   CALL batch_update_house_number(
--       p_table_name  := 'public.enterprise_address',
--       p_address_col := 'address',
--       p_house_col   := 'house_no',
--       p_batch_size  := 5000,
--       p_where_clause:= ''   -- 可选，不带 WHERE 关键字
--   );
--
-- （注：末尾有使用示例）
-- =============================================================================


-- -----------------------------------------------------------------------------
-- 函数 1：extract_house_number
--   入参：p_address TEXT  地址原文
--   出参：TEXT             解析出的房号（无匹配返回空串）
--   特性：IMMUTABLE，可建立索引、可在 SQL 中任意调用
-- -----------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION extract_house_number(p_address TEXT)
RETURNS TEXT
LANGUAGE plpgsql
IMMUTABLE
AS $$
DECLARE
    v_addr      TEXT;           -- 归一化后的地址
    v_house     TEXT := '';     -- 候选房号
    v_match     TEXT[];         -- regexp_match 返回的捕获组数组
    v_char_before TEXT;         -- 房号前一个字符（用于过滤 roadno 误识别）
    -- 后缀列表（不含"号"，"号"单独处理以支持 "数字+号+后缀" 组合）
    -- 注意：长后缀必须排在短后缀前面（如"商铺"在"铺"前），避免被短后缀抢先匹配
    v_suffix    TEXT := '(?:商铺|店铺|铺位|铺面|档铺|埔|铺|档口|档|室|房|户|间|房间|柜|柜台)';
    -- 后缀列表（含"号"和"号X"组合，用于 "数字+后缀" 模式）
    v_suffix_full TEXT := '(?:商铺|店铺|号铺|铺位|铺面|档铺|埔|铺|号档|档口|档|室|房|户|号|间|房间|柜|柜台)';
BEGIN
    IF p_address IS NULL THEN
        RETURN '';
    END IF;

    -- 归一化空白：制表符/多空格统一为单空格，再去掉首尾空白
    v_addr := regexp_replace(p_address, '[[:space:]]+', ' ', 'g');
    v_addr := btrim(v_addr);

    IF v_addr = '' THEN
        RETURN '';
    END IF;

    -- ----------------------------------------------------------------------
    -- 预处理：剥离末尾的括号备注和句号
    --   1. "(仅限办公)"、"(入驻XXX)"、"(办公场所)"、"(办公住所)"、"(办公地址)"、
    --      "(一照多址企业)" 等备注不影响房号识别，需剥离
    --      注意：保留房号内的括号内容如 "(03)"（A-3501(03) 的房号一部分）
    --      注意：入驻备注可能含嵌套括号（如"(入驻XX(深圳)有限公司)"），需贪婪匹配
    --   2. 末尾句号"。"剥离（如"105号。"→"105号"）
    -- ----------------------------------------------------------------------
    v_addr := regexp_replace(v_addr, '[(（]入驻.*[)）]\s*$', '');
    v_addr := regexp_replace(v_addr, '[(（]仅限办公[)）]\s*$', '');
    v_addr := regexp_replace(v_addr, '[(（]仅限[^()]*[)）]\s*$', '');
    v_addr := regexp_replace(v_addr, '[(（]办公(?:场所|住所|地址)[)）]\s*$', '');
    v_addr := regexp_replace(v_addr, '[(（]一照多址企业[)）]\s*$', '');
    v_addr := regexp_replace(v_addr, '[。.]+\s*$', '');

    -- ----------------------------------------------------------------------
    -- 模式 1：横杠连接 + 后缀（如 A1-2铺、B3-4档）
    --   后缀不纳入 house 值
    -- ----------------------------------------------------------------------
    v_match := regexp_match(
        v_addr,
        '([A-Za-z0-9]+(?:[-－/]+[A-Za-z0-9]+)+)[[:space:]]*' || v_suffix || '$'
    );
    IF v_match IS NOT NULL THEN
        RETURN v_match[1];
    END IF;

    -- ----------------------------------------------------------------------
    -- 模式 1A：横杠连接 + 号 + 后缀（如 A17-3号铺、LG-M-05号铺、102-103-2号商铺、28-29号商铺）
    --   "号" 和后缀均不纳入 house 值
    --   过滤：house 前一个字符不能是道路关键字（路/街/道/巷/弄）或连接符
    --         例如「振兴路91-13号商铺」中 91-13 前面是「路」，是 roadno，跳过
    --         例如「首层28-29号商铺」中 28-29 前面是「层」，是 house
    --   注意：roadno（如「91-13号」无后缀）不会匹配本模式（本模式要求末尾有后缀）
    -- ----------------------------------------------------------------------
    v_match := regexp_match(
        v_addr,
        '([A-Za-z0-9]+(?:[-－/]+[A-Za-z0-9]+)+)号' || v_suffix || '$'
    );
    IF v_match IS NOT NULL THEN
        v_house := v_match[1];
        v_char_before := substring(
            v_addr FROM '.*([^0-9A-Za-z])' || v_house || '号' || v_suffix || '$'
        );
        IF v_char_before IS NULL
           OR v_char_before !~ '[\-－/\\路街道巷弄]' THEN
            RETURN v_house;
        END IF;
        v_house := '';
    END IF;

    -- ----------------------------------------------------------------------
    -- 模式 1B：前导连接符 + 横杠连接 + 号 + 后缀（如 -LM-11号商铺）
    --   房号包含前导"-"，属于特殊格式
    -- ----------------------------------------------------------------------
    v_match := regexp_match(
        v_addr,
        '([-－][A-Za-z0-9]+(?:[-－/]+[A-Za-z0-9]+)+)号' || v_suffix || '$'
    );
    IF v_match IS NOT NULL THEN
        RETURN v_match[1];
    END IF;

    -- ----------------------------------------------------------------------
    -- 模式 2：横杠连接 + 号（如 101-1号、62-6号）
    --   "号" 不纳入 house 值
    --   过滤：house 前一个字符不能是道路关键字（路/街/道/巷/弄）或数字或连接符
    --         例如「振兴路91-13号」中 91-13 前面是「路」，是 roadno，跳过
    --         例如「A单元101-1号」中 101-1 前面是「元」，是 house
    -- ----------------------------------------------------------------------
    v_match := regexp_match(v_addr, '([A-Za-z0-9]+(?:[-－/]+[A-Za-z0-9]+)+)号$');
    IF v_match IS NOT NULL THEN
        v_house := v_match[1];
        -- 取 house 前一个非数字字符（.* 贪婪会回溯到最近的非数字字符）
        v_char_before := substring(
            v_addr FROM '.*([^0-9])' || v_house || '号$'
        );
        IF v_char_before IS NOT NULL
           AND v_char_before !~ '[\-－/\\路街道巷弄]' THEN
            RETURN v_house;
        END IF;
        v_house := '';
    END IF;

    -- ----------------------------------------------------------------------
    -- 模式 3：横杠连接（如 101-102、L1-21A、1-2-3-4）
    --   过滤：末尾紧跟楼栋关键字（bldg 残留）或「号」（roadno）时跳过
    -- ----------------------------------------------------------------------
    v_match := regexp_match(v_addr, '([A-Za-z0-9]+(?:[-－/]+[A-Za-z0-9]+)+)$');
    IF v_match IS NOT NULL THEN
        v_house := v_match[1];
        IF v_addr !~ (v_house || '(?:号楼|塔楼|栋|幢|座|号)$') THEN
            RETURN v_house;
        END IF;
        v_house := '';
    END IF;

    -- ----------------------------------------------------------------------
    -- 模式 3A：横杠连接 + 括号数字（如 A-3501(03)）
    --   括号内容是房号的一部分，需保留
    -- ----------------------------------------------------------------------
    v_match := regexp_match(v_addr, '([A-Za-z0-9]+(?:[-－/]+[A-Za-z0-9]+)+\([0-9]+\))$');
    IF v_match IS NOT NULL THEN
        RETURN v_match[1];
    END IF;

    -- ----------------------------------------------------------------------
    -- 模式 3B：字母数字组合(必含字母) + 号 + 后缀
    --   如 3B号商铺、417A号商铺、104S号商铺、18B号铺、A137号铺、A4480A号商铺、3C11A号商铺、G23C号铺
    --   "号"和后缀均不纳入 house 值
    --   房号必须含字母（否则是 roadno，如 22号）
    --   注意：[A-Za-z0-9]* 允许字母后0个字符（如 3B、111A）
    -- ----------------------------------------------------------------------
    v_match := regexp_match(
        v_addr,
        '([0-9]*[A-Za-z][A-Za-z0-9]*)号' || v_suffix || '$'
    );
    IF v_match IS NOT NULL THEN
        RETURN v_match[1];
    END IF;

    -- ----------------------------------------------------------------------
    -- 模式 3C：字母数字组合(必含字母) + 号
    --   如 111A号、510B号、A137号、3C11A号、A4480A号、G23C号、8110A号、1108B号
    --   "号"不纳入 house 值
    --   过滤：house 前一个字符不能是道路关键字（路/街/道/巷/弄）
    --         例如「振兴路A137号」中 A137 前面是「路」，是 roadno，跳过
    -- ----------------------------------------------------------------------
    v_match := regexp_match(v_addr, '([0-9]*[A-Za-z][A-Za-z0-9]*)号$');
    IF v_match IS NOT NULL THEN
        v_house := v_match[1];
        v_char_before := substring(
            v_addr FROM '.*([^0-9A-Za-z])' || v_house || '号$'
        );
        IF v_char_before IS NULL
           OR v_char_before !~ '[路街道巷弄]' THEN
            RETURN v_house;
        END IF;
        v_house := '';
    END IF;

    -- ----------------------------------------------------------------------
    -- 模式 3D：字母+数字+字母+数字+字母（如 A4480A）
    --   必须早于"字母+数字+字母"模式，避免末尾字母被截断
    -- ----------------------------------------------------------------------
    v_match := regexp_match(v_addr, '([A-Za-z]+[0-9]+[A-Za-z][0-9]+[A-Za-z])$');
    IF v_match IS NOT NULL THEN
        RETURN v_match[1];
    END IF;

    -- ----------------------------------------------------------------------
    -- 模式 3E：数字+字母+数字+字母（如 1B057A、3C11A）
    --   必须早于"数字+字母+数字"模式，避免末尾字母被截断
    --   注意：2B01 末尾是数字，由现有模式4处理
    -- ----------------------------------------------------------------------
    v_match := regexp_match(v_addr, '([0-9]+[A-Za-z][0-9]+[A-Za-z])$');
    IF v_match IS NOT NULL THEN
        RETURN v_match[1];
    END IF;

    -- ----------------------------------------------------------------------
    -- 模式 3F：字母+数字+字母+字母（如 B11HI、G23C）
    --   必须早于"字母+数字+字母"模式，避免末尾字母被截断
    -- ----------------------------------------------------------------------
    v_match := regexp_match(v_addr, '([A-Za-z]+[0-9]+[A-Za-z]{2,})$');
    IF v_match IS NOT NULL THEN
        RETURN v_match[1];
    END IF;

    -- ----------------------------------------------------------------------
    -- 模式 4：数字+字母+数字（如 7B12、1A101）
    -- ----------------------------------------------------------------------
    v_match := regexp_match(v_addr, '([0-9]+[A-Za-z][0-9]+)$');
    IF v_match IS NOT NULL THEN
        RETURN v_match[1];
    END IF;

    -- ----------------------------------------------------------------------
    -- 模式 5：字母+数字+字母（如 B16D、A101B、B16G）
    --   必须早于「字母+数字」模式，避免末尾字母被截断
    -- ----------------------------------------------------------------------
    v_match := regexp_match(v_addr, '([A-Za-z]+[0-9]+[A-Za-z][0-9]*)$');
    IF v_match IS NOT NULL THEN
        RETURN v_match[1];
    END IF;

    -- ----------------------------------------------------------------------
    -- 模式 6：附+数字（如 附01、附1）
    -- ----------------------------------------------------------------------
    v_match := regexp_match(v_addr, '(附[[:space:]]*[0-9]+)$');
    IF v_match IS NOT NULL THEN
        RETURN v_match[1];
    END IF;

    -- ----------------------------------------------------------------------
    -- 模式 7：数字+字母+后缀（如 18A铺、101A室）
    --   后缀不纳入 house 值
    -- ----------------------------------------------------------------------
    v_match := regexp_match(
        v_addr,
        '([0-9]+[A-Za-z])[[:space:]]*' || v_suffix || '$'
    );
    IF v_match IS NOT NULL THEN
        RETURN v_match[1];
    END IF;

    -- ----------------------------------------------------------------------
    -- 模式 8：字母+数字+后缀（如 C4店铺、B201店铺）
    --   后缀不纳入 house 值
    -- ----------------------------------------------------------------------
    v_match := regexp_match(
        v_addr,
        '([A-Za-z]+[0-9]+)[[:space:]]*' || v_suffix || '$'
    );
    IF v_match IS NOT NULL THEN
        RETURN v_match[1];
    END IF;

    -- ----------------------------------------------------------------------
    -- 模式 9：字母+后缀（如 A铺、B档、C档口）
    --   后缀不纳入 house 值
    -- ----------------------------------------------------------------------
    v_match := regexp_match(
        v_addr,
        '([A-Za-z]+)[[:space:]]*' || v_suffix || '$'
    );
    IF v_match IS NOT NULL THEN
        RETURN v_match[1];
    END IF;

    -- ----------------------------------------------------------------------
    -- 模式 10：字母+数字（如 F521、B101、A1、A10、C4）
    -- ----------------------------------------------------------------------
    v_match := regexp_match(v_addr, '([A-Za-z]+[0-9]+)$');
    IF v_match IS NOT NULL THEN
        RETURN v_match[1];
    END IF;

    -- ----------------------------------------------------------------------
    -- 模式 11：末尾纯数字 2-4 位（如 101、302、1101、2001）
    --   优先于「数字+后缀」模式，避免 3号集装箱101 被误识别为 3
    -- ----------------------------------------------------------------------
    v_match := regexp_match(v_addr, '([0-9]{2,4})$');
    IF v_match IS NOT NULL THEN
        RETURN v_match[1];
    END IF;

    -- ----------------------------------------------------------------------
    -- 模式 12：数字+号+后缀（如 3号档口、5号店铺、118号铺、104号商铺）
    --   "号+后缀" 不纳入 house 值
    --   过滤：house 前一个字符不能是数字、连接符或道路关键字（避免 roadno 误识别）
    --         例如「华强北路15号3号档口」中 3 前面是「号」(非数字/连接符/道路)，是 house
    --         例如「龙平东路69号」不会落到本模式（无后缀，由模式 13 处理）
    --         例如「91-13号」不会落到本模式（无后缀，由模式 2/3 处理）
    -- ----------------------------------------------------------------------
    v_match := regexp_match(v_addr, '([0-9]+)号' || v_suffix || '$');
    IF v_match IS NOT NULL THEN
        v_house := v_match[1];
        v_char_before := substring(
            v_addr FROM '.*([^0-9])[[:space:]]*[0-9]+号' || v_suffix || '$'
        );
        IF v_char_before IS NOT NULL
           AND v_char_before !~ '[\-－/\\路街道巷弄]' THEN
            RETURN v_house;
        END IF;
        v_house := '';
    END IF;

    -- ----------------------------------------------------------------------
    -- 模式 13：数字+后缀（如 118商铺、3铺、4号、101房、3号档、118号档、69号）
    --   后缀不纳入 house 值
    --   过滤：house 前一个字符不能是数字、连接符或道路关键字（避免 roadno 误识别）
    --         例如「2栋4号」中 4 前面是「栋」，是 house
    --         例如「工作房1号」中 1 前面是「房」，是 house
    --         例如「91-13号」中 13 前面是「-」，是 roadno，跳过
    --         例如「龙平东路69号」中 69 前面是「路」，是 roadno，跳过
    -- ----------------------------------------------------------------------
    v_match := regexp_match(v_addr, '([0-9]+)[[:space:]]*' || v_suffix_full || '$');
    IF v_match IS NOT NULL THEN
        v_house := v_match[1];
        v_char_before := substring(
            v_addr FROM '.*([^0-9])[[:space:]]*[0-9]+[[:space:]]*' || v_suffix_full || '$'
        );
        IF v_char_before IS NOT NULL
           AND v_char_before !~ '[\-－/\\路街道巷弄]' THEN
            RETURN v_house;
        END IF;
        v_house := '';
    END IF;

    -- ----------------------------------------------------------------------
    -- 模式 13A：数字+字母+字母（如 25AF、11KL、1505AB）
    --   必须早于"数字+字母"模式，避免末尾字母被截断
    -- ----------------------------------------------------------------------
    v_match := regexp_match(v_addr, '([0-9]+[A-Za-z]{2,})$');
    IF v_match IS NOT NULL THEN
        RETURN v_match[1];
    END IF;

    -- ----------------------------------------------------------------------
    -- 模式 14：数字+字母（如 101A、202A、8A）
    -- ----------------------------------------------------------------------
    v_match := regexp_match(v_addr, '([0-9]+[A-Za-z])$');
    IF v_match IS NOT NULL THEN
        RETURN v_match[1];
    END IF;

    -- ----------------------------------------------------------------------
    -- 模式 15：楼层后的单字母（如 一层B、G层A）
    --   仅当前面是楼层关键字（层/楼/F）时，末尾单字母作为 house
    -- ----------------------------------------------------------------------
    v_match := regexp_match(v_addr, '(?:层|楼|F)([A-Za-z])$');
    IF v_match IS NOT NULL THEN
        RETURN v_match[1];
    END IF;

    -- ----------------------------------------------------------------------
    -- 模式 16：特殊无数字 house 描述（如 会议室、大堂、食堂、之一）
    --   仅当所有数字模式都不匹配时才回退使用
    -- ----------------------------------------------------------------------
    v_match := regexp_match(
        v_addr,
        '(整套|之一|公共空间|机房|食堂|大堂|东面|西面|南面|北面|操作间|垃圾房|避难层|杂物房|工具房|工人食堂|架空层|风机房|水泵房|配电房|变压器房|垃圾站|公厕|卫生间|楼梯间|电梯间|走廊|过道|门厅|前台|办公室|会议室|库房|车间|工区|工位)$'
    );
    IF v_match IS NOT NULL THEN
        RETURN v_match[1];
    END IF;

    RETURN '';
END;
$$;


-- -----------------------------------------------------------------------------
-- 存储过程 2：batch_update_house_number
--   批量从地址字段解析房号，写回房号字段。针对大表做了如下优化：
--     1. 基于 ctid + LIMIT 的分批 UPDATE，无需主键，无需一次性加载全表
--     2. 每批次独立事务并 COMMIT，避免长事务锁表、WAL 膨胀
--     3. 默认仅处理「房号字段为 NULL 或空串」的记录，已处理过的不会重复处理
--     4. 可通过 p_where_clause 自定义过滤条件
--     5. 每批次输出进度（RAISE NOTICE）
--     6. 子查询 WHERE 中增加 extract_house_number(addr) <> '' 过滤，
--        跳过无法解析出房号的记录，避免死循环（核心修复）
--
-- 入参：
--   p_table_name   TEXT  表名（支持 schema.table 格式，如 public.enterprise_address）
--   p_address_col  TEXT  地址字段名
--   p_house_col    TEXT  房号字段名（写入目标）
--   p_batch_size   INT   每批次处理行数，默认 5000
--                        - 小表（<10万）：可设 1000~5000
--                        - 大表（>100万）：建议 5000~20000，过大易引发长事务
--   p_where_clause TEXT  可选额外过滤条件（不带 WHERE 关键字）
--                        例如：'create_time >= ''2026-01-01'''
--
-- 出参：无（通过 RAISE NOTICE 输出处理进度）
-- -----------------------------------------------------------------------------
CREATE OR REPLACE PROCEDURE batch_update_house_number(
    p_table_name   TEXT,
    p_address_col  TEXT,
    p_house_col    TEXT,
    p_batch_size   INT  DEFAULT 5000,
    p_where_clause TEXT DEFAULT ''
)
LANGUAGE plpgsql
AS $$
DECLARE
    v_total_count   BIGINT;        -- 待处理总行数
    v_updated_total BIGINT := 0;   -- 累计更新行数
    v_updated_batch INT;           -- 当前批次更新行数
    v_loop_count    INT := 0;      -- 循环计数
    v_update_sql    TEXT;          -- 动态 UPDATE SQL
    v_count_sql     TEXT;          -- 统计 SQL
    v_extra_cond    TEXT := '';    -- 额外过滤条件拼接
BEGIN
    -- ---------------- 参数校验 ----------------
    IF p_table_name IS NULL OR p_table_name = '' THEN
        RAISE EXCEPTION 'p_table_name 不能为空';
    END IF;
    IF p_address_col IS NULL OR p_address_col = '' THEN
        RAISE EXCEPTION 'p_address_col 不能为空';
    END IF;
    IF p_house_col IS NULL OR p_house_col = '' THEN
        RAISE EXCEPTION 'p_house_col 不能为空';
    END IF;
    IF p_batch_size IS NULL OR p_batch_size <= 0 THEN
        p_batch_size := 5000;
    END IF;

    -- 校验表是否存在（无效表名会直接抛错）
    PERFORM p_table_name::regclass;

    -- 拼接额外过滤条件
    IF p_where_clause IS NOT NULL AND p_where_clause <> '' THEN
        v_extra_cond := ' AND (' || p_where_clause || ')';
    END IF;

    -- ---------------- 统计待处理行数 ----------------
    -- 仅统计「房号为空」且「地址非空」的记录
    v_count_sql := format(
        'SELECT count(*) FROM %s WHERE (%I IS NULL OR %I = '''' ) AND %I IS NOT NULL AND %I <> ''''',
        p_table_name, p_house_col, p_house_col,
        p_address_col, p_address_col
    ) || v_extra_cond;

    EXECUTE v_count_sql INTO v_total_count;

    RAISE NOTICE '==== 房号批量解析开始 ====';
    RAISE NOTICE '表名: %, 地址字段: %, 房号字段: %, 批量大小: %',
        p_table_name, p_address_col, p_house_col, p_batch_size;
    RAISE NOTICE '待处理记录数: %', v_total_count;

    IF v_total_count = 0 THEN
        RAISE NOTICE '没有需要处理的记录，结束';
        RETURN;
    END IF;

    -- ---------------- 分批 UPDATE 循环 ----------------
    -- 使用 ctid IN (SELECT ctid ... LIMIT n) 方式分批：
    --   - 无需主键，对任何表都适用
    --   - 子查询在单事务内执行，ctid 一致性有保证
    --   - 每批次 COMMIT 一次，释放锁、控制 WAL 增长
    -- 注意：v_extra_cond 必须放在子查询 WHERE 中（过滤待选记录），
    --       而不是外层 WHERE，否则会因外层缺少字段引用而报错。
    -- 关键修复：子查询 WHERE 中增加 AND extract_house_number(%I) <> ''
    --   原因：若 extract_house_number 对某地址返回空串，UPDATE 后 house_no 仍为 ''，
    --   下次查询 WHERE (house_no IS NULL OR house_no = '') 又会选中该记录，导致死循环。
    --   增加该条件后，只选择能解析出非空房号的记录，无法解析的记录被跳过，
    --   当所有能解析的记录都处理完后，子查询返回 0 条，UPDATE 影响 0 行，循环正常退出。
    v_update_sql := format(
        'UPDATE %s SET %I = extract_house_number(%I) '
        'WHERE ctid IN ('
        '    SELECT ctid FROM %s '
        '    WHERE (%I IS NULL OR %I = '''' ) '
        '      AND %I IS NOT NULL AND %I <> '''' '
        '      AND extract_house_number(%I) <> '''' ',
        p_table_name, p_house_col, p_address_col,
        p_table_name,
        p_house_col, p_house_col,
        p_address_col, p_address_col,
        p_address_col
    );
    -- 拼接额外过滤条件到子查询 WHERE 中
    IF v_extra_cond <> '' THEN
        v_update_sql := v_update_sql || v_extra_cond;
    END IF;
    v_update_sql := v_update_sql || ' LIMIT $1)';

    LOOP
        v_loop_count := v_loop_count + 1;

        -- 执行一批 UPDATE
        EXECUTE v_update_sql USING p_batch_size;
        GET DIAGNOSTICS v_updated_batch = ROW_COUNT;

        -- 本批无更新 → 全部处理完（能解析的已全部处理）
        IF v_updated_batch = 0 THEN
            EXIT;
        END IF;

        v_updated_total := v_updated_total + v_updated_batch;

        -- 每批次提交一次事务（PROCEDURE 内允许 COMMIT）
        COMMIT;

        -- 输出进度（每批一次，避免日志过多）
        -- 注意：PG 的 RAISE NOTICE 只支持 % 占位符，不支持 C 风格的 %.2f
        --       用 round() 四舍五入后用 || '%' 拼接百分号
        RAISE NOTICE '[批次 %] 本批更新 % 条, 累计更新 % / % (%)',
            v_loop_count, v_updated_batch, v_updated_total, v_total_count,
            CASE WHEN v_total_count > 0
                 THEN round(100.0 * v_updated_total / v_total_count, 2) || '%'
                 ELSE '0%' END;
    END LOOP;

    RAISE NOTICE '==== 房号批量解析完成 ====';
    RAISE NOTICE '累计更新 % 条, 共 % 个批次', v_updated_total, v_loop_count;
    -- 提示无法解析的记录数（这些记录的 house_no 保持原值 NULL/空串）
    IF v_total_count > v_updated_total THEN
        RAISE NOTICE '注: % 条记录无法解析出房号，保持原值不变（可后续人工处理）',
            v_total_count - v_updated_total;
    END IF;
END;
$$;


-- =============================================================================
-- 使用示例（注释，不会被 PG 执行）
-- =============================================================================
-- 1. 单条地址解析测试：
--    SELECT extract_house_number('广东省深圳市福田区华强北街道华航社区振兴路91-13号B101');
--    -- 期望: B101
--
--    SELECT extract_house_number('广东省深圳市宝安区新安街道甲岸社区宝民一路甲岸村22号401');
--    -- 期望: 401
--
--    SELECT extract_house_number('广东省深圳市罗湖区黄贝街道水库社区东湖公园杜鹃园宿舍2栋4号');
--    -- 期望: 4
--
--    SELECT extract_house_number('广东省深圳市南山区桃源街道峰景社区北环大道8028号方直珑樾山花园1栋负3层');
--    -- 期望: '' (空，因为是楼层而非房号)
--
--    SELECT extract_house_number('广东省深圳市福田区华强北街道华航社区振兴路91-13号');
--    -- 期望: '' (空，末尾是门牌号 roadno)
--
-- 2. 批量更新表：
--    CALL batch_update_house_number(
--        p_table_name  := 'public.enterprise_address',
--        p_address_col := 'address',
--        p_house_col   := 'house_no',
--        p_batch_size  := 10000
--    );
--    -- 注意：无法解析出房号的记录会被跳过（house_no 保持 NULL/空串），
--    --      避免死循环。可用以下 SQL 查看未解析的记录：
--    --      SELECT * FROM public.enterprise_address
--    --      WHERE house_no IS NULL OR house_no = '';
--
-- 3. 带过滤条件批量更新（只处理某天新增的数据）：
--    CALL batch_update_house_number(
--        p_table_name   := 'public.enterprise_address',
--        p_address_col  := 'address',
--        p_house_col    := 'house_no',
--        p_batch_size   := 5000,
--        p_where_clause := 'create_time >= ''2026-07-01'''
--    );
--
-- 4. 查看解析效果（不写入，仅预览）：
--    SELECT address, extract_house_number(address) AS house
--    FROM public.enterprise_address
--    LIMIT 100;
-- =============================================================================
