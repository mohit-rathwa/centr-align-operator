from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable


@dataclass(frozen=True)
class ToolContext:
    run_id: str
    goal: str
    state: dict[str, Any]
    simulate_failure: bool = False


@dataclass(frozen=True)
class ToolSpec:
    """Allowlisted capability. The planner cannot register new tools at runtime."""

    name: str
    description: str
    observation_key: str
    connector: str
    handler: Callable[[ToolContext], dict[str, Any]]


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, ToolSpec] = {}

    def add(self, spec: ToolSpec) -> None:
        if spec.name in self._tools:
            raise ValueError(f"Tool already registered: {spec.name}")
        self._tools[spec.name] = spec

    def get(self, name: str) -> ToolSpec | None:
        return self._tools.get(name)

    def require(self, name: str) -> ToolSpec:
        spec = self._tools.get(name)
        if spec is None:
            raise KeyError(name)
        return spec

    def names(self) -> list[str]:
        return list(self._tools)

    def descriptions(self) -> dict[str, str]:
        return {name: spec.description for name, spec in self._tools.items()}

    def public_catalog(self) -> list[dict[str, str]]:
        return [
            {
                "name": spec.name,
                "description": spec.description,
                "connector": spec.connector,
                "observation_key": spec.observation_key,
            }
            for spec in self._tools.values()
        ]


registry = ToolRegistry()
