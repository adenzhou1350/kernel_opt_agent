# RTX 4060：lossless packed BF16 lm_head 持久回放

本目录是 `candidate-smoke-result-v6` 和 `PERSISTENT_PER_ARM` 的真实 GPU 回放证据，
不是生产接受证书，也不是理论最优证明。

## 冻结条件

- GPU：NVIDIA GeForce RTX 4060 Laptop GPU（SM89，8 GiB）
- 模型：Qwen3.5-0.8B GPTQ backbone，BF16 output head
- vLLM 源码：PR #55494，commit `4048b5edbad29bed0d052c6e258fd1c53072218f`
- 对照：`lm_head_backend=torch`
- 候选：`lm_head_backend=lossless_packed`
- 请求：3 个冻结 prompt，每个 greedy 生成 64 token
- 进程模型：每臂一个持久引擎，每个引擎连续处理 3 个请求

## 结果

| 指标 | 基线 | 候选 |
|---|---:|---:|
| 三请求稳态均值 | 316.173 ms | 286.511 ms |
| 单请求范围 | 298.815–336.902 ms | 272.823–297.857 ms |
| engine init | 1 | 1 |
| packed kernel profiler count | 0 | 8 |

候选降低完整请求稳态延迟 **9.382%**，即 **1.104x**；3/3 输出 token digest
精确一致。框架状态为 `PROMOTED_TO_QUALIFICATION`。

## 失败也属于证据

初版候选两次启动失败分别来自嵌套包找不到 FlashAttention 二进制扩展，以及空源码
子模块遮蔽 wheel 中 FlashMLA 文件。两次均保存 immutable receipt，并在预算用完后自动
变为 `TECHNICALLY_BLOCKED`。`overlay-v2` 使用统一递归 import overlay 解决，而不是继续
逐模块打补丁。

## 关键文件

- `models/candidate-execution/lossless-packed-lmhead-overlay-v2.json`：执行路由与预计实验成本
- `candidates/lossless-packed-lmhead/vllm-source-identity.json`：PR commit 与源码文件哈希
- `candidates/lossless-packed-lmhead/smoke-result-v2.json`：性能、正确性和 reachability 总证据
- `candidates/lossless-packed-lmhead-overlay-v2/attempts/attempt-01/`：框架执行 transcript 与回执
- `models/discovery_promotions/lossless-packed-lmhead-overlay-v2.json`：晋级 artifact

复验入口：

```powershell
python -B scripts/kernel_opt.py candidate status --run runs/20260907_lmhead_persistent_replay_sm89_v1
python -B scripts/validate_json_schema.py --schema schemas/candidate_smoke_result.schema.json --instance runs/20260907_lmhead_persistent_replay_sm89_v1/candidates/lossless-packed-lmhead/smoke-result-v2.json
```
