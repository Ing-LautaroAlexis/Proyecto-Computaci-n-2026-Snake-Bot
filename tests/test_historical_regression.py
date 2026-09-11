"""Run the historical V6/V7.5 correctness audit against the refactored engine.

The test body is extracted from the frozen pre-refactor snapshot, then compiled
with the current bot module globals. This keeps the regression oracle independent
from the refactored implementations while exercising the current code.
"""
from __future__ import annotations
import ast
import importlib.util
import sys
import types
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent
ROOT = TESTS_DIR.parent / "src" / "bot_final"
BOT = ROOT / 'botv8.0_v5.py'
REFERENCE = TESTS_DIR / 'REFERENCE_DO_NOT_DEPLOY.snapshot'
for name in ('pygame', 'websockets'):
    sys.modules.setdefault(name, types.ModuleType(name))

spec = importlib.util.spec_from_file_location('botv76_hist', BOT)
bot = importlib.util.module_from_spec(spec)
sys.modules['botv76_hist'] = bot
spec.loader.exec_module(bot)

source = REFERENCE.read_text(encoding='utf-8')
tree = ast.parse(source)
run_tests_node = next(
    node for node in tree.body
    if isinstance(node, ast.FunctionDef) and node.name == 'run_tests'
)
module = ast.Module(body=[run_tests_node], type_ignores=[])
ast.fix_missing_locations(module)
exec(compile(module, str(REFERENCE), 'exec'), bot.__dict__)
bot.run_tests()
