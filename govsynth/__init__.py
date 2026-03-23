"""synthetic-gov-data-kit — govsynth package.

Generate structured synthetic US government benefits data for LLM reasoning evaluation.
Part of the CivBench open source ecosystem.

Quick start:
    from govsynth import Pipeline

    pipeline = Pipeline.from_preset("snap.va")
    cases = pipeline.generate(n=100, seed=42)
    pipeline.save(cases, "./output/", formats=["civbench_yaml", "jsonl", "csv"])
"""

from govsynth.pipeline import BatchPipeline, Pipeline
from govsynth.presets import PRESETS, list_presets
from govsynth.models import (
    Difficulty,
    OutputFormat,
    PolicyCitation,
    ProfileStrategy,
    Program,
    RationaleTrace,
    ReasoningStep,
    ScenarioBlock,
    TaskBlock,
    TaskType,
    TestCase,
)
from govsynth.fiscal_year import (
    FiscalYearConfig,
    current_federal_fy,
    fpl_year_for_program,
    DEFAULT_SNAP_FY,
    DEFAULT_WIC_FY,
    DEFAULT_MEDICAID_CY,
)

__version__ = "0.1.0"

__all__ = [
    # Top-level API
    "Pipeline",
    "BatchPipeline",
    "PRESETS",
    "list_presets",
    # Models
    "TestCase",
    "ScenarioBlock",
    "TaskBlock",
    "RationaleTrace",
    "ReasoningStep",
    "PolicyCitation",
    # Enums
    "Difficulty",
    "OutputFormat",
    "ProfileStrategy",
    "Program",
    "TaskType",
    # Fiscal year utilities
    "FiscalYearConfig",
    "current_federal_fy",
    "fpl_year_for_program",
    "DEFAULT_SNAP_FY",
    "DEFAULT_WIC_FY",
    "DEFAULT_MEDICAID_CY",
]

# Evaluation
from govsynth.evaluation import RationaleEvaluator, RationaleScore
