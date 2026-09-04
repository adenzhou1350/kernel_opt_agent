# Qwen3.5-0.8B 在 RTX 4060 Laptop 上的端到端优化可行性报告

## 结论

本次验证证明了两件不同的事：

1. 这台 8GB RTX 4060 Laptop 能运行并研究 Qwen3.5-0.8B 的真实生产推理路径。vLLM 自动选择了 Triton/FLA GDN prefill、CUDA GDN decode 与 FlashAttention 2；三种 workload 的 128 个输出 token 均与 Transformers BF16 reference 完全一致。
2. 在“同一 BF16 权重、batch=1、单 token 自回归、禁止量化/推测解码/跳层”的严格赛道里，通用的 2 倍目标仍不成立，但 vLLM 并非每个形状都已最优。针对 SM89 上 `M=1, N=248320, K=1024` 的 BF16 `lm_head`，专用 Triton GEMV 在相邻 3 warmup × 10 trial 验证中达到 **1.180x / 1.184x**；随后又在同一份源码、同一编译缓存、仅切换运行时开关的 C-S-S-C 复验中达到 **1.193x E2E / 1.199x TPOT**。两轮六类自然请求的 128-token 输出均逐 token 相等。

所以，“比朴素 Transformers 快很多倍”已经实现；“在这个具体低并发形状上进一步快过 stock vLLM 约 18%”也已实现；“严格 BF16 下普遍再快 2 倍”仍不能成立。若业务目标必须是 2 倍，需要显式进入第二赛道：降低每 token 的权重字节数（量化）、一次权重读取产出多个有效 token（推测/MTP）或改变模型/硬件。

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

## 4060 持续候选搜索（第二轮）

第二轮没有把原始 Transformers 当作优化起点，而是直接以成熟 vLLM BF16 路径为对手。候选覆盖运行时专用化、GDN decode 后端、chunked prefill、编译 custom-op 策略和 FP8 KV cache。所有成功运行的候选都与冻结 vLLM baseline 的三组完整 128-token 输出逐 token 相等。

为降低实验闭环延迟，模型另复制到 WSL EXT4：同一 1.63 GiB checkpoint 的权重加载从 9P 上的 17.42 秒降到 EXT4 热缓存下的 0.33--1.23 秒。这个收益只减少启动等待，不改变 GPU 稳态推理。

当前同一时段的主要 discovery 结果如下。加权值使用冻结 workload 的 0.2/0.3/0.5 权重；不同 engine 进程间尚未做交错 paired qualification，所以小于约 2% 的差异均视为噪声，不作胜出声明。

| 候选 | trials | 加权 E2E | 加权 TPOT | 初始化 | 决策 |
|---|---:|---:|---:|---:|---|
| CUDA GDN、max_num_seqs=1、512 MiB 固定 cache | 7 | 961.44 ms | 6.957 ms | 25.60 s | 保留为快速实验配置 |
| Triton GDN decode、其余相同 | 7 | 1014.18 ms | 7.290 ms | 24.93 s | 淘汰 |
| CUDA GDN、max_num_seqs=80、512 MiB 固定 cache | 7 | 959.76 ms | 6.922 ms | 31.06 s | 延迟差异不确定，启动更慢 |
| 关闭 chunked prefill | 3 | 968.15 ms | 7.003 ms | 22.84 s | vLLM 明确警告该模型不正式支持；淘汰 |
| 强制全部 custom ops | 3 | 963.10 ms | 6.957 ms | 97.88 s（首次编译） | 无可测收益；淘汰 |
| max_num_seqs=1、自动显存 profile | 3 | 972.20 ms | 7.028 ms | 26.41 s | 固定 cache 的热启动收益仅 1.03x |

明确结论：

