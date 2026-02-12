from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Dict, List, Optional

from svg_anim_demo.runtime.state_store import StateStore


def _iso_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


@dataclass
class RunRecord:
    run_id: str
    kind: str
    status: str
    started_at: str
    finished_at: Optional[str] = None
    steps: List[Dict[str, Any]] = field(default_factory=list)


class ExecutionEngine:
    """Deterministic animation command compiler/executor for Phase 5."""

    def __init__(self, store: StateStore) -> None:
        self.store = store
        self._counter = 0
        self.active_runs: Dict[str, RunRecord] = {}
        self.completed_runs: Dict[str, RunRecord] = {}

    def _next_run_id(self) -> str:
        self._counter += 1
        return f"run_{self._counter:06d}"

    def cancel_run(self, run_id: str) -> bool:
        run = self.active_runs.get(run_id)
        if run is None:
            return False
        run.status = "cancelled"
        run.finished_at = _iso_now()
        self.completed_runs[run_id] = run
        del self.active_runs[run_id]
        return True

    def _finish(self, run: RunRecord) -> None:
        run.status = "completed"
        run.finished_at = _iso_now()
        self.completed_runs[run.run_id] = run
        self.active_runs.pop(run.run_id, None)

    def run_set(self, layer_id: str, props: Dict[str, Any]) -> Dict[str, Any]:
        run = RunRecord(run_id=self._next_run_id(), kind="set", status="running", started_at=_iso_now())
        self.active_runs[run.run_id] = run

        applied = self.store.set(layer_id, props, propagate=True)
        run.steps.append({"layerId": layer_id, "action": "set", "props": applied})

        self._finish(run)
        return {
            "runId": run.run_id,
            "plannedEndState": self.store.get_layer_state(layer_id),
        }

    def run_animate(
        self,
        layer_id: str,
        from_props: Optional[Dict[str, float]],
        to_props: Dict[str, float],
        duration: float,
        ease: str,
        delay: float,
    ) -> Dict[str, Any]:
        run = RunRecord(run_id=self._next_run_id(), kind="animate_layer", status="running", started_at=_iso_now())
        self.active_runs[run.run_id] = run

        if from_props:
            self.store.set(layer_id, from_props, propagate=True)
            run.steps.append({"layerId": layer_id, "action": "from", "props": dict(from_props)})

        self.store.set(layer_id, dict(to_props), propagate=True)
        run.steps.append(
            {
                "layerId": layer_id,
                "action": "to",
                "props": dict(to_props),
                "duration": float(duration),
                "ease": str(ease),
                "delay": float(delay),
            }
        )

        self._finish(run)
        return {
            "runId": run.run_id,
            "plannedEndState": self.store.get_layer_state(layer_id),
        }

    def run_timeline(self, steps: List[Dict[str, Any]]) -> Dict[str, Any]:
        run = RunRecord(run_id=self._next_run_id(), kind="timeline", status="running", started_at=_iso_now())
        self.active_runs[run.run_id] = run

        for step in steps:
            layer_id = step["layerId"]
            from_props = step.get("from")
            to_props = step["to"]
            if from_props:
                self.store.set(layer_id, from_props, propagate=True)

            self.store.set(layer_id, to_props, propagate=True)
            run.steps.append(
                {
                    "layerId": layer_id,
                    "to": dict(to_props),
                    "duration": float(step.get("duration", 0.0)),
                    "ease": str(step.get("ease", "linear")),
                    "delay": float(step.get("delay", 0.0)),
                    "at": step.get("at"),
                }
            )

        self._finish(run)
        return {
            "runId": run.run_id,
            "stepCount": len(steps),
        }
