"""starveguard: audit priority-queue scheduler comparators for the
preemption-starvation bug reported against vLLM's v1 scheduler
(vllm-project/vllm#41951)."""
from .core import (
    PriorityQueue,
    Request,
    SimulationResult,
    fair_sort_key,
    naive_sort_key,
    simulate,
)

__version__ = "0.1.3"
__all__ = [
    "PriorityQueue",
    "Request",
    "SimulationResult",
    "fair_sort_key",
    "naive_sort_key",
    "simulate",
    "__version__",
]
