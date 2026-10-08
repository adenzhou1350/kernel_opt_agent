"""Offline import timing checks; never install or execute candidate packages."""

import ast
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import kimi_scout_delivery_source as source
from kimi_scout_delivery import choose_profile


def imports(code, *, allow=True):
    return source._import_notes(
        ast.parse(code, feature_version=(3, 10)), "example.py", allow
    )


class DefinitionImportsTests(unittest.TestCase):
    def test_profile_selection_uses_definition_time_torch_import(self):
        for expression in (
            "def f(x=__import__('torch')): pass\n",
            "@__import__('torch').no_grad()\ndef f(): pass\n",
        ):
            with self.subTest(expression=expression):
                _, dependencies, required = imports(expression)
                profile = choose_profile(
                    {
                        "dependency_modules": dependencies,
                        "required_dependency_modules": required,
                    }
                )
                self.assertEqual(profile, "torch-cpu")
        _, dependencies, required = imports("def f():\n    import torch\n")
        self.assertEqual(
            choose_profile(
                {
                    "dependency_modules": dependencies,
                    "required_dependency_modules": required,
                }
            ),
            "stdlib",
        )

    def test_defaults_and_decorators_are_required_for_sync_and_async(self):
        for prefix in ("def", "async def"):
            with self.subTest(prefix=prefix):
                code = (
                    "import importlib\n"
                    "@importlib.import_module('decorator_dep').decorate\n"
                    f"{prefix} f(x=__import__('default_dep'), "
                    "*, y=importlib.import_module('kw_dep')):\n"
                    "    import body_dep\n"
                )
                _, dependencies, required = imports(code)
                self.assertEqual(
                    dependencies, ["body_dep", "decorator_dep", "default_dep", "kw_dep"]
                )
                self.assertEqual(required, ["decorator_dep", "default_dep", "kw_dep"])

    def test_definition_import_is_rejected_before_stdlib_execution(self):
        code = "def f(x=__import__('unavailable_default_dep')): pass\n"
        with self.assertRaisesRegex(
            source.UnsupportedEnvironment, "unavailable_default_dep"
        ):
            imports(code, allow=False)

    def test_annotations_follow_the_future_annotations_setting(self):
        code = (
            "def f(x: __import__('arg_dep'), /, "
            "*args: __import__('vararg_dep'), "
            "y: __import__('kwarg_dep')=__import__('default_dep'), "
            "**kwargs: __import__('kwargs_dep')) -> __import__('return_dep'):\n"
            "    pass\n"
        )
        names = [
            "arg_dep",
            "default_dep",
            "kwarg_dep",
            "kwargs_dep",
            "return_dep",
            "vararg_dep",
        ]
        self.assertEqual(imports(code)[1:], (names, names))
        self.assertEqual(
            imports("from __future__ import annotations\n" + code)[1:],
            (names, ["default_dep"]),
        )

    def test_nested_definition_keeps_its_enclosing_deferred_context(self):
        code = (
            "def outer():\n"
            "    @__import__('decorator_dep').decorate\n"
            "    def inner(x=__import__('default_dep')) -> __import__('return_dep'):\n"
            "        import body_dep\n"
            "    return inner\n"
        )
        self.assertEqual(
            imports(code)[1:],
            (["body_dep", "decorator_dep", "default_dep", "return_dep"], []),
        )

    def test_lambda_body_is_deferred_but_its_defaults_are_not(self):
        code = (
            "def f(callback=lambda: __import__('callback_dep'), "
            "other=lambda x=__import__('lambda_default_dep'): x): pass\n"
        )
        self.assertEqual(
            imports(code)[1:],
            (["callback_dep", "lambda_default_dep"], ["lambda_default_dep"]),
        )

    def test_optional_guard_still_defers_definition_time_imports(self):
        code = (
            "try:\n"
            "    @__import__('decorator_dep').decorate\n"
            "    def f(x=__import__('default_dep')): pass\n"
            "except ImportError:\n"
            "    pass\n"
        )
        self.assertEqual(imports(code)[1:], (["decorator_dep", "default_dep"], []))

    def test_native_python_imports_default_before_function_call(self):
        name = "__scout_uninstalled_default_probe_9dc58b"
        with self.assertRaisesRegex(ModuleNotFoundError, name):
            exec(f"def f(x=__import__({name!r})): pass", {})
        namespace = {}
        exec(f"def f():\n    return __import__({name!r})", namespace)
        with self.assertRaisesRegex(ModuleNotFoundError, name):
            namespace["f"]()

    def test_native_future_annotation_does_not_import_at_definition(self):
        name = "__scout_uninstalled_annotation_probe_9dc58b"
        with self.assertRaisesRegex(ModuleNotFoundError, name):
            exec(f"def f(x: __import__({name!r})): pass", {})
        namespace = {}
        exec(
            f"from __future__ import annotations\ndef f(x: __import__({name!r})): pass",
            namespace,
        )
        self.assertIn(name, namespace["f"].__annotations__["x"])


if __name__ == "__main__":
    unittest.main()
