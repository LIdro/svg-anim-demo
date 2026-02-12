from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
import re
from typing import Any, Dict, List, Optional, Tuple
import xml.etree.ElementTree as ET

from svg_anim_demo.api import schemas
from svg_anim_demo.services import config


SVG_NS = "{http://www.w3.org/2000/svg}"
SHAPE_TAGS = {"rect", "circle", "ellipse", "line", "polygon", "polyline", "path"}


def _strip_ns(tag: str) -> str:
    return tag.split("}", 1)[1] if "}" in tag else tag


def _to_float(value: Optional[str], default: float = 0.0) -> float:
    if value is None:
        return default
    cleaned = value.strip().replace("px", "")
    if not cleaned:
        return default
    try:
        return float(cleaned)
    except ValueError:
        return default


def _iso_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _sha256_text(value: str) -> str:
    return f"sha256:{hashlib.sha256(value.encode('utf-8')).hexdigest()}"


def _payload_checksum(payload: Dict[str, Any]) -> str:
    stable = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return _sha256_text(stable)


def _model_validate(model_cls: Any, payload: Dict[str, Any]) -> Any:
    if hasattr(model_cls, "model_validate"):
        return model_cls.model_validate(payload)
    return model_cls.parse_obj(payload)


def _model_dump(model: Any) -> Dict[str, Any]:
    if hasattr(model, "model_dump"):
        return model.model_dump()
    return model.dict()


def _tokenize_aliases(*values: str) -> List[str]:
    tokens: List[str] = []
    for value in values:
        if not value:
            continue
        for token in re.split(r"[^a-z0-9]+", value.lower()):
            if token and len(token) > 1:
                tokens.append(token)
    deduped = sorted(set(tokens))
    return deduped


def _parse_points(value: str) -> List[Tuple[float, float]]:
    normalized = value.replace(",", " ")
    raw = [part for part in normalized.split() if part]
    points: List[Tuple[float, float]] = []
    idx = 0
    while idx + 1 < len(raw):
        x = _to_float(raw[idx])
        y = _to_float(raw[idx + 1])
        points.append((x, y))
        idx += 2
    return points


def _infer_type(tag: str) -> schemas.LayerType:
    if tag == "text":
        return schemas.LayerType.text
    if tag in SHAPE_TAGS:
        return schemas.LayerType.shape
    if tag == "g":
        return schemas.LayerType.group
    if tag == "image":
        return schemas.LayerType.image
    return schemas.LayerType.unknown


def _infer_capabilities(layer_type: schemas.LayerType) -> schemas.LayerCapabilities:
    common = {
        "move": True,
        "scale": True,
        "rotate": True,
        "opacity": True,
        "depth": True,
        "maxRotation": 45.0,
        "minDepth": -200.0,
        "maxDepth": 200.0,
    }
    if layer_type == schemas.LayerType.shape:
        return schemas.LayerCapabilities(**common, effect=True, jitter=True)
    if layer_type == schemas.LayerType.image:
        return schemas.LayerCapabilities(**common, effect=True, jitter=False)
    if layer_type == schemas.LayerType.group:
        return schemas.LayerCapabilities(**common, effect=True, jitter=False)
    if layer_type == schemas.LayerType.text:
        return schemas.LayerCapabilities(**common, effect=False, jitter=False)
    return schemas.LayerCapabilities(**common, effect=False, jitter=False)


def _bbox_union(boxes: List[schemas.BBox]) -> schemas.BBox:
    if not boxes:
        return schemas.BBox(x=0, y=0, width=0, height=0, cx=0, cy=0)
    min_x = min(box.x for box in boxes)
    min_y = min(box.y for box in boxes)
    max_x = max(box.x + box.width for box in boxes)
    max_y = max(box.y + box.height for box in boxes)
    width = max(0.0, max_x - min_x)
    height = max(0.0, max_y - min_y)
    return schemas.BBox(x=min_x, y=min_y, width=width, height=height, cx=min_x + width / 2, cy=min_y + height / 2)


