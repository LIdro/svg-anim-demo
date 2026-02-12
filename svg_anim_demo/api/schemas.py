from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field


class LayerType(str, Enum):
    text = "text"
    shape = "shape"
    group = "group"
    image = "image"
    unknown = "unknown"


class LayerStatus(str, Enum):
    idle = "idle"
    animating = "animating"
    locked = "locked"


class BBox(BaseModel):
    model_config = ConfigDict(extra="forbid")

    x: float
    y: float
    width: float
    height: float
    cx: float
    cy: float


class Origin(BaseModel):
    model_config = ConfigDict(extra="forbid")

    x: float
    y: float


class LayerCapabilities(BaseModel):
    model_config = ConfigDict(extra="forbid")

    move: bool = False
    scale: bool = False
    rotate: bool = False
    opacity: bool = False
    depth: bool = False
    effect: bool = False
    jitter: bool = False
    maxRotation: Optional[float] = None
    minDepth: Optional[float] = None
    maxDepth: Optional[float] = None


class LayerMapItemMin(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    label: str
    type: LayerType = LayerType.unknown
    bbox: BBox
    defaultOrigin: Optional[Origin] = None
    zIndex: int
    tags: List[str] = Field(default_factory=list)
    aliases: List[str] = Field(default_factory=list)
    capabilities: LayerCapabilities = Field(default_factory=LayerCapabilities)
    fingerprint: str


class LayerMapItemFull(LayerMapItemMin):
    children: List[str] = Field(default_factory=list)
    constraints: Dict[str, float | int | bool] = Field(default_factory=dict)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class LayerMapMinDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schemaVersion: str = "1.0"
    compilerVersion: str
    sourceChecksum: str
    generatedAt: str
    layerCount: int
    layers: List[LayerMapItemMin]


class LayerMapFullDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schemaVersion: str = "1.0"
    compilerVersion: str
    sourceChecksum: str
    generatedAt: str
    layerCount: int
    layers: List[LayerMapItemFull]


class CompileManifestDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schemaVersion: str = "1.0"
    compilerVersion: str
    sourceChecksum: str
    layerMapMinChecksum: str
    layerMapFullChecksum: str
    generatedAt: str


class LayerRuntimeState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    x: float = 0.0
    y: float = 0.0
    scale: float = 1.0
    rotation: float = 0.0
    opacity: float = Field(default=1.0, ge=0.0, le=1.0)
    visible: bool = True
    origin: Optional[Origin] = None
    status: LayerStatus = LayerStatus.idle
    lastUpdate: str
    z: float = 0.0


class LayerStateDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schemaVersion: str = "1.0"
    timestamp: str
    layers: Dict[str, LayerRuntimeState]


class ToolError(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    message: str
    details: List[Dict[str, Any]] = Field(default_factory=list)


class ToolErrorResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ok: bool = False
    error: ToolError


class ToolSuccessResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ok: bool = True


class EmptyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


class GetLayerMapRequest(EmptyRequest):
    refresh: bool = False
    includeFull: bool = False


class GetLayerMapResponse(ToolSuccessResponse):
    map: LayerMapMinDocument


class ListLayersRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    filter: Optional[Dict[str, Any]] = None
    limit: int = Field(default=25, ge=1)
    cursor: Optional[str] = None


class ListLayersResponse(ToolSuccessResponse):
    items: List[LayerMapItemMin]
    nextCursor: Optional[str] = None


class GetLayerStateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    layerIds: Optional[List[str]] = None


class GetLayerStateResponse(ToolSuccessResponse):
    state: LayerStateDocument


class SetLayerStateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    layerId: str
    props: Dict[str, Any]


class SetLayerStateResponse(ToolSuccessResponse):
    layerId: str
    applied: Dict[str, Any]


class SetOriginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    layerId: str
    origin: Origin | str


class SetOriginResponse(ToolSuccessResponse):
    layerId: str
    origin: Origin


class AnimateLayerRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    layerId: str
    from_: Optional[Dict[str, float]] = Field(default=None, alias="from")
    to: Dict[str, float]
    duration: float = Field(gt=0)
    ease: str
    delay: float = Field(default=0.0, ge=0.0)


class AnimateLayerResponse(ToolSuccessResponse):
    runId: str
    plannedEndState: Dict[str, Any]


class TimelineStep(BaseModel):
    model_config = ConfigDict(extra="forbid")

    layerId: str
    from_: Optional[Dict[str, float]] = Field(default=None, alias="from")
    to: Dict[str, float]
    duration: float = Field(gt=0)
    ease: str
    delay: float = Field(default=0.0, ge=0.0)
    at: Optional[str | float] = None


class TimelineRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    steps: List[TimelineStep] = Field(min_length=1)


class TimelineResponse(ToolSuccessResponse):
    runId: str
    stepCount: int


class RenderSnapshotRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    size: Optional[Dict[str, int]] = None
    background: Optional[str] = None
    layers: Optional[List[str]] = None


class RenderSnapshotResponse(ToolSuccessResponse):
    png: str


class RenderSequenceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    frames: int = Field(ge=2, le=12)
    size: Optional[Dict[str, int]] = None
    background: Optional[str] = None
    layers: Optional[List[str]] = None


class RenderSequenceResponse(ToolSuccessResponse):
    frames: List[str]


class GetLayerDetailRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    layerId: str


class GetLayerDetailResponse(ToolSuccessResponse):
    layer: LayerMapItemFull


class ReconcileStateRequest(EmptyRequest):
    dryRun: bool = False


class ReconcileStateResponse(ToolSuccessResponse):
    changedLayerIds: List[str]


class SetLayerDepthRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    layerId: str
    z: float


class SetLayerDepthResponse(ToolSuccessResponse):
    layerId: str
    z: float


class AnimateLayerDepthRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    layerId: str
    from_: Optional[float] = Field(default=None, alias="from")
    to: float
    duration: float = Field(gt=0)
    ease: str


class AnimateLayerDepthResponse(ToolSuccessResponse):
    runId: str
    plannedEndState: Dict[str, Any]


class SetEffectLayerRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    layerId: str
    effect: Dict[str, Any]


class SetEffectLayerResponse(ToolSuccessResponse):
    layerId: str
    effect: Dict[str, Any]


class SetJitterRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    layerId: str
    seed: int
    maxXY: float = Field(ge=0)
    maxZ: float = Field(ge=0)
    pointLimit: int = Field(ge=1)


class SetJitterResponse(ToolSuccessResponse):
    layerId: str
    jitter: Dict[str, Any]
