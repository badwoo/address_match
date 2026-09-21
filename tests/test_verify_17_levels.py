"""
验证 17级 和 17_2 模式功能测试
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from model.address_tagging_model import (
    AddressTaggingModel, OUTPUT_FIELDS_17, OUTPUT_FIELDS_17_2, OUTPUT_FIELD_LABELS_17
)


def test_predict_17():
    """测试 predict_17 方法"""
    print("=" * 60)
    print("测试 predict_17")
    print("=" * 60)

    model = AddressTaggingModel(device='cpu')

    test_addresses = [
        "广东省深圳市福田区泰然立城幸福里A栋",
        "北京市朝阳区建国路88号SOHO现代城A座2801",
        "浙江省杭州市西湖区文三路478号华星创业大厦15楼1501室",
    ]

    results = model.predict_17(test_addresses)

    print(f"\n输入 {len(test_addresses)} 条地址，输出 {len(results)} 条结果")

    for i, r in enumerate(results):
        print(f"\n--- 地址 {i+1}: {r['original_address']} ---")

        # 验证必含字段
        assert 'dom_json' in r, "dom_json 字段缺失"
        assert 'original_address' in r, "original_address 字段缺失"

        # 验证17个字段
        for f in OUTPUT_FIELDS_17:
            assert f in r, f"字段 {f} 缺失"

        print(f"  dom_json 前100字符: {r['dom_json'][:100]}...")
        print(f"  dom_json 长度: {len(r['dom_json'])}")

        # 打印有值的字段
        for f in OUTPUT_FIELDS_17:
            if r[f]:
                label = OUTPUT_FIELD_LABELS_17.get(f, f)
                print(f"  {f}({label}): {r[f]}")

    print("\npredict_17 测试通过!")
    return True


def test_predict_17_2():
    """测试 predict_17_2 方法"""
    print("\n" + "=" * 60)
    print("测试 predict_17_2")
    print("=" * 60)

    model = AddressTaggingModel(device='cpu')

    test_addresses = [
        "广东省深圳市福田区泰然立城幸福里A栋",
        "北京市朝阳区建国路88号SOHO现代城A座2801",
    ]

    results = model.predict_17_2(test_addresses)

    print(f"\n输入 {len(test_addresses)} 条地址，输出 {len(results)} 条结果")

    for i, r in enumerate(results):
        print(f"\n--- 地址 {i+1}: {r['original_address']} ---")

        # 验证必含字段
        assert 'dom_json' in r, "dom_json 字段缺失"
        assert '_id_field' not in r, "_id_field 不应在模型层结果中"

        # 验证34个双字段
        assert len(OUTPUT_FIELDS_17_2) == 34, f"OUTPUT_FIELDS_17_2 应有34个字段，实际 {len(OUTPUT_FIELDS_17_2)}"
        for f in OUTPUT_FIELDS_17_2:
            assert f in r, f"字段 {f} 缺失"

        print(f"  dom_json 前100字符: {r['dom_json'][:100]}...")

        # 打印有值的主字段和_2字段
        for f in OUTPUT_FIELDS_17:
            f2 = f'{f}_2'
            v1 = r[f]
            v2 = r[f2]
            if v1 or v2:
                label = OUTPUT_FIELD_LABELS_17.get(f, f)
                if v1:
                    print(f"  {f}({label}): {v1}")
                if v2:
                    print(f"  {f2}({label}-副): {v2}")

    print("\npredict_17_2 测试通过!")
    return True


def test_dom_json_raw_format():
    """验证 dom_json 是标准DOM格式 {"text":..., "elements":[...]}"""
    print("\n" + "=" * 60)
    print("验证 dom_json 格式")
    print("=" * 60)

    model = AddressTaggingModel(device='cpu')
    results = model.predict_17(["广东省深圳市福田区泰然立城幸福里A栋"])
    dom_json = results[0]['dom_json']

    import json
    try:
        parsed = json.loads(dom_json)
        print(f"\ndom_json 解析成功，类型: {type(parsed)}")

        assert isinstance(parsed, dict), "dom_json 应为字典"
        assert 'text' in parsed, "dom_json 应包含 text 字段"
        assert 'elements' in parsed, "dom_json 应包含 elements 字段"
        assert isinstance(parsed['elements'], list), "elements 应为列表"
        assert len(parsed['elements']) > 0, "elements 不应为空"

        for item in parsed['elements']:
            assert isinstance(item, dict), f"每个元素应为字典: {item}"
            assert 'type' in item, f"元素应包含 type 字段: {item}"
            assert 'span' in item, f"元素应包含 span 字段: {item}"
            assert 'start' in item, f"元素应包含 start 字段: {item}"
            assert 'end' in item, f"元素应包含 end 字段: {item}"
            assert isinstance(item['type'], str), f"type 应为字符串: {item['type']}"
            assert isinstance(item['span'], str), f"span 应为字符串: {item['span']}"
            assert isinstance(item['start'], int), f"start 应为整数: {item['start']}"
            assert isinstance(item['end'], int), f"end 应为整数: {item['end']}"

        print("  text:", parsed['text'])
        print("  实体数量:", len(parsed['elements']))
        print("  前3个元素:", parsed['elements'][:3])
        print("  格式验证通过: 每个元素为 {type, span, start, end}")

    except json.JSONDecodeError as e:
        print(f"dom_json JSON解析失败: {e}")
        return False

    print("\ndom_json 格式验证通过!")
    return True


if __name__ == '__main__':
    print("开始验证 17级 和 17_2 模式功能...")

    ok = True
    ok = test_predict_17() and ok
    ok = test_predict_17_2() and ok
    ok = test_dom_json_raw_format() and ok

    print("\n" + "=" * 60)
    if ok:
        print("全部测试通过!")
    else:
        print("部分测试失败，请检查输出")
    print("=" * 60)
