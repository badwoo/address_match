"""
进度跟踪工具模块
================

提供进度跟踪和回调管理功能。

核心功能：
    1. 跟踪任务进度
    2. 管理多个回调函数
    3. 计算处理速度和剩余时间

使用说明：
    tracker = ProgressTracker()
    tracker.add_callback(callback_function)
    tracker.update(stage='processing', processed=100, total=1000)
"""

class ProgressTracker:
    def __init__(self):
        self.stage = ''
        self.processed = 0
        self.total = 0
        self.progress = 0.0
        self.speed = 0.0
        self.remaining_time = 0.0
        self.callbacks = []
    
    def update(self, **kwargs):
        for key, value in kwargs.items():
            if hasattr(self, key):
                setattr(self, key, value)
        
        for callback in self.callbacks:
            callback(self.get_status())
    
    def get_status(self):
        return {
            'stage': self.stage,
            'processed': self.processed,
            'total': self.total,
            'progress': self.progress,
            'speed': self.speed,
            'remaining_time': self.remaining_time
        }
    
    def reset(self):
        self.stage = ''
        self.processed = 0
        self.total = 0
        self.progress = 0.0
        self.speed = 0.0
        self.remaining_time = 0.0
    
    def add_callback(self, callback):
        self.callbacks.append(callback)
