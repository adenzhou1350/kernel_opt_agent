# Qwen3.5-0.8B 在 RTX 4060 Laptop 上的端到端优化可行性报告

## 结论

本次验证证明了两件不同的事：

1. 这台 8GB RTX 4060 Laptop 能运行并研究 Qwen3.5-0.8B 的真实生产推理路径。vLLM 自动选择了 Triton/FLA GDN prefill、CUDA GDN decode 与 FlashAttention 2；三种 workload 的 128 个输出 token 均与 Transformers BF16 reference 完全一致。
2. 在“同一 BF16 权重、batch=1、单 token 自回归、禁止量化/推测解码/跳层”的严格赛道里，相对当前 vLLM 再快 2 倍不可行。实测的乐观权重流下界是 6.194 ms/token，而 vLLM 已达到 6.50--6.90 ms/token；按 workload 权重计算，忽略所有非权重成本后的最大乐观加速仅约 1.10 倍。

所以，“比朴素 Transformers 快很多倍”已经实现；“比正常 vLLM 再快很多倍”不能在当前严格合同下成立。若业务目标必须是 2 倍，需要显式进入第二赛道：降低每 token 的权重字节数（量化）、一次权重读取产出多个有效 token（推测/MTP）或改变模型/硬件。

## 冻结对象

- 模型：`Qwen/Qwen3.5-0.8B`，ModelScope master 下载。
- 模型配置 SHA256：`b90b86f35c8e6925ef74ee04d0e758f0a845c83a42089ad82bbaa948de9b4204`。
- 权重 SHA256：`04b1c301231dd422b8860db31311ab2721511346a32cb1e079c4c4e5f1fe4696`。
- 权重大小：1,746,942,600 bytes；Range 下载逐段校验 `Content-Range`，最终 SHA256 与 ModelScope linked ETag 一致。
- GPU：NVIDIA GeForce RTX 4060 Laptop GPU，compute capability 8.9，8GB。
- vLLM 环境：vLLM `0.28.1rc1.dev312+g41848caa6`、Torch `2.13.0+cu130`、Triton `3.7.1`、Transformers `5.16.1`。
- 执行约束：BF16、batch=1、concurrency=1、text-only、greedy、prefix cache 关闭、每个请求状态/KV cache 新建、max model length 4096。

模型共有 873,438,784 个参数。视觉部分 100,592,896 参数被 language-model-only 模式排除。严格生成路径中纳入带宽下界的活跃权重为 1,541,502,656 bytes/token，分布如下：

| 部分 | 存储字节 |
|---|---:|
| Embedding / tied LM head | 508,559,360 |
| 18 层 Gated DeltaNet | 379,562,688 |
| MLP | 550,502,400 |
| 6 层 full attention | 102,767,616 |
| Normalization | 110,592 |

## 正确性与性能

### 逐 token 正确性

vLLM 的每个 case 先在 3 次 discovery 测量中检查重复一致性，再由独立 Transformers BF16 路径生成完整 128 token 对照。三个 case 均为精确相等，首个不一致位置均为 `null`。

### vLLM discovery baseline

本轮采用 1 次 warmup、3 次计时，case 顺序按 iteration 轮换。它足以做候选排序和可行性判断，但还不是 3 warmup、10 trial 的最终 qualification。

| Workload | 中位 TTFT | 中位 TPOT | 输出速度 | 中位 E2E |
|---|---:|---:|---:|---:|
| prompt 128 / generate 128 | 26.71 ms | 6.497 ms | 153.92 tok/s | 851.89 ms |
| prompt 512 / generate 128 | 29.92 ms | 6.893 ms | 145.07 tok/s | 904.79 ms |
| prompt 2048 / generate 128 | 113.60 ms | 6.895 ms | 145.03 tok/s | 988.67 ms |

### 与 Transformers 慢路径的对照

Transformers 当前缺少 `flash-linear-attention` 与 `causal-conv1d`，因此该数据只代表朴素 reference，不是成熟 serving baseline。

