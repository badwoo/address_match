"""
标签转拼音工具模块
==============

将中文标签转为拼音前缀，用于生成数据库表名前缀。

核心功能：
    1. tag_to_prefix - 将标签转为表名前缀（中文转拼音，英文/数字保持原样）
    2. get_tag_tables - 根据标签前缀生成对应的 recall 和 match 表名
    3. get_existing_tags - 从数据库中检索所有已有标签前缀
"""

import re
from pypinyin import lazy_pinyin, Style

# 常用汉字拼音映射表（覆盖常见地名用字，作为 pypinyin 的回退）
_HANZI_PINYIN = {
    '福': 'fu', '田': 'tian', '罗': 'luo', '湖': 'hu', '南': 'nan', '北': 'bei',
    '东': 'dong', '西': 'xi', '山': 'shan', '龙': 'long', '华': 'hua', '宝': 'bao',
    '安': 'an', '新': 'xin', '深': 'shen', '圳': 'zhen', '广': 'guang', '州': 'zhou',
    '上': 'shang', '海': 'hai', '京': 'jing', '天': 'tian', '津': 'jin',
    '重': 'chong', '庆': 'qing', '杭': 'hang', '苏': 'su', '成': 'cheng', '都': 'du',
    '武': 'wu', '汉': 'han', '郑': 'zheng',
    '长': 'chang', '沙': 'sha', '沈': 'shen', '阳': 'yang', '大': 'da', '连': 'lian',
    '青': 'qing', '岛': 'dao', '厦': 'xia', '门': 'men', '宁': 'ning', '波': 'bo',
    '济': 'ji', '无': 'wu', '锡': 'xi', '常': 'chang', '州': 'zhou',
    '通': 'tong', '徐': 'xu', '温': 'wen', '合': 'he', '肥': 'fei', '昆': 'kun',
    '明': 'ming', '哈': 'ha', '尔': 'er', '滨': 'bin', '莞': 'guan',
    '佛': 'fo', '中': 'zhong', '珠': 'zhu', '惠': 'hui', '汕': 'shan', '头': 'tou',
    '三': 'san', '亚': 'ya', '桂': 'gui', '林': 'lin',
    '贵': 'gui', '阳': 'yang', '兰': 'lan', '太': 'tai', '原': 'yuan', '石': 'shi',
    '家': 'jia', '庄': 'zhuang', '呼': 'hu', '和': 'he', '浩': 'hao', '特': 'te',
    '银': 'yin', '川': 'chuan', '乌': 'wu', '鲁': 'lu', '木': 'mu', '齐': 'qi',
    '拉': 'la', '萨': 'sa', '香': 'xiang', '港': 'gang', '澳': 'ao', '台': 'tai',
    '桃': 'tao', '园': 'yuan', '高': 'gao', '雄': 'xiong', '基': 'ji', '隆': 'long',
    '松': 'song', '平': 'ping', '盐': 'yan', '埔': 'pu', '坂': 'ban', '岗': 'gang',
    '区': 'qu', '县': 'xian', '市': 'shi', '镇': 'zhen', '乡': 'xiang', '村': 'cun',
    '街': 'jie', '道': 'dao', '路': 'lu', '巷': 'xiang', '弄': 'long', '号': 'hao',
    '楼': 'lou', '栋': 'dong', '层': 'ceng', '室': 'shi', '单': 'dan', '元': 'yuan',
    '企': 'qi', '业': 'ye', '公': 'gong', '司': 'si', '厂': 'chang', '工': 'gong',
    '科': 'ke', '技': 'ji', '发': 'fa', '展': 'zhan', '实': 'shi', '有': 'you',
    '限': 'xian', '责': 'ze', '任': 'ren', '股': 'gu', '份': 'fen', '贸': 'mao',
    '易': 'yi', '投': 'tou', '资': 'zi', '管': 'guan', '理': 'li', '服': 'fu',
    '务': 'wu', '咨': 'zi', '询': 'xun', '信': 'xin', '息': 'xi', '网': 'wang',
    '络': 'luo', '电': 'dian', '子': 'zi', '商': 'shang', '建': 'jian', '筑': 'zhu',
    '材': 'cai', '设': 'she', '备': 'bei', '机': 'ji', '械': 'xie', '五': 'wu',
    '金': 'jin', '化': 'hua', '纺': 'fang', '织': 'zhi', '食': 'shi', '品': 'pin',
    '药': 'yao', '医': 'yi', '疗': 'liao', '保': 'bao', '健': 'jian', '教': 'jiao',
    '培': 'pei', '训': 'xun', '文': 'wen', '旅': 'lv', '酒': 'jiu', '店': 'dian',
    '餐': 'can', '饮': 'yin', '物': 'wu', '流': 'liu', '快': 'kuai', '递': 'di',
    '仓': 'cang', '储': 'chu', '运': 'yun', '输': 'shu', '出': 'chu', '租': 'zu',
    '汽': 'qi', '车': 'che', '零': 'ling', '配': 'pei', '维': 'wei', '修': 'xiu',
    '装': 'zhuang', '饰': 'shi', '广': 'guang', '告': 'gao', '印': 'yin', '刷': 'shua',
    '娱': 'yu', '乐': 'le', '健': 'jian', '身': 'shen', '美': 'mei', '容': 'rong',
    '律': 'lv', '师': 'shi', '会': 'hui', '计': 'ji', '审': 'shen', '税': 'shui',
    '法': 'fa', '人': 'ren', '代': 'dai', '表': 'biao', '销': 'xiao', '售': 'shou',
    '批': 'pi', '零': 'ling', '进': 'jin', '出': 'chu', '口': 'kou', '综': 'zong',
    '农': 'nong', '牧': 'mu', '渔': 'yu', '矿': 'kuang', '石': 'shi', '油': 'you',
    '天': 'tian', '然': 'ran', '气': 'qi', '水': 'shui', '力': 'li', '环': 'huan',
    '境': 'jing', '卫': 'wei', '生': 'sheng', '市': 'shi', '政': 'zheng', '园': 'yuan',
    '绿': 'lv', '地': 'di', '规': 'gui', '划': 'hua', '勘': 'kan', '察': 'cha',
    '研': 'yan', '究': 'jiu', '试': 'shi', '验': 'yan', '检': 'jian', '测': 'ce',
    '认': 'ren', '证': 'zheng', '标': 'biao', '准': 'zhun', '质': 'zhi', '量': 'liang',
    '特': 'te', '种': 'zhong', '行': 'xing', '政': 'zheng', '事': 'shi', '社': 'she',
    '组': 'zu', '织': 'zhi', '民': 'min', '政': 'zheng', '福': 'fu', '利': 'li',
    '慈': 'ci', '善': 'shan', '红': 'hong', '十': 'shi', '字': 'zi', '宗': 'zong',
    '寺': 'si', '庙': 'miao', '堂': 'tang', '祠': 'ci', '观': 'guan', '庵': 'an',
    '校': 'xiao', '图': 'tu', '书': 'shu', '馆': 'guan', '档': 'dang', '案': 'an',
    '体': 'ti', '育': 'yu', '运': 'yun', '动': 'dong', '赛': 'sai', '博': 'bo',
    '览': 'lan', '展': 'zhan', '会': 'hui', '议': 'yi', '中': 'zhong', '心': 'xin',
    '一': 'yi', '二': 'er', '四': 'si', '六': 'liu', '七': 'qi', '八': 'ba',
    '九': 'jiu', '十': 'shi', '百': 'bai', '千': 'qian', '万': 'wan', '亿': 'yi',
    '第': 'di', '期': 'qi', '批': 'pi', '次': 'ci', '组': 'zu', '队': 'dui',
    '前': 'qian', '后': 'hou', '左': 'zuo', '右': 'you', '内': 'nei', '外': 'wai',
    '上': 'shang', '下': 'xia', '里': 'li', '边': 'bian', '旁': 'pang',
}


