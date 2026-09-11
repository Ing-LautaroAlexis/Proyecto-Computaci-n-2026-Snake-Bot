"""No-dependency cyclomatic-complexity gate for the delivered Python sources.

The calculation is intentionally McCabe/radon-like and uses the common
A=1..5 threshold.  The package also includes a command for running the official
Radon tool when it is installed on the grading machine.
"""
from __future__ import annotations

import ast
import bisect
import json
import sys
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent
ROOT = TESTS_DIR.parent / "src" / "bot_final"
EXCLUDED = {"REFERENCE_DO_NOT_DEPLOY.py"}
LIMITS = [5, 10, 20, 30, 40]
GRADES = "ABCDEF"


def grade(value):
    return GRADES[bisect.bisect_left(LIMITS, value)]


class Complexity(ast.NodeVisitor):
    def __init__(self):
        self.value = 1

    def visit_If(self, node):
        self.value += 1
        self.generic_visit(node)

    def visit_For(self, node):
        self.value += 1
        self.generic_visit(node)

    def visit_AsyncFor(self, node):
        self.value += 1
        self.generic_visit(node)

    def visit_While(self, node):
        self.value += 1
        self.generic_visit(node)

    def visit_Try(self, node):
        self.value += len(node.handlers)
        self.generic_visit(node)

    def visit_IfExp(self, node):
        self.value += 1
        self.generic_visit(node)

    def visit_BoolOp(self, node):
        self.value += max(0, len(node.values) - 1)
        self.generic_visit(node)

    def visit_comprehension(self, node):
        self.value += 1 + len(node.ifs)
        self.generic_visit(node)

    def visit_With(self, node):
        self.value += 1
        self.generic_visit(node)

    def visit_AsyncWith(self, node):
        self.value += 1
        self.generic_visit(node)

    def visit_Assert(self, node):
        self.value += 1
        self.generic_visit(node)

    def visit_Match(self, node):
        self.value += max(0, len(node.cases) - 1)
        self.generic_visit(node)


def function_complexity(node):
    visitor = Complexity()
    for statement in node.body:
        visitor.visit(statement)
    return visitor.value


def function_record(node):
    value = function_complexity(node)
    return {
        "name": node.name,
        "line": node.lineno,
        "complexity": value,
        "grade": grade(value),
    }


def function_nodes(tree):
    return [
        node for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    ]


def analyze_file(path):
    source = path.read_text(encoding="utf-8")
    functions = [function_record(node) for node in function_nodes(ast.parse(source))]
    average = sum(item["complexity"] for item in functions) / max(1, len(functions))
    non_a = [item for item in functions if item["grade"] != "A"]
    return {
        "file": path.name,
        "physical_lines": len(source.splitlines()),
        "functions": len(functions),
        "average_complexity": average,
        "average_grade": grade(round(average)),
        "all_functions_A": not non_a,
        "non_A": non_a,
    }


def delivered_python_files():
    return sorted(
        path for path in ROOT.glob("*.py")
        if path.name not in EXCLUDED
    )


def project_report():
    reports = [analyze_file(path) for path in delivered_python_files()]
    return {
        "all_files_A": all(report["all_functions_A"] for report in reports),
        "files": reports,
    }


def main():
    report = project_report()
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0 if report["all_files_A"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
