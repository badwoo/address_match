"""
深圳地址语义识别测评数据生成脚本
==================================

功能：
    1. 生成100组企业地址与标准地址的测试数据（语义不同但预期完全匹配）
    2. 生成1000条干扰标准地址数据（用于混淆，验证系统匹配能力）
    3. 所有地址数据均无重复
    4. 将数据写入enterprise表和standard_address表

数据结构：
    - enterprise表：100条企业地址（ID: EVAL_E0001~EVAL_E0100）
    - standard_address表：100条目标标准地址（addr_code: EVAL_A0001~EVAL_A0100）
                          + 1000条干扰标准地址（addr_code: EVAL_D0001~EVAL_D1000）
"""

import psycopg2
import csv
import os
import random

random.seed(42)

# ===== 深圳区域信息 =====
DISTRICTS = {
    "福田区": {
        "streets": ["福田街道", "沙头街道", "梅林街道", "华富街道", "香蜜湖街道", "莲花街道", "福保街道", "华强北街道", "南园街道", "园岭街道"],
        "roads": ["深南大道", "滨河大道", "福华路", "福华三路", "益田路", "金田路", "民田路", "新洲路", "皇岗路", "彩田路", "莲花路", "香梅路", "红荔路", "华强路", "华富路", "梅林路", "北环大道", "福中路", "福强路", "中心路"],
        "communities": ["皇岗社区", "水围社区", "福田社区", "岗厦社区", "石厦社区", "新洲社区", "沙尾社区", "上沙社区", "下沙社区", "梅富社区"],
        "buildings": ["平安金融中心", "新世界中心", "大中华国际交易广场", "深圳国际商会中心", "中心书城", "市民中心", "财富大厦", "卓越世纪中心", "皇庭中心", "金中环商务大厦"]
    },
    "南山区": {
        "streets": ["粤海街道", "南头街道", "沙河街道", "蛇口街道", "招商街道", "桂湾街道", "前海街道", "南山街道", "桃源街道", "西丽街道"],
        "roads": ["科技南路", "科苑路", "高新南一道", "高新南四道", "后海大道", "南海大道", "创业路", "学府路", "留仙大道", "沙河西路", "龙珠大道", "桃园路", "海德路", "深南大道", "望海路", "工业八路", "东滨路", "科华路", "科技中一路", "科智路"],
        "communities": ["后海社区", "粤海门社区", "科技园社区", "大冲社区", "白石洲社区", "蛇口社区", "桂湾社区", "前海社区", "南光社区", "南油社区"],
        "buildings": ["创维大厦", "深圳湾科技生态园", "腾讯大厦", "百度大厦", "中兴通讯大厦", "科兴科学园", "软件产业基地", "深圳湾创新科技中心", "前海深港合作区", "蛇口网谷"]
    },
    "罗湖区": {
        "streets": ["桂园街道", "黄贝街道", "东门街道", "翠竹街道", "南湖街道", "笋岗街道", "清水河街道", "东湖街道", "莲塘街道", "东晓街道"],
        "roads": ["深南东路", "东门路", "宝安北路", "宝安南路", "人民南路", "和平路", "桂园路", "红岭路", "翠竹路", "爱国路", "怡景路", "湖贝路", "笋岗路", "泥岗路", "布心路", "太白路", "文锦路", "沿河路", "春风路", "嘉宾路"],
        "communities": ["东门社区", "湖贝社区", "桂园社区", "黄贝岭社区", "翠竹社区", "笋岗社区", "清水河社区", "莲塘社区", "东湖社区", "南湖社区"],
        "buildings": ["地王大厦", "京基100", "国贸大厦", "东门大厦", "罗湖商务中心", "华润万象城", "嘉里中心", "深圳发展中心", "世界金融中心", "金光华广场"]
    },
    "宝安区": {
        "streets": ["新安街道", "西乡街道", "福永街道", "沙井街道", "松岗街道", "石岩街道", "航城街道", "新桥街道", "燕罗街道", "福海街道"],
        "roads": ["宝安大道", "建安一路", "兴华路", "创业二路", "新安路", "西乡大道", "固戍路", "航城大道", "沙井路", "松岗大道", "石岩大道", "福永大道", "凤凰山大道", "广深公路", "前进一路", "上川路", "公园路", "流塘路", "鹤洲路", "洲石路"],
        "communities": ["新安社区", "西乡社区", "福永社区", "沙井社区", "松岗社区", "石岩社区", "航城社区", "新桥社区", "燕罗社区", "福海社区"],
        "buildings": ["宝安中心大厦", "前海中心", "华美居商务中心", "宝安万达广场", "宏发中心", "中洲中心", "海雅缤纷城", "壹方中心", "前海HOP", "宝安图书馆"]
    },
    "龙华区": {
        "streets": ["民治街道", "龙华街道", "大浪街道", "观澜街道", "福城街道", "观湖街道", "清湖街道"],
        "roads": ["民治大道", "民康路", "梅龙路", "龙华路", "和平路", "建设路", "东环二路", "清龙路", "民旺路", "观澜大道", "大浪路", "龙观路", "布龙路", "人民路", "三联路", "工业路", "龙胜路", "景龙路", "清泉路", "华荣路"],
        "communities": ["民治社区", "龙华社区", "大浪社区", "观澜社区", "福城社区", "观湖社区", "清湖社区"],
        "buildings": ["龙华ICO", "星河WORLD", "锦绣科学园", "宝能科技园", "硅谷大院", "展滔科技大厦", "特区1980", "龙华万达广场", "鸿荣源壹方城", "龙华商业中心"]
    },
    "龙岗区": {
        "streets": ["龙城街道", "龙岗街道", "坂田街道", "布吉街道", "横岗街道", "平湖街道", "南湾街道", "宝龙街道", "园山街道", "吉华街道"],
        "roads": ["龙翔大道", "龙城大道", "黄阁路", "龙平西路", "深汕路", "布吉路", "横岗路", "坂田路", "平湖路", "南湾路", "宝龙路", "园山路", "吉华路", "龙岭路", "龙岗大道", "如意路", "清林路", "龙潭路", "爱南路", "碧新路"],
        "communities": ["龙城社区", "龙岗社区", "坂田社区", "布吉社区", "横岗社区", "平湖社区", "南湾社区", "宝龙社区", "园山社区", "吉华社区"],
        "buildings": ["龙岗万达广场", "天安云谷", "星河WORLD龙岗", "大运软件小镇", "龙岗智慧家园", "启迪协信科技园", "中海信创新产业城", "坂田手造文化街", "李朗软件园", "甘坑客家小镇"]
    },
    "盐田区": {
        "streets": ["海山街道", "盐田街道", "沙头角街道", "梅沙街道"],
        "roads": ["深盐路", "海景路", "盐田路", "明珠路", "沙盐路", "海山路", "东海道", "北山道", "梧桐路", "环梅路"],
        "communities": ["海山社区", "盐田社区", "沙头角社区", "梅沙社区"],
        "buildings": ["盐田港大厦", "壹海城", "海智云谷", "盐田科技大厦", "沙头角商贸中心"]
    },
    "坪山区": {
        "streets": ["坪山街道", "坑梓街道", "碧岭街道", "石井街道", "马峦街道", "龙田街道"],
        "roads": ["坪山大道", "深汕路", "兰竹路", "金牛路", "丹梓大道", "锦绣路", "中山大道", "建设路", "行政一路", "行政八路"],
        "communities": ["坪山社区", "坑梓社区", "碧岭社区", "石井社区", "马峦社区", "龙田社区"],
        "buildings": ["坪山万达广场", "坪山创新广场", "坪山科技园", "中天美景大厦", "坪山文化中心"]
    },
    "光明区": {
        "streets": ["光明街道", "公明街道", "新湖街道", "凤凰街道", "玉塘街道", "马田街道"],
        "roads": ["光明大道", "光明大街", "松白路", "观光路", "光明路", "华夏路", "科泰路", "光明高新路", "塘明路", "长凤路"],
        "communities": ["光明社区", "公明社区", "新湖社区", "凤凰社区", "玉塘社区", "马田社区"],
        "buildings": ["光明万达广场", "光明科技园", "华强创意公园", "光明文化艺术中心", "光明新城公园"]
    },
    "大鹏新区": {
        "streets": ["大鹏街道", "南澳街道", "葵涌街道"],
        "roads": ["鹏飞路", "大鹏路", "南澳路", "葵涌路", "迎宾路", "中山路", "建设路", "金沙路", "滨海路", "海景路"],
        "communities": ["大鹏社区", "南澳社区", "葵涌社区"],
        "buildings": ["大鹏所城", "南澳渔港大厦", "葵涌商贸中心", "大鹏文化中心", "坝光科创中心"]
    }
}

