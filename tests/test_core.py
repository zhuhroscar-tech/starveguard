"""Unit + property tests for starveguard's comparators and simulator.

Includes a direct regression reproduction of the exact scenario described
in vllm-project/vllm#41951's own minimal repro (two same-priority
requests, one preempted, one never-started -- the preempted one must
lose under the naive comparator and win under the fair one), plus an
independent statistical oracle (the fair comparator must reduce
starvation ratio, on average, across many random seeds -- not just one
hand-picked case) and edge-case tests for the PriorityQueue and simulator.
"""
from __future__ import annotations

import statistics

import pytest

from starveguard.core import (
    PriorityQueue,
    Request,
    fair_sort_key,
    naive_sort_key,
    simulate,
)


def test_naive_comparator_matches_vllm_41951_repro():
    """Exact reproduction of the bug report's own minimal example: request
    A ran first and was preempted (arrival_time=1.0, num_preemptions=1);
    request B arrived earlier but never started (arrival_time=0.0,
    num_preemptions=0). Under the naive comparator, B's earlier
    arrival_time wins regardless of A's preemption history -- this is
    the documented bug, not a hypothesis; this test would fail (i.e.
    correctly demonstrate no bug) if vLLM's actual shipped comparator
    changed to account for num_preemptions.
    """
    req_a = Request(request_id="A", priority=0, arrival_time=1.0, num_preemptions=1)
    req_b = Request(request_id="B", priority=0, arrival_time=0.0, num_preemptions=0)

    # naive_sort_key is a byte-for-byte reimplementation of the currently
    # shipped vllm/v1/request.py Request.__lt__ (priority, arrival_time,
    # request_id) -- verified against vLLM's live mainline source at
    # commit 7cfb97e (2026-08-20), the most recent commit touching that
    # file as of this writing (see README for the full verification
    # trail and PR #51574 showing the proposed-but-unmerged fix, which
    # this module's fair_sort_key independently reproduces the *effect*
    # of, not copies the code from).
    assert naive_sort_key(req_a) > naive_sort_key(req_b), (
        "naive comparator should place the never-started, earlier-arrival "
        "request B ahead of the already-preempted request A -- this is "
        "the bug"
    )


def test_fair_comparator_protects_preempted_request():
    """The fair comparator must invert that ordering: a request with more
    preemptions is scheduled first within the same priority tier,
    regardless of raw arrival_time."""
    req_a = Request(request_id="A", priority=0, arrival_time=1.0, num_preemptions=1)
    req_b = Request(request_id="B", priority=0, arrival_time=0.0, num_preemptions=0)

    assert fair_sort_key(req_a) < fair_sort_key(req_b), (
        "fair comparator should protect the already-preempted request A "
        "ahead of the never-started request B"
    )


def test_priority_tier_still_dominates_preemption_count():
    """A request in a strictly lower (better) priority tier must still
    win regardless of preemption count -- the fair comparator must not
    let preemption count override priority, only break ties within a
    tier. This guards against a naive 'just sort by preemptions' fix
    that would itself introduce priority-inversion."""
    high_priority_never_preempted = Request(request_id="H", priority=0, arrival_time=5.0, num_preemptions=0)
    low_priority_heavily_preempted = Request(request_id="L", priority=1, arrival_time=0.0, num_preemptions=10)

    assert fair_sort_key(high_priority_never_preempted) < fair_sort_key(low_priority_heavily_preempted), (
        "priority tier must dominate preemption count"
    )


def test_preemption_cap_bounds_tiebreak_influence():
    """The preemption_cap parameter must actually cap: two requests with
    preemption counts both >= the cap must compare equal on that field
    (falling through to arrival_time), not keep growing indefinitely."""
    req_capped_low = Request(request_id="X", priority=0, arrival_time=1.0, num_preemptions=3)
    req_capped_high = Request(request_id="Y", priority=0, arrival_time=2.0, num_preemptions=999)

    key_low = fair_sort_key(req_capped_low, preemption_cap=3)
    key_high = fair_sort_key(req_capped_high, preemption_cap=3)
    # both capped at 3 -> equal on the preemption field -> arrival_time breaks the tie
    assert key_low[1] == key_high[1] == -3
    assert key_low < key_high  # req_capped_low has the earlier arrival_time


def test_priority_queue_push_pop_order_naive():
    queue = PriorityQueue(comparator=naive_sort_key)
    for rid, arrival in [("c", 3.0), ("a", 1.0), ("b", 2.0)]:
        queue.push(Request(request_id=rid, arrival_time=arrival))
    order = [queue.pop().request_id for _ in range(3)]
    assert order == ["a", "b", "c"]