- 该轮 CUDA fused GDN 相比 Triton GDN 的加权 E2E 快 1.055x、TPOT 快 1.048x；后续带遥测的低频复验显示二者可落入 1% 内，因此这个 5% 排名只对当轮状态成立。
- max_num_seqs 从 80 专用化到 1 后，缓存热启动快 1.21x；稳态 E2E 差异只有约 0.2%，不能宣称推理加速。
- 固定 KV cache 本身在缓存已热时只把初始化从 26.41 秒降到 25.60 秒（1.03x）。此前观察到的约 4x 必须归因于固定 cache、编译缓存命中和文件系统迁移的合成效果，不能单独记到固定 cache 名下。
- 冻结 vLLM baseline 的加权 E2E 是 936.15 ms，仍优于本轮最快的跨进程候选。截至第二轮没有发现可宣称的 strict-BF16 vLLM 之上加速，当时答案是 **1.00x（无可测提升）**；第五轮随后找到并验证了 `lm_head` 候选。

FP8 KV cache 仍是技术失败而非性能失败：它令 full-attention 后端切换到 FlashInfer，但 JIT 首先误用系统 CUDA 12.0 `nvcc`；改用虚拟环境 CUDA 13.3 `nvcc` 后，又与当前 CUDA 13.0 runtime headers 不兼容。因此没有生成可比较性能数据，也没有把该方向判成“算法无效”。考虑到 Qwen3.5-0.8B 只有 6 层 full attention、当前 batch=1 又主要受权重流限制，这个修复的预期全局收益很低，按预算停止继续追查。

### 推荐的快速复现实验配置

下面配置用于候选 screening，目标是缩短 agent 周转，而不是替代生产服务容量配置：

```bash
VLLM_USE_V2_MODEL_RUNNER=0 \
VLLM_USE_FLASHINFER_SAMPLER=0 \
VLLM_GDN_DECODE_KERNEL=cuda \
/home/aden/.venvs/qwen35-vllm-4060/bin/python \
  tools/benchmark_vllm_offline.py \
  --model /home/aden/models/Qwen3.5-0.8B \
  --output traces/<candidate>.json \
  --warmups 1 --trials 3 \
  --max-num-seqs 1 \
  --kv-cache-memory-bytes 536870912
```

只有候选越过噪声阈值后，才恢复生产容量设置并做交错 paired qualification。这样把“每次全量启动并深测”改成“缓存热身一次、短筛、最多两个晋级”，正面解决几十小时停留在实验测量的问题。

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

### 4. 候选执行路径证明

`candidate-smoke-result` 升级为 v3。smoke 除了正确性和目标值，还必须提供：

- `expected_path` 与实际观测的 `observed_path`，两者必须相等；
- 至少一个位于 run 内、SHA256 闭合的源码或执行证据；
- `FRESH`、`SOURCE_HASHED` 或 `NOT_COMPILED` 编译缓存策略。
- 运行时 `execution_proof`：kernel 实例数、插桩调用数或非编译直调 sentinel，并绑定到上述证据。对 `torch.compile`/CUDA Graph 候选禁止只用 host sentinel。

不满足时，`candidate_discovery.py` 把结果视为技术失败，不能进入 `QUALIFICATION_READY`；晋级凭证也会携带 reachability 记录。真实 vLLM harness 另增加 backend、source hash、空 cache root 三个启动前门和逐请求 GPU 遥测。源码/缓存门防止跑错版本，运行时计数则进一步防止 Python 条件在图捕获时被冻结、候选 custom op 实际没有进入 decode 图。

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

## 第三轮：怎样在 4060 上真正快过 vLLM

这一轮把问题拆成三个不同合同：严格 BF16、可验证投机、量化运行时。新增 6 类自然请求（中文解释、Python 代码、算术推理、编辑、系统设计、翻译），每类固定生成 128 token，禁用 prefix/prompt cache，1 次 warmup、3 次 measurement，并轮换 case 顺序。

### 投机解码不是这个小模型的答案

