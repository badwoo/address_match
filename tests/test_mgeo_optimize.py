"""验证MGeo模型优化后的加载和推理功能"""
import sys
import os
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import torch
print(f"PyTorch: {torch.__version__}")
print(f"CUDA available: {torch.cuda.is_available()}")
if torch.cuda.is_available():
    print(f"GPU: {torch.cuda.get_device_name(0)}")
    print(f"VRAM: {torch.cuda.get_device_properties(0).total_memory / 1024**3:.1f} GB")
print(f"torch.compile available: {hasattr(torch, 'compile')}")

print("\n[1/3] 加载MGeo模型...")
from model.mgeo_model import MGeoModel
model = MGeoModel()
print(f"模型加载成功, device={model.device}, fp16={model.use_fp16}")

print("\n[2/3] 验证predict_optimized功能...")
test_pairs = [
    ("浙江省杭州市西湖区文三路478号", "浙江省杭州市西湖区文三路478号华星创业大厦"),
    ("北京市朝阳区建国路88号", "上海市浦东新区陆家嘴环路1000号"),
    ("广东省深圳市南山区科技园南区深南大道9996号", "广东省深圳市南山区科技园南区深南大道9996号"),
    ("杭州市西湖区文三路100号", "杭州市西湖区文三路200号"),
    ("江苏省南京市鼓楼区中山路100号", "江苏省南京市鼓楼区中山路100号新街口百货商场"),
]
results = model.predict_optimized(test_pairs)
for i, (pair, result) in enumerate(zip(test_pairs, results)):
    print(f"  对{i+1}: exact={result['exact_match']:.4f}, partial={result['partial_match']:.4f}, not={result['not_match']:.4f}")

print("\n[3/3] 性能基准测试（首次推理会触发torch.compile编译，耗时较长）...")
# 生成批量测试数据
import random
provinces = ["浙江省", "江苏省", "广东省", "北京市", "上海市"]
cities = ["杭州市", "南京市", "深圳市", "朝阳区", "浦东新区"]
streets = ["文三路", "中山路", "科技路", "建国路", "陆家嘴环路"]
numbers = ["100号", "200号", "300号", "88号", "9996号"]

perf_pairs = []
for _ in range(2000):
    a1 = random.choice(provinces) + random.choice(cities) + random.choice(streets) + random.choice(numbers)
    a2 = random.choice(provinces) + random.choice(cities) + random.choice(streets) + random.choice(numbers)
    perf_pairs.append((a1, a2))

# 第一次运行（触发编译）
print("  首次推理（触发torch.compile编译）...")
t0 = time.time()
_ = model.predict_optimized(perf_pairs[:100])
t1 = time.time()
print(f"  首次推理耗时: {t1-t0:.2f}s（含编译开销）")

# 第二次运行（编译后）
print("  正式推理测试（2000对）...")
t0 = time.time()
results = model.predict_optimized(perf_pairs)
t1 = time.time()
elapsed = t1 - t0
pairs_per_sec = len(perf_pairs) / elapsed
print(f"  推理耗时: {elapsed:.2f}s")
print(f"  吞吐量: {pairs_per_sec:.0f} 地址对/秒")
print(f"  每对耗时: {elapsed/len(perf_pairs)*1000:.2f}ms")

print("\n验证完成!")
