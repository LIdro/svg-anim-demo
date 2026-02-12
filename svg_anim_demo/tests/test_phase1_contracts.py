from __future__ import annotations

import json
import unittest
from pathlib import Path

from svg_anim_demo.api import schemas, tools
from svg_anim_demo.services import config


FIXTURE_DIR = Path(__file__).parent / "fixtures"


def _load_fixture(name: str) -> dict:
    return json.loads((FIXTURE_DIR / name).read_text(encoding="utf-8"))


def _validate(model_cls, payload):
    if hasattr(model_cls, "model_validate"):
        return model_cls.model_validate(payload)
    return model_cls.parse_obj(payload)


class TestPhase1Contracts(unittest.TestCase):
    def test_layer_map_min_fixture_validates(self):
        _validate(schemas.LayerMapMinDocument, _load_fixture("layer_map_min.valid.json"))

    def test_layer_map_full_fixture_validates(self):
        _validate(schemas.LayerMapFullDocument, _load_fixture("layer_map_full.valid.json"))

    def test_compile_manifest_fixture_validates(self):
        _validate(schemas.CompileManifestDocument, _load_fixture("compile_manifest.valid.json"))

    def test_layer_state_fixture_validates(self):
        _validate(schemas.LayerStateDocument, _load_fixture("layer_state.valid.json"))

    def test_tool_payload_validates(self):
        payload = _load_fixture("animate_layer.valid.json")
        req = _validate(schemas.AnimateLayerRequest, payload)
        self.assertEqual(req.layerId, "layer_text_highlife")

    def test_invalid_payload_fails_deterministically(self):
        payload = _load_fixture("animate_layer.invalid.json")
        result = tools.animate_layer(payload)

        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["code"], "VALIDATION_ERROR")
        self.assertEqual(result["error"]["message"], "Invalid payload for tool 'animate_layer'")
        self.assertGreaterEqual(len(result["error"]["details"]), 2)

    def test_list_layers_limit_is_enforced(self):
        payload = {"limit": config.MAX_LIST_LAYERS_LIMIT + 1}
        result = tools.list_layers(payload)

        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["code"], "LIST_LIMIT_EXCEEDED")
        self.assertEqual(result["error"]["details"][0]["limit"], config.MAX_LIST_LAYERS_LIMIT)

    def test_budget_constants_are_shared_in_config(self):
        self.assertEqual(config.MAX_TOOL_RESPONSE_CHARS, config.settings.max_tool_response_chars)
        self.assertEqual(config.MAX_LIST_LAYERS_LIMIT, config.settings.max_list_layers_limit)
        self.assertEqual(config.MAX_RECURSIVE_DEPTH, config.settings.max_recursive_depth)
        self.assertEqual(config.MAX_SUBCALLS_PER_REQUEST, config.settings.max_subcalls_per_request)
        self.assertEqual(config.TOOL_TIMEOUT_MS, config.settings.tool_timeout_ms)

    def test_unknown_tool_is_deterministic(self):
        result = tools.dispatch_tool("missing_tool", {})
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["code"], "UNKNOWN_TOOL")


if __name__ == "__main__":
    unittest.main()
