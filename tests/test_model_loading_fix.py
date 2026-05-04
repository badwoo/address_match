"""
测试修复：模型加载多路径搜索和回退机制

测试内容：
    1. _find_model_local_path 函数的路径搜索逻辑
    2. Config 中 LOCAL_EMBEDDING_PATH 和 LOCAL_MODEL_PATH 不再硬编码
    3. embedding.py 和 mgeo_model.py 源码中包含正确的加载策略
"""

import sys
import os
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import Config, _find_model_local_path


def test_find_model_local_path_project_dir():
    project_model_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                      'models', 'iic', 'mgeo_backbone_chinese_base')
    os.makedirs(project_model_dir, exist_ok=True)
    try:
        result = _find_model_local_path('iic/mgeo_backbone_chinese_base')
        assert result is not None, "Should find model in project directory"
        assert 'models' in result and 'iic' in result, f"Expected project models dir, got {result}"
        assert result == project_model_dir, f"Expected {project_model_dir}, got {result}"
        print("test_find_model_local_path_project_dir: PASSED")
    finally:
        os.rmdir(project_model_dir)
        parent = os.path.dirname(project_model_dir)
        if os.path.isdir(parent) and not os.listdir(parent):
            os.rmdir(parent)
        grandparent = os.path.dirname(parent)
        if os.path.isdir(grandparent) and not os.listdir(grandparent):
            os.rmdir(grandparent)


def test_find_model_local_path_not_found():
    result = _find_model_local_path('nonexistent/model_xyz_12345')
    assert result is None, f"Expected None for nonexistent model, got {result}"
    print("test_find_model_local_path_not_found: PASSED")


def test_find_model_local_path_modelscope_cache():
    home = os.path.expanduser('~')
    modelscope_cache = os.environ.get('MODELSCOPE_CACHE',
                                      os.path.join(home, '.cache', 'modelscope', 'hub', 'models'))
    test_model_dir = os.path.join(modelscope_cache, 'test_org', 'test_model_xyz')
    os.makedirs(test_model_dir, exist_ok=True)
    try:
        result = _find_model_local_path('test_org/test_model_xyz')
        assert result is not None, "Should find model in modelscope cache"
        assert result == test_model_dir, f"Expected {test_model_dir}, got {result}"
        print("test_find_model_local_path_modelscope_cache: PASSED")
    finally:
        os.rmdir(test_model_dir)
        parent = os.path.dirname(test_model_dir)
        if os.path.isdir(parent) and not os.listdir(parent):
            os.rmdir(parent)


def test_config_local_paths_not_hardcoded():
    config_file_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'config.py')
    with open(config_file_path, 'r', encoding='utf-8') as f:
        config_source = f.read()
    assert r"C:\Users\Administrator" not in config_source, \
        "Config source should not contain hardcoded Administrator path"
    assert "_find_model_local_path" in config_source, \
        "Config should use _find_model_local_path() for model paths"
    print("test_config_local_paths_not_hardcoded: PASSED")


def test_config_local_paths_are_none_or_valid_dir():
    if Config.LOCAL_EMBEDDING_PATH is not None:
        assert os.path.isdir(Config.LOCAL_EMBEDDING_PATH), \
            f"LOCAL_EMBEDDING_PATH should be a valid dir or None, got {Config.LOCAL_EMBEDDING_PATH}"
    if Config.LOCAL_MODEL_PATH is not None:
        assert os.path.isdir(Config.LOCAL_MODEL_PATH), \
            f"LOCAL_MODEL_PATH should be a valid dir or None, got {Config.LOCAL_MODEL_PATH}"
    print("test_config_local_paths_are_none_or_valid_dir: PASSED")


