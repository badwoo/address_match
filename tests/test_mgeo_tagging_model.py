import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from model.address_tagging_model import AddressTaggingModel, OUTPUT_FIELD_LABELS

def test_model_raw_capability():
    print("=" * 80)
    print("MGeo地址要素解析模型测试")
    print("模型名称: iic/mgeo_geographic_elements_tagging_chinese_base")
    print("=" * 80)
    
    try:
        print("\n[1/3] 加载模型...")
        model = AddressTaggingModel()
        print(f"✓ 模型加载成功")
        print(f"  - 设备: {model.device}")
        print(f"  - 标签数量: {len(model.id2label)}")
        print(f"  - 使用FP16: {model.use_fp16}")
        
        print("\n[2/3] 显示所有可用标签:")
        sorted_labels = sorted(model.id2label.items(), key=lambda x: x[0])
        for idx, label in sorted_labels:
            print(f"  {idx:2d}: {label}")
        
        print("\n[3/3] 测试地址解析能力:")
        test_addresses = [
            "浙江省杭州市西湖区文三路478号华星创业大厦15楼1501室",
            "北京市朝阳区建国路88号SOHO现代城A座2801",
            "广东省深圳市南山区科技园南区深南大道9996号",
            "上海市浦东新区陆家嘴环路1000号恒生银行大厦23层",
            "江苏省南京市鼓楼区中山路100号新街口百货商场5楼",
            "四川省成都市锦江区春熙路步行街88号群光广场B1层",
            "湖北省武汉市洪山区珞喻路1037号武汉大学计算机学院",
            "湖南省长沙市芙蓉区五一大道389号华美达大酒店12楼",
            "山东省济南市历下区泉城路188号恒隆广场B座1001",
            "福建省厦门市思明区中山路步行街200号中华城3楼",
            "广州市天河区珠江新城冼村路5号凯华国际中心18楼",
            "天津市和平区南京路100号伊势丹百货6楼",
        ]
        
        print("\n测试结果:")
        print("-" * 80)
        
        results = model.predict(test_addresses)
        
        for i, result in enumerate(results):
            addr = result['original_address']
            print(f"\n地址{i+1}: {addr}")
            print("  " + "-" * 60)
            
            parsed_fields = []
            for field in ['province', 'city', 'district', 'street', 'community', 
                          'road', 'roadno', 'area', 'bldg', 'unit', 'floor', 'house']:
                value = result.get(field, '')
                if value:
                    label = OUTPUT_FIELD_LABELS.get(field, field)
                    parsed_fields.append(f"{label}={value}")
            
            print(f"  解析出 {len(parsed_fields)} 个要素:")
            for field_info in parsed_fields:
                print(f"    • {field_info}")
        
        print("\n" + "=" * 80)
        print("测试完成!")
        print("\n模型最多可解析的12级结构化要素:")
        for field, label in OUTPUT_FIELD_LABELS.items():
            print(f"  • {field}: {label}")
        
    except Exception as e:
        print(f"\n✗ 测试失败: {str(e)}")
        import traceback
        traceback.print_exc()
        return False
    
    return True

if __name__ == "__main__":
    success = test_model_raw_capability()
    sys.exit(0 if success else 1)