"""Check a distinct consumer contract; stable canonical metadata alone is insufficient."""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from transformers.models.auto.configuration_auto import CONFIG_MAPPING
from vllm.transformers_utils import config as config_module

ALIASES = ('kimi_k2', 'deepseek_v32', 'RefinedWeb', 'RefinedWebModel',
           'unlimited-ocr', 'unlimited_ocr')


@pytest.fixture(autouse=True)
def isolate_registry():
    mapping = dict(CONFIG_MAPPING._extra_content)
    classes = {config_module._CONFIG_REGISTRY[a] for a in ALIASES}
    old_types = {cls: cls.model_type for cls in classes}
    yield
    for cls, value in old_types.items():
        cls.model_type = value
    CONFIG_MAPPING._extra_content.clear()
    CONFIG_MAPPING._extra_content.update(mapping)


def roundtrip(tmp_path, alias):
    source = tmp_path / 'source'
    source.mkdir()
    (source / 'config.json').write_text(json.dumps({'model_type': alias}))
    before = config_module.get_config(source, trust_remote_code=False)
    saved = tmp_path / 'saved'
    before.save_pretrained(saved)
    after = config_module.get_config(saved, trust_remote_code=False)
    print('ROUNDTRIP=' + json.dumps(dict(alias=alias, before=before.model_type,
        serialized=json.loads((saved / 'config.json').read_text())['model_type'],
        after=after.model_type, original_class=type(before).__name__,
        reloaded_class=type(after).__name__)))
    return before, after


@pytest.mark.parametrize('alias', ALIASES)
def test_alias_survives_save_and_reload(tmp_path, alias):
    before, after = roundtrip(tmp_path, alias)
    assert after.model_type == before.model_type


def test_kimi_tool_call_id_dispatch_survives_reload(tmp_path):
    from vllm.renderers.chat_utils.tool_call import get_tool_call_id_type
    before, after = roundtrip(tmp_path, 'kimi_k2')
    def select(config):
        return get_tool_call_id_type(SimpleNamespace(
            hf_config=config, hf_text_config=config, hf_overrides=None))
    # Calls the real model-type dispatch helper, not a replacement assertion.
    assert select(before) == 'kimi_k2'
    assert select(after) == select(before)