def _bbox_for_element(node: ET.Element) -> schemas.BBox:
    tag = _strip_ns(node.tag)

    if tag == "rect":
        x = _to_float(node.attrib.get("x"))
        y = _to_float(node.attrib.get("y"))
        w = max(0.0, _to_float(node.attrib.get("width")))
        h = max(0.0, _to_float(node.attrib.get("height")))
        return schemas.BBox(x=x, y=y, width=w, height=h, cx=x + w / 2, cy=y + h / 2)

    if tag == "circle":
        cx = _to_float(node.attrib.get("cx"))
        cy = _to_float(node.attrib.get("cy"))
        r = max(0.0, _to_float(node.attrib.get("r")))
        return schemas.BBox(x=cx - r, y=cy - r, width=2 * r, height=2 * r, cx=cx, cy=cy)

    if tag == "ellipse":
        cx = _to_float(node.attrib.get("cx"))
        cy = _to_float(node.attrib.get("cy"))
        rx = max(0.0, _to_float(node.attrib.get("rx")))
        ry = max(0.0, _to_float(node.attrib.get("ry")))
        return schemas.BBox(x=cx - rx, y=cy - ry, width=2 * rx, height=2 * ry, cx=cx, cy=cy)

    if tag == "line":
        x1 = _to_float(node.attrib.get("x1"))
        y1 = _to_float(node.attrib.get("y1"))
        x2 = _to_float(node.attrib.get("x2"))
        y2 = _to_float(node.attrib.get("y2"))
        min_x = min(x1, x2)
        min_y = min(y1, y2)
        width = abs(x2 - x1)
        height = abs(y2 - y1)
        return schemas.BBox(x=min_x, y=min_y, width=width, height=height, cx=min_x + width / 2, cy=min_y + height / 2)

    if tag in {"polygon", "polyline"}:
        points = _parse_points(node.attrib.get("points", ""))
        if not points:
            return schemas.BBox(x=0, y=0, width=0, height=0, cx=0, cy=0)
        xs = [point[0] for point in points]
        ys = [point[1] for point in points]
        min_x = min(xs)
        max_x = max(xs)
        min_y = min(ys)
        max_y = max(ys)
        width = max(0.0, max_x - min_x)
        height = max(0.0, max_y - min_y)
        return schemas.BBox(x=min_x, y=min_y, width=width, height=height, cx=min_x + width / 2, cy=min_y + height / 2)

    if tag in {"path", "text", "image"}:
        x = _to_float(node.attrib.get("x"))
        y = _to_float(node.attrib.get("y"))
        w = max(0.0, _to_float(node.attrib.get("width"), 1.0))
        h = max(0.0, _to_float(node.attrib.get("height"), 1.0))
        return schemas.BBox(x=x, y=y, width=w, height=h, cx=x + w / 2, cy=y + h / 2)

    return schemas.BBox(x=0, y=0, width=0, height=0, cx=0, cy=0)


def _fingerprint_for_node(node: ET.Element) -> str:
    tag = _strip_ns(node.tag)
    attrs = {}
    for key, value in sorted(node.attrib.items()):
        if key == "id":
            continue
        attrs[key] = value.strip() if isinstance(value, str) else str(value)
    text = (node.text or "").strip()
    structure = {"tag": tag, "attrs": attrs, "text": text}
    return hashlib.sha1(json.dumps(structure, sort_keys=True, ensure_ascii=True).encode("utf-8")).hexdigest()[:12]


def _stable_layer_id(node: ET.Element, fingerprint: str) -> str:
    source_id = (node.attrib.get("id") or "").strip()
    if source_id:
        normalized = re.sub(r"[^a-zA-Z0-9_\-]", "_", source_id)
        return normalized
    tag = _strip_ns(node.tag)
    return f"layer_{tag}_{fingerprint}"


def _layer_label(node: ET.Element, layer_id: str) -> str:
    label = (node.attrib.get("data-label") or node.attrib.get("inkscape:label") or "").strip()
    if label:
        return label
    if layer_id.startswith("layer_"):
        return layer_id[6:].replace("_", " ").strip() or layer_id
    return layer_id


@dataclass
class CompileResult:
    layer_map_min: Dict[str, Any]
    layer_map_full: Dict[str, Any]
    compile_manifest: Dict[str, Any]
    recompile_required: bool
    recompile_reason: Optional[str]


