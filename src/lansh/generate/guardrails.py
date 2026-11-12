"""
Guardrails: what a migrated module must pass before it runs (plan §8.5).

1. **The syntax tree.** Only allowlisted imports (``pyspark``, ``datetime``, ``decimal``,
   ``math``, ``re``, ``functools``, ``typing``); no ``open``, ``eval``, ``exec``,
   ``__import__``, ``getattr`` and the like; no I/O or engine internals (``.read``,
   ``.write``, ``_jvm``, ``_jsc``, ``sparkContext``, ``.rdd``, ``.cache()``, ``.persist()``,
   ``spark.conf``), no UDFs and no dunder attributes. Jobs never do their own I/O, and these
   APIs don't run on Databricks serverless compute.
2. **SQL strings.** Text given to ``spark.sql``, ``F.expr``, ``selectExpr`` or a string
   ``where``/``filter`` must be a plain literal, is parsed with sqlglot (Spark dialect), and
   must not use ``TRANSFORM ... USING``, ``reflect``/``java_method``, file-path tables
   (``csv.`/path```), ``ADD JAR``, ``CREATE FUNCTION``, ``LOAD DATA`` or ``SET``. Every
   other string is scanned for the same, so nothing reaches Spark around the check.
3. **The literal check.** Every data literal (a number or string that isn't a column name,
   alias, table name, type or join kind) must appear in the legacy code, the contract, the
   job's parameters or a trap card's allowed literals. One found nowhere blocks H3 until a
   reviewer accepts it with a reason: a fixer can't hard-code its way to a MATCH.
4. **Lint.** ruff must find no syntax errors or undefined names. The job then runs in an
   isolated worker with a timeout (:mod:`lansh.generate.worker`).
"""

from __future__ import annotations

import ast
import functools
import re
import subprocess
import sys
from collections.abc import Iterable
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from pathlib import Path

from lansh.contracts import LiteralFinding

