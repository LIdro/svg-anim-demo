from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Optional, Tuple, Type

from pydantic import BaseModel, ValidationError

from svg_anim_demo.api import schemas
from svg_anim_demo.api.runtime_service import RuntimeService
from svg_anim_demo.services import config


RequestModel = Type[BaseModel]
ResponseModel = Type[BaseModel]
ToolHandler = Callable[[BaseModel, "ToolContext"], BaseModel | Dict[str, Any]]


@dataclass
class ToolContext:
    recursive_depth: int = 0
    subcalls: int = 0
    started_at_ms: int = field(default_factory=lambda: int(time.time() * 1000))
    cumulative_response_chars: int = 0
    fallback_mode: bool = False


TOOL_MODELS: Dict[str, Tuple[RequestModel, Optional[ResponseModel]]] = {
    "get_layer_map": (schemas.GetLayerMapRequest, schemas.GetLayerMapResponse),
    "list_layers": (schemas.ListLayersRequest, schemas.ListLayersResponse),
    "get_layer_state": (schemas.GetLayerStateRequest, schemas.GetLayerStateResponse),
    "set_layer_state": (schemas.SetLayerStateRequest, schemas.SetLayerStateResponse),
    "set_origin": (schemas.SetOriginRequest, schemas.SetOriginResponse),
    "animate_layer": (schemas.AnimateLayerRequest, schemas.AnimateLayerResponse),
    "timeline": (schemas.TimelineRequest, schemas.TimelineResponse),
    "render_snapshot": (schemas.RenderSnapshotRequest, schemas.RenderSnapshotResponse),
    "render_sequence": (schemas.RenderSequenceRequest, schemas.RenderSequenceResponse),
    "get_layer_detail": (schemas.GetLayerDetailRequest, schemas.GetLayerDetailResponse),
    "reconcile_state_from_dom": (schemas.ReconcileStateRequest, schemas.ReconcileStateResponse),
    "set_layer_depth": (schemas.SetLayerDepthRequest, schemas.SetLayerDepthResponse),
    "animate_layer_depth": (schemas.AnimateLayerDepthRequest, schemas.AnimateLayerDepthResponse),
    "set_effect_layer": (schemas.SetEffectLayerRequest, schemas.SetEffectLayerResponse),
    "set_jitter": (schemas.SetJitterRequest, schemas.SetJitterResponse),
}


def _model_validate(model: Type[BaseModel], payload: Dict[str, Any]) -> BaseModel:
    if hasattr(model, "model_validate"):
        return model.model_validate(payload)
    return model.parse_obj(payload)


def _model_dump(instance: BaseModel) -> Dict[str, Any]:
    if hasattr(instance, "model_dump"):
        return instance.model_dump(by_alias=True)
    return instance.dict(by_alias=True)


def _validation_error(tool_name: str, exc: ValidationError) -> schemas.ToolErrorResponse:
    details = []
    for err in exc.errors():
        loc = [str(part) for part in err.get("loc", ())]
        details.append(
            {
                "path": ".".join(loc) if loc else "$",
                "type": err.get("type", "validation_error"),
                "message": err.get("msg", "Invalid value"),
            }
        )

    details = sorted(details, key=lambda item: (item["path"], item["type"], item["message"]))
    return schemas.ToolErrorResponse(
        error=schemas.ToolError(
            code="VALIDATION_ERROR",
            message=f"Invalid payload for tool '{tool_name}'",
            details=details,
        )
    )


def _tool_error(code: str, message: str, details: Optional[list[dict[str, Any]]] = None) -> schemas.ToolErrorResponse:
    return schemas.ToolErrorResponse(
        error=schemas.ToolError(code=code, message=message, details=details or [])
    )


def _enforce_context_budgets(ctx: ToolContext) -> Optional[schemas.ToolErrorResponse]:
    if ctx.recursive_depth > config.MAX_RECURSIVE_DEPTH:
        return _tool_error(
            code="RECURSION_LIMIT_EXCEEDED",
            message="Maximum recursive depth exceeded",
            details=[{"limit": config.MAX_RECURSIVE_DEPTH, "actual": ctx.recursive_depth}],
        )

    elapsed = int(time.time() * 1000) - ctx.started_at_ms
    if elapsed > config.TOOL_TIMEOUT_MS:
        return _tool_error(
            code="TOOL_TIMEOUT",
            message="Tool execution timeout",
            details=[{"limit": config.TOOL_TIMEOUT_MS, "elapsed": elapsed}],
        )

    return None


