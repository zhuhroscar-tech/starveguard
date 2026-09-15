# starveguard

Simulate and audit priority-queue scheduling policies for **preemption
starvation** — the failure mode where a request that already ran (and was
evicted under memory pressure) gets stuck behind newly-arrived requests
forever, because the scheduler's ordering only looks at arrival time, not
preemption history.

## The bug this models

vLLM's v1 engine scheduler (`vllm/v1/request.py`, `Request.__lt__`)
orders requests for `SchedulingPolicy.PRIORITY` by `(priority,
arrival_time, request_id)` and completely ignores `num_preemptions`. When
a running request is preempted (its KV-cache blocks are evicted to make
room), it is re-queued using the *same* comparator. A same-priority
request that arrived earlier but never started will always win that
comparison, so the just-preempted request goes to the back of the line —
even though it has partially completed work being thrown away, and it can
be preempted again indefinitely by a steady stream of same-tier arrivals.

This is filed as **[vllm-project/vllm#41951](https://github.com/vllm-project/vllm/issues/41951)**
("v1 Scheduler: preempted requests lose re-admission priority in
PriorityRequestQueue, causing redundant recompute"), with related
follow-ups **[#56843](https://github.com/vllm-project/vllm/pull/56843)**
("prevent thrashing") and the still-open feature request
**[#40004](https://github.com/vllm-project/vllm/issues/40004)** asking
for priority-aware preemption more broadly.

### Live-source verification (not just issue metadata)

Per this project's own reproduce-before-accept discipline: issue #41951
was auto-closed by a stale-bot (`state_reason: not_planned`), **not**
fixed — and its linked fix PRs (**#41952**, **#51574**, **#56843**) are
all either closed-unmerged or still open as of this writing. Rather than
trust that state alone, I read vLLM's actual current mainline source
directly:

- `vllm/v1/request.py` at commit `7cfb97e33791a348cd5d7b622cca521d82d8399f`
  (2026-08-20, the most recent commit touching that file) — `Request.__lt__`
  still compares `(priority, arrival_time, request_id, id(self))` with no
  reference to `num_preemptions` anywhere in the comparison.
- `vllm/v1/core/sched/scheduler.py` — victim selection for
  `SchedulingPolicy.PRIORITY` preemption is
  `max(self.running, key=lambda r: (r.priority, r.arrival_time))`
  (lines ~748-753), confirming the *victim-selection* path has the exact
  same blind spot as the *re-admission* path.
- PR **#51574** (open, unmerged) proposes exactly the fix modeled here:
  a `sort_key` property adding `-min(num_preemptions, 3)` as a secondary
  sort field between priority and arrival_time.

So the bug is confirmed live and unfixed on vLLM's actual current
mainline, not merely "was reported at some point."

## What this tool provides

- `naive_sort_key` / `fair_sort_key` — drop-in comparator functions you
  can audit your own scheduler's ordering logic against.
- `PriorityQueue` — a small heap wrapper parameterized by either
  comparator, demonstrating how re-pushing a mutated request changes its
  position (or doesn't) under each policy.
- `simulate()` — a deterministic, seeded discrete-event simulation of a
  capacity-limited preemptive scheduler (arrivals, admission, preemption,
  completion) that reports a **starvation ratio** (max completion
  latency ÷ mean completion latency) so a fix's effect can be measured
  quantitatively across many scenarios and seeds, not eyeballed from one
  example.

```
$ starveguard
●  fair comparator reduces or matches starvation in every scenario

balanced-load
  naive starvation ratio      1.90
  fair starvation ratio       1.88
  naive max preemptions       11
  fair max preemptions        8
  improved                    yes
...
```

`--json` emits machine-readable results; `--no-color` / `NO_COLOR` /
`FORCE_COLOR` are all respected (see `style.py`).

## Verification

- 17 tests: an exact reproduction of issue #41951's own minimal example
  (`test_naive_comparator_matches_vllm_41951_repro`), the fair
  comparator's fix property, a priority-tier-dominance guard (the fix
  must not itself introduce priority inversion), a preemption-cap
  boundary test, `PriorityQueue` push/pop/re-prioritization/edge cases,
  a per-seed statistical oracle across 5 seeds, an aggregate mean-
  improvement oracle across 20 seeds, load/determinism/zero-request edge
  cases.
- A regression check confirms the test suite actually catches the bug:
  running the "fair" oracle test with the naive comparator substituted in
  its place fails as expected (`mean_fair < mean_naive` becomes false),
  proving the tests are sensitive to the fix rather than vacuously
  passing.
- CI runs on both `ubuntu-latest` and `macos-latest` (Python 3.9 and
  3.12) — this is pure Python with no OS-specific syscalls, so behavior
  is expected to be identical across both, and CI confirms it rather
  than assuming it from local macOS-only testing.

## Limitations (stated honestly)

- This is a **simplified discrete-event model** of scheduling dynamics,
  not a byte-for-byte port of vLLM's scheduler. It captures the ordering
  bug's core mechanism (comparator ignores preemption history for both
  re-admission and victim selection) but does not model chunked prefill,
  KV-block-level memory accounting, or the actual recompute cost of a
  real preemption (which is typically far more expensive than the pure
  re-ordering delay modeled here).
- `fair_sort_key`'s specific tie-breaking formula (`-min(num_preemptions,
  3)`) is independently derived to demonstrate the fix's *effect*, not a
  verbatim copy of PR #51574's code — the improvement direction and
  magnitude will differ somewhat from whatever fix (if any) eventually
  lands upstream.
- The measured improvement in the default scenarios is real but modest
  (a few percent reduction in mean starvation ratio) at these particular
  parameters; it is not a dramatic effect, and this is reported honestly
  rather than tuned to look more dramatic than it is. Use `--seed-offset`
  or adjust `simulate()`'s parameters directly to explore other regimes.

## Install

```
pip install -e ".[dev]"
python -m pytest
```

## License

MIT