ALLOWED_IMPORTS = frozenset(
    {"pyspark", "datetime", "decimal", "math", "re", "functools", "typing", "__future__"}
)
BANNED_CALLS = frozenset(
    {
        "open",
        "eval",
        "exec",
        "compile",
        "__import__",
        "getattr",
        "setattr",
        "delattr",
        "globals",
        "locals",
        "vars",
        "input",
        "breakpoint",
        "exit",
        "quit",
        "help",
        "memoryview",
    }
)
BANNED_NAMES = frozenset({"os", "sys", "subprocess", "socket", "shutil", "builtins", "importlib"})
BANNED_ATTRIBUTES = frozenset(
    {
        "read",
        "readStream",
        "write",
        "writeStream",
        "writeTo",
        "saveAsTable",
        "insertInto",
        "_jvm",
        "_jsc",
        "_jdf",
        "_jsparkSession",
        "_sc",
        "sparkContext",
        "rdd",
        "cache",
        "persist",
        "checkpoint",
        "conf",
        "udf",
        "pandas_udf",
        "udtf",
        "mapInPandas",
        "mapInArrow",
        "applyInPandas",
        "foreach",
        "foreachPartition",
        "registerJavaFunction",
        "addArtifact",
        "addArtifacts",
        "copyFromLocalToFs",
    }
)
# calls whose (first) string argument is Spark SQL text
SQL_TEXT_CALLS = frozenset({"sql", "expr", "selectExpr", "where", "filter"})
# file formats that Spark SQL accepts as table prefixes, as in csv.`/path`
_FILE_FORMATS = "csv|parquet|json|orc|text|delta|avro|binaryfile|jdbc|xml|hive"
_SQL_DANGER = [
    (
        re.compile(r"\btransform\s*\(.*?\)\s*using\b", re.I | re.S),
        "TRANSFORM ... USING runs scripts",
    ),
    (
        re.compile(r"\b(try_)?reflect\s*\(|\bjava_method\s*\(", re.I),
        "reflect/java_method calls Java",
    ),
    (re.compile(rf"\b({_FILE_FORMATS})\s*\.\s*`", re.I), "file-path table reads files"),
    (re.compile(r"\badd\s+(jar|file|archive)s?\b", re.I), "ADD JAR/FILE"),
    (
        re.compile(r"\bcreate\s+(or\s+replace\s+)?(temporary\s+)?function\b", re.I),
        "CREATE FUNCTION",
    ),
    (re.compile(r"\bload\s+data\b", re.I), "LOAD DATA"),
    (re.compile(r"^\s*(re)?set\s+[\w.]+\s*(=|$)", re.I | re.M), "SET changes the session"),
    (re.compile(r"\b(dfs|hdfs|s3a?|file|abfss?|wasbs?|gs)://", re.I), "a filesystem URL"),
]
# strings that are Spark vocabulary, never data
SPARK_VOCABULARY = frozenset(
    {
        "inner", "left", "right", "outer", "full", "fullouter", "full_outer", "leftouter",
        "left_outer", "rightouter", "right_outer", "leftsemi", "left_semi", "semi", "leftanti",
        "left_anti", "anti", "cross",
        "int", "integer", "bigint", "long", "smallint", "short", "tinyint", "byte", "double",
        "float", "string", "boolean", "date", "timestamp", "timestamp_ntz", "binary", "void",
        "first", "last", "any", "all", "asc", "desc",
    }
)  # fmt: skip
_TYPE_PATTERN = re.compile(
    r"^(decimal|numeric)\s*\(\s*[0-9]+\s*,\s*[0-9]+\s*\)$|^(array|map|struct)<.*>$", re.I
)
_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
# a decimal type in a type string or in SQL text, for the precisions and scales it declares
_DECIMAL_TYPE = re.compile(
    r"\b(?:decimal|numeric)\s*\(\s*([0-9]{1,2})\s*,\s*([0-9]{1,2})\s*\)", re.I
)
# Spark calls whose integer arguments are a scale or precision
_SCALE_CALLS = frozenset({"round", "bround", "floor", "ceil", "format_number", "DecimalType"})
# calls whose string arguments name columns, aliases or tables, never data
_NAMING_CALLS = frozenset(
    {
        "col", "column", "alias", "name", "withColumn", "withColumnRenamed", "withColumns",
        "withColumnsRenamed", "select", "groupBy", "groupby", "orderBy", "sort",
        "sortWithinPartitions", "partitionBy", "drop", "dropDuplicates", "drop_duplicates",
        "asc", "desc", "asc_nulls_first", "asc_nulls_last", "desc_nulls_first",
        "desc_nulls_last", "sum", "min", "max", "avg", "mean", "count", "countDistinct",
        "count_distinct", "first", "last", "collect_list", "collect_set", "getField",
        "getItem", "pivot", "agg", "createOrReplaceTempView", "struct", "array", "isNotNull",
        "isNull", "coalesce", "greatest", "least", "concat", "concat_ws", "upper", "lower",
        "rtrim", "ltrim", "trim", "length", "year", "month", "dayofmonth", "datediff",
        "months_between", "add_months", "last_day", "to_date", "unix_timestamp", "abs",
        "floor", "ceil", "round", "bround", "date_add", "date_sub", "date_format",
        "substring", "rpad", "lpad", "row_number", "rank", "dense_rank", "lag", "lead",
        "sum_distinct", "approx_count_distinct", "unpivot", "melt", "join", "union",
        "unionByName", "fillna", "na", "replace", "explode", "posexplode", "split",
        "regexp_extract", "regexp_replace", "isin", "when", "otherwise", "lit", "expr",
        "selectExpr", "where", "filter",
    }
)  # fmt: skip
# of the calls above, those whose string arguments are names (the rest may hold data)
_NAME_ONLY_CALLS = frozenset(
    {
        "col", "column", "alias", "name", "withColumnRenamed", "withColumnsRenamed", "select",
        "groupBy", "groupby", "orderBy", "sort", "sortWithinPartitions", "partitionBy", "drop",
        "dropDuplicates", "drop_duplicates", "asc", "desc", "asc_nulls_first",
        "asc_nulls_last", "desc_nulls_first", "desc_nulls_last", "getField",
        "createOrReplaceTempView", "countDistinct", "count_distinct", "collect_list",
        "collect_set", "struct", "unpivot", "melt",
    }
)  # fmt: skip
# of the calls above, those whose first string argument is a name and the rest data
_FIRST_IS_NAME = frozenset(
    {"withColumn", "sum", "min", "max", "avg", "mean", "count", "first", "last", "pivot",
     "agg", "isNotNull", "isNull", "upper", "lower", "rtrim", "ltrim", "trim", "length",
     "year", "month", "dayofmonth", "abs", "floor", "ceil", "datediff", "add_months",
     "last_day", "to_date", "date_add", "date_sub", "row_number", "rank", "dense_rank", "lag",
     "lead", "explode", "posexplode", "fillna"}
)  # fmt: skip
_ALWAYS_ALLOWED_NUMBERS = frozenset({Decimal(0), Decimal(1), Decimal(-1)})


