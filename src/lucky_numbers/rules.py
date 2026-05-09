"""Rule expression evaluation and dispatch."""
from __future__ import annotations

from typing import Any

from simpleeval import EvalWithCompoundTypes

from .models import PLANET_NUMBER


class WhenEvaluationError(ValueError):
    """Raised when a rule's `when` expression cannot be evaluated.

    Distinguishes "could not evaluate" (missing context key, attr error) from
    "evaluated to False" (rule legitimately did not match). The caller in
    seeds.py turns this into a visible audit entry so silently-broken rules
    are no longer hidden.
    """


class RuleEvaluator:
    def __init__(self, context: dict[str, Any]):
        self.context = context
        self._eval = EvalWithCompoundTypes(names=context, functions={
            "abs": abs, "min": min, "max": max, "len": len, "int": int,
        })

    def eval_expr(self, expr: Any) -> Any:
        """Evaluate an expression. If it's a literal int/list, return as-is."""
        if isinstance(expr, (int, float, list)):
            return expr
        if expr is None or expr == "":
            return None
        try:
            return self._eval.eval(str(expr))
        except Exception as e:
            raise ValueError(f"Failed to evaluate '{expr}': {e}") from e

    def truthy_when(self, when: Any) -> bool:
        """Evaluate a `when` clause.

        Raises WhenEvaluationError when the expression itself cannot be
        evaluated (missing key/attr in context). Returns False only when the
        expression was successfully evaluated to a falsy value. The caller
        records the error in the audit trail rather than silently skipping.
        """
        if when is None or when == "" or when is True:
            return True
        if when is False:
            return False
        if isinstance(when, str):
            s = when.strip().lower()
            if s in ("true", "yes", "1"):
                return True
            if s in ("false", "no", "0"):
                return False
        try:
            return bool(self.eval_expr(when))
        except Exception as e:
            raise WhenEvaluationError(str(e)) from e

    @staticmethod
    def planet_number(planet: str) -> int:
        return PLANET_NUMBER.get(planet, 0)

