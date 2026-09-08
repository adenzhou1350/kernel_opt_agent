# vLLM V1 单进程架构候选

整模时间线显示，B=1 和 B=8 decode 的 GPU kernel 活跃时间都只有约 19%–20%，其余时间主要表现为逐步 kernel burst 之间的 GPU 空隙。`synchronize_input_prep` 本身只有约 0.1% 墙钟，不能解释问题；`get_output` 等待的是当前 token 的采样结果，不能直接删除。

因此筛查了 `VLLM_ENABLE_V1_MULTIPROCESSING=0`：不改模型和 kernel，只移除 offline `LLM` 的 EngineCore 子进程边界。

- B=1 筛查约 0.958x，回归，不能全局启用。
- B=8 两次配对性能分别 1.1516x、1.1175x，pooled 1.1345x。
- multiprocess CONTROL 自己两次生成结果不完全一致，因此原冻结的跨 arm exact-token gate 保持未通过；不能事后修改该结论。
- 随后单独预注册了 vLLM 自己 `check_logprobs_close` 使用的 reciprocal top-5 oracle：6/8 请求完全一致，2/8 在首个分叉点互在 top-5，正确性 PASS。

组合独立性能与正确性证据后，本结果升级为受 workload 约束的 `QUALIFIED_GUARDED_ARCHITECTURE_RESULT`。下一步仍必须在 clean current main 上复现，并找到可维护的代码或配置路由形式；不能直接把单进程设成全局默认。
