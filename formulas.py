"""
Excel-like formula engine — safe by construction.
Parses expressions with Python's ast module and only allows:
  numbers, strings, column names, + - * / ( ), comparisons,
  and the functions: IF, TODAY, DAYS, ROUND, MIN, MAX, ABS.

Examples business owners can type:
  Profit         = revenue - cost
  Pending Amount = invoice_value - received_payment
  Lead Age       = DAYS(TODAY(), lead_date)
  Discounted     = IF(quantity > 10, price * 0.9, price)
"""
import ast
import operator
from datetime import date, datetime
import pandas as pd

_BIN_OPS = {ast.Add: operator.add, ast.Sub: operator.sub,
            ast.Mult: operator.mul, ast.Div: operator.truediv}
_CMP_OPS = {ast.Gt: operator.gt, ast.GtE: operator.ge, ast.Lt: operator.lt,
            ast.LtE: operator.le, ast.Eq: operator.eq, ast.NotEq: operator.ne}


def _to_date(v):
    if isinstance(v, date) and not isinstance(v, datetime):
        return v
    if isinstance(v, datetime):
        return v.date()
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return None
    try:
        return pd.to_datetime(str(v)).date()
    except Exception:
        return None


def _days(a, b):
    da, db = _to_date(a), _to_date(b)
    if da is None or db is None:
        return None
    return (da - db).days


_FUNCS = {
    "TODAY": lambda: date.today(),
    "DAYS": _days,
    "ROUND": lambda x, n=0: round(float(x), int(n)) if x is not None else None,
    "MIN": min, "MAX": max,
    "ABS": lambda x: abs(float(x)) if x is not None else None,
    "IF": lambda cond, a, b: a if cond else b,
}


class FormulaError(ValueError):
    pass


def _eval_node(node, row: dict):
    if isinstance(node, ast.Expression):
        return _eval_node(node.body, row)
    if isinstance(node, ast.Constant):
        if isinstance(node.value, (int, float, str, bool)) or node.value is None:
            return node.value
        raise FormulaError("Unsupported constant")
    if isinstance(node, ast.Name):
        key = node.id.lower()
        if key not in row:
            raise FormulaError(f"Unknown column: {node.id}")
        v = row[key]
        if v is None or (isinstance(v, float) and pd.isna(v)):
            return 0
        return v
    if isinstance(node, ast.BinOp) and type(node.op) in _BIN_OPS:
        left = _eval_node(node.left, row)
        right = _eval_node(node.right, row)
        try:
            return _BIN_OPS[type(node.op)](_num(left), _num(right))
        except ZeroDivisionError:
            return None
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
        return -_num(_eval_node(node.operand, row))
    if isinstance(node, ast.Compare) and len(node.ops) == 1:
        left = _eval_node(node.left, row)
        right = _eval_node(node.comparators[0], row)
        return _CMP_OPS[type(node.ops[0])](_num(left), _num(right))
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
        fname = node.func.id.upper()
        if fname not in _FUNCS:
            raise FormulaError(f"Unknown function: {fname}")
        args = [_eval_node(a, row) for a in node.args]
        return _FUNCS[fname](*args)
    raise FormulaError("Formula contains something that is not allowed")


def _num(v):
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return v
    if isinstance(v, (date, datetime)):
        return v
    if v is None or v == "":
        return 0
    try:
        return float(v)
    except (TypeError, ValueError):
        return v  # allow string comparisons


def evaluate(formula: str, row: dict):
    """Evaluate one formula against one row dict (keys lowercased)."""
    try:
        tree = ast.parse(formula, mode="eval")
        result = _eval_node(tree, {str(k).lower(): v for k, v in row.items()})
        if isinstance(result, date):
            return result.isoformat()
        if isinstance(result, bool):
            return int(result)
        if isinstance(result, float):
            return round(result, 2)
        return result
    except FormulaError:
        raise
    except Exception as e:
        raise FormulaError(str(e))


def validate(formula: str, columns: list[str]) -> str | None:
    """Return an error message, or None if the formula looks OK."""
    dummy = {c.lower(): 1 for c in columns}
    dummy_dates = {c.lower(): "2025-01-01" for c in columns}
    try:
        evaluate(formula, dummy)
        return None
    except FormulaError:
        try:
            evaluate(formula, dummy_dates)
            return None
        except FormulaError as e:
            return str(e)


def apply_formulas(df: pd.DataFrame, cols_meta: pd.DataFrame) -> pd.DataFrame:
    """Recompute all Formula columns for a table dataframe."""
    formula_cols = cols_meta[cols_meta["col_type"] == "Formula"]
    if formula_cols.empty or df.empty:
        return df
    df = df.copy()
    for _, fc in formula_cols.iterrows():
        if not fc["formula"]:
            continue
        results = []
        for _, r in df.iterrows():
            try:
                results.append(evaluate(fc["formula"], r.to_dict()))
            except Exception:
                results.append(None)
        df[fc["name"]] = results
    return df