合成 prompt 的输出高度周期性，n-gram-4 在该数据上得到 397.89 ms，对默认 vLLM 的 936.15 ms 看似有 2.353x；但换成自然请求后，默认 vLLM 为 940.98 ms，n-gram-4 变成 1813.21 ms（0.519x），且 6/6 输出都与默认路径不同。MTP-1 在自然请求上也只有 1138.91 ms（0.826x），仅 2/6 输出相同。llama.cpp 的 MTP-1 同样从 Q8 默认的 789.22 ms 退化到 1348.59 ms。

因此合成 n-gram 的 2.353x 是 benchmark exploitation，不是可推广的模型加速。agent 现在必须先通过代表性 workload 和输出合同，才能晋级候选。

### 轻量运行时与量化前沿

使用官方 llama.cpp Windows CUDA build `b10700`，将同一 BF16 checkpoint 转成 GGUF BF16，并另测官方 Q8_0、Q4_0。服务器保持常驻、单 slot、全部层在 GPU、Flash Attention 开启、提示缓存关闭。高性能状态下的量化 discovery 如下：

| 路径 | 加权 E2E | 输出速度 | 相对 vLLM BF16 | 数值合同 |
|---|---:|---:|---:|---|
| vLLM BF16 | 940.98 ms | 143.4 tok/s | 1.000x | 冻结 BF16 reference |
| llama.cpp Q8_0 | 789.22 ms | 175.4 tok/s | **1.192x** | 量化，需质量门 |
| llama.cpp Q4_0 | 700.18 ms | 201.7 tok/s | **1.344x** | 更激进量化，需质量门 |

后段低功耗状态下，llama.cpp BF16 为 2063.14 ms，而相邻时段 vLLM BF16 为 1222.63 ms，前者仍慢 1.687x，并且没有维持逐 token parity。这说明“只换掉 vLLM”并不会赢；实际胜点来自更少权重字节和适合 batch=1 的量化 kernel/轻量服务路径共同作用。

质量 discovery 使用本报告作为中英技术语料，512 context、8 chunks。llama.cpp BF16 perplexity 为 25.4609，Q8_0 为 25.4991（+0.15%），Q4_0 为 27.9038（+9.59%）。这不是下游任务 qualification，但足以把 Q8_0 排为当前质量优先候选，把 Q4_0 标为明确的延迟优先候选。

### 为什么现在还不能承诺稳定 1.34x

本机后段发生明显功耗状态漂移：vLLM 相同自然套件从 940.98 ms 变为 1222.63 ms（1.299x 变慢）；紧邻的 Q4_0 复测为 1147.39 ms，只领先 1.066x。独立的 21 点负载采样记录到中位 26.64 W、核心 780 MHz、显存 8001 MHz、GPU 利用率 87%，而设备默认功耗上限为 80 W。当前数据证明“存在胜出配置”，但还不是电源锁定、随机交错的 qualification。

下一道正式门应是：锁定笔记本性能模式；每个样本记录功耗、核心/显存时钟、温度；vLLM/Q8/Q4 随机交错；至少 3 warmups × 10 trials；再跑真实任务质量集。通过后才能把 1.19x 或 1.34x 写成产品承诺。

新增的可复现入口：

- `tools/benchmark_llamacpp_server.py`：启动持久 llama.cpp server 并跑自然请求套件；
- `tools/benchmark_llamacpp_perplexity.py`：量化质量 discovery；
- `tools/summarize_vllm_speculation.py`：识别合成投机假胜利；
- `tools/summarize_runtime_frontier.py`：合并速度、质量与功耗漂移证据；
- `models/vllm_speculation_search.json`、`models/runtime_frontier.json`：机器可读决策；
- `traces/llamacpp_server_natural_*.json`、`traces/llamacpp_quantization_ppl_c512_n8.json`：原始样本、输出与二进制/模型 SHA256。

## 第四轮：vLLM 是否已经最优，以及量化 vLLM 的实测

### “同参数量”不是同一推理合同

