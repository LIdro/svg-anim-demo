from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Dict, Iterable, List, Optional

from svg_anim_demo.api import schemas


TRACKED_FIELDS = {
    "x",
    "y",
    "scale",
    "rotation",
    "opacity",
    "visible",
    "origin",
    "status",
    "lastUpdate",
    "z",
}

ADDITIVE_FIELDS = {"x", "y", "rotation", "z"}


def _iso_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _clamp_opacity(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def _default_layer_state(default_origin: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    return {
        "x": 0.0,
        "y": 0.0,
        "scale": 1.0,
        "rotation": 0.0,
        "opacity": 1.0,
        "visible": True,
        "origin": deepcopy(default_origin) if default_origin else None,
        "status": schemas.LayerStatus.idle.value,
        "lastUpdate": _iso_now(),
        "z": 0.0,
    }


@dataclass
class StateStore:
    """Redux-style state store with deterministic history and group propagation."""

    layer_tree: Dict[str, List[str]] = field(default_factory=dict)
    current: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    history: List[Dict[str, Dict[str, Any]]] = field(default_factory=list)
    future: List[Dict[str, Dict[str, Any]]] = field(default_factory=list)

    @classmethod
    def from_layer_map_full(cls, layer_map_full: Dict[str, Any]) -> "StateStore":
        layers = layer_map_full.get("layers", [])
        layer_tree: Dict[str, List[str]] = {}
        current: Dict[str, Dict[str, Any]] = {}

        for layer in layers:
            layer_id = layer["id"]
            children = list(layer.get("children", []))
            layer_tree[layer_id] = children
            current[layer_id] = _default_layer_state(layer.get("defaultOrigin"))

        return cls(layer_tree=layer_tree, current=current)

    def snapshot(self) -> Dict[str, Any]:
        return {
            "current": deepcopy(self.current),
            "history_len": len(self.history),
            "future_len": len(self.future),
        }

    def get_layer_state(self, layer_id: str) -> Dict[str, Any]:
        self._ensure_layer(layer_id)
        return deepcopy(self.current[layer_id])

    def get_state(self) -> Dict[str, Dict[str, Any]]:
        return deepcopy(self.current)

    def _ensure_layer(self, layer_id: str) -> None:
        if layer_id not in self.current:
            self.current[layer_id] = _default_layer_state()
        if layer_id not in self.layer_tree:
            self.layer_tree[layer_id] = []

    def _commit_history(self) -> None:
        self.history.append(deepcopy(self.current))
        self.future.clear()

    def _normalize_props(self, props: Dict[str, Any]) -> Dict[str, Any]:
        normalized: Dict[str, Any] = {}
        for key, value in props.items():
            if key not in TRACKED_FIELDS:
                continue
            if key == "opacity":
                normalized[key] = _clamp_opacity(float(value))
            elif key == "scale":
                normalized[key] = float(value)
            elif key in {"x", "y", "rotation", "z"}:
                normalized[key] = float(value)
            elif key == "visible":
                normalized[key] = bool(value)
            elif key == "origin":
                normalized[key] = deepcopy(value)
            elif key == "status":
                normalized[key] = str(value)
            elif key == "lastUpdate":
                normalized[key] = str(value)
        if "lastUpdate" not in normalized:
            normalized["lastUpdate"] = _iso_now()
        return normalized

    def _apply_direct(self, layer_id: str, props: Dict[str, Any]) -> Dict[str, Any]:
        self._ensure_layer(layer_id)
        normalized = self._normalize_props(props)
        self.current[layer_id].update(normalized)
        return normalized

    def _propagate_group_delta(self, layer_id: str, old_parent: Dict[str, Any], new_parent: Dict[str, Any]) -> None:
        children = self.layer_tree.get(layer_id, [])
        if not children:
            return

        deltas = {
            "x": float(new_parent.get("x", 0.0)) - float(old_parent.get("x", 0.0)),
            "y": float(new_parent.get("y", 0.0)) - float(old_parent.get("y", 0.0)),
            "rotation": float(new_parent.get("rotation", 0.0)) - float(old_parent.get("rotation", 0.0)),
            "z": float(new_parent.get("z", 0.0)) - float(old_parent.get("z", 0.0)),
        }

        old_scale = float(old_parent.get("scale", 1.0))
        new_scale = float(new_parent.get("scale", 1.0))
        scale_ratio = 1.0 if old_scale == 0 else new_scale / old_scale

        old_opacity = float(old_parent.get("opacity", 1.0))
        new_opacity = float(new_parent.get("opacity", 1.0))
        opacity_ratio = 1.0 if old_opacity == 0 else new_opacity / old_opacity

        for child_id in children:
            self._ensure_layer(child_id)
            child_before = deepcopy(self.current[child_id])

            for key in ADDITIVE_FIELDS:
                self.current[child_id][key] = float(self.current[child_id].get(key, 0.0)) + deltas[key]

            self.current[child_id]["scale"] = float(self.current[child_id].get("scale", 1.0)) * scale_ratio
            self.current[child_id]["opacity"] = _clamp_opacity(float(self.current[child_id].get("opacity", 1.0)) * opacity_ratio)
            self.current[child_id]["lastUpdate"] = _iso_now()

            self._propagate_group_delta(child_id, child_before, self.current[child_id])

    def set(self, layer_id: str, props: Dict[str, Any], propagate: bool = True) -> Dict[str, Any]:
        self._ensure_layer(layer_id)
        self._commit_history()

        old_parent = deepcopy(self.current[layer_id])
        applied = self._apply_direct(layer_id, props)

        if propagate and self.layer_tree.get(layer_id):
            self._propagate_group_delta(layer_id, old_parent, self.current[layer_id])

        return applied

    def batch_set(self, changes: Iterable[Dict[str, Any]], propagate: bool = True) -> List[Dict[str, Any]]:
        self._commit_history()
        applied_changes: List[Dict[str, Any]] = []

        for change in changes:
            layer_id = change.get("layerId")
            props = change.get("props", {})
            if not layer_id or not isinstance(props, dict):
                continue

            self._ensure_layer(layer_id)
            old_parent = deepcopy(self.current[layer_id])
            applied = self._apply_direct(layer_id, props)

            if propagate and self.layer_tree.get(layer_id):
                self._propagate_group_delta(layer_id, old_parent, self.current[layer_id])

            applied_changes.append({"layerId": layer_id, "applied": applied})

        return applied_changes

    def undo(self) -> bool:
        if not self.history:
            return False
        self.future.append(deepcopy(self.current))
        self.current = self.history.pop()
        return True

    def redo(self) -> bool:
        if not self.future:
            return False
        self.history.append(deepcopy(self.current))
        self.current = self.future.pop()
        return True

    def export_layer_state_document(self) -> Dict[str, Any]:
        payload = {
            "schemaVersion": "1.0",
            "timestamp": _iso_now(),
            "layers": deepcopy(self.current),
        }

        if hasattr(schemas.LayerStateDocument, "model_validate"):
            return schemas.LayerStateDocument.model_validate(payload).model_dump()
        return schemas.LayerStateDocument.parse_obj(payload).dict()
