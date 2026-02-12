from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Dict, List

from svg_anim_demo.runtime.state_store import StateStore


RECONCILE_FIELDS = ("x", "y", "scale", "rotation", "opacity", "visible", "origin", "status", "z")


@dataclass
class ReconcileResult:
    changed_layer_ids: List[str]
    dom_patch: Dict[str, Dict[str, Any]]


def _values_different(a: Any, b: Any, tolerance: float = 1e-6) -> bool:
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return abs(float(a) - float(b)) > tolerance
    return a != b


def reconcile_with_dom(
    store: StateStore,
    dom_layers: Dict[str, Dict[str, Any]],
    prefer: str = "dom",
    dry_run: bool = False,
    tolerance: float = 1e-6,
) -> ReconcileResult:
    """Reconcile store and DOM snapshots using deterministic conflict rules.

    Rules:
    1. If layer status is 'locked', store is authoritative.
    2. Otherwise, choose authority from `prefer` ('dom' or 'store').
    3. Only tracked runtime fields are reconciled.
    """

    if prefer not in {"dom", "store"}:
        raise ValueError("prefer must be 'dom' or 'store'")

    changed_layer_ids: List[str] = []
    dom_patch: Dict[str, Dict[str, Any]] = {}

    for layer_id, dom_state in dom_layers.items():
        if layer_id not in store.current:
            continue

        store_state = store.current[layer_id]
        authoritative = "store" if str(store_state.get("status", "")) == "locked" else prefer

        needs_change = False
        update_for_store: Dict[str, Any] = {}
        update_for_dom: Dict[str, Any] = {}

        for field in RECONCILE_FIELDS:
            if field not in dom_state and field not in store_state:
                continue

            if authoritative == "dom" and field not in dom_state:
                continue
            if authoritative == "store" and field not in store_state:
                continue

            store_value = store_state.get(field)
            dom_value = dom_state.get(field)

            if not _values_different(store_value, dom_value, tolerance=tolerance):
                continue

            needs_change = True
            if authoritative == "dom":
                update_for_store[field] = deepcopy(dom_value)
            else:
                update_for_dom[field] = deepcopy(store_value)

        if not needs_change:
            continue

        changed_layer_ids.append(layer_id)

        if dry_run:
            continue

        if update_for_store:
            store.set(layer_id, update_for_store, propagate=False)

        if update_for_dom:
            dom_patch[layer_id] = update_for_dom

    return ReconcileResult(changed_layer_ids=sorted(set(changed_layer_ids)), dom_patch=dom_patch)


def reconcile_state_from_dom(
    store: StateStore,
    dom_layers: Dict[str, Dict[str, Any]],
    prefer: str = "dom",
    dry_run: bool = False,
) -> List[str]:
    result = reconcile_with_dom(store, dom_layers, prefer=prefer, dry_run=dry_run)
    return result.changed_layer_ids
