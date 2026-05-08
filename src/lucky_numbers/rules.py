"""Rule expression evaluation and dispatch."""
from __future__ import annotations

from typing import Any

from simpleeval import EvalWithCompoundTypes

from .models import PLANET_NUMBER


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
        return bool(self.eval_expr(when))

    @staticmethod
    def planet_number(planet: str) -> int:
        return PLANET_NUMBER.get(planet, 0)