def test_embedding_source_has_correct_loading_strategy():
    embedding_file = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                   'model', 'embedding.py')
    with open(embedding_file, 'r', encoding='utf-8') as f:
        source = f.read()

    assert "MODELSCOPE_AVAILABLE = True" in source or "MODELSCOPE_AVAILABLE = False" in source, \
        "embedding.py should have MODELSCOPE_AVAILABLE flag"
    assert "_try_load_from_local" in source, \
        "embedding.py should have _try_load_from_local method"
    assert "_try_load_from_model_name" in source, \
        "embedding.py should have _try_load_from_model_name method"
    assert "TRANSFORMERS_AVAILABLE" in source, \
        "embedding.py should have TRANSFORMERS_AVAILABLE flag"
    assert "MS_AutoTokenizer" in source or "MS_AutoModel" in source, \
        "embedding.py should import modelscope with alias"
    assert "HF_AutoTokenizer" in source or "HF_AutoModel" in source, \
        "embedding.py should import transformers with alias"
    assert "MODELSCOPE_AVAILABLE = False" not in source.split("try:")[0] if "try:" in source else True, \
        "MODELSCOPE_AVAILABLE should be set inside try/except, not hardcoded to False"
    print("test_embedding_source_has_correct_loading_strategy: PASSED")


def test_mgeo_model_source_has_correct_loading_strategy():
    mgeo_file = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                              'model', 'mgeo_model.py')
    with open(mgeo_file, 'r', encoding='utf-8') as f:
        source = f.read()

    assert "MODELSCOPE_AVAILABLE" in source, \
        "mgeo_model.py should have MODELSCOPE_AVAILABLE flag"
    assert "_try_load_from_local" in source, \
        "mgeo_model.py should have _try_load_from_local method"
    assert "_try_load_from_model_name" in source, \
        "mgeo_model.py should have _try_load_from_model_name method"
    assert "TRANSFORMERS_AVAILABLE" in source, \
        "mgeo_model.py should have TRANSFORMERS_AVAILABLE flag"
    assert "MS_AutoTokenizer" in source or "MS_AutoModelForSeqCls" in source, \
        "mgeo_model.py should import modelscope with alias"
    assert "HF_AutoTokenizer" in source or "HF_AutoModelForSeqCls" in source, \
        "mgeo_model.py should import transformers with alias"
    assert "_find_model_local_path" in source, \
        "mgeo_model.py should use _find_model_local_path for path search"
    print("test_mgeo_model_source_has_correct_loading_strategy: PASSED")


def test_embedding_no_hardcoded_false_flag():
    embedding_file = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                   'model', 'embedding.py')
    with open(embedding_file, 'r', encoding='utf-8') as f:
        source = f.read()
    lines_after_import = source.split("from modelscope")
    if len(lines_after_import) > 1:
        next_few_lines = lines_after_import[1][:200]
        assert "MODELSCOPE_AVAILABLE = False" not in next_few_lines, \
            "MODELSCOPE_AVAILABLE should not be set to False right after modelscope import"
    print("test_embedding_no_hardcoded_false_flag: PASSED")


def test_find_model_local_path_with_env_var():
    with tempfile.TemporaryDirectory() as tmpdir:
        test_model_dir = os.path.join(tmpdir, 'test_org', 'test_model_env')
        os.makedirs(test_model_dir, exist_ok=True)

        old_env = os.environ.get('MODELSCOPE_CACHE')
        os.environ['MODELSCOPE_CACHE'] = tmpdir
        try:
            result = _find_model_local_path('test_org/test_model_env')
            assert result is not None, "Should find model via MODELSCOPE_CACHE env var"
            assert result == test_model_dir, f"Expected {test_model_dir}, got {result}"
            print("test_find_model_local_path_with_env_var: PASSED")
        finally:
            if old_env is not None:
                os.environ['MODELSCOPE_CACHE'] = old_env
            else:
                os.environ.pop('MODELSCOPE_CACHE', None)


if __name__ == '__main__':
    test_find_model_local_path_project_dir()
    test_find_model_local_path_not_found()
    test_find_model_local_path_modelscope_cache()
    test_config_local_paths_not_hardcoded()
    test_config_local_paths_are_none_or_valid_dir()
    test_embedding_source_has_correct_loading_strategy()
    test_mgeo_model_source_has_correct_loading_strategy()
    test_embedding_no_hardcoded_false_flag()
    test_find_model_local_path_with_env_var()
    print('\n===== ALL TESTS PASSED =====')
