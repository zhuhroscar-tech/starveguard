# starveguard

[![English](https://img.shields.io/badge/English-555555?style=flat)](README.md) [![简体中文](https://img.shields.io/badge/%E7%AE%80%E4%BD%93%E4%B8%AD%E6%96%87-555555?style=flat)](README.zh-CN.md)

一个用于比较优先队列抢占策略的小型确定性模拟器。它演示：排序忽略抢占历史时，请求可能迟迟无法重新运行，或反复成为被抢占对象。问题背景见 [vLLM issue #41951](https://github.com/vllm-project/vllm/issues/41951)。

## 比较什么

朴素比较器依次按优先级、到达时间、请求 ID 排序。公平比较器在优先级之后加入 `-min(num_preemptions, 3)`，让已被抢占的请求在**同一优先级内**获得优先机会，不改变不同优先级之间的顺序。

CLI 比较均衡负载、高竞争、低竞争三种场景，报告最大完成延迟、最大抢占次数，以及 starvation ratio（最大完成延迟 ÷ 平均完成延迟）。Python API 提供 `Request`、`PriorityQueue`、两种比较器和 `simulate()`，可自行调整实验参数。

## 安装与运行

需要 Python 3.9+，无运行时依赖，不需要 GPU。本工具只运行本地模拟，不检查或修改实际调度器。

```bash
git clone https://github.com/zhuhroscar-tech/starveguard.git
cd starveguard
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
```

```bash
starveguard
starveguard --json
starveguard --seed-offset 10
starveguard --no-color
```

文本模式下，公平策略在所有场景中的比值均不高于朴素策略时退出码为 `0`，否则为 `1`。**JSON 模式输出后始终返回 `0`，不代表策略有所改善**；脚本应检查每行的 `improved` 字段。其他参数见 `--help`。

## 限制

这是简化的离散事件模型，不是 vLLM 移植版，不模拟 chunked prefill、KV block 内存管理或真实重计算成本。带上限的比较器用于展示一种策略选择，不保证所有工作负载下的公平性，也不能预测生产吞吐量。结果取决于参数和随机种子，默认场景的改善幅度可能不大。

上游 issue 和[抢占感知排序提案](https://github.com/vllm-project/vllm/pull/51574)仅作背景，不表示上游修复目前处于某种状态。模拟参数见 [core.py](src/starveguard/core.py)，排序和回归检查见[测试](tests/test_core.py)。

## 开发与卸载

```bash
python -m pytest -q
python -m pip uninstall starveguard
```

[发布文件](https://github.com/zhuhroscar-tech/starveguard/releases) · [MIT 许可证](LICENSE)