@dataclass
class GuardrailReport:
    """
    What the guardrails found in one module.

    Attributes:
        violations: Refusals from the syntax tree, the SQL scan or lint; any one stops the run.
        literals: Every data literal with its provenance; one with provenance ``none`` blocks
            H3 until a reviewer accepts it.
        sql_strings: The SQL texts found and parsed.
    """

    violations: list[str] = field(default_factory=list)
    literals: list[LiteralFinding] = field(default_factory=list)
    sql_strings: list[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        """
        Whether the module may run: no violations (literals are judged at H3, not here).
        """
        return not self.violations

    @property
    def blocking_literals(self) -> list[LiteralFinding]:
        """
        The literals found nowhere else that nobody has accepted.
        """
        return [lit for lit in self.literals if lit.blocks_h3]


### 1. The syntax tree


def _last_name(node: ast.AST) -> str:
    """
    Give the last part of a dotted name: ``re`` for ``re``, ``F`` for ``pyspark.sql.F``.
    """
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return ""


def _call_name(node: ast.Call) -> str:
    """
    Give the name a call is made through: ``f`` for ``f()`` and ``x.f()``.
    """
    if isinstance(node.func, ast.Name):
        return node.func.id
    if isinstance(node.func, ast.Attribute):
        return node.func.attr
    return ""


def check_tree(tree: ast.AST) -> list[str]:
    """
    Refuse imports, calls, names and attributes outside the allowlist.

    Args:
        tree: The module's syntax tree.

    Returns:
        One message per refusal, with its line.
    """
    found = []
    for node in ast.walk(tree):
        line = getattr(node, "lineno", 0)
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.split(".")[0] not in ALLOWED_IMPORTS:
                    found.append(f"line {line}: import {alias.name} is not allowed")
        elif isinstance(node, ast.ImportFrom):
            root = (node.module or "").split(".")[0]
            if node.level or root not in ALLOWED_IMPORTS:
                found.append(f"line {line}: from {node.module or '.'} import is not allowed")
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            if node.func.id in BANNED_CALLS:
                found.append(f"line {line}: {node.func.id}() is not allowed")
        elif isinstance(node, ast.Name) and node.id in BANNED_NAMES | BANNED_CALLS:
            found.append(f"line {line}: the name {node.id} is not allowed")
        elif isinstance(node, ast.Attribute):
            if node.attr in BANNED_ATTRIBUTES:
                found.append(f"line {line}: .{node.attr} is not allowed (jobs do no I/O)")
            elif node.attr.startswith("__"):
                found.append(f"line {line}: dunder attribute .{node.attr} is not allowed")
        elif isinstance(node, (ast.Global, ast.Nonlocal)):
            found.append(f"line {line}: global and nonlocal are not allowed")
    if not any(
        isinstance(n, ast.FunctionDef) and n.name == "run" for n in getattr(tree, "body", [])
    ):
        found.append("the module has no run(spark, inputs, params) function")
    return found


### 2. SQL strings


def scan_sql_text(text: str) -> list[str]:
    """
    Look for the dangerous Spark SQL constructs in one piece of text.

    Args:
        text: SQL text, or any string literal.

    Returns:
        What it found, one phrase each.
    """
    return [why for pattern, why in _SQL_DANGER if pattern.search(text)]


def parse_sql(text: str) -> list[str]:
    """
    Parse Spark SQL with sqlglot and refuse anything but queries and expressions.

    Args:
        text: The SQL text of a ``spark.sql``, ``F.expr``, ``selectExpr`` or string filter.

    Returns:
        Problems: a parse failure, a statement that isn't a query, or a forbidden function.
    """
    import sqlglot
    from sqlglot import exp

    try:
        trees = sqlglot.parse(text, read="spark")
    except Exception as exc:  # any sqlglot error means we can't vouch for the text
        try:
            sqlglot.parse_one(f"SELECT {text}", read="spark")
            return []
        except Exception:
            return [f"sqlglot can't parse it: {str(exc).splitlines()[0][:120]}"]
    problems = []
    for tree in trees:
        if tree is None:
            continue
        if isinstance(tree, exp.Command | exp.Set | exp.Create | exp.Insert | exp.Drop):
            problems.append(f"{type(tree).__name__.upper()} statements are not allowed")
        for node in tree.walk():
            if isinstance(node, exp.Anonymous) and node.name.lower() in {
                "reflect",
                "java_method",
                "try_reflect",
            }:
                problems.append(f"{node.name}() calls Java")
    return problems


def check_strings(tree: ast.AST) -> tuple[list[str], list[str]]:
    """
    Scan every string literal, and parse the ones that are SQL text.

    Args:
        tree: The module's syntax tree.

    Returns:
        Refusals, and the SQL texts parsed.
    """
    found, sql = [], []
    sql_args: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and _call_name(node) in SQL_TEXT_CALLS and node.args:
            first = node.args[0]
            name = _call_name(node)
            if isinstance(first, ast.JoinedStr):
                found.append(f"line {node.lineno}: {name}() needs a plain string, not an f-string")
            elif isinstance(first, ast.Constant) and isinstance(first.value, str):
                sql_args.add(id(first))
                if name in {"sql", "expr", "selectExpr"} or not _IDENTIFIER.match(first.value):
                    sql.append(first.value)
                    found += [f"line {node.lineno}: {name}(): {p}" for p in parse_sql(first.value)]
            elif name == "sql" and not isinstance(first, ast.Constant):
                found.append(f"line {node.lineno}: spark.sql() needs a plain string literal")
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            for why in scan_sql_text(node.value):
                found.append(f"line {node.lineno}: a string holds {why}")
    return found, sql


### 3. The literal check


def _numbers(text: str) -> set[Decimal]:
    """
    Collect the numeric values written in a text, such as legacy code.
    """
    out = set()
    for token in re.findall(r"(?<![\w.])-?[0-9]+(?:\.[0-9]+)?(?:[eE][-+]?[0-9]+)?(?![\w])", text):
        try:
            out.add(Decimal(token))
            out.add(abs(Decimal(token)))
        except InvalidOperation:
            continue
    return out


def _sql_literals(text: str) -> list[str | Decimal]:
    """
    Pull the string and number literals out of one piece of Spark SQL.
    """
    import sqlglot
    from sqlglot import exp

    try:
        trees = sqlglot.parse(text, read="spark")
    except Exception:
        try:
            trees = [sqlglot.parse_one(f"SELECT {text}", read="spark")]
        except Exception:
            return []
    out: list[str | Decimal] = []
    for tree in trees:
        if tree is None:
            continue
        for node in tree.walk():
            if isinstance(node, exp.Literal):
                if node.find_ancestor(exp.DataType):
                    continue  # DECIMAL(38,10)'s precision and scale are a type's, not data
                if node.is_string:
                    out.append(node.this)
                else:
                    try:
                        out.append(Decimal(node.this))
                    except InvalidOperation:
                        continue
    return out


@dataclass(frozen=True)
class Provenance:
    """
    Where a literal may legitimately come from: the evidence the literal check searches.

    Attributes:
        legacy_text: The legacy code.
        names: Column, table and parameter names (contract, inputs, outputs, params).
        params: The job's parameter values.
        allowed: The trap cards' allowed literals.
    """

    legacy_text: str
    names: frozenset[str]
    params: frozenset[str]
    allowed: frozenset[str]

    def of(self, value: str | Decimal) -> str:
        """
        Say where a literal comes from: legacy, contract, params, trap_card or none.
        """
        if isinstance(value, Decimal):
            if value in _ALWAYS_ALLOWED_NUMBERS or value in _numbers(self.legacy_text):
                return "legacy"
            if str(value) in self.allowed or format(value.normalize(), "f") in self.allowed:
                return "trap_card"
            return "none"
        if value.casefold() in self.names:
            return "contract"
        if value in self.params:
            return "params"
        if value in self.allowed:
            return "trap_card"
        folded = value.casefold()
        if value == "" or folded in _legacy_tokens(self.legacy_text):
            return "legacy"
        # a longer string may appear inside a bigger one ('MEDI' in 'MEDIUM'); a short one
        # appears somewhere by chance, so it must be a whole literal or word of the code
        if len(value) > 3 and folded in self.legacy_text.casefold():
            return "legacy"
        if _TYPE_PATTERN.match(value) or value.casefold() in SPARK_VOCABULARY:
            return "contract"
        if self._derived(value):
            return "trap_card"
        return "none"

    def _derived(self, value: str) -> bool:
        """
        Tell whether a literal is legacy text joined only by a trap card's syntax tokens.

        A T-SQL ``LIKE '[0-9][0-9]%-[A-Z]%'`` becomes the regex ``^[0-9][0-9].*-[A-Z]`` (card
        TSQL-14): take the card's tokens (``^``, ``.*``, flags) out, and every piece left must
        be in the legacy code. A hard-coded value (``^300035$``) leaves a piece that isn't.
        """
        tokens = sorted(
            (
                a
                for a in self.allowed
                if a and (not re.search(r"[A-Za-z0-9]", a) or re.fullmatch(r"\(\?[a-z]+\)", a))
            ),
            key=len,
            reverse=True,
        )
        pieces = [value]
        for token in tokens:
            pieces = [part for piece in pieces for part in piece.split(token)]
        pieces = [p for p in pieces if p]
        if not pieces or pieces == [value]:
            return False
        legacy = self.legacy_text.casefold()
        return all(p.casefold() in legacy for p in pieces) and sum(map(len, pieces)) >= 2


def _legacy_tokens(text: str) -> frozenset[str]:
    """
    Collect the quoted strings and the words of legacy code, folded to lower case.
    """
    return _tokens_cached(text)


@functools.cache
def _tokens_cached(text: str) -> frozenset[str]:
    """
    Collect quoted strings and words, once per text.
    """
    quoted = re.findall(r"'((?:[^']|'')*)'|\"([^\"]*)\"", text)
    strings = {(a or b).replace("''", "'").casefold() for a, b in quoted}
    words = {w.casefold() for w in re.findall(r"[^\s,;()'\"=<>+*/|]+", text)}
    return frozenset(strings | words)


def _direct_strings(node: ast.AST) -> list[ast.Constant]:
    """
    Give the string constants a call argument is, or lists directly: not those nested in calls.

    A name built from parts, ``"dev_" + str(n)`` or ``f"d{n}"``, counts: its string parts are
    part of the name. Strings inside a nested call are not, since that call may hold data.
    """
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return [node]
    if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
        return [c for e in node.elts for c in _direct_strings(e)]
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        return _direct_strings(node.left) + _direct_strings(node.right)
    if isinstance(node, ast.JoinedStr):
        return [v for v in node.values if isinstance(v, ast.Constant) and isinstance(v.value, str)]
    return []


def _naming_positions(tree: ast.AST) -> set[int]:
    """
    Find the string literals that name things (columns, aliases, tables, params), not data.

    Only a call's direct arguments (or the strings of a list argument) count as names, so a
    literal nested in an expression inside ``select(...)`` is still checked as data.
    """
    names: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Subscript) and isinstance(node.slice, ast.Constant):
            names.add(id(node.slice))  # inputs["stg.claims"], params["AsOfDate"], row["x"]
        elif isinstance(node, ast.Dict):
            names.update(id(k) for k in node.keys if isinstance(k, ast.Constant))
        elif isinstance(node, ast.keyword) and node.arg in {"on", "how", "subset", "cols"}:
            names.update(id(c) for c in _direct_strings(node.value))
        elif isinstance(node, ast.Call):
            name = _call_name(node)
            args = list(node.args)
            if name in _NAME_ONLY_CALLS:
                for arg in args:
                    names.update(id(c) for c in _direct_strings(arg))
            elif name in _FIRST_IS_NAME and args:
                names.update(id(c) for c in _direct_strings(args[0]))
            elif name == "join" and len(args) >= 2:
                for arg in args[1:]:
                    names.update(id(c) for c in _direct_strings(arg))
            elif name in {"cast", "astype"} and args:
                names.update(id(c) for c in _direct_strings(args[0]))
            elif (
                isinstance(node.func, ast.Attribute)
                and _last_name(node.func.value) == "re"
                and args
            ):
                # a pattern given to Python's re module parses the job's own text (its
                # parameters), never data; Spark's rlike and regexp_* patterns stay checked
                names.update(id(c) for c in _direct_strings(args[0]))
    return names