class LayerCompiler:
    def __init__(self, compiler_version: Optional[str] = None) -> None:
        self.compiler_version = compiler_version or config.settings.compiler_version

    def source_checksum(self, svg_text: str) -> str:
        return _sha256_text(svg_text)

    def needs_recompile(
        self,
        svg_text: str,
        previous_manifest: Optional[Dict[str, Any]] = None,
        manual_recompile: bool = False,
    ) -> Tuple[bool, Optional[str]]:
        if manual_recompile:
            return True, "manual_recompile"
        if not previous_manifest:
            return True, "missing_manifest"

        checksum = self.source_checksum(svg_text)
        if previous_manifest.get("sourceChecksum") != checksum:
            return True, "source_checksum_changed"
        if previous_manifest.get("compilerVersion") != self.compiler_version:
            return True, "compiler_version_changed"
        return False, None

    def _collect_layers(self, root: ET.Element) -> List[Dict[str, Any]]:
        collected: List[Dict[str, Any]] = []

        def visit(node: ET.Element, parent_id: Optional[str], z_counter: List[int]) -> Optional[schemas.BBox]:
            tag = _strip_ns(node.tag)
            if tag in {"defs", "clipPath", "mask", "style", "metadata", "title", "desc"}:
                return None

            fingerprint = _fingerprint_for_node(node)
            layer_id = _stable_layer_id(node, fingerprint)
            label = _layer_label(node, layer_id)
            aliases = _tokenize_aliases(layer_id, label)
            tags = _tokenize_aliases(node.attrib.get("data-label", ""), node.attrib.get("class", ""))
            layer_type = _infer_type(tag)
            capabilities = _infer_capabilities(layer_type)

            child_boxes: List[schemas.BBox] = []
            child_ids: List[str] = []
            for child in list(node):
                child_fingerprint = _fingerprint_for_node(child)
                child_layer_id = _stable_layer_id(child, child_fingerprint)
                child_bbox = visit(child, layer_id, z_counter)
                if child_bbox is not None:
                    child_boxes.append(child_bbox)
                    child_ids.append(child_layer_id)

            if layer_type == schemas.LayerType.group:
                bbox = _bbox_union(child_boxes)
            else:
                own_bbox = _bbox_for_element(node)
                bbox = _bbox_union([own_bbox] + child_boxes) if child_boxes else own_bbox

            constraints = {
                "maxRotation": capabilities.maxRotation or 45.0,
                "minDepth": capabilities.minDepth or -200.0,
                "maxDepth": capabilities.maxDepth or 200.0,
            }

            z_index = z_counter[0]
            z_counter[0] += 1

            collected.append(
                {
                    "id": layer_id,
                    "label": label,
                    "type": layer_type.value,
                    "bbox": _model_dump(bbox),
                    "defaultOrigin": {"x": bbox.cx, "y": bbox.cy},
                    "zIndex": z_index,
                    "tags": tags,
                    "aliases": aliases,
                    "capabilities": _model_dump(capabilities),
                    "fingerprint": fingerprint,
                    "children": child_ids,
                    "constraints": constraints,
                    "metadata": {
                        "tag": tag,
                        "parent": parent_id,
                        "attributeCount": len(node.attrib),
                    },
                }
            )
            return bbox

        z_counter = [0]
        visit(root, None, z_counter)
        return collected

    def compile(self, svg_text: str) -> CompileResult:
        root = ET.fromstring(svg_text)
        source_checksum = self.source_checksum(svg_text)
        generated_at = _iso_now()

        layer_rows = self._collect_layers(root)
        layer_rows_sorted = sorted(layer_rows, key=lambda item: item["zIndex"])

        full_layers: List[Dict[str, Any]] = []
        min_layers: List[Dict[str, Any]] = []
        for row in layer_rows_sorted:
            full_layers.append(dict(row))
            min_row = dict(row)
            min_row.pop("children", None)
            min_row.pop("constraints", None)
            min_row.pop("metadata", None)
            min_layers.append(min_row)

        layer_map_min = {
            "schemaVersion": "1.0",
            "compilerVersion": self.compiler_version,
            "sourceChecksum": source_checksum,
            "generatedAt": generated_at,
            "layerCount": len(min_layers),
            "layers": min_layers,
        }

        layer_map_full = {
            "schemaVersion": "1.0",
            "compilerVersion": self.compiler_version,
            "sourceChecksum": source_checksum,
            "generatedAt": generated_at,
            "layerCount": len(full_layers),
            "layers": full_layers,
        }

        layer_map_min = _model_dump(_model_validate(schemas.LayerMapMinDocument, layer_map_min))
        layer_map_full = _model_dump(_model_validate(schemas.LayerMapFullDocument, layer_map_full))

        compile_manifest = {
            "schemaVersion": "1.0",
            "compilerVersion": self.compiler_version,
            "sourceChecksum": source_checksum,
            "layerMapMinChecksum": _payload_checksum(layer_map_min),
            "layerMapFullChecksum": _payload_checksum(layer_map_full),
            "generatedAt": generated_at,
        }
        compile_manifest = _model_dump(_model_validate(schemas.CompileManifestDocument, compile_manifest))

        return CompileResult(
            layer_map_min=layer_map_min,
            layer_map_full=layer_map_full,
            compile_manifest=compile_manifest,
            recompile_required=True,
            recompile_reason="compiled",
        )

    def compile_to_directory(
        self,
        svg_text: str,
        output_dir: Path | str,
        previous_manifest: Optional[Dict[str, Any]] = None,
        manual_recompile: bool = False,
    ) -> CompileResult:
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)

        should_compile, reason = self.needs_recompile(
            svg_text=svg_text,
            previous_manifest=previous_manifest,
            manual_recompile=manual_recompile,
        )

        min_path = output_path / "layer_map_min.json"
        full_path = output_path / "layer_map_full.json"
        manifest_path = output_path / "compile_manifest.json"

        if not should_compile and min_path.exists() and full_path.exists() and manifest_path.exists():
            layer_map_min = json.loads(min_path.read_text(encoding="utf-8"))
            layer_map_full = json.loads(full_path.read_text(encoding="utf-8"))
            compile_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            return CompileResult(
                layer_map_min=layer_map_min,
                layer_map_full=layer_map_full,
                compile_manifest=compile_manifest,
                recompile_required=False,
                recompile_reason=reason,
            )

        result = self.compile(svg_text)
        min_path.write_text(json.dumps(result.layer_map_min, indent=4), encoding="utf-8")
        full_path.write_text(json.dumps(result.layer_map_full, indent=4), encoding="utf-8")
        manifest_path.write_text(json.dumps(result.compile_manifest, indent=4), encoding="utf-8")

        result.recompile_reason = reason or "compiled"
        return result
