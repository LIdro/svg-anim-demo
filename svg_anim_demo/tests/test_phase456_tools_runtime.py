from __future__ import annotations

import unittest

from svg_anim_demo.api import tools
from svg_anim_demo.api.runtime_service import RuntimeService
from svg_anim_demo.services import config


class TestPhase456ToolsRuntime(unittest.TestCase):
    def setUp(self) -> None:
        self.runtime = RuntimeService()
        self.handlers = tools.create_runtime_handlers(self.runtime)

    def test_get_layer_map_and_list_layers_with_pagination(self):
        map_res = tools.dispatch_tool("get_layer_map", {}, handlers=self.handlers)
        self.assertTrue(map_res["ok"])
        self.assertIn("layers", map_res["map"])

        listed_1 = tools.dispatch_tool("list_layers", {"limit": 1}, handlers=self.handlers)
        self.assertTrue(listed_1["ok"])
        self.assertEqual(len(listed_1["items"]), 1)
        self.assertIsNotNone(listed_1["nextCursor"])

        listed_2 = tools.dispatch_tool(
            "list_layers",
            {"limit": 10, "cursor": listed_1["nextCursor"]},
            handlers=self.handlers,
        )
        self.assertTrue(listed_2["ok"])

    def test_set_layer_state_clamps_and_updates_state(self):
        res = tools.dispatch_tool(
            "set_layer_state",
            {"layerId": "title", "props": {"rotation": 999, "opacity": -2}},
            handlers=self.handlers,
        )
        self.assertTrue(res["ok"])
        self.assertEqual(res["layerId"], "title")
        self.assertEqual(res["applied"]["rotation"], 45.0)
        self.assertEqual(res["applied"]["opacity"], 0.0)

        state = tools.dispatch_tool("get_layer_state", {"layerIds": ["title"]}, handlers=self.handlers)
        self.assertTrue(state["ok"])
        self.assertEqual(state["state"]["layers"]["title"]["rotation"], 45.0)

    def test_capability_constraint_violation_is_deterministic(self):
        res = tools.dispatch_tool(
            "set_effect_layer",
            {"layerId": "title", "effect": {"name": "blur", "radius": 3}},
            handlers=self.handlers,
        )
        self.assertFalse(res["ok"])
        self.assertEqual(res["error"]["code"], "CONSTRAINT_VIOLATION")

    def test_animate_and_timeline_execute_and_return_run_ids(self):
        animate = tools.dispatch_tool(
            "animate_layer",
            {
                "layerId": "title",
                "from": {"x": -120},
                "to": {"x": 0},
                "duration": 0.4,
                "ease": "elastic.out(1,0.4)",
                "delay": 0,
            },
            handlers=self.handlers,
        )
        self.assertTrue(animate["ok"])
        self.assertTrue(animate["runId"].startswith("run_"))

        timeline = tools.dispatch_tool(
            "timeline",
            {
                "steps": [
                    {
                        "layerId": "title",
                        "to": {"x": 10},
                        "duration": 0.2,
                        "ease": "linear",
                        "delay": 0,
                        "at": 0,
                    },
                    {
                        "layerId": "badge",
                        "to": {"z": 12},
                        "duration": 0.2,
                        "ease": "linear",
                        "delay": 0,
                        "at": 0.1,
                    },
                ]
            },
            handlers=self.handlers,
        )
        self.assertTrue(timeline["ok"])
        self.assertEqual(timeline["stepCount"], 2)

    def test_render_snapshot_and_sequence_are_cached(self):
        snap1 = tools.dispatch_tool("render_snapshot", {}, handlers=self.handlers)
        snap2 = tools.dispatch_tool("render_snapshot", {}, handlers=self.handlers)
        self.assertTrue(snap1["ok"])
        self.assertTrue(snap1["png"].startswith("data:image/png;base64,"))
        self.assertEqual(snap1["png"], snap2["png"])

        seq = tools.dispatch_tool("render_sequence", {"frames": 3}, handlers=self.handlers)
        self.assertTrue(seq["ok"])
        self.assertEqual(len(seq["frames"]), 3)

    def test_reconcile_state_from_dom_flow(self):
        self.runtime.dom_layers["title"]["x"] = 123
        result = tools.dispatch_tool("reconcile_state_from_dom", {"dryRun": False}, handlers=self.handlers)
        self.assertTrue(result["ok"])
        self.assertIn("title", result["changedLayerIds"])

    def test_subcall_overflow_fallback_for_animation(self):
        ctx = tools.ToolContext(subcalls=config.MAX_SUBCALLS_PER_REQUEST)
        result = tools.dispatch_tool(
            "animate_layer",
            {
                "layerId": "title",
                "to": {"x": 99},
                "duration": 0.5,
                "ease": "linear",
                "delay": 0,
            },
            handlers=self.handlers,
            context=ctx,
        )
        self.assertTrue(result["ok"])
        self.assertEqual(result["plannedEndState"]["x"], 0.0)

    def test_subcall_overflow_non_animation_returns_error(self):
        ctx = tools.ToolContext(subcalls=config.MAX_SUBCALLS_PER_REQUEST)
        result = tools.dispatch_tool("get_layer_state", {}, handlers=self.handlers, context=ctx)
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["code"], "SUBCALL_LIMIT_EXCEEDED")


if __name__ == "__main__":
    unittest.main()