def _type_constants(tree: ast.AST) -> set[int]:
    """
    Find the integer literals that are a decimal's precision or scale, not data.

    One counts when the module declares that precision or scale in a decimal type (a type
    string such as ``"decimal(36,13)"``, a ``DecimalType(36, 13)`` or a SQL ``CAST``) and
    passes it straight to a call that takes a scale: ``F.round``, ``F.floor`` and the like, or
    one of the module's own functions. That is how a translator follows T-SQL's type rules
    (card TSQL-07): ``int / int`` on ``DECIMAL(25,2)`` has scale 13, which the legacy code never
    writes. Only 0 to 38 can be either, so a hard-coded key or amount still needs provenance.
    """
    declared: set[int] = set()
    functions = {
        n.name for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    calls: list[ast.Call] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            for precision, scale in _DECIMAL_TYPE.findall(node.value):
                declared |= {int(precision), int(scale)}
        elif isinstance(node, ast.Call):
            calls.append(node)
            if _call_name(node) == "DecimalType":
                declared |= {
                    a.value for a in node.args if isinstance(a, ast.Constant) and _is_int(a.value)
                }
    return {
        id(a)
        for call in calls
        if _call_name(call) in _SCALE_CALLS | functions
        for a in call.args
        if isinstance(a, ast.Constant) and _is_int(a.value) and 0 <= a.value <= 38
        and a.value in declared
    }  # fmt: skip


def _call_name(call: ast.Call) -> str:
    """
    Give a call's function name: ``round`` for ``F.round(...)``, ``_trunc`` for ``_trunc(...)``.
    """
    if isinstance(call.func, ast.Attribute):
        return call.func.attr
    return call.func.id if isinstance(call.func, ast.Name) else ""


def _is_int(value: object) -> bool:
    """
    Tell whether a constant is an integer (booleans aren't).
    """
    return isinstance(value, int) and not isinstance(value, bool)


def _defined_names(tree: ast.AST) -> set[str]:
    """
    Collect the column names the module defines itself: aliases and new or renamed columns.

    A string equal to one of them, used later to refer to that column, is a name, not data.
    Only identifiers count, so a value can't be passed off as a name.
    """
    out: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name, args = _call_name(node), node.args
        picked: list[ast.AST] = []
        if name in {"alias", "withColumn", "createOrReplaceTempView", "name"} and args:
            picked = [args[0]]
        elif name == "withColumnRenamed" and len(args) >= 2:
            picked = [args[1]]
        elif (
            name in {"withColumns", "withColumnsRenamed"} and args and isinstance(args[0], ast.Dict)
        ):
            picked = (
                [*args[0].keys, *args[0].values]
                if name == "withColumnsRenamed"
                else list(args[0].keys)
            )
        for node_ in picked:
            is_text = isinstance(node_, ast.Constant) and isinstance(node_.value, str)
            if is_text and _IDENTIFIER.match(node_.value):
                out.add(node_.value.casefold())
    return out


def check_literals(
    tree: ast.AST, provenance: Provenance, sql: Iterable[str]
) -> list[LiteralFinding]:
    """
    Find every data literal in the module and where else it appears.

    Docstrings, names (see :func:`_naming_positions`), ``None``, booleans and the numbers 0, 1
    and -1 are not data, nor are a decimal's precision and scale (see :func:`_type_constants`).
    Literals inside SQL text are checked one by one, except a type's parameters.

    Args:
        tree: The module's syntax tree.
        provenance: The evidence to search.
        sql: The SQL texts the string check parsed.

    Returns:
        One finding per data literal, in line order.
    """
    docstrings = {
        id(node.body[0].value)
        for node in ast.walk(tree)
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
        and node.body
        and isinstance(node.body[0], ast.Expr)
        and isinstance(node.body[0].value, ast.Constant)
    }
    naming = _naming_positions(tree)
    # an exception's or an assertion's message never reaches an output, so it isn't data
    messages = {
        id(sub)
        for node in ast.walk(tree)
        if isinstance(node, (ast.Raise, ast.Assert))
        for part in ([node.exc] if isinstance(node, ast.Raise) else [node.msg])
        if part is not None
        for sub in ast.walk(part)
        if isinstance(sub, ast.Constant)
    }
    naming |= messages
    defined = _defined_names(tree)
    type_constants = _type_constants(tree)
    sql_texts = set(sql)
    out: list[LiteralFinding] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Constant) or id(node) in docstrings or id(node) in naming:
            continue
        value = node.value
        if value is None or isinstance(value, bool):
            continue
        if isinstance(value, str) and value in sql_texts:
            for lit in _sql_literals(value):
                out.append(
                    LiteralFinding(value=str(lit), line=node.lineno, provenance=provenance.of(lit))
                )
            continue
        if isinstance(value, (int, float)):
            number = Decimal(repr(value)) if isinstance(value, float) else Decimal(value)
            where = provenance.of(number)
            if where == "none" and id(node) in type_constants:
                where = "trap_card"  # a precision or scale by T-SQL's type rules (TSQL-07)
            out.append(LiteralFinding(value=repr(value), line=node.lineno, provenance=where))
        elif isinstance(value, str):
            is_alias = bool(_IDENTIFIER.match(value)) and value.casefold() in defined
            where = "contract" if is_alias else provenance.of(value)
            out.append(LiteralFinding(value=value, line=node.lineno, provenance=where))
    return sorted(out, key=lambda f: (f.line, f.value))


