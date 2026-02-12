from __future__ import annotations

import json
import unittest

from svg_anim_demo.ui.gradio_app import OperatorController, create_app


class TestPhase7UIOperator(unittest.TestCase):
    def setUp(self) -> None:
        self.controller = OperatorController()

    def test_controller_layer_inspector_and_state_view(self):
        layers_json, next_cursor = self.controller.layer_inspector(limit=2, cursor="", text_filter="")
        layers = json.loads(layers_json)
        self.assertGreaterEqual(len(layers), 1)
        self.assertTrue(isinstance(next_cursor, str))

        state = json.loads(self.controller.state_view("title"))
        self.assertTrue(state["ok"])
        self.assertIn("title", state["state"]["layers"])

    def test_manual_controls_and_diagnostics(self):
        apply_result = json.loads(self.controller.apply_transform("title", 5, 6, 1.2, 10, 0.8, 3))
        self.assertTrue(apply_result["ok"])

        preset = json.loads(self.controller.run_preset("title", "slide_in_left"))
        self.assertTrue(preset["ok"])

        undo = json.loads(self.controller.undo())
        redo = json.loads(self.controller.redo())
        self.assertIn("ok", undo)
        self.assertIn("ok", redo)

        _ = self.controller.tool_runner("get_layer_state", "{}")
        diagnostics = json.loads(self.controller.diagnostics())
        self.assertGreaterEqual(diagnostics["traceCount"], 1)
        self.assertIn("runtime", diagnostics)

    def test_create_app_returns_interactive_object_or_fallback(self):
        app = create_app()
        # In gradio-enabled env this is a Blocks object; otherwise dict fallback.
        is_fallback = isinstance(app, dict) and app.get("type") == "operator-controller"
        has_launch = hasattr(app, "launch")
        self.assertTrue(is_fallback or has_launch)


if __name__ == "__main__":
    unittest.main()
