"""Independent, local-only consumer checks for the reported alias contract."""
import json
import os
import pickle
from pathlib import Path
import subprocess
import sys

import pytest
from tokenizers import Tokenizer
from tokenizers.models import WordLevel
from tokenizers.pre_tokenizers import Whitespace
from transformers import AutoTokenizer
from transformers.models.auto.configuration_auto import CONFIG_MAPPING
from vllm.transformers_utils import config as config_module


@pytest.fixture(autouse=True)
def restore_registry():
    previous = dict(CONFIG_MAPPING._extra_content)
    classes = {config_module._CONFIG_REGISTRY[a] for a in ('kimi_k2', 'deepseek_v32')}
    old = {cls: cls.model_type for cls in classes}
    yield
    CONFIG_MAPPING._extra_content.clear()
    CONFIG_MAPPING._extra_content.update(previous)
    for cls, model_type in old.items():
        cls.model_type = model_type


def make_local_config(path, alias='kimi_k2'):
    path.mkdir()
    (path / 'config.json').write_text(json.dumps({'model_type': alias}))
    return config_module.get_config(path, trust_remote_code=False)


def test_exact_native_module():
    import hashlib
    import torch
    module = Path(config_module.__file__).resolve()
    assert module.is_relative_to(Path(os.environ['EXPECTED_PACKAGE_ROOT']).resolve())
    assert hashlib.sha256(module.read_bytes()).hexdigest() == os.environ['EXPECTED_CONFIG_SHA256']
    assert torch.version.cuda is None and not torch.cuda.is_initialized()


def test_pickle_in_fresh_native_interpreter(tmp_path):
    config = make_local_config(tmp_path / 'input')
    serialized = tmp_path / 'config.pkl'
    serialized.write_bytes(pickle.dumps(config))
    code = '''import json,pickle,sys
from pathlib import Path
from transformers import DeepseekV3Config
from vllm.transformers_utils import config as c
x=pickle.loads(Path(sys.argv[1]).read_bytes())
assert isinstance(x,DeepseekV3Config)
assert x.model_type=='kimi_k2'
print(json.dumps({'model_type':x.model_type,'serialized_type':x.to_dict()['model_type'],'class':type(x).__name__}))
'''
    completed = subprocess.run([os.environ['REVIEWED_UV'], '--no-config', 'run',
        '--no-project', '--offline', '--python', sys.executable, 'python', '-B',
        '-c', code, str(serialized)], check=False, capture_output=True, text=True,
        timeout=40)
    print('FRESH_PICKLE=' + completed.stdout)
    assert completed.returncode == 0, completed.stderr
    assert json.loads(completed.stdout.splitlines()[-1])['serialized_type'] == 'kimi_k2'


@pytest.mark.parametrize('alias', ['kimi_k2', 'deepseek_v32'])
def test_auto_tokenizer_native_config_class_fallback(tmp_path, alias):
    """A valid local tokenizer may omit an explicit tokenizer_class override."""
    path = tmp_path / 'snapshot'
    config = make_local_config(path, alias)
    backend = Tokenizer(WordLevel({'[UNK]': 0, 'hello': 1, 'world': 2}, unk_token='[UNK]'))
    backend.pre_tokenizer = Whitespace()
    backend.save(str(path / 'tokenizer.json'))
    (path / 'tokenizer_config.json').write_text(json.dumps({
        'unk_token': '[UNK]', 'model_max_length': 128,
    }))
    tokenizer = AutoTokenizer.from_pretrained(path, config=config,
        trust_remote_code=False, local_files_only=True)
    assert tokenizer.encode('hello world', add_special_tokens=False) == [1, 2]