def _enforce_response_budget(payload: Dict[str, Any], ctx: ToolContext) -> Optional[schemas.ToolErrorResponse]:
    raw = json.dumps(payload, separators=(",", ":"), ensure_ascii=True)
    response_chars = len(raw)
    if response_chars > config.MAX_TOOL_RESPONSE_CHARS:
        return _tool_error(
            code="RESPONSE_BUDGET_EXCEEDED",
            message="Tool response exceeds max size budget",
            details=[{"limit": config.MAX_TOOL_RESPONSE_CHARS, "actual": response_chars}],
        )

    ctx.cumulative_response_chars += response_chars
    return None


def create_runtime_handlers(runtime: RuntimeService) -> Dict[str, ToolHandler]:
    def get_layer_map_handler(request: BaseModel, ctx: ToolContext) -> Dict[str, Any]:
        req = request
        layer_map = runtime.get_layer_map(include_full=bool(getattr(req, "includeFull", False)))
        # Phase 4 default: map tiering uses min map response model.
        if getattr(req, "includeFull", False):
            layer_map = runtime.get_layer_map(include_full=False)
        return {"ok": True, "map": layer_map}

    def list_layers_handler(request: BaseModel, ctx: ToolContext) -> Dict[str, Any]:
        req = request
        listed = runtime.list_layers(layer_filter=req.filter, limit=req.limit, cursor=req.cursor)
        return {"ok": True, "items": listed["items"], "nextCursor": listed["nextCursor"]}

    def get_layer_state_handler(request: BaseModel, ctx: ToolContext) -> Dict[str, Any]:
        req = request
        state_doc = runtime.get_layer_state(layer_ids=req.layerIds)
        return {"ok": True, "state": state_doc}

    def set_layer_state_handler(request: BaseModel, ctx: ToolContext) -> Dict[str, Any]:
        req = request
        try:
            result = runtime.set_layer_state(req.layerId, req.props)
        except KeyError:
            raise ValueError(f"Unknown layer '{req.layerId}'")
        except PermissionError as exc:
            raise ValueError(str(exc))
        return {"ok": True, "layerId": req.layerId, "applied": result["applied"]}

    def set_origin_handler(request: BaseModel, ctx: ToolContext) -> Dict[str, Any]:
        req = request
        try:
            resolved = runtime.set_origin(req.layerId, req.origin)
        except KeyError:
            raise ValueError(f"Unknown layer '{req.layerId}'")
        return {"ok": True, "layerId": req.layerId, "origin": resolved}

    def animate_layer_handler(request: BaseModel, ctx: ToolContext) -> Dict[str, Any]:
        req = request
        try:
            result = runtime.animate_layer(
                layer_id=req.layerId,
                from_props=req.from_,
                to_props=req.to,
                duration=req.duration,
                ease=req.ease,
                delay=req.delay,
                fallback=ctx.fallback_mode,
            )
        except KeyError:
            raise ValueError(f"Unknown layer '{req.layerId}'")
        except PermissionError as exc:
            raise ValueError(str(exc))
        return {"ok": True, "runId": result["runId"], "plannedEndState": result["plannedEndState"]}

    def timeline_handler(request: BaseModel, ctx: ToolContext) -> Dict[str, Any]:
        req = request
        raw_steps = [_model_dump(step) for step in req.steps]
        try:
            result = runtime.timeline(raw_steps, fallback=ctx.fallback_mode)
        except KeyError as exc:
            raise ValueError(f"Unknown layer '{exc.args[0]}'")
        except PermissionError as exc:
            raise ValueError(str(exc))
        return {"ok": True, "runId": result["runId"], "stepCount": result["stepCount"]}

    def render_snapshot_handler(request: BaseModel, ctx: ToolContext) -> Dict[str, Any]:
        req = request
        png = runtime.render_snapshot(size=req.size, background=req.background, layers=req.layers)
        return {"ok": True, "png": png}

    def render_sequence_handler(request: BaseModel, ctx: ToolContext) -> Dict[str, Any]:
        req = request
        frames = runtime.render_sequence(frames=req.frames, size=req.size, background=req.background, layers=req.layers)
        return {"ok": True, "frames": frames}

    def get_layer_detail_handler(request: BaseModel, ctx: ToolContext) -> Dict[str, Any]:
        req = request
        try:
            layer = runtime.get_layer_detail(req.layerId)
        except KeyError:
            raise ValueError(f"Unknown layer '{req.layerId}'")
        return {"ok": True, "layer": layer}

    def reconcile_handler(request: BaseModel, ctx: ToolContext) -> Dict[str, Any]:
        req = request
        changed = runtime.reconcile(dry_run=req.dryRun)
        return {"ok": True, "changedLayerIds": changed}

    def set_layer_depth_handler(request: BaseModel, ctx: ToolContext) -> Dict[str, Any]:
        req = request
        try:
            z = runtime.set_layer_depth(req.layerId, req.z)
        except KeyError:
            raise ValueError(f"Unknown layer '{req.layerId}'")
        except PermissionError as exc:
            raise ValueError(str(exc))
        return {"ok": True, "layerId": req.layerId, "z": z}

    def animate_layer_depth_handler(request: BaseModel, ctx: ToolContext) -> Dict[str, Any]:
        req = request
        try:
            result = runtime.animate_layer_depth(
                layer_id=req.layerId,
                from_depth=req.from_,
                to_depth=req.to,
                duration=req.duration,
                ease=req.ease,
                fallback=ctx.fallback_mode,
            )
        except KeyError:
            raise ValueError(f"Unknown layer '{req.layerId}'")
        except PermissionError as exc:
            raise ValueError(str(exc))
        return {"ok": True, "runId": result["runId"], "plannedEndState": result["plannedEndState"]}

    def set_effect_handler(request: BaseModel, ctx: ToolContext) -> Dict[str, Any]:
        req = request
        try:
            effect = runtime.set_effect_layer(req.layerId, req.effect)
        except KeyError:
            raise ValueError(f"Unknown layer '{req.layerId}'")
        except PermissionError as exc:
            raise ValueError(str(exc))
        return {"ok": True, "layerId": req.layerId, "effect": effect}

    def set_jitter_handler(request: BaseModel, ctx: ToolContext) -> Dict[str, Any]:
        req = request
        try:
            jitter = runtime.set_jitter(req.layerId, req.seed, req.maxXY, req.maxZ, req.pointLimit)
        except KeyError:
            raise ValueError(f"Unknown layer '{req.layerId}'")
        except PermissionError as exc:
            raise ValueError(str(exc))
        return {"ok": True, "layerId": req.layerId, "jitter": jitter}

    return {
        "get_layer_map": get_layer_map_handler,
        "list_layers": list_layers_handler,
        "get_layer_state": get_layer_state_handler,
        "set_layer_state": set_layer_state_handler,
        "set_origin": set_origin_handler,
        "animate_layer": animate_layer_handler,
        "timeline": timeline_handler,
        "render_snapshot": render_snapshot_handler,
        "render_sequence": render_sequence_handler,
        "get_layer_detail": get_layer_detail_handler,
        "reconcile_state_from_dom": reconcile_handler,
        "set_layer_depth": set_layer_depth_handler,
        "animate_layer_depth": animate_layer_depth_handler,
        "set_effect_layer": set_effect_handler,
        "set_jitter": set_jitter_handler,
    }