Q8、Q4 与 BF16 可以拥有相同数量的权重元素，但每个元素的表示和值都不同。对本机 batch=1 decode，BF16 每 token 至少读取约 1.542 GB 活跃权重；Q8/Q4 的主要收益来自减少这些字节，而不是找到了一个数学上等价、却凭空快数倍的 BF16 kernel。因此量化实现战胜 BF16 vLLM 不能证明其 runtime 更强，必须再与使用相同量化格式的 vLLM 比较。

vLLM 也不是抽象意义上的“理论最优”。但在本机高性能状态中，它的 6.497--6.895 ms TPOT 已经接近 6.194 ms 的乐观 BF16 权重流下界，对 batch=1 严格 BF16 只剩约 5%--11% 的理论空间。此时继续微调小算子不可能兑现 2x；要获得数量级更大的变化，必须减少权重字节、摊薄权重读取，或减少需要执行的目标模型 token step。

### GDN 局部候选：先撤回错误归因，再做可达性复验

Qwen3.5-0.8B 每 token 执行 18 个 GDN 层。packed recurrent Triton kernel 固定 `BV=32, num_warps=1, num_stages=3`。穷举 `BV={16,32,64,128}`、warps `{1,2,4,8}`、stages `{2,3,4}` 后，首轮曾因把 stock wrapper 与候选 direct launch 混测，误报 `num_stages=2` 快 1.315x；修正为两侧都 direct launch 后，原版为 53.51 us，局部最快 `BV=64, warps=1, stages=4` 为 38.99 us，表面快 1.372x，且输出和更新后的 FP32 recurrent state 均逐元素相等。

随后审计执行图发现：早先两组所谓“整模候选”运行时设置的是 `VLLM_GDN_DECODE_KERNEL=cuda`，实际走 C++ CUDA fused op，根本不会调用被修改的 Triton wrapper。因此此前把 4.44%/15.93% 变慢归因给两个 Triton launch 配置是错误的；这些数据只能证明跨进程功耗漂移，不能用于候选裁决，现正式撤回该归因。

加入 `--expect-gdn-decode-kernel` 可达性门后重新测试真实 Triton 路径：

| 可达路径 | 加权 E2E | 加权 TPOT | 输出 |
|---|---:|---:|---|
| Triton 原版 `BV=32, stages=3` | 893.92 ms | 6.789 ms | 6/6 exact |
| Triton 候选 `BV=64, stages=4` | 990.43 ms | 7.518 ms | 6/6 exact |

真实候选慢 10.8%，因此仍应淘汰，但现在淘汰理由来自正确执行路径。另一次同低频状态的 3-trial 对照中，CUDA 与 stock Triton 只差不足 1%，说明早先“CUDA 稳定快 5%”也不能跨功耗状态泛化。agent 必须同时记录实际 backend、候选源码 hash、编译缓存状态和 GPU 遥测，任何一项不满足都不得晋级或淘汰候选。

### vLLM W4A16/Marlin：速度通过，质量失败

下载并测试了第三方 `BlivionIaG/Qwen3.5-0.8B-AWQ-INT4` checkpoint。它是 compressed-tensors W4A16、group size 128，vLLM 成功选择 `MarlinLinearKernel`。在质量门加入前，其自然套件表面结果为 888.24 ms E2E、6.640 ms TPOT，相邻 BF16 原版为 1058.58 ms、7.959 ms，即表面约 1.19x。

但六个自然请求都退化为只有 2--3 个 distinct token 的特殊 token 循环，例如重复 `<think>\n\n</think>`。将 checkpoint 在 Transformers 中解压回 BF16 后仍得到同样循环，证明这是 checkpoint/量化结果失效，不是 vLLM Marlin 独有错误。该候选最终状态是 **FAIL / REJECT**，不能把 1.19x 当成可用结论。

benchmark 现新增低多样性退化门，并修复两类量化 checkpoint 兼容问题：

