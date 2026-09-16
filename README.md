# starveguard

[![English](https://img.shields.io/badge/English-555555?style=flat)](README.md) [![简体中文](https://img.shields.io/badge/%E7%AE%80%E4%BD%93%E4%B8%AD%E6%96%87-555555?style=flat)](README.zh-CN.md)

A small, deterministic simulator for comparing priority-queue policies under repeated preemption. It models how ignoring preemption history can delay re-admission and repeatedly select the same request as a victim, inspired by [vLLM issue #41951](https://github.com/vllm-project/vllm/issues/41951).

## What it compares

The naive comparator orders requests by priority, arrival time and request ID. The fair comparator inserts `-min(num_preemptions, 3)` after priority: previously preempted requests gain preference **within the same priority tier**, without overriding tier order.

The CLI compares balanced, heavy-contention and light-contention scenarios. Reports include maximum latency, maximum preemptions and the **starvation ratio** (maximum completion latency divided by mean completion latency). The Python API exposes `Request`, `PriorityQueue`, both comparator functions and `simulate()` for custom experiments.

## Install and run

Requires Python 3.9+; no runtime dependencies or GPU. It runs a local simulation, not a live scheduler inspection or patch.

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

Text mode exits `0` if the fair ratio improves or matches the naive ratio in every scenario, otherwise `1`. **JSON mode exits `0` after emitting results regardless of improvement**; scripts must inspect each row's `improved` field. Use `--help` for the available CLI options.

## Limits

This is a simplified discrete-event model, not a port of vLLM. It does not model chunked prefill, KV-block memory accounting or the real cost of recomputation. The capped comparator demonstrates a policy choice; it does not guarantee universal fairness or predict production throughput. Results depend on workload parameters and seeds, and improvements in the default scenarios can be modest.

The upstream issue and [proposed preemption-aware ordering](https://github.com/vllm-project/vllm/pull/51574) are background, not a claim about the current status of upstream fixes. See [core.py](src/starveguard/core.py) for simulation parameters and [tests](tests/test_core.py) for ordering and regression checks.

## Development and removal

```bash
python -m pytest -q
python -m pip uninstall starveguard
```

[Releases](https://github.com/zhuhroscar-tech/starveguard/releases) · [MIT license](LICENSE)
