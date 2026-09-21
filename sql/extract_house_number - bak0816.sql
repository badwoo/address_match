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
--       p_id_col      := 'id',
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
    v_bracket_text TEXT;        -- 末尾括号内容（用于通用括号剥离判断）
    -- 后缀列表（不含"号"，"号"单独处理以支持 "数字+号+后缀" 组合）
    -- 注意：长后缀必须排在短后缀前面（如"商铺"在"铺"前），避免被短后缀抢先匹配
    -- 扩展：增加 专柜/店/房屋/厂房 等房号后缀类型（与 Python _HOUSE_SUFFIX 同步）
    -- 扩展：增加 教师宿舍/宿舍/杂物间/夹层/教室/裙楼 等建筑/房间类型后缀
    --   - 教师宿舍(4字) 必须在 宿舍(2字) 前
    --   - 杂物间(3字) 必须在 间(1字) 前
    v_suffix    TEXT := '(?:商铺|店铺|铺位|铺面|档铺|教师宿舍|杂物间|房间|房屋|厂房|柜台|专柜|档口|裙楼|夹层|教室|宿舍|埔|铺|档|室|房|户|间|柜|店)';
    -- 后缀列表（含"号"和"号X"组合，用于 "数字+后缀" 模式）
    -- 扩展：增加 专柜/店/房屋/厂房（与 Python _HOUSE_SUFFIX 同步）
    -- 扩展：增加 教师宿舍/宿舍/杂物间/夹层/教室/裙楼（与 Python _HOUSE_SUFFIX 同步）
    v_suffix_full TEXT := '(?:商铺|店铺|号铺|铺位|铺面|档铺|教师宿舍|杂物间|房间|房屋|厂房|柜台|专柜|号档|档口|裙楼|夹层|教室|宿舍|埔|铺|号|档|室|房|户|间|柜|店)';
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
    -- 预处理（顺序与 Python _parse_single 同步）：
    --   1. 特定备注剥离：(入驻XXX)、(仅限办公)、(仅办公)、(办公场所/住所/地址)、
    --      (一照多址企业) 等。注意：入驻备注可能含嵌套括号，需贪婪匹配
    --   2. 通用末尾括号剥离：剥离"非房号"括号（不含数字 或 含楼层关键字层/楼/F），
    --      保留"可能是房号"的括号（含数字且不含楼层关键字），如 (102铺)、(03)，
    --      由后续模式 3A / 3A1 匹配
    --   3. 末尾句号"。"剥离
    --   4. 末尾位置说明剥离（东侧/西侧/南侧/北侧/旁边/旁）
    --   5. 房号后的 # 号剥离（如 303#→303、119#铺→119铺、501B-1#→501B-1）
    --      注意：不剥离 "2#A栋" 中的 #（# 后是字母且非末尾后缀）
    -- ----------------------------------------------------------------------
    -- 1. 特定备注剥离（合并为单个正则，与 Python _BRACKET_NOTE_PATTERN 同步）
    v_addr := regexp_replace(
        v_addr,
        '[(（](?:入驻.*|仅限办公|仅限[^()]*|仅办公|办公(?:场所|住所|地址)|一照多址企业)[)）][[:space:]]*$',
        ''
    );

    -- 2. 通用末尾括号剥离
    v_bracket_text := substring(v_addr FROM '[(（]([^()]*)[)）][[:space:]]*$');
    IF v_bracket_text IS NOT NULL THEN
        -- 不含数字 或 含楼层关键字(层/楼/F) → 一定不是房号，剥离
        -- 例如 (2层-3层)→剥离、(珠光创新科技园旁)→剥离、(中佳创意园)→剥离
        -- 含数字且不含楼层关键字 → 可能是房号，保留让模式 3A/3A1 处理
        -- 例如 (102铺)→保留、(03)→保留
        -- 扩展：括号内"末尾"含 数字+房号后缀 时也保留（如 (一楼102铺) 中"102铺"是房号），
        -- 此类括号内含楼层描述（一楼）+房号（102铺），不能因含"楼"字被误剥离
        IF (v_bracket_text !~ '[0-9]' OR v_bracket_text ~ '(?:层|楼|F)')
           AND v_bracket_text !~ ('[0-9]+[[:space:]]*(?:' || v_suffix || ')$') THEN
            v_addr := regexp_replace(v_addr, '[(（][^()]*[)）][[:space:]]*$', '');
        END IF;
    END IF;

    -- 3. 末尾句号剥离
    v_addr := regexp_replace(v_addr, '[。.]+[[:space:]]*$', '');

    -- 4. 末尾位置说明剥离（如"52栋301东侧"→"52栋301"）
    v_addr := regexp_replace(v_addr, '(?:东侧|西侧|南侧|北侧|旁边|旁)[[:space:]]*$', '');

    -- 5. 剥离末尾"房号后缀+商业后缀"中的商业后缀
    --    如 101室商铺→101室、124室商铺→124室，使房号能被后续模式正确匹配
    v_addr := regexp_replace(
        v_addr,
        '(室|房|户|间|房间|铺|埔|档|档口|号档|号铺|铺位|铺面|档铺)(商铺|店铺|专柜|柜台)$',
        '\1'
    );

    -- 6. 房号后的 # 号剥离（与 Python _HOUSE_HASH_PATTERN 同步）
    --    (\d)#((?:后缀)?\s*$) → \1\2，即去掉 # 保留数字和可选后缀
    v_addr := regexp_replace(v_addr, '(\d)#((?:' || v_suffix || ')?[[:space:]]*)$', '\1\2');
    --    扩展：末尾 # 兜底剥离（如 102室# 中 # 前是后缀"室"而非数字），
    --    剥离后 "102室" 可被模式 13a 正确匹配
    v_addr := regexp_replace(v_addr, '#[[:space:]]*$', '');

    -- ----------------------------------------------------------------------
    -- 模式 0：多房号顿号分隔（如 F202、203 / 1311、1312、1313室 / B-2201、2202A /
    --   24D-F、D1 / B1JF105、106号）
    --   段 = 字母数字+可选横杠/长横杠连接；末尾可带"号"或房号后缀，末尾锚定$
    --   避免"7、8、9、16栋201"（bldg序列）误匹配：段后跟"栋"无法消化，整体不匹配
    --   （与 Python HOUSE_PATTERNS 第一个模式同步）
    -- ----------------------------------------------------------------------
    v_match := regexp_match(
        v_addr,
        '((?:[A-Za-z0-9]+(?:[-－/—]+[A-Za-z0-9]+)*)'
        || '(?:、[A-Za-z0-9]+(?:[-－/—]+[A-Za-z0-9]+)*)+)'
        || '[[:space:]]*(?:号)?[[:space:]]*(?:' || v_suffix || ')?$'
    );
    IF v_match IS NOT NULL THEN
        RETURN v_match[1];
    END IF;

    -- ----------------------------------------------------------------------
    -- 模式 1：横杠连接 + 后缀（如 A1-2铺、B3-4档、B1-09——CB109柜）
    --   后缀不纳入 house 值
    --   支持长横杠/双横杠（如 ——，U+2014）
    -- ----------------------------------------------------------------------
    v_match := regexp_match(
        v_addr,
        '([A-Za-z0-9]+(?:[-－/—]+[A-Za-z0-9]+)+)[[:space:]]*' || v_suffix || '$'
    );
    IF v_match IS NOT NULL THEN
        RETURN v_match[1];
    END IF;

    -- ----------------------------------------------------------------------
    -- 模式 1A：横杠连接 + 号 + 后缀（如 A17-3号铺、LG-M-05号铺、102-103-2号商铺、28-29号商铺、196—215号商铺）
    --   "号" 和后缀均不纳入 house 值
    --   支持长横杠（如 196—215，U+2014）
    --   注意：末尾有房号后缀说明一定是 house，不过滤道路关键字（路/街/道/巷/弄）
    --         但仍过滤连接符（- / ／），让模式 1B 处理前导连接符的情况（如 -LM-11号商铺）
    --         roadno（如「91-13号」无后缀）不会匹配本模式（本模式要求末尾有后缀）
    --         与 Python _HOUSE_SUFFIX_AFTER_ROADNO_PATTERN 逻辑一致：
    --         roadno 后跟房号后缀时，roadno 被丢弃让主流程处理为 house
    -- ----------------------------------------------------------------------
    v_match := regexp_match(
        v_addr,
        '([A-Za-z0-9]+(?:[-－/—]+[A-Za-z0-9]+)+)号' || v_suffix || '$'
    );
    IF v_match IS NOT NULL THEN
        v_house := v_match[1];
        v_char_before := substring(
            v_addr FROM '.*([^0-9A-Za-z])' || v_house || '号' || v_suffix || '$'
        );
        -- 只过滤连接符（让模式 1B 处理前导 -），不过滤道路关键字（有后缀说明是 house）
        IF v_char_before IS NULL
           OR v_char_before !~ '[\-－/\\—]' THEN
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
    v_match := regexp_match(v_addr, '([A-Za-z0-9]+(?:[-－/—]+[A-Za-z0-9]+)+)号$');
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
    -- 模式 3：横杠连接（如 101-102、L1-21A、1-2-3-4、B1-49.50）
    --   过滤：末尾紧跟楼栋关键字（bldg 残留）或「号」（roadno）时跳过
    --   扩展：连接符支持点号（如 B1-49.50）和长横杠
    -- ----------------------------------------------------------------------
    v_match := regexp_match(v_addr, '([A-Za-z0-9]+(?:[-－/—.]+[A-Za-z0-9]+)+)$');
    IF v_match IS NOT NULL THEN
        v_house := v_match[1];
        IF v_addr !~ (v_house || '(?:号楼|塔楼|栋|幢|座|号)$') THEN
            RETURN v_house;
        END IF;
        v_house := '';
    END IF;

    -- ----------------------------------------------------------------------
    -- 模式 3A：横杠连接 + 括号数字（如 A-3501(03)、3A08-(2)）
    --   括号内容是房号的一部分，需保留
    --   扩展：横杠后可直接跟括号（如 3A08-(2) 中"-"后无字母数字段）
    --   支持长横杠
    -- ----------------------------------------------------------------------
    v_match := regexp_match(v_addr, '([A-Za-z0-9]+(?:[-－/—]+[A-Za-z0-9]+)*[-－/—]?\([0-9]+\))$');
    IF v_match IS NOT NULL THEN
        RETURN v_match[1];
    END IF;

    -- ----------------------------------------------------------------------
    -- 模式 3A1：末尾括号内房号（如 (102铺)、(03)、(101A)、(A07-08号商铺)、(一楼102铺)）
    --   仅在模式 3A 不匹配时尝试（3A 处理"横杠连接+括号数字"整体）
    --   预处理阶段已剥离"非房号"括号（不含数字或含层/楼/F 且末尾无数字+后缀），
    --   到这里的括号内一定是房号格式（含数字且不含楼层关键字，或末尾含数字+后缀）
    --   扩展：[^()]*? 允许括号内有前置中文（如"一楼102铺"中的"一楼"楼层描述）
    --   提取括号内房号，去掉末尾"号"和后缀
    --   例如：13号（102铺）→ 102，5栋(03)→03，101号(101A)→101A，6号(一楼102铺)→102
    -- ----------------------------------------------------------------------
    v_match := regexp_match(
        v_addr,
        '[(（][^()]*?([A-Za-z]?\d+(?:[-－/—]+\d+)*(?:[A-Za-z]\d*)?)[[:space:]]*(?:号)?[[:space:]]*(?:' || v_suffix || ')?[[:space:]]*[)）][[:space:]]*$'
    );
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
    -- 模式 3C1：下划线连接房号（如 A322B_01）
    --   lookahead 要求至少含一个数字，避免纯字母 A_B 误匹配
    --   必须早于"通用字母数字多段交替"模式（3C2）：否则 A322B_01 会被通用模式
    --   通过回溯拆分为 A32+2B 两段抢先匹配为 A322B，丢失 _01 部分
    --   PG 正则不支持 lookbehind，用 (?:[^0-9A-Za-z]|^) 变通锚定串首
    -- ----------------------------------------------------------------------
    v_match := regexp_match(
        v_addr,
        '(?:[^0-9A-Za-z]|^)((?=[A-Za-z0-9_]*[0-9])[A-Za-z0-9]+(?:_[A-Za-z0-9]+)+)$'
    );
    IF v_match IS NOT NULL THEN
        RETURN v_match[1];
    END IF;

    -- ----------------------------------------------------------------------
    -- 模式 3C2：通用字母数字多段交替（如 6A1BC、N2C248、12B19G1、B1JF428、F1F0009、A4207A6、1F0009）
    --   {2,} 确保至少两段"字母+数字"/"数字+字母"交替，避免误匹配单段（B16、100B、A137等）
    --   必须早于 3D/3E/3F（字母数字截断模式），避免末尾字母/数字被截断：
    --     「B1JF428」会被 3F 截断为 B1JF；「6A1BC」会被 3E 截断为 6A1B；「12B19G1」会被 3E 截断为 12B19G
    --   PG 正则不支持 lookbehind，用 (?:[^0-9A-Za-z]|^) 变通锚定串首，
    --   避免开头字母残留（如 N2C248 被切为 N+2C248）
    --   注意：A4480A/1B057A/B11HI/G23C/B16D/A101B 等场景回溯后结果与 3D/3E/3F/模式5 一致
    -- ----------------------------------------------------------------------
    v_match := regexp_match(
        v_addr,
        '(?:[^0-9A-Za-z]|^)((?:[A-Za-z]+[0-9]+|[0-9]+[A-Za-z]+){2,}[A-Za-z0-9]*)$'
    );
    IF v_match IS NOT NULL THEN
        RETURN v_match[1];
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
    -- 模式 10A："之X"子房号（如 302之2→302、106之8→106、201之4→201、302之12→302）
    --   提取"之"前面的数字作为房号，"之X"为子房号标识不纳入 house 值
    --   必须在"末尾纯数字2-4位"之前，避免"302之12"中"12"被末尾纯数字模式抢先匹配
    --   末尾锚定 $，避免匹配文本中间的"数字+之+数字"
    --   注意：仅匹配"之+ASCII数字"，不匹配"之一/之二"等中文数字
    -- ----------------------------------------------------------------------
    v_match := regexp_match(v_addr, '([0-9]+)[[:space:]]*之[0-9]+$');
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
    -- 模式 12：数字+号+后缀（如 3号档口、5号店铺、118号铺、104号商铺、17号商铺、06号铺）
    --   "号+后缀" 不纳入 house 值
    --   注意：末尾有房号后缀说明一定是 house，不再过滤前字符
    --         与 Python _HOUSE_SUFFIX_AFTER_ROADNO_PATTERN 逻辑一致
    --         roadno（如「69号」无后缀）不会匹配本模式（本模式要求末尾有后缀）
    -- ----------------------------------------------------------------------
    v_match := regexp_match(v_addr, '([0-9]+)号' || v_suffix || '$');
    IF v_match IS NOT NULL THEN
        RETURN v_match[1];
    END IF;

    -- ----------------------------------------------------------------------
    -- 模式 12A：数字+房号后缀+"之X"子房号（如 106商铺之一→106、102室之二→102）
    --   必须早于模式 16（特殊中文描述），否则"之一"会被模式 16 误识别为 house
    --   "之X"为子房号标识不纳入 house 值（与模式 10A "数字+之X" 同理）
    -- ----------------------------------------------------------------------
    v_match := regexp_match(
        v_addr,
        '([0-9]+)[[:space:]]*(?:' || v_suffix || ')[[:space:]]*之[一二三四五六七八九十0-9]+$'
    );
    IF v_match IS NOT NULL THEN
        RETURN v_match[1];
    END IF;

    -- ----------------------------------------------------------------------
    -- 模式 13a：数字+房号后缀（不含"号"，如 118商铺、3铺、101房、301厂房、511室）
    --   后缀不纳入 house 值
    --   注意：末尾有房号后缀（室/房/铺等）说明一定是 house，不检查前字符
    --         例如「5层-511室」中 511 前是「-」，但有后缀「室」，是 house
    --         例如「华强南路3018店铺」中 3018 前是「路」，但有后缀「店」，是 house
    -- ----------------------------------------------------------------------
    v_match := regexp_match(v_addr, '([0-9]+)[[:space:]]*' || v_suffix || '$');
    IF v_match IS NOT NULL THEN
        RETURN v_match[1];
    END IF;

    -- ----------------------------------------------------------------------
    -- 模式 13b：数字+号（无其他后缀，如 2栋4号、工作房1号、69号）
    --   "号" 不纳入 house 值
    --   正向检查：只有前一个字符是建筑物关键字或楼栋关键字时，"X号"才是房号
    --   否则"X号"是门牌号（roadno），跳过
    --   建筑物关键字：房/屋/室/楼/厦/堂/馆/轩/舍/宿（area以建筑物名结尾）
    --   楼栋关键字：栋/幢/座/层/F（楼栋/楼层后的"X号"是房号）
    --   单元关键字：元/梯（单元/电梯后的"X号"是房号，如"6单元824号"）
    --   "号"关键字：前一个"号"后的"X号"是房号（如"18号101号"中"101号"是房号）
    --   例如「2栋4号」中 4 前面是「栋」，是 house
    --   例如「工作房1号」中 1 前面是「房」，是 house
    --   例如「综合楼14号」中 14 前面是「楼」，是 house
    --   例如「6单元824号」中 824 前面是「元」，是 house
    --   例如「18号101号」中 101 前面是「号」，是 house
    --   例如「30号103号」中 103 前面是「号」，是 house
    --   例如「下企沙村33号」中 33 前面是「村」，是 roadno，跳过
    --   例如「三坊67号」中 67 前面是「坊」，是 roadno，跳过
    --   例如「91-13号」中 13 前面是「-」，是 roadno，跳过
    --   例如「龙平东路69号」中 69 前面是「路」，是 roadno，跳过
    -- ----------------------------------------------------------------------
    v_match := regexp_match(v_addr, '([0-9]+)号$');
    IF v_match IS NOT NULL THEN
        v_house := v_match[1];
        v_char_before := substring(
            v_addr FROM '.*([^0-9])[[:space:]]*[0-9]+号$'
        );
        IF v_char_before IS NOT NULL
           AND v_char_before ~ '[房屋室楼厦堂馆轩舍宿栋幢座层F号元梯]' THEN
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
--     1. 使用用户指定的 p_id_col 列作为分批游标（keyset pagination）
--        要求 p_id_col 是数值类型（int/bigint/serial）且其上有 B-tree 索引（通常是主键）
--     2. 无需给表加临时列、无需 DDL，避免锁表和 schema 膨胀
--     3. 单个 CTE SQL 同时完成「取本批 + 调用函数 + UPDATE + 返回统计」
--        无法解析的记录不更新（house_no 保持原值），每行只调用一次函数
--     4. 每批次独立事务并 COMMIT，避免长事务锁表、WAL 膨胀
--     5. 保留 (house_no IS NULL OR house_no = '') 判断保证幂等性（重复调用安全）
--     6. 可通过 p_where_clause 自定义过滤条件
--     7. 输出开始/结束时间、执行时长，每批输出批次进度（当前批次/总批次）
--
-- ★ 为什么用 p_id_col 而不用 ctid 分批？
--   PostgreSQL 的 UPDATE 是 MVCC「DELETE+INSERT」，行的 ctid 会变化，
--   UPDATE 后行的 ctid 变了，WHERE ctid > last_ctid 会重复扫描已处理行。
--   p_id_col 是普通列，UPDATE 不改变其值，可作为稳定游标；
--   且用户主键上通常已有索引，keyset pagination 直接走索引扫描，性能稳定。
--
-- ★ 性能要点：
--   - p_id_col 上必须有 B-tree 索引（主键/唯一索引均可），否则 WHERE id > $1 ORDER BY id
--     会退化为全表扫描 + 排序，大表性能极差
--   - UPDATE 的 WHERE t.id = b.id_val 走主键索引，单行定位高效
--   - 每批扫描行数固定为 batch_size，不随进度增长（keyset pagination 优势）
--
-- 入参：
--   p_table_name   TEXT  表名（支持 schema.table 格式）
--   p_id_col       TEXT  分批游标列名（必须是数值类型，建议为主键且有索引）
--   p_address_col  TEXT  地址字段名
--   p_house_col    TEXT  房号字段名（写入目标）
--   p_batch_size   INT   每批次处理行数，默认 5000
--   p_where_clause TEXT  可选额外过滤条件（不带 WHERE 关键字）
--
-- 出参：无（通过 RAISE NOTICE 输出处理进度）
-- -----------------------------------------------------------------------------
CREATE OR REPLACE PROCEDURE batch_update_house_number(
    p_table_name   TEXT,
    p_id_col       TEXT,
    p_address_col  TEXT,
    p_house_col    TEXT,
    p_batch_size   INT  DEFAULT 5000,
    p_where_clause TEXT DEFAULT ''
)
LANGUAGE plpgsql
AS $$
DECLARE
    v_total_count     BIGINT;          -- 待处理总行数
    v_total_batches   BIGINT;          -- 总批次数（向上取整）
    v_processed_total BIGINT := 0;     -- 累计处理行数（含无法解析的，用于进度统计）
    v_updated_total   BIGINT := 0;     -- 累计更新行数（实际写入房号的）
    v_updated_batch   BIGINT;          -- 当前批次更新行数
    v_batch_total     BIGINT;          -- 当前批次处理行数（含无法解析的）
    v_loop_count      INT := 0;        -- 已处理批次数
    v_last_id         BIGINT := 0;     -- p_id_col 游标（keyset pagination）
    v_batch_sql       TEXT;            -- 合并取批+UPDATE+统计的 CTE SQL
    v_extra_cond      TEXT := '';      -- 额外过滤条件拼接
    v_start_time      TIMESTAMP;       -- 开始时间
    v_end_time        TIMESTAMP;       -- 结束时间
    v_id_type         TEXT;            -- p_id_col 的数据类型