- 不再把“同一垃圾输出可以稳定重复”判作正确；
- 支持独立指定原模型 tokenizer/chat template，避免第三方量化目录缺模板；
- 权重证据改为 safetensors shard manifest hash，不再假设固定 shard 文件名；
- `compressed-tensors` 成为显式量化选项，报告会记录实际量化合同。
- 新增独立的 `scripts/audit_generation_quality.py`，让任何 runtime trace 都能在进入性能排行榜前先过低成本输出退化门；该门只排除明显坏结果，不替代 perplexity 与任务质量评测。

这个 checkpoint 的 734 MB 中仍保留 BF16 `lm_head`，而 248,320 x 1,024 的 tied vocabulary matrix 本身约 508 MB，并且每个生成 token 都要读取。其余层即使压到 INT4，也无法把全模型字节流缩成四分之一；再加上未量化层、GDN state、反量化与 launch 开销，正确实现的实际加速本来也会显著小于理论 4x。

当前结论是：量化 vLLM 在机制上应该参与公平竞赛，Marlin 已证明能执行并产生约 1.2x 的原始速度变化；但本次可获得的 AWQ checkpoint 质量失效，所以可用的 vLLM 量化冠军仍为空。下一步应从官方 BF16 权重生成分层量化前沿：先只量化 MLP，再加入 full-attention projection，最后才尝试 GDN q/k/v projection；每一级先过自然输出、perplexity/任务质量门，再测速度。

## 第五轮：严格 BF16 首个可复现胜出候选

### 为什么 stock vLLM 仍有缺口

vLLM 是面向多模型、多 GPU、多 batch 和高并发的通用 serving runtime，不保证每个 `M=1` GEMV 都拥有针对具体消费卡的最优 kernel。本模型的语言头是一个 `1 x 1024` 向量乘 `248320 x 1024` BF16 权重；在 Ada SM89 上，当前版本的 FlashInfer BF16 backend 只支持 SM100，CuTeDSL skinny GEMM 又只支持 SM90+，所以该形状最终退回 `torch.nn.functional.linear`/cuBLAS。

最初的顺序式单形状微基准把该投影测成 4076.13 us 对 2049.69 us（1.989x）；新增交错、每轮反转顺序的 paired 测量后，两边变为 2054.90 us 对 2046.79 us（1.004x）。这说明消费级笔记本 GPU 的升频/热状态足以让“先测完 torch、再测 Triton”的局部数字严重失真，微基准只能用于候选筛选，不能作为端到端收益的因果证明。Triton 核读取约 508 MB 权重，对应约 248 GB/s，仍接近本机实测显存读服务率；随机输入最大绝对差为 0.00390625、平均绝对差约 2.5e-7，argmax 相同。最终晋级依据是下面的整模复验，而不是 1.989x 的旧局部数字。

### 3×10 自然请求 qualification

只替换该 `lm_head`，不修改其余层、权重、精度、采样器或生成步数。candidate 与 stock 分别独立启动；每边 3 次 warmup、10 次测量，六类自然请求轮换顺序，每请求固定生成 128 token，并记录逐请求 GPU 功耗和时钟。

| 路径 | 加权 E2E | 加权 TPOT | 核心频率中位数 | 功耗中位数 |
|---|---:|---:|---:|---:|
| stock vLLM BF16 | 1262.67 ms | 9.623 ms | 930 MHz | 37.03 W |
| SM89 BF16 `lm_head` GEMV | 1070.37 ms | 8.128 ms | 915 MHz | 37.70 W |
| 加速 | **1.180x** | **1.184x** | 候选略低 | 近似相同 |

六类任务各自的 E2E 加速均在 1.173x--1.186x，TPOT 加速在 1.177x--1.193x；两边完整 128-token 序列 6/6 精确相等。候选没有靠更高核心频率取得收益。这是当前 4060 环境中首个通过同权重、同 BF16、自然 workload、逐 token 回归和功耗遥测的 vLLM 之上候选。