DEFAULT_RUNTIME = RuntimeService()
DEFAULT_HANDLERS = create_runtime_handlers(DEFAULT_RUNTIME)


def dispatch_tool(
    tool_name: str,
    payload: Dict[str, Any],
    handlers: Optional[Dict[str, ToolHandler]] = None,
    context: Optional[ToolContext] = None,
) -> Dict[str, Any]:
    if tool_name not in TOOL_MODELS:
        return _model_dump(_tool_error("UNKNOWN_TOOL", f"Unknown tool '{tool_name}'"))

    request_model, response_model = TOOL_MODELS[tool_name]
    ctx = context or ToolContext()
    ctx.subcalls += 1

    budget_error = _enforce_context_budgets(ctx)
    if budget_error:
        return _model_dump(budget_error)

    try:
        request_obj = _model_validate(request_model, payload)
    except ValidationError as exc:
        return _model_dump(_validation_error(tool_name, exc))

    if tool_name == "list_layers" and getattr(request_obj, "limit", 0) > config.MAX_LIST_LAYERS_LIMIT:
        return _model_dump(
            _tool_error(
                "LIST_LIMIT_EXCEEDED",
                "Requested limit exceeds configured maximum",
                [{"limit": config.MAX_LIST_LAYERS_LIMIT, "actual": request_obj.limit}],
            )
        )

    active_handlers = handlers or DEFAULT_HANDLERS

    if ctx.subcalls > config.MAX_SUBCALLS_PER_REQUEST:
        if tool_name in {"animate_layer", "timeline", "animate_layer_depth"}:
            ctx.fallback_mode = True
        else:
            return _model_dump(
                _tool_error(
                    code="SUBCALL_LIMIT_EXCEEDED",
                    message="Maximum sub-calls per request exceeded",
                    details=[{"limit": config.MAX_SUBCALLS_PER_REQUEST, "actual": ctx.subcalls}],
                )
            )

    handler = active_handlers.get(tool_name)
    if handler is None:
        return _model_dump(
            _tool_error(
                code="NOT_IMPLEMENTED",
                message=f"Tool '{tool_name}' has no runtime handler",
            )
        )

    try:
        raw_result = handler(request_obj, ctx)
    except ValueError as exc:
        return _model_dump(_tool_error("CONSTRAINT_VIOLATION", str(exc)))

    if isinstance(raw_result, BaseModel):
        result_obj = raw_result
    else:
        if response_model is None:
            result_obj = schemas.ToolSuccessResponse()
        else:
            try:
                result_obj = _model_validate(response_model, raw_result)
            except ValidationError as exc:
                return _model_dump(_validation_error(tool_name, exc))

    result_dump = _model_dump(result_obj)
    response_budget_error = _enforce_response_budget(result_dump, ctx)
    if response_budget_error:
        return _model_dump(response_budget_error)

    return result_dump