# ===== 语义变换规则 =====
# 每种变换规则生成企业地址和标准地址的对应关系

def apply_transform(road, number, district, transform_type):
    """
    根据变换类型生成企业地址和标准地址

    Args:
        road: 路名
        number: 门牌号
        district: 区名
        transform_type: 变换类型编号(0-19)

    Returns:
        tuple: (企业地址, 标准地址, 语义差异说明)
    """
    full_prefix = f"广东省深圳市{district}"
    city_prefix = f"深圳市{district}"
    dist_prefix = f"{district}"

    if transform_type == 0:
        return (f"{full_prefix}{road}{number}号", f"{full_prefix}{road}{number}号", "地址文本完全相同")

    elif transform_type == 1:
        return (f"广东深圳市{district}{road}{number}号", f"{full_prefix}{road}{number}号", "企业地址省略'省'字")

    elif transform_type == 2:
        return (f"{city_prefix}{road}{number}号", f"{full_prefix}{road}{number}号", "企业地址省略省份")

    elif transform_type == 3:
        return (f"广东深圳{district}{road}{number}号", f"{full_prefix}{road}{number}号", "企业地址省略'省'和'市'字")

    elif transform_type == 4:
        return (f"{dist_prefix}{road}{number}号", f"{full_prefix}{road}{number}号", "企业地址省略省份和'市'")

    elif transform_type == 5:
        street = DISTRICTS[district]["streets"][hash(road + str(number)) % len(DISTRICTS[district]["streets"])]
        return (f"{city_prefix}{road}{number}号", f"{full_prefix}{street}{road}{number}号", f"标准地址补充了'{street}'")

    elif transform_type == 6:
        street = DISTRICTS[district]["streets"][(hash(road + str(number)) + 1) % len(DISTRICTS[district]["streets"])]
        community = DISTRICTS[district]["communities"][(hash(road + str(number)) + 2) % len(DISTRICTS[district]["communities"])]
        return (f"{city_prefix}{road}{number}号", f"{full_prefix}{street}{community}{road}{number}号", f"标准地址补充了'{street}{community}'")

    elif transform_type == 7:
        return (f"{full_prefix}{road}{number}号A栋6楼601室", f"{full_prefix}{road}{number}号A幢6层601房", "'栋'与'幢'、'楼'与'层'、'室'与'房'同义替换")

    elif transform_type == 8:
        return (f"{full_prefix}{road}{number}号B座12层1203", f"{full_prefix}{road}{number}号B栋12楼1203室", "'座'与'栋'、'层'与'楼'同义，企业地址省略'室'")

    elif transform_type == 9:
        return (f"{full_prefix}{road}{number}号3号楼15层", f"{full_prefix}{road}{number}号3幢15楼", "'号楼'与'幢'、'层'与'楼'同义替换")

    elif transform_type == 10:
        return (f"{full_prefix}{road}{number}号8F", f"{full_prefix}{road}{number}号8楼", "'8F'与'8楼'为同一楼层的不同表达")

    elif transform_type == 11:
        return (f"{full_prefix}{road}{number}号22/F", f"{full_prefix}{road}{number}号22层", "'22/F'与'22层'为同一楼层的不同表达")

    elif transform_type == 12:
        return (f"{full_prefix}{road}{number}号B1", f"{full_prefix}{road}{number}号负1层", "'B1'与'负1层'为同一地下楼层的不同表达")

    elif transform_type == 13:
        return (f"{full_prefix}{road}{number}号A-601", f"{full_prefix}{road}{number}号A栋601室", "'A-601'与'A栋601室'为同一房间的不同表达")

    elif transform_type == 14:
        return (f"{full_prefix}{road}{number}号1203房", f"{full_prefix}{road}{number}号1203室", "'房'与'室'同义替换")

    elif transform_type == 15:
        return (f"{full_prefix}{road}{number}号3-1502", f"{full_prefix}{road}{number}号3栋1502室", "'3-1502'与'3栋1502室'为同一房间的不同表达")

    elif transform_type == 16:
        return (f"{full_prefix}{road}{number}-1号", f"{full_prefix}{road}{number}号附1号", f"'{number}-1号'与'{number}号附1号'为同一地址的不同格式")

    elif transform_type == 17:
        building = DISTRICTS[district]["buildings"][(hash(road + str(number)) + 3) % len(DISTRICTS[district]["buildings"])]
        return (f"{city_prefix}{road}{number}号（{building}）", f"{full_prefix}{road}{number}号{building}", f"企业地址用括号标注'{building}'，标准地址无括号")

    elif transform_type == 18:
        building = DISTRICTS[district]["buildings"][(hash(road + str(number)) + 4) % len(DISTRICTS[district]["buildings"])]
        short_name = building[:2] if len(building) > 4 else building
        return (f"{city_prefix}{road}{number}号{short_name}", f"{full_prefix}{road}{number}号{building}", f"'{short_name}'与'{building}'为同一建筑的不同简称")

    elif transform_type == 19:
        community = DISTRICTS[district]["communities"][(hash(road + str(number)) + 5) % len(DISTRICTS[district]["communities"])]
        return (f"{city_prefix}{community}{road}{number}号", f"{full_prefix}{road}{number}号", f"企业地址多了社区名'{community}'，标准地址省略")

    return None


