# 从哪里开始

如果你第一次打开这个仓库，先试下面的经验检索和实验笔记。它们只需要 Git 和
Python 3.10+，不需要模型 API、GPU 或调度服务。先熟悉怎样找一条经验、留下
一份记录，再决定是否需要后面的环境复用和资源协调工具。

这里把已经公开的工作分成两个入口，代码都固定到 commit，便于复现：

| 入口 | 版本 | 用途 |
| --- | --- | --- |
| 轻量工具 | [`4880b87`](https://github.com/adenzhou1350/kernel_opt_agent/tree/4880b87a22281dde93ed54839389164813619c26)，来自 `codex/lean-optimization-core`，2026-09-17 | 经验检索、实验笔记、按需使用的硬件工具 |
| 集成研究记录 | [`85be3c6`](https://github.com/adenzhou1350/kernel_opt_agent/tree/85be3c623cfc405984da6f20d4111fe02357ed1f)，来自 `upstream/integrated-agent-runtime`，2026-09-12 | 环境复用、验证任务排队、实验与交付状态管理 |

两者是不同的工作快照，不是一套安装完成后自动运行的服务。当前 `main` 仍是
基础框架；本页提供导航，没有把所有实验分支合并成一个产品。后续分支可能有
更新，本页列出的验证只对应这两个固定版本。

## 先试轻量工具

在一个新目录克隆，避免影响你已有的工作区。以下单行命令可在 PowerShell
执行；其他系统如果没有 `python` 命令，可换成 Python 3 的实际命令。

```text
git clone --filter=blob:none --single-branch --branch codex/lean-optimization-core https://github.com/adenzhou1350/kernel_opt_agent.git kernel-opt-demo
cd kernel-opt-demo
git switch --detach 4880b87a22281dde93ed54839389164813619c26
python -B scripts/kernel_opt.py --help
python -B scripts/kernel_opt.py knowledge check
python -B scripts/kernel_opt.py knowledge search "graph mode latency"
```

这个快照的 `knowledge check` 应读到 9 条经验。检索结果包括适用条件、例外和
公开依据；例如，eager 模式省下的开销，不一定还能在生产环境的 graph replay
中省下来。搜索命中只是阅读建议，不能代替你的实验结果。

接着创建一份演示笔记。下面只写本地 JSON，不执行算子：

```text
python -B scripts/kernel_opt.py worklog init --run runs/entry-demo --objective "Try the notebook without running a kernel" --source "kernel_opt_agent@4880b87a22281dde93ed54839389164813619c26" --workload "documentation walkthrough" --hardware "CPU-only"
python -B scripts/kernel_opt.py worklog record --run runs/entry-demo --kind decision --summary "Entry walkthrough only; no kernel or performance experiment executed" --status INCONCLUSIVE
python -B scripts/kernel_opt.py worklog status --run runs/entry-demo
```

你会得到 `runs/entry-demo/run.json`，状态是明确记录的 `INCONCLUSIVE`。
重复 `init` 会拒绝覆盖已有笔记；需要重试时换一个目录名。正式实验应填写
真实的源码、负载和硬件，并用 `--evidence` 关联已有结果文件。笔记会保存文件
哈希，也会检查文件后来是否改变；它不会执行 `--command` 里的文字，更不会
仅凭一条记录认定优化成功。

## 已有的三组实现

这些都是仓库中已有的代码。表里的测试用于核对行为范围，不是 GPU 加速数据。

| 解决什么问题 | 实现与测试 | 当前边界 |
| --- | --- | --- |
| 经验散在聊天和日志里，下次还得重新找 | 轻量快照的 [`knowledge_notes.py`](https://github.com/adenzhou1350/kernel_opt_agent/blob/4880b87a22281dde93ed54839389164813619c26/scripts/knowledge_notes.py) 和 [`test_knowledge_notes.py`](https://github.com/adenzhou1350/kernel_opt_agent/blob/4880b87a22281dde93ed54839389164813619c26/tests/test_knowledge_notes.py) | 有搜索、重复条目检查和适用条件；不是自动证明或自动选择优化方案 |
| 跑过什么、依据在哪，过几天说不清 | 轻量快照的 [`worklog.py`](https://github.com/adenzhou1350/kernel_opt_agent/blob/4880b87a22281dde93ed54839389164813619c26/scripts/worklog.py) 和 [`test_worklog.py`](https://github.com/adenzhou1350/kernel_opt_agent/blob/4880b87a22281dde93ed54839389164813619c26/tests/test_worklog.py) | 记录复现命令、上下文和文件哈希；检测证据文件改变或丢失，不替代正确性测试 |
| 验证任务反复搭环境，多个任务又争用同一组卡 | 集成快照的 [`qualification_environment.py`](https://github.com/adenzhou1350/kernel_opt_agent/blob/85be3c623cfc405984da6f20d4111fe02357ed1f/scripts/qualification_environment.py)、[`resource_broker.py`](https://github.com/adenzhou1350/kernel_opt_agent/blob/85be3c623cfc405984da6f20d4111fe02357ed1f/scripts/resource_broker.py)；对应[环境测试](https://github.com/adenzhou1350/kernel_opt_agent/blob/85be3c623cfc405984da6f20d4111fe02357ed1f/tests/test_qualification_environment.py)与[资源测试](https://github.com/adenzhou1350/kernel_opt_agent/blob/85be3c623cfc405984da6f20d4111fe02357ed1f/tests/test_resource_broker.py) | 区分环境复用、源码重新绑定、扩展重编译；资源分配检查卡组占用。复用建议不是执行许可，资源租约也不会自动启动进程 |

集成研究快照适合阅读环境检查与排队的实现。它包含更多历史流程和实验管理
约束；初次试用不需要走完整套流程。这里没有给出它在新集群的部署保证，也
没有用单元测试推导节省了多少 GPU 时间。

## 本次检查到哪一步

2026-10-13，在 Windows 原生 Python 3.14.3 上检查了轻量快照：

- 上面的 `--help`、`knowledge check/search` 和 `worklog init/record/status`
  都执行成功，没有安装额外依赖。
- 使用仓库已有测试检查实验笔记和经验检索：20 项中 19 项通过，1 项因该环境
  无法创建符号链接而跳过。跳过项是经验文件的符号链接越界检查。
- 集成研究快照只核对了表中源码与现有测试，本次没有运行其部署流程或测试集。
- 没有启动本地 WSL、容器、GPU 工作负载或模型训练。这些检查说明轻量入口
  可以使用，不说明任意算子能被自动优化，也不构成性能结论。

可重复的轻量测试命令如下，不需要 pytest：

```text
python -B -m unittest discover -s tests -p test_worklog.py
python -B -m unittest discover -s tests -p test_knowledge_notes.py
```

如果想继续做一个真实优化，带上目标仓库和 commit、要改的算子、代表性输入、
当前复现命令与目标硬件即可。先把一个具体问题跑清楚，再决定是否引入更多
流程。请不要把访问凭据、私有日志或机器地址放进公开 issue。
