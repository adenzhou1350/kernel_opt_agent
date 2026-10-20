"""Native HF witness for shared-class alias registration, not a vLLM suite.

Exit 1 means a previously loaded config changed its serialized model type.
No network, model weights, tensors or GPU work are required.
"""

import argparse
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


def check_order(first_alias, second_alias, *, use_vllm=False):
    old_type = DeepseekV3Config.model_type
    old_mapping = dict(CONFIG_MAPPING._extra_content)
    try:
        with tempfile.TemporaryDirectory() as folder:
            def load(alias):
                if not use_vllm:
                    register(alias, DeepseekV3Config)
                root = Path(folder) / alias
                root.mkdir(exist_ok=True)
                (root / "config.json").write_text(
                    json.dumps(dict(model_type=alias,
                                    architectures=["DeepseekV3ForCausalLM"],
                                    hidden_size=128, num_hidden_layers=2,
                                    num_attention_heads=4, num_key_value_heads=4,
                                    intermediate_size=256, n_routed_experts=4,
                                    num_experts_per_tok=2)), encoding="utf-8"
                )
                if use_vllm:
                    from vllm.transformers_utils.config import get_config

                    return get_config(root, trust_remote_code=False)
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
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vllm", action="store_true",
                        help="Use installed vLLM get_config, not the copied helper")
    args = parser.parse_args()
    rows = [check_order(a, b, use_vllm=args.vllm) for a, b in (
        ("kimi_k2", "deepseek_v32"),
        ("deepseek_v32", "kimi_k2"),
        ("kimi_k2", "kimi_k2"),
    )]
    print(json.dumps(dict(transformers=importlib.metadata.version("transformers"),
                          mode="full_vllm_get_config" if args.vllm else "copied_helper",
                          checks=rows), indent=2))
    raise SystemExit(1 if any(not row["preserved"] for row in rows) else 0)