def generate_100_match_pairs():
    """
    生成100组语义不同但预期完全匹配的深圳地址数据

    Returns:
        list: 100组匹配数据
    """
    results = []
    used_enterprise = set()
    used_standard = set()
    used_roads_numbers = set()

    district_names = list(DISTRICTS.keys())
    pair_idx = 0

    for di, district in enumerate(district_names):
        roads = DISTRICTS[district]["roads"]
        for ri, road in enumerate(roads):
            if pair_idx >= 100:
                break

            number = (pair_idx + 1) * 37 + 100
            road_number_key = f"{district}{road}{number}"
            if road_number_key in used_roads_numbers:
                continue
            used_roads_numbers.add(road_number_key)

            transform_type = pair_idx % 20

            ent_addr, std_addr, diff_desc = apply_transform(road, number, district, transform_type)

            if ent_addr in used_enterprise or std_addr in used_standard:
                number = (pair_idx + 1) * 53 + 200
                ent_addr, std_addr, diff_desc = apply_transform(road, number, district, transform_type)
                if ent_addr in used_enterprise or std_addr in used_standard:
                    continue

            used_enterprise.add(ent_addr)
            used_standard.add(std_addr)

            pair_idx += 1
            results.append({
                'group_id': pair_idx,
                'enterprise_id': f"EVAL_E{pair_idx:04d}",
                'enterprise_name': f"深圳测评企业{pair_idx:04d}",
                'enterprise_address': ent_addr,
                'standard_addr_code': f"EVAL_A{pair_idx:04d}",
                'standard_address': std_addr,
                'house_code': f"HC{pair_idx:08d}",
                'consistency_type': '部分一致' if ent_addr != std_addr else '完全一致',
                'expected_match': '完全匹配',
                'semantic_diff': diff_desc,
                'transform_type': transform_type,
            })

        if pair_idx >= 100:
            break

    return results