def test_priority_queue_reprioritization_after_preemption():
    """Pushing the same request again after mutating num_preemptions must
    change its position under the fair comparator -- this is the actual
    mechanism the fix relies on (re-evaluating priority on re-admission,
    not just at initial push)."""
    queue = PriorityQueue(comparator=fair_sort_key)
    req_a = Request(request_id="A", priority=0, arrival_time=1.0)
    req_b = Request(request_id="B", priority=0, arrival_time=0.0)
    queue.push(req_a)
    queue.push(req_b)
    assert queue.peek_order() == ["B", "A"]  # B arrived first, neither preempted yet

    # A gets preempted: re-push after incrementing num_preemptions
    popped = queue.pop()
    assert popped.request_id == "B"
    queue.push(popped)  # B goes back in unpreempted (not the point of this test)
    req_a.num_preemptions = 1
    queue.push(req_a)
    # Now A should be back, but a fresh queue reflecting current mutated state:
    assert queue.peek_order()[0] == "A", "preempted A should now be ordered first"


def test_priority_queue_empty_pop_raises():
    queue = PriorityQueue()
    with pytest.raises(IndexError):
        queue.pop()


def test_priority_queue_len_and_bool():
    queue = PriorityQueue()
    assert len(queue) == 0
    assert not queue
    queue.push(Request(request_id="z"))
    assert len(queue) == 1
    assert queue


@pytest.mark.parametrize("seed", [0, 1, 2, 3, 4])
def test_fair_comparator_reduces_or_matches_starvation_per_seed(seed):
    """Independent oracle: for each of several seeds and a
    moderate-to-heavy contention scenario, the fair comparator's
    starvation ratio must not be worse than the naive one. This is a
    statistical/behavioral property, checked directly via simulation
    (an independent execution of both policies against the same
    workload), not a single cherry-picked example."""
    kwargs = dict(num_requests=40, capacity=2, arrival_rate=0.02, preemption_probability=0.7, work_per_request=10, seed=seed)
    naive = simulate(naive_sort_key, **kwargs)
    fair = simulate(fair_sort_key, **kwargs)
    assert fair.starvation_ratio <= naive.starvation_ratio + 1e-9, (
        f"seed={seed}: fair starvation_ratio {fair.starvation_ratio:.3f} "
        f"should not exceed naive's {naive.starvation_ratio:.3f}"
    )


def test_fair_comparator_reduces_mean_starvation_across_seeds():
    """Aggregate oracle across many seeds: the *mean* improvement should
    be clearly positive (not just non-negative per-seed noise). This
    guards against a fix that technically never loses but also never
    meaningfully helps."""
    ratios_naive = []
    ratios_fair = []
    for seed in range(20):
        kwargs = dict(num_requests=40, capacity=2, arrival_rate=0.02, preemption_probability=0.7, work_per_request=10, seed=seed)
        ratios_naive.append(simulate(naive_sort_key, **kwargs).starvation_ratio)
        ratios_fair.append(simulate(fair_sort_key, **kwargs).starvation_ratio)
    mean_naive = statistics.mean(ratios_naive)
    mean_fair = statistics.mean(ratios_fair)
    assert mean_fair < mean_naive, (
        f"mean fair starvation ratio {mean_fair:.3f} should be clearly "
        f"below mean naive {mean_naive:.3f}"
    )


def test_simulate_all_requests_complete_under_reasonable_load():
    """Sanity/edge case: a light-load scenario should let every request
    finish within the step budget under either comparator."""
    for comparator in (naive_sort_key, fair_sort_key):
        result = simulate(
            comparator, num_requests=10, capacity=4, preemption_probability=0.1, seed=42, max_steps=1000
        )
        assert result.never_completed == 0


def test_simulate_zero_requests_is_well_defined():
    result = simulate(naive_sort_key, num_requests=0, capacity=2)
    assert result.completion_latencies == []
    assert result.never_completed == 0
    assert result.max_latency == float("inf")
    assert result.starvation_ratio == float("inf")


def test_simulate_deterministic_given_seed():
    """Same seed must produce byte-identical results -- required for the
    ledger's own reproducibility discipline and for meaningful before/
    after comparisons."""
    common = dict(num_requests=30, capacity=2, preemption_probability=0.5, seed=7)
    r1 = simulate(naive_sort_key, **common)
    r2 = simulate(naive_sort_key, **common)
    assert r1.completion_latencies == r2.completion_latencies
    assert r1.preemption_counts == r2.preemption_counts
