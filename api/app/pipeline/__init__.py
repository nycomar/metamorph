"""Pipeline (track A): stage image generation + evolution render.

Both stages move data through the shared ``CloudClient`` (``api/app/cloud.py``)
— no direct HTTP from this package — and load the API-format workflow graphs
from ``workflows/``, overriding only the node inputs documented in
``workflows/README.md``.
"""
from __future__ import annotations

from .evolve import EvolutionSpec, RenderResult, render_evolution
from .stages import StageSpec, StageTuning, build_stages

__all__ = [
    "StageSpec",
    "StageTuning",
    "EvolutionSpec",
    "RenderResult",
    "build_stages",
    "render_evolution",
]