| Workload | Transformers | vLLM | vLLM 加速 |
|---|---:|---:|---:|
| prompt 128 / generate 128 | 7.665 s | 0.852 s | 9.00x |
| prompt 512 / generate 128 | 6.665 s | 0.905 s | 7.37x |
| prompt 2048 / generate 128 | 7.144 s | 0.989 s | 7.23x |

这说明模型级“大幅提升”主要来自选对生产 runtime、专用 GDN kernel、编译和 CUDA Graph。不能把这部分收益再次记到自研算子名下。

## 为什么严格 BF16 的 2 倍不可行

使用与活跃语言权重同量级的 BF16 read-only Triton stream，在本机得到：

- 输入读取 1,545,686,592 bytes，另有很小的每 program 输出；
- 中位 6.223 ms；
- 248.88 GB/s；
- 20 个原始样本范围为 6.199--6.317 ms。

排除视觉与未启用的 MTP 权重后，生成一个 token 至少消费 1,541,502,656 bytes 活跃权重。用实测 read service 作为乐观天花板：

`TPOT_floor = 1,541,502,656 / 248.878e9 = 6.194 ms`

该下界故意忽略 activation、GDN recurrent state、KV cache、同步、launch、采样和算术，所以只能偏乐观，不能把真实最优估得更慢。

| Workload | vLLM TPOT | 有效权重带宽 | 达实测读带宽比例 | 乐观最大加速 |
|---|---:|---:|---:|---:|
| prompt 128 | 6.497 ms | 237.26 GB/s | 95.3% | 1.049x |
| prompt 512 | 6.893 ms | 223.63 GB/s | 89.9% | 1.113x |
| prompt 2048 | 6.895 ms | 223.57 GB/s | 89.8% | 1.113x |

2 倍目标要求 3.25--3.45 ms/token，低于 6.194 ms 的乐观权重流下界。该结论不是“当前还没找到好 kernel”，而是“现有合同不允许移除造成下界的字节”。

## 对 agent 架构的修改

### 1. Intake 失败前置

`scripts/new_run.py` 原先只检查部分字段是否存在，会接受不符合仓库 JSON Schema 的 shape、额外字段和 objective enum，然后在下一阶段才失败。现在它在创建 run 目录前调用仓库的完整 Schema validator：

- operator、workload、hardware 任一不合法立即退出；
- 不创建半成品 run；
- 测试覆盖字符串 shape 这一真实失败形式。

这解决“实验合同从一开始就无效，但 agent 数小时后才发现”的浪费。

### 2. 目标可行性门

`optimizer_step.py` 现在识别 `models/feasibility_gate.json`：

- 校验 schema、目标、上界与 evidence SHA256；
- evidence 变化时返回 `BLOCK_INVALID_FEASIBILITY_GATE`，防止手改数字制造停止理由；
- 乐观资源下界仍排除目标时返回 `STOP_OR_REFRAME_INFEASIBLE_TARGET`；
- 给出必须重新选择的合同方向，不再要求 agent 为不可达目标凑候选、继续测量。

对应 opportunity-driven search 测试已通过。

### 3. 从局部利用率转成“可移除端到端时间”

真实 Transformers profile 显示一次 128-token prefill 的 ATen GPU 时间并非单一 GEMM 主导：

| ATen 类别 | GPU 时间占比 | 调用次数 |
|---|---:|---:|
| mm | 27.1% | 187 |
| copy | 22.7% | 4,149 |
| sum | 13.2% | 1,170 |
| mul | 11.0% | 1,692 |
| bmm | 10.1% | 235 |
| add | 5.6% | 1,481 |

因此候选生成的先验顺序应是：运行时/图捕获、GDN recurrence 融合、状态布局和物化消除、GEMM/epilogue；不应从一个 launch 参数 sweep 开始。到了成熟 vLLM 后，带宽闭合又会自动压低这些候选对 decode 的全局预期，避免把局部 1.8x 错写成模型 1.8x。