为排除“改源码导致另一份 Inductor 图”这一混杂因素，又把补丁改成默认关闭、由 `VLLM_SM89_BF16_LM_HEAD=1` 开启；stock 与 candidate 因而共享完全相同的 `utils.py` SHA256（`a2b0d1ac...3dc23`）和编译缓存。按 C1-S1-S2-C2 顺序各做 1 warmup × 3 trial：

| 同源复验 | 加权 E2E | 加权 TPOT | 核心频率中位数 | 功耗中位数 |
|---|---:|---:|---:|---:|
| candidate C1 | 1060.27 ms | 8.084 ms | 915 MHz | 37.28 W |
| stock S1 | 1262.98 ms | 9.683 ms | 952.5 MHz | 36.69 W |
| stock S2 | 1264.43 ms | 9.684 ms | 922.5 MHz | 36.71 W |
| candidate C2 | 1058.61 ms | 8.075 ms | 892.5 MHz | 37.61 W |
| 两边均值之比 | **1.193x** | **1.199x** | 候选更低 | 近似相同 |

两组配对比较都为 6/6 token-exact，且每个任务均胜出。paired 微基准与整模结果不矛盾于“候选有效”的判定：前者证明局部计时会受前序 workload 影响，后者才覆盖真实权重布局、调用节奏、CUDA Graph 与 runtime 调度。

随后在用户目录安装 Nsight Systems 2025.5.1，并用 `--cuda-graph-trace=node` 成功展开 CUDA Graph。六个 32-token 自然请求共生成 192 token，其中 186 个稳定 decode 图步骤。`lm_head` 候选被观察到 192 次，平均 2057.54 us；主干 cuBLAS GEMV 被观察到 21,204 次，即每个 decode 步骤 114 次，总计约 5.036 ms/step。这个 timeline 同时给出了后续搜索的全局预算，但 node tracing 会扰动短 kernel，因此只用于机会排序和执行路径证明，不把它的百分比当作生产 qualification。

这个结论的边界也很明确：它是单请求延迟胜出，不是高并发吞吐 SOTA；逐 token 相等覆盖当前六类 qualification 请求，不等于对所有可能输入证明浮点 bitwise 等价；历史高功耗状态与当前低功耗状态不能横向混排。补丁位于 `patches/vllm_0.28.1_sm89_bf16_lm_head.patch`，机器可读证据位于 `models/sm89_lm_head_candidate.json`。

### 为什么没有把同一 GEMV 铺满主干

孤立微基准曾预测多个主干投影也会变快。旧实验即使使用了新 `VLLM_CACHE_ROOT`，其 `x.numel()==x.shape[-1]` Python 分支仍可能在 `torch.compile` 动态图捕获时被冻结；因此旧的 GDN/MLP/全开消融没有证明候选 custom op 被执行。此前写下的“慢 1.0%--2.4%”因果归因现正式撤回，原始数据只保留为不可达实验记录。

修复后的候选让所选权重形状无条件经过 opaque custom op，并在 op 内部决定 `M=1` 使用 Triton、其他形状回退 `F.linear`。Nsight 分别观察到预期的 **3,540/3,540** 和 **12,468/12,468** 个候选 kernel，证明它们真正进入了 decode 图：

| 可达候选 | 局部证据 | 非 profiler 端到端筛选 | 输出合同 | 决定 |
|---|---:|---:|---:|---|
| GDN `8192x1024` | 80.46 → 72.54 us | profiler E2E 1.022x | 5/6 exact | 淘汰 |
| GDN + MLP gate-up | kernel 均下降 | C-S-C 平均 TPOT 1.016x | 2/6 exact | 淘汰 |
| attention stacked QKV `5120x1024` | micro 1.625x | screening TPOT 1.007x | 2/6 exact | 淘汰 |

