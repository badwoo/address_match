"""
异常体系模块
============

定义地址匹配系统的统一异常层次，替代各模块直接 raise Exception。

异常层次：
    AddressMatchError (基础异常)
    ├── DatabaseError       数据库操作异常
    ├── ModelInferenceError 模型推理异常
    ├── OOMRiskError        内存超限风险异常
    └── ConfigError         配置异常
"""


class AddressMatchError(Exception):
    """地址匹配系统基础异常"""


class DatabaseError(AddressMatchError):
    """数据库操作异常（连接失败、SQL 执行错误、事务失败等）"""


class ModelInferenceError(AddressMatchError):
    """模型推理异常（向量化失败、精排预测失败等）"""


class OOMRiskError(AddressMatchError):
    """内存超限风险异常（全量 fetchall 风险等）"""


class ConfigError(AddressMatchError):
    """配置异常（参数非法、模型路径未找到等）"""
