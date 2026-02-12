from __future__ import annotations

from dataclasses import dataclass, field
import json
from typing import Any, Dict, List, Tuple

from svg_anim_demo.api import tools
from svg_anim_demo.api.runtime_service import RuntimeService


@dataclass
class OperatorController:
    runtime: RuntimeService = field(default_factory=RuntimeService)
    traces: List[Dict[str, Any]] = field(default_factory=list)

    def _record_trace(
        self,
        tool_name: str,
        payload: Dict[str, Any],
        result: Dict[str, Any],
        context: tools.ToolContext,
    ) -> None:
        self.traces.append(
            {
                "tool": tool_name,
                "payload": payload,
                "ok": bool(result.get("ok", False)),
                "error": result.get("error"),
                "budget": {
                    "subcalls": context.subcalls,
                    "depth": context.recursive_depth,
                    "responseChars": context.cumulative_response_chars,
                    "fallbackMode": context.fallback_mode,
                },
            }
        )
        if len(self.traces) > 100:
            self.traces = self.traces[-100:]

    def _call_tool(self, tool_name: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        ctx = tools.ToolContext()
        result = tools.dispatch_tool(
            tool_name=tool_name,
            payload=payload,
            handlers=tools.create_runtime_handlers(self.runtime),
            context=ctx,
        )
        self._record_trace(tool_name, payload, result, ctx)
        return result

    def compile_recompile(self, svg_text: str, force: bool) -> Tuple[str, str]:
        try:
            self.runtime.compile_svg(svg_text=svg_text, force=force)
            status = self.runtime.compile_status()
            return "ok", json.dumps(status, indent=2)
        except Exception as exc:  # pragma: no cover - defensive
            return "error", str(exc)

    def layer_inspector(self, limit: int, cursor: str, text_filter: str) -> Tuple[str, str]:
        payload: Dict[str, Any] = {"limit": int(limit)}
        if cursor.strip():
            payload["cursor"] = cursor.strip()
        if text_filter.strip():
            payload["filter"] = {"text": text_filter.strip()}

        result = self._call_tool("list_layers", payload)
        if not result.get("ok"):
            return json.dumps(result, indent=2), ""
        next_cursor = result.get("nextCursor") or ""
        return json.dumps(result["items"], indent=2), str(next_cursor)

    def state_view(self, layer_ids_csv: str) -> str:
        layer_ids = [item.strip() for item in layer_ids_csv.split(",") if item.strip()]
        payload: Dict[str, Any] = {"layerIds": layer_ids} if layer_ids else {}
        result = self._call_tool("get_layer_state", payload)
        return json.dumps(result, indent=2)

    def apply_transform(
        self,
        layer_id: str,
        x: float,
        y: float,
        scale: float,
        rotation: float,
        opacity: float,
        z: float,
    ) -> str:
        payload = {
            "layerId": layer_id,
            "props": {
                "x": float(x),
                "y": float(y),
                "scale": float(scale),
                "rotation": float(rotation),
                "opacity": float(opacity),
                "z": float(z),
            },
        }
        return json.dumps(self._call_tool("set_layer_state", payload), indent=2)

    def run_preset(self, layer_id: str, preset: str) -> str:
        try:
            result = self.runtime.run_preset_animation(layer_id, preset)
            return json.dumps({"ok": True, **result}, indent=2)
        except Exception as exc:
            return json.dumps({"ok": False, "error": str(exc)}, indent=2)

    def undo(self) -> str:
        return json.dumps({"ok": self.runtime.undo()}, indent=2)

    def redo(self) -> str:
        return json.dumps({"ok": self.runtime.redo()}, indent=2)

    def reconcile_now(self) -> str:
        result = self._call_tool("reconcile_state_from_dom", {"dryRun": False})
        return json.dumps(result, indent=2)

    def snapshot_preview(self, frames: int) -> Tuple[str, str]:
        snap = self._call_tool("render_snapshot", {})
        seq = self._call_tool("render_sequence", {"frames": int(frames)})
        if not snap.get("ok"):
            return "", json.dumps(snap, indent=2)
        return snap.get("png", ""), json.dumps(seq, indent=2)

    def timeline_log(self) -> str:
        return json.dumps(self.runtime.timeline_log(limit=30), indent=2)

    def diagnostics(self) -> str:
        data = {
            "runtime": self.runtime.diagnostics(),
            "traceCount": len(self.traces),
            "lastTraces": self.traces[-10:],
            "validationFailures": [trace for trace in self.traces if trace.get("error")],
        }
        return json.dumps(data, indent=2)

    def tool_runner(self, tool_name: str, payload_text: str) -> str:
        try:
            payload = json.loads(payload_text) if payload_text.strip() else {}
        except json.JSONDecodeError as exc:
            return json.dumps({"ok": False, "error": f"Invalid JSON: {exc}"}, indent=2)
        result = self._call_tool(tool_name, payload)
        return json.dumps(result, indent=2)


def create_app() -> Any:
    controller = OperatorController()

    try:
        import gradio as gr
    except Exception:
        # Minimal fallback in environments without gradio.
        return {
            "type": "operator-controller",
            "controller": controller,
            "note": "gradio is not available in this environment",
        }

    with gr.Blocks(title="svg_anim_demo Operator") as app:
        gr.Markdown("# svg_anim_demo Operator Console")

        with gr.Tab("Compile/Status"):
            svg_input = gr.Textbox(value=controller.runtime.svg_text, lines=10, label="SVG Source")
            force_recompile = gr.Checkbox(value=False, label="Force Recompile")
            compile_btn = gr.Button("Compile/Recompile")
            compile_state = gr.Textbox(label="Result", interactive=False)
            compile_status = gr.Code(label="Compile Status", language="json")
            compile_btn.click(controller.compile_recompile, inputs=[svg_input, force_recompile], outputs=[compile_state, compile_status])

        with gr.Tab("Layer Inspector"):
            limit = gr.Slider(1, 100, value=10, step=1, label="Page Size")
            cursor = gr.Textbox(value="", label="Cursor")
            filter_text = gr.Textbox(value="", label="Text Filter")
            list_btn = gr.Button("List Layers")
            layer_table = gr.Code(label="Layers", language="json")
            next_cursor = gr.Textbox(label="Next Cursor")
            list_btn.click(controller.layer_inspector, inputs=[limit, cursor, filter_text], outputs=[layer_table, next_cursor])

        with gr.Tab("State & Controls"):
            ids_csv = gr.Textbox(value="", label="Layer IDs CSV (optional)")
            get_state_btn = gr.Button("Get State")
            state_out = gr.Code(label="State", language="json")
            get_state_btn.click(controller.state_view, inputs=[ids_csv], outputs=[state_out])

            layer_id = gr.Textbox(value="title", label="Layer ID")
            x = gr.Number(value=0, label="x")
            y = gr.Number(value=0, label="y")
            scale = gr.Number(value=1, label="scale")
            rotation = gr.Number(value=0, label="rotation")
            opacity = gr.Number(value=1, label="opacity")
            z = gr.Number(value=0, label="z")
            apply_btn = gr.Button("Apply Transform")
            apply_out = gr.Code(label="Apply Result", language="json")
            apply_btn.click(controller.apply_transform, inputs=[layer_id, x, y, scale, rotation, opacity, z], outputs=[apply_out])

            preset = gr.Dropdown(choices=["slide_in_left", "pop", "lift"], value="slide_in_left", label="Preset")
            preset_btn = gr.Button("Run Preset")
            preset_out = gr.Code(label="Preset Result", language="json")
            preset_btn.click(controller.run_preset, inputs=[layer_id, preset], outputs=[preset_out])

            with gr.Row():
                undo_btn = gr.Button("Undo")
                redo_btn = gr.Button("Redo")
                reconcile_btn = gr.Button("Reconcile Now")
            history_out = gr.Code(label="History/Reconcile", language="json")
            undo_btn.click(controller.undo, outputs=[history_out])
            redo_btn.click(controller.redo, outputs=[history_out])
            reconcile_btn.click(controller.reconcile_now, outputs=[history_out])

        with gr.Tab("Timeline/Snapshot"):
            log_btn = gr.Button("Refresh Timeline Log")
            log_out = gr.Code(label="Timeline Log", language="json")
            log_btn.click(controller.timeline_log, outputs=[log_out])

            frames = gr.Slider(2, 12, value=3, step=1, label="Sequence Frames")
            snapshot_btn = gr.Button("Render Snapshot + Sequence")
            preview_img = gr.Image(label="Snapshot")
            seq_out = gr.Code(label="Sequence Result", language="json")
            snapshot_btn.click(controller.snapshot_preview, inputs=[frames], outputs=[preview_img, seq_out])

        with gr.Tab("Diagnostics"):
            tool_name = gr.Dropdown(
                choices=list(tools.TOOL_MODELS.keys()),
                value="get_layer_state",
                label="Tool",
            )
            tool_payload = gr.Code(value="{}", language="json", label="Payload")
            run_tool_btn = gr.Button("Run Tool")
            tool_result = gr.Code(label="Tool Result", language="json")
            run_tool_btn.click(controller.tool_runner, inputs=[tool_name, tool_payload], outputs=[tool_result])

            diag_btn = gr.Button("Refresh Diagnostics")
            diag_out = gr.Code(label="Diagnostics", language="json")
            diag_btn.click(controller.diagnostics, outputs=[diag_out])

    return app