这里还修正了 attention QKV 的真实输出宽度：vLLM 把 `q=4096, k=512, v=512` 堆叠为 5120，而不是旧记录中的 3072。结果说明这些局部替换确实能减少 kernel 时间，但独立替换每个 GEMV 的全局收益只剩约 0.7%--1.7%，且改变 BF16 累加顺序后未通过当前 token-exact 合同。它们不能进入补丁；下一代候选必须通过跨投影融合、持久化或物化消除，移除流量/launch，而不是继续扫单个 GEMV 参数。

### 下一轮由全局机会图决定

Nsight 结果已通过公共 `kernel_opt.py opportunity` 入口写回正式机会图，并覆盖 12 个不同 rewrite family。按“预期全局收益 × 置信度 / 实现分钟数”排序如下：

| 排名 | 机会 | 可能移除的时间/step | 实现预算 | 含义 |
|---:|---|---:|---:|---|
| 1 | 跨投影融合/持久调度 | 200--500 us | 120 min | 唯一值得优先投入的主路径 |
| 2 | normalization/epilogue 融合 | 20--80 us | 60 min | 小而较便宜 |
| 3 | recurrent state 融合与布局 | 30--100 us | 90 min | 需跨算子边界 |
| 4 | decode graph 小 kernel 压缩 | 20--100 us | 60 min | node tracing 下低置信度 |
| 5 | attention/KV 布局协同 | 10--50 us | 90 min | 预期收益较小 |
| 6 | 继续微调 lm-head | 0--50 us | 45 min | 已接近带宽屋顶，停止无界 sweep |

因此 agent 下一步不能再随机挑一个 launch 参数：先给排名 1 的跨投影候选最多两小时实现预算；若 production smoke 没有至少约 2% 的可测收益，就转向排名 2/3，而不是在同一形状上继续几十小时。这里的区间是经验搜索先验，不是理论最优证明；实际结果必须再由运行时可达性、正确性和交错 A/B 更新。

这一轮也修正了原先过强的理论推断：整模型权重流下界能排除严格 BF16 的普遍 2x，但不能证明 stock vLLM 的每个子算子已高效。理论模型应输出“剩余总预算”和“按算子可移除时间”两个层级；只要某个大算子明显低于同机带宽屋顶，局部专用化仍可能兑现两位数的端到端收益。

复现补丁与 qualification：

```bash
cd /home/aden/.venvs/qwen35-vllm-4060/lib/python3.12/site-packages
patch -p1 < /mnt/d/codes/kernel_opt_agent/runs/20260902_qwen35_08b_e2e_sm89_v1/patches/vllm_0.28.1_sm89_bf16_lm_head.patch

cd /mnt/d/codes/kernel_opt_agent/runs/20260902_qwen35_08b_e2e_sm89_v1
VLLM_USE_V2_MODEL_RUNNER=0 \
VLLM_USE_FLASHINFER_SAMPLER=0 \
VLLM_GDN_DECODE_KERNEL=cuda \
VLLM_SM89_BF16_LM_HEAD=1 \
/home/aden/.venvs/qwen35-vllm-4060/bin/python tools/benchmark_vllm_offline.py \
  --model /home/aden/models/Qwen3.5-0.8B \
  --output traces/reproduction.json \
  --prompt-suite natural --new-tokens 128 \
  --warmups 3 --trials 10 --max-num-seqs 1 \
  --kv-cache-memory-bytes 536870912 \
  --expect-gdn-decode-kernel cuda --expect-sm89-lm-head triton --gpu-telemetry \
  --expect-source-sha256 /home/aden/.venvs/qwen35-vllm-4060/lib/python3.12/site-packages/vllm/model_executor/layers/utils.py=a2b0d1ac0600564dae318afc544d7876e13b2e847e44cb1d5632bec7d213dc23
```

