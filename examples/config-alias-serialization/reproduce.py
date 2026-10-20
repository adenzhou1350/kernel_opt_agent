"""Native HF witness for shared-class alias registration, not a vLLM suite.

Exit 1 means a previously loaded config changed its serialized model type.
No network, model weights, tensors or GPU work are required.
"""

import importlib.metadata
import json
import os
from pathlib import Path
import tempfile

os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["TRANSFORMERS_OFFLINE"] = "1"
os.environ["CUDA_VISIBLE_DEVICES"] = ""

from transformers import AutoConfig, DeepseekV3Config  # noqa: E402
from transformers.models.auto.configuration_auto import CONFIG_MAPPING  # noqa: E402


def register(model_type, config_class):
    # Same two statements as the pinned vLLM _register_config_class helper.
    config_class.model_type = model_type
    AutoConfig.register(model_type, config_class, exist_ok=True)


def check_order(first_alias, second_alias):
    old_type = DeepseekV3Config.model_type
    old_mapping = dict(CONFIG_MAPPING._extra_content)
    try:
        with tempfile.TemporaryDirectory() as folder:
            def load(alias):
                register(alias, DeepseekV3Config)
                root = Path(folder) / alias
                root.mkdir(exist_ok=True)
                (root / "config.json").write_text(
                    json.dumps({"model_type": alias}), encoding="utf-8"
                )
                return AutoConfig.from_pretrained(root, local_files_only=True)

            first = load(first_alias)
            before = first.to_dict()["model_type"]
            load(second_alias)
            after = first.to_dict()["model_type"]
            destination = Path(folder) / "saved-first"
            first.save_pretrained(destination)
            saved = json.loads((destination / "config.json").read_text())["model_type"]
            return dict(first_alias=first_alias, second_alias=second_alias,
                        instance_type=first.model_type, before=before,
                        after=after, saved=saved,
                        preserved=before == after == saved == first_alias)
    finally:
        # Internal mapping access is cleanup in this standalone probe only.
        DeepseekV3Config.model_type = old_type
        CONFIG_MAPPING._extra_content.clear()
        CONFIG_MAPPING._extra_content.update(old_mapping)


if __name__ == "__main__":
    rows = [check_order(a, b) for a, b in (
        ("kimi_k2", "deepseek_v32"),
        ("deepseek_v32", "kimi_k2"),
        ("kimi_k2", "kimi_k2"),
    )]
    print(json.dumps(dict(transformers=importlib.metadata.version("transformers"),
                          checks=rows), indent=2))
    raise SystemExit(1 if any(not row["preserved"] for row in rows) else 0)
