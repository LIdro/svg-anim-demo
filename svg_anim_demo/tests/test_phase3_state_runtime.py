from __future__ import annotations

import unittest

from svg_anim_demo.runtime.reconcile import reconcile_state_from_dom, reconcile_with_dom
from svg_anim_demo.runtime.state_store import StateStore


LAYER_MAP_FULL = {
    "layers": [
        {
            "id": "root_group",
            "children": ["child_a", "child_b"],
            "defaultOrigin": {"x": 50, "y": 50},
        },
        {
            "id": "child_a",
            "children": [],
            "defaultOrigin": {"x": 10, "y": 10},
        },
        {
            "id": "child_b",
            "children": [],
            "defaultOrigin": {"x": 20, "y": 20},
        },
    ]
}


class TestPhase3StateRuntime(unittest.TestCase):
    def test_undo_redo_restores_exact_snapshots(self):
        store = StateStore.from_layer_map_full(LAYER_MAP_FULL)
        before = store.get_state()

        store.set("child_a", {"x": 12, "rotation": 15})
        after_set = store.get_state()

        self.assertTrue(store.undo())
        self.assertEqual(store.get_state(), before)

        self.assertTrue(store.redo())
        self.assertEqual(store.get_state(), after_set)

    def test_group_updates_propagate_to_children(self):
        store = StateStore.from_layer_map_full(LAYER_MAP_FULL)

        store.set("child_a", {"x": 2, "y": 4, "scale": 1.5, "rotation": 10, "z": 1})
        store.set("child_b", {"x": 3, "y": 5, "scale": 2.0, "rotation": 20, "z": 2})

        child_a_before = store.get_layer_state("child_a")
        child_b_before = store.get_layer_state("child_b")

        store.set("root_group", {"x": 10, "y": -3, "scale": 2.0, "rotation": 5, "z": 7})

        child_a_after = store.get_layer_state("child_a")
        child_b_after = store.get_layer_state("child_b")

        self.assertAlmostEqual(child_a_after["x"], child_a_before["x"] + 10)
        self.assertAlmostEqual(child_a_after["y"], child_a_before["y"] - 3)
        self.assertAlmostEqual(child_a_after["rotation"], child_a_before["rotation"] + 5)
        self.assertAlmostEqual(child_a_after["z"], child_a_before["z"] + 7)
        self.assertAlmostEqual(child_a_after["scale"], child_a_before["scale"] * 2.0)

        self.assertAlmostEqual(child_b_after["x"], child_b_before["x"] + 10)
        self.assertAlmostEqual(child_b_after["y"], child_b_before["y"] - 3)
        self.assertAlmostEqual(child_b_after["rotation"], child_b_before["rotation"] + 5)
        self.assertAlmostEqual(child_b_after["z"], child_b_before["z"] + 7)
        self.assertAlmostEqual(child_b_after["scale"], child_b_before["scale"] * 2.0)

    def test_reconcile_updates_store_from_dom(self):
        store = StateStore.from_layer_map_full(LAYER_MAP_FULL)
        store.set("child_a", {"x": 1, "y": 2, "scale": 1.0})

        dom_layers = {
            "child_a": {"x": 100, "y": 200, "scale": 1.25, "status": "idle", "z": 5},
        }

        changed = reconcile_state_from_dom(store, dom_layers, prefer="dom")
        self.assertEqual(changed, ["child_a"])

        state = store.get_layer_state("child_a")
        self.assertEqual(state["x"], 100)
        self.assertEqual(state["y"], 200)
        self.assertEqual(state["scale"], 1.25)
        self.assertEqual(state["z"], 5)

    def test_reconcile_locked_layer_prefers_store(self):
        store = StateStore.from_layer_map_full(LAYER_MAP_FULL)
        store.set("child_a", {"x": 7, "status": "locked"})

        dom_layers = {"child_a": {"x": 99, "status": "idle"}}
        result = reconcile_with_dom(store, dom_layers, prefer="dom")

        self.assertEqual(result.changed_layer_ids, ["child_a"])
        self.assertIn("child_a", result.dom_patch)
        self.assertEqual(result.dom_patch["child_a"]["x"], 7)

        state = store.get_layer_state("child_a")
        self.assertEqual(state["x"], 7)
        self.assertEqual(state["status"], "locked")

    def test_reconcile_dry_run_does_not_mutate(self):
        store = StateStore.from_layer_map_full(LAYER_MAP_FULL)
        store.set("child_b", {"x": 11})
        before = store.get_state()

        dom_layers = {"child_b": {"x": 88}}
        result = reconcile_with_dom(store, dom_layers, prefer="dom", dry_run=True)

        self.assertEqual(result.changed_layer_ids, ["child_b"])
        self.assertEqual(store.get_state(), before)


if __name__ == "__main__":
    unittest.main()