正式比较 stock 时使用同一份已打补丁源码，取消 `VLLM_SM89_BF16_LM_HEAD`，并指定 `--expect-sm89-lm-head stock`；这样无需通过反向打补丁制造两份不同源码。若修改的是编译图内部路径，还应给每个候选设置独立、初始为空的 `VLLM_CACHE_ROOT` 并增加 `--require-empty-vllm-cache-root`；本候选的 `lm_head` 位于已编译 backbone 之外，但仍保留 source hash 与实际路径门以防跑错版本。

## 技术失败与环境边界

- vLLM V2 runner 在当前 WSL 驱动上因 UVA 不可用而失败；固定 `VLLM_USE_V2_MODEL_RUNNER=0` 后兼容 runner 正常。
- FlashInfer top-k/top-p sampler 首次 JIT 需要虚拟环境 `ninja` 在 PATH；本工作负载是 greedy，固定 `VLLM_USE_FLASHINFER_SAMPLER=0`，避免无关采样器污染主干验证。
- 当前虚拟环境同时存在 CUDA 13.0 runtime headers、CUDA 13.3 `nvcc`，系统还有 CUDA 12.0 `nvcc`。需要 JIT 的候选必须先做 compiler/header 一致性 preflight；本轮 FP8 KV cache 因此只记技术失败，不作性能拒绝。
- 当前 Nsight Compute counters 受 `ERR_NVGPUCTRPERM` 限制，所以没有伪造 cache/issue/stall 归因。
- WSL 系统自带的 Nsight Systems 2022.4 无法导入 CUDA 13 profiler-range capture；后来在用户目录安装 2025.5.1 后已经成功获得 CUDA Graph node timeline。旧失败文件仍只作技术记录，新 SQLite timeline 用于机会排序和运行时可达性证明。
- 5090 未被访问或占用，遵守其正在运行 MiniMax-H3 的约束。
- `lm_head` 候选已完成带功耗/温度遥测的 3×10、同源 C-S-S-C 和 nsys GPU-active 拆分，但仍不是最终 SOTA certificate；尚未完成锁定电源模式后的随机进程交错、更大质量集和最终 binary/SASS 审计。

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
- `models/vllm_candidate_search.json`
- `traces/vllm_confirm_fastloop_cuda_a_w1_n7.json`
- `traces/vllm_confirm_fastloop_triton_w1_n7.json`
- `traces/vllm_confirm_maxseq80_cache512m_repeat_w1_n7.json`
- `tools/summarize_vllm_search.py`
- `tools/benchmark_bf16_skinny_gemm.py`
- `tools/compare_vllm_candidate.py`
- `patches/vllm_0.28.1_sm89_bf16_lm_head.patch`
- `models/sm89_lm_head_candidate.json`
- `models/sm89_lm_head_comparison.json`
- `models/sm89_lm_head_abba.json`
- `models/sm89_selective_backbone_ablations.json`
- `models/sm89_nsys_operator_map.json`
- `models/nsys2025_lmhead_opportunity_map.json`
- `models/nsys2025_reachable_gdnqkvz_map.json`
- `models/nsys2025_reachable_all_map.json`
- `models/nsys_tool_identity.json`
- `models/opportunity_map.json`
- `models/opportunity_specs/*.json`
- `profiles/nsys2025_lmhead_candidate_nodes.sqlite`
- `profiles/nsys2025_reachable_gdnqkvz_b.sqlite`
- `profiles/nsys2025_reachable_all_b.sqlite`
- `comparisons/vllm_lmhead_toggle_pair1.json`
- `comparisons/vllm_lmhead_toggle_pair2.json`
- `traces/vllm_natural_sm89_lmhead_gemv_qual_n_w3_n10.json`
- `traces/vllm_natural_stock_qual_o_w3_n10.json`
- `traces/vllm_lmhead_restored_smoke_w1_n1_t16.json`

ModelScope 模型页：<https://modelscope.cn/models/Qwen/Qwen3.5-0.8B>