def get_layer_map(payload: Dict[str, Any], **kwargs: Any) -> Dict[str, Any]:
    return dispatch_tool("get_layer_map", payload, **kwargs)


def list_layers(payload: Dict[str, Any], **kwargs: Any) -> Dict[str, Any]:
    return dispatch_tool("list_layers", payload, **kwargs)


def get_layer_state(payload: Dict[str, Any], **kwargs: Any) -> Dict[str, Any]:
    return dispatch_tool("get_layer_state", payload, **kwargs)


def set_layer_state(payload: Dict[str, Any], **kwargs: Any) -> Dict[str, Any]:
    return dispatch_tool("set_layer_state", payload, **kwargs)


def set_origin(payload: Dict[str, Any], **kwargs: Any) -> Dict[str, Any]:
    return dispatch_tool("set_origin", payload, **kwargs)


def animate_layer(payload: Dict[str, Any], **kwargs: Any) -> Dict[str, Any]:
    return dispatch_tool("animate_layer", payload, **kwargs)


def timeline(payload: Dict[str, Any], **kwargs: Any) -> Dict[str, Any]:
    return dispatch_tool("timeline", payload, **kwargs)


def render_snapshot(payload: Dict[str, Any], **kwargs: Any) -> Dict[str, Any]:
    return dispatch_tool("render_snapshot", payload, **kwargs)


def render_sequence(payload: Dict[str, Any], **kwargs: Any) -> Dict[str, Any]:
    return dispatch_tool("render_sequence", payload, **kwargs)


def get_layer_detail(payload: Dict[str, Any], **kwargs: Any) -> Dict[str, Any]:
    return dispatch_tool("get_layer_detail", payload, **kwargs)


def reconcile_state_from_dom(payload: Dict[str, Any], **kwargs: Any) -> Dict[str, Any]:
    return dispatch_tool("reconcile_state_from_dom", payload, **kwargs)


def set_layer_depth(payload: Dict[str, Any], **kwargs: Any) -> Dict[str, Any]:
    return dispatch_tool("set_layer_depth", payload, **kwargs)


def animate_layer_depth(payload: Dict[str, Any], **kwargs: Any) -> Dict[str, Any]:
    return dispatch_tool("animate_layer_depth", payload, **kwargs)


def set_effect_layer(payload: Dict[str, Any], **kwargs: Any) -> Dict[str, Any]:
    return dispatch_tool("set_effect_layer", payload, **kwargs)


def set_jitter(payload: Dict[str, Any], **kwargs: Any) -> Dict[str, Any]:
    return dispatch_tool("set_jitter", payload, **kwargs)