### 4. Lint, and the whole check


def lint(path: Path) -> list[str]:
    """
    Run ruff for syntax errors and undefined names only.

    Args:
        path: The module file.

    Returns:
        One message per problem.
    """
    proc = subprocess.run(
        [sys.executable, "-m", "ruff", "check", "--no-cache", "--select", "E9,F63,F7,F82",
         "--output-format", "concise", str(path)],
        capture_output=True,
        text=True,
        check=False,
    )  # fmt: skip
    if proc.returncode == 0:
        return []
    return [
        line.split(":", 1)[-1].strip()
        for line in proc.stdout.splitlines()
        if line.strip() and not line.startswith("Found")
    ] or [proc.stderr.strip() or "ruff failed"]


def check_module(path: Path, provenance: Provenance) -> GuardrailReport:
    """
    Run every guardrail on one migrated module.

    Args:
        path: The module file.
        provenance: The evidence the literal check searches.

    Returns:
        The report. ``passed`` says whether it may run; ``blocking_literals`` what H3 needs.
    """
    source = path.read_text(encoding="utf-8")
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        return GuardrailReport(violations=[f"line {exc.lineno}: syntax error: {exc.msg}"])
    report = GuardrailReport()
    report.violations += check_tree(tree)
    found, sql = check_strings(tree)
    report.violations += found
    report.sql_strings = sql
    report.violations += lint(path)
    report.literals = check_literals(tree, provenance, sql)
    return report


def provenance_for(
    legacy_text: str,
    names: Iterable[str],
    params: dict[str, object],
    allowed: Iterable[str],
) -> Provenance:
    """
    Gather the evidence the literal check searches for one job.

    Args:
        legacy_text: The legacy code.
        names: Every column and table name of the job's inputs, outputs and contract.
        params: The job's parameters (names and values).
        allowed: The trap cards' allowed literals.

    Returns:
        The provenance to check literals against.
    """
    folded = {n.casefold() for n in names} | {k.casefold() for k in params}
    folded |= {n.split(".", 1)[-1].casefold() for n in names if "." in n}
    return Provenance(
        legacy_text=legacy_text,
        names=frozenset(folded),
        params=frozenset(str(v) for v in params.values()),
        allowed=frozenset(allowed),
    )
