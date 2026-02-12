from __future__ import annotations

import unittest

from svg_anim_demo.api import tools
from svg_anim_demo.api.runtime_service import RuntimeService


def build_large_svg(num_rects: int = 22000) -> str:
    rows = ["<svg xmlns='http://www.w3.org/2000/svg' width='4096' height='4096'>"]
    for i in range(num_rects):
        x = i % 400
        y = (i // 400) % 400
        rows.append(f"<rect id='r{i}' x='{x}' y='{y}' width='2' height='2' />")
    rows.append("</svg>")
    return "".join(rows)


class TestPhase8Hardening(unittest.TestCase):
    def setUp(self) -> None:
        self.runtime = RuntimeService()
        self.handlers = tools.create_runtime_handlers(self.runtime)

    def test_integration_compile_to_tool_to_reconcile(self):
        integration_svg = """
        <svg xmlns='http://www.w3.org/2000/svg' width='300' height='200'>
            <g id='group_main'>
                <rect id='box' x='10' y='10' width='40' height='20' />
                <text id='caption' x='20' y='50' width='80' height='20'>Hello</text>
            </g>
        </svg>
        """.strip()
        self.runtime.compile_svg(integration_svg, force=True)

        layer_map = tools.dispatch_tool("get_layer_map", {}, handlers=self.handlers)
        self.assertTrue(layer_map["ok"])

        set_state = tools.dispatch_tool(
            "set_layer_state",
            {"layerId": "caption", "props": {"x": 15, "y": 5}},
            handlers=self.handlers,
        )
        self.assertTrue(set_state["ok"])

        animate = tools.dispatch_tool(
            "animate_layer",
            {
                "layerId": "caption",
                "to": {"x": 0},
                "duration": 0.2,
                "ease": "linear",
                "delay": 0,
            },
            handlers=self.handlers,
        )
        self.assertTrue(animate["ok"])

        self.runtime.dom_layers["caption"]["x"] = 77
        reconciled = tools.dispatch_tool("reconcile_state_from_dom", {"dryRun": False}, handlers=self.handlers)
        self.assertTrue(reconciled["ok"])
        self.assertIn("caption", reconciled["changedLayerIds"])

    def test_scale_large_svg_and_many_tool_calls(self):
        large_svg = build_large_svg()
        self.assertGreater(len(large_svg), 1_000_000)

        self.runtime.compile_svg(large_svg, force=True)
        listed = tools.dispatch_tool("list_layers", {"limit": 10}, handlers=self.handlers)
        self.assertTrue(listed["ok"])
        self.assertEqual(len(listed["items"]), 10)

        # many sequential calls should remain stable
        for i in range(40):
            layer_id = f"r{i}"
            result = tools.dispatch_tool(
                "set_layer_state",
                {"layerId": layer_id, "props": {"x": i, "y": i}},
                handlers=self.handlers,
            )
            self.assertTrue(result["ok"])

        snapshot = tools.dispatch_tool("render_snapshot", {}, handlers=self.handlers)
        self.assertTrue(snapshot["ok"])

    def test_regression_same_input_same_seed_same_output_state(self):
        out1 = tools.dispatch_tool(
            "set_jitter",
            {"layerId": "badge", "seed": 42, "maxXY": 2, "maxZ": 1, "pointLimit": 30},
            handlers=self.handlers,
        )
        out2 = tools.dispatch_tool(
            "set_jitter",
            {"layerId": "badge", "seed": 42, "maxXY": 2, "maxZ": 1, "pointLimit": 30},
            handlers=self.handlers,
        )

        self.assertTrue(out1["ok"])
        self.assertTrue(out2["ok"])
        self.assertEqual(out1["jitter"], out2["jitter"])


if __name__ == "__main__":
    unittest.main()
