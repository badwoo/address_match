import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import unittest
from unittest.mock import patch, MagicMock
import subprocess


class TestDetectGpuInfoNoGpu(unittest.TestCase):

    def test_no_gpu_no_nvidia_smi(self):
        mock_torch = MagicMock()
        mock_torch.cuda.is_available.return_value = False
        mock_torch.__version__ = '2.11.0+cpu'
        mock_torch.backends.cuda.is_built.return_value = False

        with patch.dict('sys.modules', {'torch': mock_torch}):
            import importlib
            import config as config_module
            importlib.reload(config_module)
            from config import _detect_gpu_info

            with patch('config.subprocess.run', side_effect=FileNotFoundError("nvidia-smi not found")):
                info = _detect_gpu_info()

                self.assertFalse(info['has_gpu'])
                self.assertFalse(info['cuda_available'])
                self.assertFalse(info['torch_is_cuda_build'])
                self.assertEqual(info['device_name'], '')
                self.assertEqual(info['warning'], '')

    def test_nvidia_gpu_but_cpu_pytorch(self):
        mock_torch = MagicMock()
        mock_torch.cuda.is_available.return_value = False
        mock_torch.__version__ = '2.11.0+cpu'
        mock_torch.backends.cuda.is_built.return_value = False

        with patch.dict('sys.modules', {'torch': mock_torch}):
            import importlib
            import config as config_module
            importlib.reload(config_module)
            from config import _detect_gpu_info

            mock_result = MagicMock()
            mock_result.returncode = 0
            mock_result.stdout = 'NVIDIA GeForce RTX 3090, 535.129.03\n'

            with patch('config.subprocess.run', return_value=mock_result):
                info = _detect_gpu_info()

                self.assertTrue(info['has_gpu'])
                self.assertFalse(info['cuda_available'])
                self.assertFalse(info['torch_is_cuda_build'])
                self.assertEqual(info['device_name'], 'NVIDIA GeForce RTX 3090')
                self.assertIn('CPU版本', info['warning'])
                self.assertIn('NVIDIA GeForce RTX 3090', info['warning'])

    def test_nvidia_smi_fails(self):
        mock_torch = MagicMock()
        mock_torch.cuda.is_available.return_value = False
        mock_torch.__version__ = '2.11.0+cpu'
        mock_torch.backends.cuda.is_built.return_value = False

        with patch.dict('sys.modules', {'torch': mock_torch}):
            import importlib
            import config as config_module
            importlib.reload(config_module)
            from config import _detect_gpu_info

            mock_result = MagicMock()
            mock_result.returncode = 1
            mock_result.stderr = 'NVIDIA-SMI has failed'

            with patch('config.subprocess.run', return_value=mock_result):
                info = _detect_gpu_info()

                self.assertFalse(info['has_gpu'])
                self.assertFalse(info['cuda_available'])

    def test_nvidia_smi_timeout(self):
        mock_torch = MagicMock()
        mock_torch.cuda.is_available.return_value = False
        mock_torch.__version__ = '2.11.0+cpu'
        mock_torch.backends.cuda.is_built.return_value = False

        with patch.dict('sys.modules', {'torch': mock_torch}):
            import importlib
            import config as config_module
            importlib.reload(config_module)
            from config import _detect_gpu_info

            with patch('config.subprocess.run', side_effect=subprocess.TimeoutExpired(cmd='nvidia-smi', timeout=10)):
                info = _detect_gpu_info()

                self.assertFalse(info['has_gpu'])
                self.assertFalse(info['cuda_available'])

    def test_nvidia_smi_empty_output(self):
        mock_torch = MagicMock()
        mock_torch.cuda.is_available.return_value = False
        mock_torch.__version__ = '2.11.0+cpu'
        mock_torch.backends.cuda.is_built.return_value = False

        with patch.dict('sys.modules', {'torch': mock_torch}):
            import importlib
            import config as config_module
            importlib.reload(config_module)
            from config import _detect_gpu_info

            mock_result = MagicMock()
            mock_result.returncode = 0
            mock_result.stdout = ''

            with patch('config.subprocess.run', return_value=mock_result):
                info = _detect_gpu_info()

                self.assertFalse(info['has_gpu'])

    def test_multi_gpu_nvidia_smi(self):
        mock_torch = MagicMock()
        mock_torch.cuda.is_available.return_value = False
        mock_torch.__version__ = '2.11.0+cpu'
        mock_torch.backends.cuda.is_built.return_value = False

        with patch.dict('sys.modules', {'torch': mock_torch}):
            import importlib
            import config as config_module
            importlib.reload(config_module)
            from config import _detect_gpu_info

            mock_result = MagicMock()
            mock_result.returncode = 0
            mock_result.stdout = 'NVIDIA GeForce RTX 4090, 535.129.03\nNVIDIA GeForce RTX 4090, 535.129.03\n'

            with patch('config.subprocess.run', return_value=mock_result):
                info = _detect_gpu_info()

                self.assertTrue(info['has_gpu'])
                self.assertEqual(info['device_name'], 'NVIDIA GeForce RTX 4090')


class TestConfigDeviceSetting(unittest.TestCase):

    def test_config_has_gpu_info(self):
        from config import Config
        self.assertTrue(hasattr(Config, 'GPU_INFO'))
        self.assertIsInstance(Config.GPU_INFO, dict)

    def test_config_gpu_info_has_required_fields(self):
        from config import Config
        required_fields = ['has_gpu', 'cuda_available', 'torch_is_cuda_build',
                          'device_name', 'cuda_version', 'torch_version', 'warning']
        for field in required_fields:
            self.assertIn(field, Config.GPU_INFO, f"GPU_INFO缺少字段: {field}")

    def test_config_device_consistent_with_gpu_info(self):
        from config import Config
        if Config.GPU_INFO['cuda_available']:
            self.assertEqual(Config.DEVICE, 'cuda')
        else:
            self.assertEqual(Config.DEVICE, 'cpu')


class TestDeviceSelectorLogic(unittest.TestCase):

    def test_gpu_available_returns_cuda_options(self):
        gpu_info = {
            'cuda_available': True,
            'has_gpu': True,
            'device_name': 'NVIDIA GeForce RTX 4090',
            'warning': ''
        }
        if gpu_info['cuda_available']:
            options = ['🖥️ GPU模式运行', '💻 CPU模式运行']
            self.assertEqual(len(options), 2)
            self.assertIn('🖥️ GPU模式运行', options)
            self.assertIn('💻 CPU模式运行', options)

    def test_no_gpu_returns_cpu_only(self):
        gpu_info = {
            'cuda_available': False,
            'has_gpu': False,
            'device_name': '',
            'warning': ''
        }
        if not gpu_info['cuda_available']:
            options = ['💻 CPU模式运行']
            self.assertEqual(len(options), 1)
            self.assertIn('💻 CPU模式运行', options)

    def test_gpu_detected_but_cpu_pytorch_returns_cpu_only(self):
        gpu_info = {
            'cuda_available': False,
            'has_gpu': True,
            'device_name': 'NVIDIA GeForce RTX 3090',
            'warning': '检测到NVIDIA独立显卡...'
        }
        if not gpu_info['cuda_available'] and gpu_info['has_gpu']:
            options = ['💻 CPU模式运行']
            self.assertEqual(len(options), 1)
            self.assertTrue(gpu_info['warning'] != '')


if __name__ == '__main__':
    unittest.main()