def generate_1000_interference_addresses(match_pairs):
    """
    生成1000条干扰标准地址数据

    Args:
        match_pairs: 100组匹配数据，用于避免重复

    Returns:
        list: 1000条干扰数据
    """
    existing_addrs = set()
    for p in match_pairs:
        existing_addrs.add(p['enterprise_address'])
        existing_addrs.add(p['standard_address'])

    results = []
    district_names = list(DISTRICTS.keys())

    idx = 0
    attempts = 0
    while idx < 1000 and attempts < 50000:
        attempts += 1
        district = district_names[idx % len(district_names)]
        roads = DISTRICTS[district]["roads"]
        road = roads[idx % len(roads)]
        number = idx * 7 + 501

        street = DISTRICTS[district]["streets"][idx % len(DISTRICTS[district]["streets"])]
        building = DISTRICTS[district]["buildings"][idx % len(DISTRICTS[district]["buildings"])]

        patterns = [
            f"广东省深圳市{district}{street}{road}{number}号",
            f"广东省深圳市{district}{road}{number}号{building}",
            f"广东省深圳市{district}{road}{number}号{idx % 5 + 1}栋{idx % 20 + 1}楼{idx % 8 + 1}01室",
            f"广东省深圳市{district}{road}{number}号A座{idx % 30 + 1}层",
            f"广东省深圳市{district}{road}{number}号附{idx % 3 + 1}号",
            f"广东省深圳市{district}{road}{number}号之{['一','二','三','四','五'][idx % 5]}",
        ]

        addr = patterns[idx % len(patterns)]

        if addr in existing_addrs:
            continue

        existing_addrs.add(addr)
        idx += 1
        results.append({
            'addr_code': f"EVAL_D{idx:04d}",
            'standard_address': addr,
            'house_code': f"HD{idx:08d}",
        })

    return results


