"""starveguard core: priority-queue scheduling comparators and a discrete-
event starvation simulator, modeling the request re-ordering bug reported
against vLLM's v1 scheduler (vllm-project/vllm#41951, still open/unfixed
upstream as of this writing -- see README for the live-source verification
trail).

The bug: a priority scheduler orders waiting requests by (priority,
arrival_time, request_id) and pops the lowest key first. When a running
request is preempted (evicted under memory/KV-cache pressure) it is
pushed back into the *same* waiting queue. If another request at the same
priority tier arrived earlier but never started, that request's smaller
arrival_time wins every comparison, so the preempted request is placed
*behind* it -- even though the preempted request already has partially
completed work that gets thrown away, and the just-preempted request may
now be preempted again indefinitely by a steady stream of same-priority
arrivals. This module gives:

  - ``naive_sort_key``: exact re-implementation of the currently-shipped
    (buggy) comparator.
  - ``fair_sort_key``: a preemption-aware comparator (independently
    derived from the bug report's own suggested fix, capped so a
    pathological number of preemptions cannot invert priority order).
  - ``PriorityQueue``: a small heap wrapper parameterized by either key
    function, so callers can audit their own scheduler's behavior.
  - ``simulate``: a deterministic, seeded discrete-event simulator that
    runs many requests with random arrivals and scripted/random
    preemptions and reports a starvation metric per comparator, so a
    fix (or a regression) can be measured quantitatively, not just
    demonstrated on one hand-picked case.
"""
from __future__ import annotations

import heapq
import itertools
import random
from dataclasses import dataclass, field
from typing import Callable, List, Optional, Tuple

SortKey = Tuple  # opaque, comparator-defined tuple; must be a total order


@dataclass
class Request:
    request_id: str
    priority: int = 0
    arrival_time: float = 0.0
    num_preemptions: int = 0
    # simulation-only bookkeeping (unused by the comparators themselves)
    work_remaining: int = 1
    completed_at: Optional[float] = None
    preemption_events: int = 0


def naive_sort_key(req: Request) -> SortKey:
    """The currently-shipped vLLM v1 ``Request.__lt__`` ordering: priority,
    then arrival_time, then request_id. Deliberately ignores
    ``num_preemptions`` -- this is the bug.
    """
    return (req.priority, req.arrival_time, req.request_id)


def fair_sort_key(req: Request, preemption_cap: int = 3) -> SortKey:
    """Preemption-aware ordering: within the same priority tier, a request
    that has already been preempted more times is scheduled *before* one
    that has been preempted fewer times (or never started), regardless of
    raw arrival_time. ``preemption_cap`` bounds how much preemption count
    can override priority-tier ordering, so a pathologically-thrashing
    request cannot starve every other tier indefinitely -- it can only
    win ties within its own priority tier.
    """
    return (req.priority, -min(req.num_preemptions, preemption_cap), req.arrival_time, req.request_id)


Comparator = Callable[[Request], SortKey]


class PriorityQueue:
    """Min-heap of ``Request`` ordered by an injected comparator. Requests
    are re-keyed on every push, so pushing the *same* request object again
    after mutating ``num_preemptions`` re-evaluates its position under a
    preemption-aware comparator -- this is what the bug and its fix are
    actually about.
    """

    def __init__(self, comparator: Comparator = naive_sort_key):
        self._comparator = comparator
        self._heap: List[Tuple[SortKey, int, Request]] = []
        self._counter = itertools.count()  # stable tiebreak for equal keys

    def push(self, req: Request) -> None:
        heapq.heappush(self._heap, (self._comparator(req), next(self._counter), req))

    def pop(self) -> Request:
        if not self._heap:
            raise IndexError("pop from empty PriorityQueue")
        _, _, req = heapq.heappop(self._heap)
        return req

    def peek_order(self) -> List[str]:
        """Return request_ids in the order they would be popped, without
        mutating the queue."""
        return [req.request_id for _, _, req in sorted(self._heap)]

    def __len__(self) -> int:
        return len(self._heap)

    def __bool__(self) -> bool:
        return bool(self._heap)


