"""Command-line interface: run the naive-vs-fair scheduler comparison and
report a starvation metric, using the shared semantic-color design system.
"""
from __future__ import annotations

import argparse
import json
import sys

from .core import fair_sort_key, naive_sort_key, simulate
from .style import print_fields, resolve_style, section, status_headline

DEFAULT_SCENARIOS = [
    {"label": "balanced-load", "num_requests": 40, "capacity": 2, "arrival_rate": 0.02, "preemption_probability": 0.5, "work_per_request": 10, "seed": 0},
    {"label": "heavy-contention", "num_requests": 40, "capacity": 2, "arrival_rate": 0.02, "preemption_probability": 0.9, "work_per_request": 20, "seed": 1},
    {"label": "light-contention", "num_requests": 30, "capacity": 3, "arrival_rate": 0.02, "preemption_probability": 0.5, "work_per_request": 5, "seed": 2},
]


def _run_all(seed_offset: int = 0) -> list:
    rows = []
    for scenario in DEFAULT_SCENARIOS:
        label = scenario["label"]
        params = {k: v for k, v in scenario.items() if k != "label"}
        params["seed"] = int(params["seed"]) + seed_offset
        naive = simulate(naive_sort_key, **params)
        fair = simulate(fair_sort_key, **params)
        rows.append(
            {
                "scenario": label,
                "naive_starvation_ratio": naive.starvation_ratio,
                "naive_max_latency": naive.max_latency,
                "naive_max_preemptions": naive.max_preemptions,
                "fair_starvation_ratio": fair.starvation_ratio,
                "fair_max_latency": fair.max_latency,
                "fair_max_preemptions": fair.max_preemptions,
                "improved": fair.starvation_ratio <= naive.starvation_ratio,
            }
        )
    return rows


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="starveguard",
        description=(
            "Audit priority-queue scheduler comparators for the preemption-"
            "starvation bug class reported against vLLM's v1 scheduler "
            "(vllm-project/vllm#41951): compare the naive (priority, "
            "arrival_time, request_id) ordering against a preemption-aware "
            "fair ordering across several simulated contention scenarios."
        ),
    )
    parser.add_argument("--json", action="store_true", help="emit machine-readable JSON instead of text")
    parser.add_argument("--no-color", action="store_true", help="disable ANSI color even on a TTY")
    parser.add_argument("--seed-offset", type=int, default=0, help="shift all scenario seeds (default 0)")
    parser.add_argument("--version", action="store_true", help="print version and exit")
    args = parser.parse_args(argv)

    if args.version:
        from . import __version__

        print(f"starveguard {__version__}")
        return 0

    rows = _run_all(seed_offset=args.seed_offset)

    if args.json:
        print(json.dumps(rows, indent=2))
        return 0

    style = resolve_style(no_color_flag=args.no_color)
    all_improved = all(r["improved"] for r in rows)
    level = "ok" if all_improved else "warn"
    print(
        status_headline(
            style,
            level,
            "fair comparator reduces or matches starvation in every scenario"
            if all_improved
            else "fair comparator did not improve every scenario",
        )
    )
    for r in rows:
        section(r["scenario"])
        print_fields(
            [
                ("naive starvation ratio", f"{r['naive_starvation_ratio']:.2f}"),
                ("fair starvation ratio", f"{r['fair_starvation_ratio']:.2f}"),
                ("naive max preemptions", str(r["naive_max_preemptions"])),
                ("fair max preemptions", str(r["fair_max_preemptions"])),
                ("improved", "yes" if r["improved"] else "no"),
            ]
        )
    return 0 if all_improved else 1


if __name__ == "__main__":
    sys.exit(main())