def save_match_csv(data, filepath):
    """
    将匹配数据保存为CSV文件

    Args:
        data: 匹配数据列表
        filepath: CSV文件保存路径
    """
    if not data:
        return
    fieldnames = [
        'group_id', 'enterprise_id', 'enterprise_name', 'enterprise_address',
        'standard_addr_code', 'standard_address', 'house_code',
        'consistency_type', 'expected_match', 'semantic_diff', 'transform_type'
    ]
    with open(filepath, 'w', newline='', encoding='utf-8-sig') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(data)
    print(f"匹配数据CSV已保存: {filepath}")


def save_interference_csv(data, filepath):
    """
    将干扰数据保存为CSV文件

    Args:
        data: 干扰数据列表
        filepath: CSV文件保存路径
    """
    if not data:
        return
    fieldnames = ['addr_code', 'standard_address', 'house_code']
    with open(filepath, 'w', newline='', encoding='utf-8-sig') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(data)
    print(f"干扰数据CSV已保存: {filepath}")


def insert_to_database(match_pairs, interference_addrs):
    """
    将数据插入数据库

    Args:
        match_pairs: 100组匹配数据
        interference_addrs: 1000条干扰数据

    Returns:
        tuple: (enterprise插入数, standard_address插入数)
    """
    conn = psycopg2.connect(
        dbname='postgres',
        user='postgres',
        password='123456',
        host='localhost',
        port=5432
    )
    conn.autocommit = False
    cur = conn.cursor()

    try:
        e_count = 0
        s_count = 0

        for item in match_pairs:
            cur.execute(
                "INSERT INTO enterprise (id, name, address) VALUES (%s, %s, %s)",
                (item['enterprise_id'], item['enterprise_name'], item['enterprise_address'])
            )
            e_count += 1

            cur.execute(
                "INSERT INTO standard_address (addr_code, standard_addr, house_code) VALUES (%s, %s, %s)",
                (item['standard_addr_code'], item['standard_address'], item['house_code'])
            )
            s_count += 1

        for item in interference_addrs:
            cur.execute(
                "INSERT INTO standard_address (addr_code, standard_addr, house_code) VALUES (%s, %s, %s)",
                (item['addr_code'], item['standard_address'], item['house_code'])
            )
            s_count += 1

        conn.commit()
        print(f"数据插入完成: enterprise表 {e_count} 条, standard_address表 {s_count} 条")
        return e_count, s_count

    except Exception as e:
        conn.rollback()
        print(f"数据插入失败: {e}")
        raise
    finally:
        cur.close()
        conn.close()


