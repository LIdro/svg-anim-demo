from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    compiler_version: str = os.getenv("SVG_ANIM_COMPILER_VERSION", "0.1.0")
    tool_timeout_ms: int = int(os.getenv("SVG_ANIM_TOOL_TIMEOUT_MS", "3000"))
    max_tool_response_chars: int = int(os.getenv("SVG_ANIM_MAX_TOOL_RESPONSE_CHARS", "12000"))
    max_list_layers_limit: int = int(os.getenv("SVG_ANIM_MAX_LIST_LAYERS_LIMIT", "100"))
    max_recursive_depth: int = int(os.getenv("SVG_ANIM_MAX_RECURSIVE_DEPTH", "4"))
    max_subcalls_per_request: int = int(os.getenv("SVG_ANIM_MAX_SUBCALLS_PER_REQUEST", "12"))


settings = Settings()

MAX_TOOL_RESPONSE_CHARS = settings.max_tool_response_chars
MAX_LIST_LAYERS_LIMIT = settings.max_list_layers_limit
MAX_RECURSIVE_DEPTH = settings.max_recursive_depth
MAX_SUBCALLS_PER_REQUEST = settings.max_subcalls_per_request
TOOL_TIMEOUT_MS = settings.tool_timeout_ms
