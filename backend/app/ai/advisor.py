"""Explicit deterministic compatibility helper; never creates a provider client.

Paid explanations run exclusively through AgentManager and its usage ledger.
"""

from typing import Any

from .fallback import explain_comparison, explain_simulation
from .schemas import Explanation


def explain(result: dict[str, Any], comparison: dict[str, Any] | None = None) -> Explanation:
    return explain_comparison(result, comparison) if comparison else explain_simulation(result)