BEGIN
    v_start_time := clock_timestamp();

    -- ---------------- 参数校验 ----------------
    IF p_table_name IS NULL OR p_table_name = '' THEN
        RAISE EXCEPTION 'p_table_name 不能为空';
    END IF;
    IF p_id_col IS NULL OR p_id_col = '' THEN
        RAISE EXCEPTION 'p_id_col 不能为空';
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

    -- 校验 p_id_col 列存在且是数值类型（int2/int4/int8/serial 等）
    -- 非数值类型无法用于 keyset pagination 的 > 比较
    SELECT format_type(atttypid, atttypmod)
      INTO v_id_type
      FROM pg_attribute
     WHERE attrelid = p_table_name::regclass
       AND attname = p_id_col
       AND NOT attisdropped;

    IF v_id_type IS NULL THEN
        RAISE EXCEPTION '列 % 不存在于表 %', p_id_col, p_table_name;
    END IF;
    IF v_id_type !~ '^(int|bigint|smallint|serial|bigserial)' THEN
        RAISE EXCEPTION 'p_id_col 必须是数值类型（int/bigint/serial），当前类型: %', v_id_type;
    END IF;

    -- 校验 address_col / house_col 列存在
    IF NOT EXISTS (
        SELECT 1 FROM pg_attribute
        WHERE attrelid = p_table_name::regclass
          AND attname = p_address_col
          AND NOT attisdropped
    ) THEN
        RAISE EXCEPTION '地址列 % 不存在于表 %', p_address_col, p_table_name;
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_attribute
        WHERE attrelid = p_table_name::regclass
          AND attname = p_house_col
          AND NOT attisdropped
    ) THEN
        RAISE EXCEPTION '房号列 % 不存在于表 %', p_house_col, p_table_name;
    END IF;

    -- 拼接额外过滤条件
    IF p_where_clause IS NOT NULL AND p_where_clause <> '' THEN
        v_extra_cond := ' AND (' || p_where_clause || ')';
    END IF;

    -- ---------------- 1. 统计待处理总数 + 计算总批次数 ----------------
    -- 不调用 extract_house_number 提前过滤，只过滤 house_no 为空 + address 非空
    -- 无法解析出房号的记录也包含在内，CTE 的 house_val <> '' 会过滤
    EXECUTE format(
        'SELECT count(*) FROM %s '
        'WHERE (%I IS NULL OR %I = '''') '
        '  AND %I IS NOT NULL AND %I <> '''' %s',
        p_table_name,
        p_house_col, p_house_col,
        p_address_col, p_address_col,
        v_extra_cond
    ) INTO v_total_count;

    -- 总批次数（向上取整，整数除法避免 float 转换）
    v_total_batches := (v_total_count + p_batch_size - 1) / p_batch_size;

    RAISE NOTICE '==== 房号批量解析开始 ====';
    RAISE NOTICE '开始时间: %', v_start_time;
    RAISE NOTICE '表名: %, ID列: %, 地址字段: %, 房号字段: %, 批量大小: %',
        p_table_name, p_id_col, p_address_col, p_house_col, p_batch_size;
    RAISE NOTICE '待处理记录数: %, 预计批次: %', v_total_count, v_total_batches;

    -- ---------------- 2. 分批处理（单个 CTE SQL 完成取批+UPDATE+统计）----------------
    -- CTE batch：取本批 p_id_col 对应且 house_no 为空的记录，调用一次 extract_house_number
    -- CTE upd  ：UPDATE 只更新 house_val <> '' 的记录（无法解析的保持原值），RETURNING 用于统计
    -- 主 SELECT：返回 本批总数 / 更新数 / 本批最大 p_id_col（推进游标）
    -- 每行只调用一次函数，无法解析的记录不 UPDATE（house_no 保持 NULL/空串，幂等安全）
    -- 性能：WHERE id > $1 ORDER BY id 走 B-tree 索引，UPDATE WHERE t.id = b.id_val 走主键索引
    v_batch_sql := format(
        'WITH batch AS ('
        '    SELECT %I AS id_val, extract_house_number(%I) AS house_val '
        '    FROM %s '
        '    WHERE %I > $1 '
        '      AND (%I IS NULL OR %I = '''' ) '
        '      AND %I IS NOT NULL AND %I <> '''' '
        '      %s '
        '    ORDER BY %I LIMIT $2'
        '), '
        'upd AS ('
        '    UPDATE %s AS t SET %I = b.house_val '
        '    FROM batch b '
        '    WHERE t.%I = b.id_val AND b.house_val <> '''' '
        '    RETURNING t.%I'
        ') '
        'SELECT '
        '    (SELECT count(*) FROM batch), '
        '    (SELECT count(*) FROM upd), '
        '    (SELECT max(id_val) FROM batch)',
        p_id_col, p_address_col,
        p_table_name,
        p_id_col,
        p_house_col, p_house_col,
        p_address_col, p_address_col,
        v_extra_cond,
        p_id_col,
        p_table_name, p_house_col,
        p_id_col,
        p_id_col
    );

    IF v_total_count > 0 THEN
        LOOP
            -- 单个 CTE SQL 一次完成：取本批 + UPDATE + 返回统计
            EXECUTE v_batch_sql
            INTO v_batch_total, v_updated_batch, v_last_id
            USING v_last_id, p_batch_size;

            -- 无数据则退出（已处理完全部待处理记录）
            IF v_batch_total = 0 OR v_last_id IS NULL THEN
                EXIT;
            END IF;

            v_loop_count := v_loop_count + 1;
            v_processed_total := v_processed_total + v_batch_total;
            v_updated_total := v_updated_total + v_updated_batch;

            -- 每批次提交一次事务（PROCEDURE 内允许 COMMIT），避免长事务锁表、WAL 膨胀
            COMMIT;

            -- 输出批次进度（当前批次/总批次，基于处理记录数的进度）
            RAISE NOTICE '[批次 %/%] 本批 % 条, 更新 % 条, 累计处理 % / % (%)',
                v_loop_count, v_total_batches, v_batch_total, v_updated_batch,
                v_processed_total, v_total_count,
                CASE WHEN v_total_count > 0
                     THEN round(100.0 * v_processed_total / v_total_count, 2) || '%'
                     ELSE '0%' END;
        END LOOP;
    END IF;

    -- ---------------- 3. 输出统计信息 ----------------
    v_end_time := clock_timestamp();
    RAISE NOTICE '==== 房号批量解析完成 ====';
    RAISE NOTICE '开始时间: %', v_start_time;
    RAISE NOTICE '结束时间: %', v_end_time;
    RAISE NOTICE '执行时长: %', v_end_time - v_start_time;
    RAISE NOTICE '累计处理 % 条, 更新 % 条, 共 % / % 个批次',
        v_processed_total, v_updated_total, v_loop_count, v_total_batches;
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
--        p_id_col      := 'id',
--        p_address_col := 'address',
--        p_house_col   := 'house_no',
--        p_batch_size  := 10000
--    );
--    -- 注意：无法解析出房号的记录会被跳过（house_no 保持 NULL/空串），
--    --      避免死循环。可用以下 SQL 查看未解析的记录：
--    --      SELECT * FROM public.enterprise_address
--    --      WHERE house_no IS NULL OR house_no = '';
--    -- 要求：p_id_col 必须是数值类型（int/bigint/serial）且其上有 B-tree 索引（通常是主键）
--
-- 3. 带过滤条件批量更新（只处理某天新增的数据）：
--    CALL batch_update_house_number(
--        p_table_name   := 'public.enterprise_address',
--        p_id_col       := 'id',
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