def verify_data():
    """
    验证数据库中的数据

    Returns:
        dict: 验证结果统计
    """
    conn = psycopg2.connect(
        dbname='postgres',
        user='postgres',
        password='123456',
        host='localhost',
        port=5432
    )
    cur = conn.cursor()

    try:
        cur.execute("SELECT COUNT(*) FROM enterprise WHERE id LIKE 'EVAL_E%'")
        e_count = cur.fetchone()[0]

        cur.execute("SELECT COUNT(*) FROM standard_address WHERE addr_code LIKE 'EVAL_A%'")
        a_count = cur.fetchone()[0]

        cur.execute("SELECT COUNT(*) FROM standard_address WHERE addr_code LIKE 'EVAL_D%'")
        d_count = cur.fetchone()[0]

        cur.execute("SELECT COUNT(*) FROM standard_address WHERE addr_code LIKE 'EVAL_%'")
        s_total = cur.fetchone()[0]

        cur.execute("SELECT address FROM enterprise WHERE id LIKE 'EVAL_E%'")
        e_addrs = [r[0] for r in cur.fetchall()]

        cur.execute("SELECT standard_addr FROM standard_address WHERE addr_code LIKE 'EVAL_%'")
        s_addrs = [r[0] for r in cur.fetchall()]

        e_dup = len(e_addrs) - len(set(e_addrs))
        s_dup = len(s_addrs) - len(set(s_addrs))

        print(f"\n验证结果:")
        print(f"  enterprise表测评数据: {e_count} 条")
        print(f"  standard_address表目标数据(EVAL_A): {a_count} 条")
        print(f"  standard_address表干扰数据(EVAL_D): {d_count} 条")
        print(f"  standard_address表总计(EVAL_): {s_total} 条")
        print(f"  enterprise地址重复数: {e_dup}")
        print(f"  standard_address地址重复数: {s_dup}")

        cur.execute("SELECT id, name, address FROM enterprise WHERE id LIKE 'EVAL_E%' ORDER BY id LIMIT 3")
        print(f"\n  enterprise样本:")
        for row in cur.fetchall():
            print(f"    {row}")

        cur.execute("SELECT addr_code, standard_addr, house_code FROM standard_address WHERE addr_code LIKE 'EVAL_A%' ORDER BY addr_code LIMIT 3")
        print(f"\n  standard_address目标样本:")
        for row in cur.fetchall():
            print(f"    {row}")

        cur.execute("SELECT addr_code, standard_addr, house_code FROM standard_address WHERE addr_code LIKE 'EVAL_D%' ORDER BY addr_code LIMIT 3")
        print(f"\n  standard_address干扰样本:")
        for row in cur.fetchall():
            print(f"    {row}")

        return {'e_count': e_count, 'a_count': a_count, 'd_count': d_count, 'e_dup': e_dup, 's_dup': s_dup}

    finally:
        cur.close()
        conn.close()


if __name__ == '__main__':
    match_pairs = generate_100_match_pairs()
    print(f"生成匹配数据: {len(match_pairs)} 组")

    e_set = set(p['enterprise_address'] for p in match_pairs)
    s_set = set(p['standard_address'] for p in match_pairs)
    print(f"企业地址唯一: {len(e_set)}/{len(match_pairs)}")
    print(f"标准地址唯一: {len(s_set)}/{len(match_pairs)}")

    interference_addrs = generate_1000_interference_addresses(match_pairs)
    print(f"生成干扰数据: {len(interference_addrs)} 条")

    i_set = set(a['standard_address'] for a in interference_addrs)
    print(f"干扰地址唯一: {len(i_set)}/{len(interference_addrs)}")

    all_std = s_set | i_set
    overlap = s_set & i_set
    print(f"目标与干扰地址重叠: {len(overlap)} 条")

    all_addrs = e_set | all_std
    print(f"全部地址唯一: {len(all_addrs)}/{len(e_set) + len(all_std)}")

    base_dir = os.path.dirname(os.path.abspath(__file__))
    save_match_csv(match_pairs, os.path.join(base_dir, 'eval_match_data.csv'))
    save_interference_csv(interference_addrs, os.path.join(base_dir, 'eval_interference_data.csv'))

    insert_to_database(match_pairs, interference_addrs)

    verify_data()

    transform_counts = {}
    for p in match_pairs:
        t = p['transform_type']
        transform_counts[t] = transform_counts.get(t, 0) + 1
    print(f"\n变换类型分布:")
    for t in sorted(transform_counts.keys()):
        print(f"  类型{t}: {transform_counts[t]} 组")
