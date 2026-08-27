# Qwen3.5 GDN 当前四阶段模型推导

"
        "本文件只定义可由数学与当前切分直接推出的量；不把逻辑请求字节当作 L2 或 DRAM 实际流量。

"
        "符号：`b=2`（BF16 字节），`f=4`（FP32 字节），`C=64`，"
        "`J=ceil(S/C)`，`P=64J`，`R=SH`，`Rp=PH`，`E=SHD`，`Ep=PHD`，`HS=JHD²`。

"
        "当前四阶段的数学最小逻辑边界字节：

"
        "- S01：`7bE + 2bR + fR + 2fH`。
"
        "- S2：`4bE + fR + bHS`。
"
        "- S3：`4bE + fR + bHS`。
"
        "- post：`3bE + bD`。
"
        "- 总计：`18bE + 2bR + 3fR + 2bHS + 2fH + bD`。

"
        "当前 padded schedule 的逻辑请求字节：

"
        "- S01：`4bE + 3bEp + 2bR + fRp + 2fH`。
"
        "- S2：`4bEp + fRp + bHS`。
"
        "- S3：`2bE + 2bEp + fRp + bHS`。
"
        "- post：`3bE + bD`。

"
        "S3 与 post 融合时，确定可以消去 raw_o 的一次写和一次读，即 `2bE=4E` 字节。"
        "这只是跨 kernel 逻辑 handoff 的消除量，不是 DRAM 节省量。

"
        "稠密 Tensor 工作量按 1 次乘加等于 2 FLOP 计。S01 对每个有效 chunk 长度 t 的"
        "主稠密工作量为 `HD(3t²+t)`；S2 使用精确尾块公式；S3 包含 `q@h` 与 chunk 内"
        "因果 pair 工作。当前 schedule 的 padded FLOP 单独记录，不能冒充有效数学量。
"
        