## 推荐的双赛道

### A. 严格等价赛道

保持当前 BF16 权重与单 token 自回归合同。目标应改为端到端 2%--8%，理论挑战上限约 10%。优先优化：

1. prompt 2048 的 GDN prefill 与 chunk/shape specialization，主要降低 TTFT；
2. 512/2048 decode 相对带宽流的约 10% residual，检查 recurrent/KV state 与 full-attention 额外流量；
3. 只在端到端预测超过测量噪声后实现新的 GDN fusion；
4. 最多两个 finalist 做完整 3×10 paired qualification。

### B. 2 倍目标赛道

它必须修改优化合同，但不应偷偷降低质量。建议依次研究：

1. W8A16/INT8 weight-only：权重字节理论减半，先测 perplexity、任务集与 token parity；
2. INT4/AWQ：带宽余量更大，但质量与 kernel 支持风险更高；
3. 可验证 speculative/MTP：用原模型验证接受 token，保持目标分布，但收益依赖接受率；
4. continuous batching：若真实 workload 允许并发，可把一次权重读取摊给多个请求，但它不是 batch=1 latency 的 2 倍。

这条赛道需要单独的 operator/workload contract、质量门和 baseline，不能与严格 BF16 数据混在一起领奖。

本轮还按 successive-halving 做了两个最小量化 smoke：

- 在线 FP8 成功使用 `CutlassFP8ScaledMMLinearKernel`，2-token parity 通过、模型显存降至 1.08 GiB；但 decode interval 从 BF16 的 26.18 ms 退化到 32.23 ms，热请求从 69.51 ms 退化到 94.82 ms，因此在完整 workload 前淘汰。
- `int8_per_channel_weight_only` preset 被解析为仅含 MoE spec，loader 明确报告 `Quantized 0 layers`。该实验在编译和计时前终止，避免把 BF16 重跑误报成 INT8 性能。

因此，“在线把现有 checkpoint 量化一下”并不能直接得到 2 倍。下一次有效的 2 倍尝试应使用明确量化了 dense linear 层的 checkpoint/配置，并先过相同的 2-token launched-mechanism gate。

## 技术失败与环境边界

- vLLM V2 runner 在当前 WSL 驱动上因 UVA 不可用而失败；固定 `VLLM_USE_V2_MODEL_RUNNER=0` 后兼容 runner 正常。
- FlashInfer top-k/top-p sampler 首次 JIT 需要虚拟环境 `ninja` 在 PATH；本工作负载是 greedy，固定 `VLLM_USE_FLASHINFER_SAMPLER=0`，避免无关采样器污染主干验证。
- 当前 Nsight Compute counters 受 `ERR_NVGPUCTRPERM` 限制，所以没有伪造 cache/issue/stall 归因。
- 5090 未被访问或占用，遵守其正在运行 MiniMax-H3 的约束。
- discovery baseline 不是最终 SOTA certificate；尚未完成 nsys GPU-active 拆分、正式 3×10、功耗/温度控制和最终 binary/SASS 审计。

## 复现入口

所有脚本、原始样本和推导都位于本 run：

- `tools/smoke_transformers_reference.py`
- `tools/profile_transformers_reference.py`
- `tools/smoke_vllm_offline.py`
- `tools/benchmark_vllm_offline.py`
- `tools/validate_vllm_against_transformers.py`
- `tools/benchmark_memory_stream.py`
- `tools/inventory_model_snapshot.py`
- `tools/analyze_bandwidth_bound.py`
- `traces/vllm_discovery_baseline_w1_n3.json`
- `traces/vllm_vs_transformers_parity.json`
- `traces/sm89_memory_stream_model_sized.json`
- `models/bandwidth_bound.json`
- `models/feasibility_gate.json`

ModelScope 模型页：<https://modelscope.cn/models/Qwen/Qwen3.5-0.8B>