def _is_all_ascii(s):
    """检查字符串是否全是 ASCII 字符"""
    return all(ord(c) < 128 for c in s)


def tag_to_prefix(tag):
    """
    将标签转为表名前缀

    - 中文标签：转为拼音（每个字拼音连接，不含空格），小写
    - 英文/数字标签：转为小写，移除特殊字符，保留字母数字和下划线

    Args:
        tag: 标签字符串

    Returns:
        str: 表名前缀，如 'futian' 或 'batch1'
    """
    if not tag:
        return 'default'

    tag = tag.strip()

    # 纯英文/数字/ASCII标签，直接清理后返回
    if _is_all_ascii(tag):
        prefix = re.sub(r'[^a-zA-Z0-9_]', '_', tag).lower().strip('_')
        return prefix if prefix else 'default'

    # 使用 pypinyin 将整个标签转为拼音，逐个字符处理
    result = []
    for char in tag:
        if '一' <= char <= '鿿':
            py_list = lazy_pinyin(char, style=Style.NORMAL)
            if py_list and py_list[0]:
                result.append(py_list[0])
            else:
                # pypinyin 未返回结果时，回退到手动字典或 Unicode 码点
                py = _HANZI_PINYIN.get(char)
                result.append(py if py else f'z{ord(char):x}')
        elif char.isalpha() or char.isdigit():
            result.append(char.lower())
        elif char in ('_', '-'):
            result.append('_')

    prefix = re.sub(r'_+', '_', ''.join(result)).strip('_')
    return prefix if prefix else 'default'


def get_tag_tables(prefix):
    """
    根据标签前缀生成对应的 recall_results 和 match_results 表名

    Args:
        prefix: 标签前缀，如 'futian'

    Returns:
        tuple: (recall_table, match_table)，如 ('futian_recall_results', 'futian_match_results')
    """
    return f'{prefix}_recall_results', f'{prefix}_match_results'


def get_existing_tags(db_conn):
    """
    从数据库中检索所有已有标签前缀

    通过查询数据库中表名符合 `{prefix}_recall_results` 模式的表来发现标签。

    Args:
        db_conn: 数据库连接

    Returns:
        list: 标签前缀列表
    """
    try:
        sql = """
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema = %s
              AND table_name LIKE '%_recall_results'
              AND table_name != 'recall_results'
        """
        cursor = db_conn.execute(sql, (db_conn.schema,))
        if cursor:
            tags = []
            for row in cursor.fetchall():
                name = row['table_name']
                prefix = name[:-len('_recall_results')]
                if prefix and prefix != 'recall':
                    tags.append(prefix)
            return sorted(tags)
    except Exception:
        pass
    return []