@dataclass
class SimulationResult:
    comparator_name: str
    completion_latencies: List[float] = field(default_factory=list)
    preemption_counts: List[int] = field(default_factory=list)
    never_completed: int = 0

    @property
    def max_latency(self) -> float:
        return max(self.completion_latencies) if self.completion_latencies else float("inf")

    @property
    def mean_latency(self) -> float:
        if not self.completion_latencies:
            return float("inf")
        return sum(self.completion_latencies) / len(self.completion_latencies)

    @property
    def max_preemptions(self) -> int:
        return max(self.preemption_counts) if self.preemption_counts else 0

    @property
    def starvation_ratio(self) -> float:
        """max completion latency / mean completion latency. A value near
        1.0 means every request waited roughly the same amount; a large
        value means at least one request waited far longer than typical
        -- the observable symptom of starvation."""
        m = self.mean_latency
        if m <= 0 or m == float("inf"):
            return float("inf")
        return self.max_latency / m


def simulate(
    comparator: Comparator,
    *,
    num_requests: int = 40,
    capacity: int = 2,
    work_per_request: int = 3,
    arrival_rate: float = 0.6,
    preemption_probability: float = 0.5,
    seed: int = 0,
    max_steps: int = 5000,
) -> SimulationResult:
    """Discrete-event simulation of a preemptive priority scheduler.

    Each step: admit waiting requests into free capacity slots (ordered by
    ``comparator``); each running request completes one unit of work;
    when capacity is full and requests are waiting, a preemption may occur
    with probability ``preemption_probability`` (modeling KV-cache memory
    pressure forcing an eviction). Victim selection uses the SAME
    ``comparator`` that orders the waiting queue: the victim is the
    currently-running request that comparator would rank *worst*
    (``max(running, key=comparator)``) -- this mirrors vLLM's actual v1
    scheduler, which picks the preemption victim under
    ``SchedulingPolicy.PRIORITY`` via ``max(running, key=lambda r:
    (r.priority, r.arrival_time))`` (see
    vllm/v1/core/sched/scheduler.py:748-753 at the commit cited in the
    README).

    This is what makes the naive-vs-fair comparator difference actually
    observable at the simulation level, not just in an isolated key
    comparison: under the naive comparator (blind to num_preemptions),
    victim selection also ignores preemption history, so whichever
    request currently has the "youngest" (comparator-worst) key keeps
    getting re-selected as victim on every subsequent preemption event --
    since its own arrival_time never changes, it remains comparator-worst
    among the running set indefinitely, and it can be repeatedly
    preempted before ever completing (thrashing / no forward-progress
    guarantee -- the failure mode PR#56843 titles "prevent thrashing").
    Under the fair comparator, each preemption event pushes a victim's
    effective key down (via ``-min(num_preemptions, cap)``), making it
    comparator-*better* than not-yet-preempted running peers, so a
    different request becomes the next victim instead -- breaking the
    thrash cycle and letting the previously-victimized request finish.
    """
    rng = random.Random(seed)
    result = SimulationResult(comparator_name=getattr(comparator, "__name__", "comparator"))

    queue = PriorityQueue(comparator=comparator)
    running: List[Request] = []
    pending_arrivals = sorted(
        (
            Request(
                request_id=f"r{i}",
                priority=rng.choice([0, 0, 0, 1]),  # mostly one tier, some priority-1
                arrival_time=round(i * arrival_rate + rng.random() * 0.1, 4),
                work_remaining=work_per_request,
            )
            for i in range(num_requests)
        ),
        key=lambda r: r.arrival_time,
    )

    t = 0
    completed = 0
    arrival_idx = 0
    while completed < num_requests and t < max_steps:
        # admit arrivals due at/by this step
        while arrival_idx < len(pending_arrivals) and pending_arrivals[arrival_idx].arrival_time <= t:
            queue.push(pending_arrivals[arrival_idx])
            arrival_idx += 1

        # try to fill free capacity
        while len(running) < capacity and queue:
            running.append(queue.pop())

        # if at capacity and queue is non-empty, maybe preempt to simulate
        # memory pressure from a contending same-tier waiting request.
        # Victim = the running request the comparator ranks worst, same
        # as vLLM's own real victim-selection rule (see docstring above).
        if len(running) >= capacity and queue and rng.random() < preemption_probability:
            victim_index = max(range(len(running)), key=lambda i: comparator(running[i]))
            victim = running.pop(victim_index)
            victim.num_preemptions += 1
            victim.preemption_events += 1
            queue.push(victim)

        # do one unit of work for every running request
        still_running = []
        for req in running:
            req.work_remaining -= 1
            if req.work_remaining <= 0:
                req.completed_at = t + 1
                result.completion_latencies.append(req.completed_at - req.arrival_time)
                result.preemption_counts.append(req.preemption_events)
                completed += 1
            else:
                still_running.append(req)
        running = still_running

        t += 1

    result.never_completed = num_requests - completed
    return result
