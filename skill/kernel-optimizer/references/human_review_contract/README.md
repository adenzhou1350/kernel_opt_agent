# 人工审核输出契约

本目录规定算子优化结果如何被人类阅读和审核。它不替代原始证据、
资源模型或极限证书，而是把这些内容压缩成语义稳定、可追溯且不误导的
中文报告。

生成报告前必须完整读取：

1. [SEMANTICS.md](SEMANTICS.md)：唯一允许的术语及其含义。
2. [MODELING_RULES.md](MODELING_RULES.md)：工作量、服务曲线、耦合和 DAG
   的建模规则。
3. [MICROBENCHMARK_RULES.md](MICROBENCHMARK_RULES.md)：哪些实验可以进入
   人工报告，以及如何证明延迟、吞吐与饱和原因。
4. [PRESENTATION_RULES.md](PRESENTATION_RULES.md)：页面结构和视觉编码。
5. [REVIEW_CHECKLIST.md](REVIEW_CHECKLIST.md)：发布前的人工签字清单。

机器入口是 `schemas/human_review_report.schema.json`。报告先写成 JSON，
再运行：

```bash
python3 scripts/kernel_opt.py report-validate path/to/report.json
python3 scripts/kernel_opt.py report-render path/to/report.json path/to/index.html
```

校验通过只说明结构和语义词表合规，不代表性能结论正确。性能结论仍需
原始样本、最终二进制、匹配实验和跨层预测共同支撑。
