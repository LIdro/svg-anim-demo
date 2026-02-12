from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
import json
from typing import Any, Dict, List, Optional

from svg_anim_demo.compiler.layer_compiler import LayerCompiler
from svg_anim_demo.runtime.engine import ExecutionEngine
from svg_anim_demo.runtime.reconcile import reconcile_with_dom
from svg_anim_demo.runtime.state_store import StateStore


TINY_PNG_DATA_URI = (
    "data:image/png;base64,"
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO5Xn5kAAAAASUVORK5CYII="
)

DEFAULT_SVG = """
<svg xmlns="http://www.w3.org/2000/svg" width="320" height="180">
    <rect id="bg" x="0" y="0" width="320" height="180" />
    <g id="title_group" data-label="Hero Title">
        <text id="title" x="40" y="60" width="140" height="30">Highlife</text>
        <path d="M10 10 L20 20" />
    </g>
    <circle id="badge" cx="220" cy="90" r="24" />
</svg>
""".strip()


@dataclass
class RuntimeService:
    svg_text: str = DEFAULT_SVG
    compiler: LayerCompiler = field(default_factory=LayerCompiler)
    layer_map_min: Dict[str, Any] = field(default_factory=dict)
    layer_map_full: Dict[str, Any] = field(default_factory=dict)
    compile_manifest: Dict[str, Any] = field(default_factory=dict)
    store: Optional[StateStore] = None
    engine: Optional[ExecutionEngine] = None
    dom_layers: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    cache_map: Dict[str, Any] = field(default_factory=dict)
    cache_state: Dict[str, Any] = field(default_factory=dict)
    cache_snapshot: Dict[str, Any] = field(default_factory=dict)
    state_version: int = 0

    def __post_init__(self) -> None:
        self.compile_svg(self.svg_text)

    def compile_svg(self, svg_text: str, force: bool = False) -> None:
        should, _ = self.compiler.needs_recompile(
            svg_text,
            previous_manifest=self.compile_manifest if self.compile_manifest else None,
            manual_recompile=force,
        )
        if not should and self.layer_map_min and self.layer_map_full:
            return

        result = self.compiler.compile(svg_text)
        self.svg_text = svg_text
        self.layer_map_min = result.layer_map_min
        self.layer_map_full = result.layer_map_full
        self.compile_manifest = result.compile_manifest

        self.store = StateStore.from_layer_map_full(self.layer_map_full)
        self.engine = ExecutionEngine(self.store)
        self.dom_layers = self.store.get_state()

        self.state_version = 0
        self.cache_map.clear()
        self.cache_state.clear()
        self.cache_snapshot.clear()

    def _layer_full_by_id(self, layer_id: str) -> Dict[str, Any]:
        for layer in self.layer_map_full.get("layers", []):
            if layer.get("id") == layer_id:
                return layer
        raise KeyError(layer_id)

    def _layer_min_by_id(self, layer_id: str) -> Dict[str, Any]:
        for layer in self.layer_map_min.get("layers", []):
            if layer.get("id") == layer_id:
                return layer
        raise KeyError(layer_id)

    def _ensure_layer(self, layer_id: str) -> Dict[str, Any]:
        return self._layer_full_by_id(layer_id)

    def _has_capability(self, layer_id: str, prop: str) -> bool:
        cap_map = {
            "x": "move",
            "y": "move",
            "scale": "scale",
            "rotation": "rotate",
            "opacity": "opacity",
            "z": "depth",
        }
        capability_key = cap_map.get(prop)
        if capability_key is None:
            return True

        layer = self._layer_full_by_id(layer_id)
        capabilities = layer.get("capabilities", {})
        return bool(capabilities.get(capability_key, False))

    def _clamp_props(self, layer_id: str, props: Dict[str, Any]) -> Dict[str, Any]:
        layer = self._layer_full_by_id(layer_id)
        constraints = layer.get("constraints", {})

        output = dict(props)

        if "opacity" in output:
            output["opacity"] = max(0.0, min(1.0, float(output["opacity"])))

        if "rotation" in output and "maxRotation" in constraints:
            max_rotation = abs(float(constraints["maxRotation"]))
            value = float(output["rotation"])
            output["rotation"] = max(-max_rotation, min(max_rotation, value))

        if "z" in output:
            min_depth = float(constraints.get("minDepth", -200.0))
            max_depth = float(constraints.get("maxDepth", 200.0))
            output["z"] = max(min_depth, min(max_depth, float(output["z"])))

        return output

    def _touch_state(self) -> None:
        if self.store is None:
            return
        self.state_version += 1
        self.dom_layers = self.store.get_state()
        self.cache_state.clear()
        self.cache_snapshot.clear()

    def get_layer_map(self, include_full: bool = False) -> Dict[str, Any]:
        key = f"map:{'full' if include_full else 'min'}"
        if key in self.cache_map:
            return deepcopy(self.cache_map[key])

        payload = self.layer_map_full if include_full else self.layer_map_min
        self.cache_map[key] = deepcopy(payload)
        return deepcopy(payload)

    def list_layers(self, layer_filter: Optional[Dict[str, Any]], limit: int, cursor: Optional[str]) -> Dict[str, Any]:
        offset = int(cursor or "0") if (cursor or "0").isdigit() else 0
        items = deepcopy(self.layer_map_min.get("layers", []))

        if layer_filter:
            tag_filter = layer_filter.get("tag")
            type_filter = layer_filter.get("type")
            capability_filter = layer_filter.get("capability")
            text_filter = str(layer_filter.get("text", "")).lower().strip()

            def _match(layer: Dict[str, Any]) -> bool:
                if tag_filter and tag_filter not in layer.get("tags", []):
                    return False
                if type_filter and layer.get("type") != type_filter:
                    return False
                if capability_filter and not layer.get("capabilities", {}).get(capability_filter, False):
                    return False
                if text_filter:
                    hay = " ".join([layer.get("id", ""), layer.get("label", ""), " ".join(layer.get("aliases", []))]).lower()
                    if text_filter not in hay:
                        return False
                return True

            items = [item for item in items if _match(item)]

        sliced = items[offset : offset + limit]
        next_cursor = str(offset + limit) if (offset + limit) < len(items) else None
        return {"items": sliced, "nextCursor": next_cursor}

    def get_layer_detail(self, layer_id: str) -> Dict[str, Any]:
        return deepcopy(self._layer_full_by_id(layer_id))

    def get_layer_state(self, layer_ids: Optional[List[str]]) -> Dict[str, Any]:
        if self.store is None:
            raise RuntimeError("State store is not initialized")

        if not layer_ids:
            key = f"state:*:v{self.state_version}"
        else:
            key = f"state:{','.join(sorted(layer_ids))}:v{self.state_version}"

        if key in self.cache_state:
            return deepcopy(self.cache_state[key])

        doc = self.store.export_layer_state_document()
        if layer_ids:
            doc["layers"] = {layer_id: doc["layers"][layer_id] for layer_id in layer_ids if layer_id in doc["layers"]}

        self.cache_state[key] = deepcopy(doc)
        return deepcopy(doc)

    def set_layer_state(self, layer_id: str, props: Dict[str, Any]) -> Dict[str, Any]:
        if self.store is None or self.engine is None:
            raise RuntimeError("Runtime not initialized")

        self._ensure_layer(layer_id)

        for key in props:
            if not self._has_capability(layer_id, key):
                raise PermissionError(f"Layer '{layer_id}' does not allow '{key}'")

        clamped = self._clamp_props(layer_id, props)
        result = self.engine.run_set(layer_id, clamped)
        self._touch_state()
        return {"applied": clamped, "runId": result["runId"]}

    def set_origin(self, layer_id: str, origin: Dict[str, Any] | str) -> Dict[str, Any]:
        layer = self._ensure_layer(layer_id)
        bbox = layer.get("bbox", {})

        if isinstance(origin, str):
            name = origin.strip().lower()
            if name == "center":
                resolved = {"x": bbox.get("cx", 0.0), "y": bbox.get("cy", 0.0)}
            elif name == "top":
                resolved = {"x": bbox.get("cx", 0.0), "y": bbox.get("y", 0.0)}
            elif name == "bottom-left":
                resolved = {
                    "x": bbox.get("x", 0.0),
                    "y": bbox.get("y", 0.0) + bbox.get("height", 0.0),
                }
            else:
                resolved = {"x": bbox.get("cx", 0.0), "y": bbox.get("cy", 0.0)}
        else:
            resolved = {"x": float(origin.get("x", 0.0)), "y": float(origin.get("y", 0.0))}

        self.set_layer_state(layer_id, {"origin": resolved})
        return resolved

    def animate_layer(
        self,
        layer_id: str,
        from_props: Optional[Dict[str, float]],
        to_props: Dict[str, float],
        duration: float,
        ease: str,
        delay: float,
        fallback: bool = False,
    ) -> Dict[str, Any]:
        if self.store is None or self.engine is None:
            raise RuntimeError("Runtime not initialized")

        self._ensure_layer(layer_id)

        target_to = dict(to_props)
        target_from = dict(from_props) if from_props else None

        if fallback:
            target_to = {"x": 0.0, "y": 0.0}
            target_from = None
            duration = 0.2
            ease = "power1.out"
            delay = 0.0

        for candidate in [target_from or {}, target_to]:
            for key in candidate:
                if not self._has_capability(layer_id, key):
                    raise PermissionError(f"Layer '{layer_id}' does not allow '{key}'")

        if target_from:
            target_from = self._clamp_props(layer_id, target_from)
        target_to = self._clamp_props(layer_id, target_to)

        result = self.engine.run_animate(layer_id, target_from, target_to, duration, ease, delay)
        self._touch_state()
        return result

    def timeline(self, steps: List[Dict[str, Any]], fallback: bool = False) -> Dict[str, Any]:
        if self.store is None or self.engine is None:
            raise RuntimeError("Runtime not initialized")

        normalized: List[Dict[str, Any]] = []
        if fallback:
            first_layer = self.layer_map_full.get("layers", [{}])[0].get("id", "bg")
            normalized.append({"layerId": first_layer, "to": {"x": 0.0, "y": 0.0}, "duration": 0.2, "ease": "power1.out", "delay": 0.0, "at": None})
        else:
            for step in steps:
                layer_id = step["layerId"]
                self._ensure_layer(layer_id)

                from_props = step.get("from")
                to_props = step["to"]

                for candidate in [from_props or {}, to_props]:
                    for key in candidate:
                        if not self._has_capability(layer_id, key):
                            raise PermissionError(f"Layer '{layer_id}' does not allow '{key}'")

                normalized.append(
                    {
                        "layerId": layer_id,
                        "from": self._clamp_props(layer_id, from_props) if from_props else None,
                        "to": self._clamp_props(layer_id, to_props),
                        "duration": float(step.get("duration", 0.0)),
                        "ease": str(step.get("ease", "linear")),
                        "delay": float(step.get("delay", 0.0)),
                        "at": step.get("at"),
                    }
                )

        result = self.engine.run_timeline(normalized)
        self._touch_state()
        return result

    def set_layer_depth(self, layer_id: str, z: float) -> float:
        output = self.set_layer_state(layer_id, {"z": z})
        return float(output["applied"]["z"])

    def animate_layer_depth(
        self,
        layer_id: str,
        from_depth: Optional[float],
        to_depth: float,
        duration: float,
        ease: str,
        fallback: bool = False,
    ) -> Dict[str, Any]:
        from_payload = {"z": float(from_depth)} if from_depth is not None else None
        to_payload = {"z": float(to_depth)}
        return self.animate_layer(
            layer_id=layer_id,
            from_props=from_payload,
            to_props=to_payload,
            duration=duration,
            ease=ease,
            delay=0.0,
            fallback=fallback,
        )

    def set_effect_layer(self, layer_id: str, effect: Dict[str, Any]) -> Dict[str, Any]:
        layer = self._ensure_layer(layer_id)
        capabilities = layer.get("capabilities", {})
        if not capabilities.get("effect", False):
            raise PermissionError(f"Layer '{layer_id}' does not allow effect")
        # Phase 5 hook placeholder: effect is stored in metadata-like runtime field.
        self.set_layer_state(layer_id, {"status": "idle"})
        return deepcopy(effect)

    def set_jitter(self, layer_id: str, seed: int, max_xy: float, max_z: float, point_limit: int) -> Dict[str, Any]:
        layer = self._ensure_layer(layer_id)
        capabilities = layer.get("capabilities", {})
        if not capabilities.get("jitter", False):
            raise PermissionError(f"Layer '{layer_id}' does not allow jitter")

        jitter_payload = {
            "seed": int(seed),
            "maxXY": float(max_xy),
            "maxZ": float(max_z),
            "pointLimit": int(point_limit),
        }
        self.set_layer_state(layer_id, {"status": "idle"})
        return jitter_payload

    def reconcile(self, dry_run: bool = False) -> List[str]:
        if self.store is None:
            raise RuntimeError("State store is not initialized")

        result = reconcile_with_dom(self.store, self.dom_layers, prefer="dom", dry_run=dry_run)
        if not dry_run:
            for layer_id, patch in result.dom_patch.items():
                self.dom_layers.setdefault(layer_id, {}).update(patch)
            self._touch_state()
        return result.changed_layer_ids

    def render_snapshot(self, size: Optional[Dict[str, int]], background: Optional[str], layers: Optional[List[str]]) -> str:
        key_obj = {
            "size": size or {},
            "background": background,
            "layers": sorted(layers or []),
            "stateVersion": self.state_version,
        }
        key = json.dumps(key_obj, sort_keys=True)
        if key in self.cache_snapshot:
            return self.cache_snapshot[key]
        self.cache_snapshot[key] = TINY_PNG_DATA_URI
        return TINY_PNG_DATA_URI

    def render_sequence(
        self,
        frames: int,
        size: Optional[Dict[str, int]],
        background: Optional[str],
        layers: Optional[List[str]],
    ) -> List[str]:
        key_obj = {
            "frames": int(frames),
            "size": size or {},
            "background": background,
            "layers": sorted(layers or []),
            "stateVersion": self.state_version,
        }
        key = json.dumps(key_obj, sort_keys=True)
        if key in self.cache_snapshot:
            return deepcopy(self.cache_snapshot[key])

        output = [TINY_PNG_DATA_URI for _ in range(int(frames))]
        self.cache_snapshot[key] = deepcopy(output)
        return output

    def undo(self) -> bool:
        if self.store is None:
            raise RuntimeError("State store is not initialized")
        ok = self.store.undo()
        if ok:
            self._touch_state()
        return ok

    def redo(self) -> bool:
        if self.store is None:
            raise RuntimeError("State store is not initialized")
        ok = self.store.redo()
        if ok:
            self._touch_state()
        return ok

    def run_preset_animation(self, layer_id: str, preset: str) -> Dict[str, Any]:
        name = preset.strip().lower()
        if name == "slide_in_left":
            return self.animate_layer(layer_id, {"x": -120.0}, {"x": 0.0}, 0.4, "power2.out", 0.0)
        if name == "pop":
            return self.animate_layer(layer_id, {"scale": 0.8}, {"scale": 1.0}, 0.25, "back.out(1.7)", 0.0)
        if name == "lift":
            return self.animate_layer(layer_id, {"y": 10.0}, {"y": 0.0}, 0.3, "power1.out", 0.0)
        return self.animate_layer(layer_id, None, {"x": 0.0, "y": 0.0}, 0.2, "power1.out", 0.0)

    def compile_status(self) -> Dict[str, Any]:
        return {
            "compilerVersion": self.compile_manifest.get("compilerVersion"),
            "sourceChecksum": self.compile_manifest.get("sourceChecksum"),
            "generatedAt": self.compile_manifest.get("generatedAt"),
            "layerCount": self.layer_map_min.get("layerCount", 0),
            "stateVersion": self.state_version,
        }

    def timeline_log(self, limit: int = 20) -> List[Dict[str, Any]]:
        if self.engine is None:
            return []
        runs = list(self.engine.completed_runs.values())
        runs_sorted = sorted(runs, key=lambda run: (run.finished_at or "", run.run_id), reverse=True)
        output: List[Dict[str, Any]] = []
        for run in runs_sorted[:limit]:
            output.append(
                {
                    "runId": run.run_id,
                    "kind": run.kind,
                    "status": run.status,
                    "startedAt": run.started_at,
                    "finishedAt": run.finished_at,
                    "stepCount": len(run.steps),
                }
            )
        return output

    def diagnostics(self) -> Dict[str, Any]:
        return {
            "cache": {
                "map": len(self.cache_map),
                "state": len(self.cache_state),
                "snapshot": len(self.cache_snapshot),
            },
            "history": {
                "undoDepth": len(self.store.history) if self.store else 0,
                "redoDepth": len(self.store.future) if self.store else 0,
            },
        }
