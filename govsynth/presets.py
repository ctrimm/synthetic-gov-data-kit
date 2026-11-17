"""Preset registry — maps preset names to fully configured pipeline configs.

A preset bundles: source class + constructor args + generator class + profile strategy.
This is the primary ergonomic entry point for most users.

Usage:
    from govsynth.presets import PRESETS
    config = PRESETS["snap.va"]
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class PresetConfig:
    """Configuration bundle for a Pipeline preset."""

    program: str
    source_class: str  # dotted import path
    source_kwargs: dict[str, Any]
    generator_class: str  # dotted import path
    generator_kwargs: dict[str, Any]
    profile_strategy: str = "edge_saturated"
    description: str = ""


# ---------------------------------------------------------------------------
# Preset registry
# ---------------------------------------------------------------------------

PRESETS: dict[str, PresetConfig] = {
    # ── SNAP ──────────────────────────────────────────────────────────────
    "snap.va": PresetConfig(
        program="snap",
        source_class="govsynth.sources.us.snap_bbce.SNAPBBCESource",
        source_kwargs={"fiscal_year": 2026, "state": "VA"},
        generator_class="govsynth.generators.snap_eligibility.SNAPEligibilityGenerator",
        generator_kwargs={"fiscal_year": 2026, "state": "VA"},
        profile_strategy="edge_saturated",
        description="Virginia SNAP FY2026 — BBCE (200% FPL gross, no asset test)",
    ),
    "snap.ca": PresetConfig(
        program="snap",
        source_class="govsynth.sources.us.snap_bbce.SNAPBBCESource",
        source_kwargs={"fiscal_year": 2026, "state": "CA"},
        generator_class="govsynth.generators.snap_eligibility.SNAPEligibilityGenerator",
        generator_kwargs={"fiscal_year": 2026, "state": "CA"},
        profile_strategy="edge_saturated",
        description="California SNAP FY2026 — BBCE (200% FPL gross, no asset test)",
    ),
    "snap.tx": PresetConfig(
        program="snap",
        source_class="govsynth.sources.us.snap_bbce.SNAPBBCESource",
        source_kwargs={"fiscal_year": 2026, "state": "TX"},
        generator_class="govsynth.generators.snap_eligibility.SNAPEligibilityGenerator",
        generator_kwargs={"fiscal_year": 2026, "state": "TX"},
        profile_strategy="edge_saturated",
        description="Texas SNAP FY2026 — BBCE (165% FPL gross, $5,000 asset cap)",
    ),
    "snap.md": PresetConfig(
        program="snap",
        source_class="govsynth.sources.us.snap_bbce.SNAPBBCESource",
        source_kwargs={"fiscal_year": 2026, "state": "MD"},
        generator_class="govsynth.generators.snap_eligibility.SNAPEligibilityGenerator",
        generator_kwargs={"fiscal_year": 2026, "state": "MD"},
        profile_strategy="edge_saturated",
        description="Maryland SNAP FY2026 — BBCE (200% FPL gross, no asset test)",
    ),
    # ── WIC ───────────────────────────────────────────────────────────────
    "wic.national": PresetConfig(
        program="wic",
        source_class="govsynth.sources.us.wic.WICSource",
        source_kwargs={"fiscal_year": 2026},
        generator_class="govsynth.generators.wic_eligibility.WICEligibilityGenerator",
        generator_kwargs={"fiscal_year": 2026},
        profile_strategy="edge_saturated",
        description="WIC FY2026 national income eligibility (185% FPL)",
    ),
    # ── Medicaid ──────────────────────────────────────────────────────────
    "medicaid.va": PresetConfig(
        program="medicaid",
        source_class="govsynth.sources.us.medicaid.MedicaidSource",
        source_kwargs={"calendar_year": 2026, "state": "VA"},
        generator_class="govsynth.generators.medicaid_eligibility.MedicaidEligibilityGenerator",
        generator_kwargs={"calendar_year": 2026, "state": "VA"},
        profile_strategy="edge_saturated",
        description="Virginia Medicaid CY2026 — ACA expansion state (adults to 138% FPL)",
    ),
    "medicaid.tx": PresetConfig(
        program="medicaid",
        source_class="govsynth.sources.us.medicaid.MedicaidSource",
        source_kwargs={"calendar_year": 2026, "state": "TX"},
        generator_class="govsynth.generators.medicaid_eligibility.MedicaidEligibilityGenerator",
        generator_kwargs={"calendar_year": 2026, "state": "TX"},
        profile_strategy="edge_saturated",
        description="Texas Medicaid CY2026 — non-expansion state (adult coverage gap)",
    ),
    # ── Medicare low-income help ─────────────────────────────────────────
    "medicare.national": PresetConfig(
        program="medicare",
        source_class="govsynth.sources.us.medicare.MedicareSource",
        source_kwargs={"calendar_year": 2026},
        generator_class="govsynth.generators.medicare_savings.MedicareSavingsGenerator",
        generator_kwargs={"calendar_year": 2026},
        profile_strategy="edge_saturated",
        description="Medicare Savings Programs (QMB/SLMB/QI) and Extra Help CY2026 — federal limits",
    ),
    # ── CHIP / children's Medicaid ───────────────────────────────────────
    "chip.va": PresetConfig(
        program="chip",
        source_class="govsynth.sources.us.chip.CHIPSource",
        source_kwargs={"calendar_year": 2026, "state": "VA"},
        generator_class="govsynth.generators.chip_eligibility.CHIPEligibilityGenerator",
        generator_kwargs={"calendar_year": 2026, "state": "VA"},
        profile_strategy="edge_saturated",
        description="Virginia children's Medicaid (148%) + separate CHIP (205%) CY2026",
    ),
    "chip.ca": PresetConfig(
        program="chip",
        source_class="govsynth.sources.us.chip.CHIPSource",
        source_kwargs={"calendar_year": 2026, "state": "CA"},
        generator_class="govsynth.generators.chip_eligibility.CHIPEligibilityGenerator",
        generator_kwargs={"calendar_year": 2026, "state": "CA"},
        profile_strategy="edge_saturated",
        description="California children's Medicaid + Medicaid-expansion CHIP (to 266%) CY2026",
    ),
    "chip.tx": PresetConfig(
        program="chip",
        source_class="govsynth.sources.us.chip.CHIPSource",
        source_kwargs={"calendar_year": 2026, "state": "TX"},
        generator_class="govsynth.generators.chip_eligibility.CHIPEligibilityGenerator",
        generator_kwargs={"calendar_year": 2026, "state": "TX"},
        profile_strategy="edge_saturated",
        description="Texas children's Medicaid + separate CHIP (206%) CY2026",
    ),
    "chip.md": PresetConfig(
        program="chip",
        source_class="govsynth.sources.us.chip.CHIPSource",
        source_kwargs={"calendar_year": 2026, "state": "MD"},
        generator_class="govsynth.generators.chip_eligibility.CHIPEligibilityGenerator",
        generator_kwargs={"calendar_year": 2026, "state": "MD"},
        profile_strategy="edge_saturated",
        description="Maryland children's Medicaid + Medicaid-expansion CHIP (to 322%) CY2026",
    ),
    # ── ACA premium tax credit ───────────────────────────────────────────
    "aca.va": PresetConfig(
        program="aca_ptc",
        source_class="govsynth.sources.us.aca_ptc.ACAPremiumTaxCreditSource",
        source_kwargs={"tax_year": 2026, "state": "VA"},
        generator_class="govsynth.generators.aca_ptc_eligibility.ACAPremiumTaxCreditGenerator",
        generator_kwargs={"tax_year": 2026, "state": "VA"},
        profile_strategy="edge_saturated",
        description="Virginia ACA premium tax credit TY2026 — expansion state (Medicaid to 138% FPL)",
    ),
    "aca.tx": PresetConfig(
        program="aca_ptc",
        source_class="govsynth.sources.us.aca_ptc.ACAPremiumTaxCreditSource",
        source_kwargs={"tax_year": 2026, "state": "TX"},
        generator_class="govsynth.generators.aca_ptc_eligibility.ACAPremiumTaxCreditGenerator",
        generator_kwargs={"tax_year": 2026, "state": "TX"},
        profile_strategy="edge_saturated",
        description="Texas ACA premium tax credit TY2026 — non-expansion state (credit from 100% FPL)",
    ),
    "aca.ca": PresetConfig(
        program="aca_ptc",
        source_class="govsynth.sources.us.aca_ptc.ACAPremiumTaxCreditSource",
        source_kwargs={"tax_year": 2026, "state": "CA"},
        generator_class="govsynth.generators.aca_ptc_eligibility.ACAPremiumTaxCreditGenerator",
        generator_kwargs={"tax_year": 2026, "state": "CA"},
        profile_strategy="edge_saturated",
        description="California ACA premium tax credit TY2026",
    ),
    "aca.md": PresetConfig(
        program="aca_ptc",
        source_class="govsynth.sources.us.aca_ptc.ACAPremiumTaxCreditSource",
        source_kwargs={"tax_year": 2026, "state": "MD"},
        generator_class="govsynth.generators.aca_ptc_eligibility.ACAPremiumTaxCreditGenerator",
        generator_kwargs={"tax_year": 2026, "state": "MD"},
        profile_strategy="edge_saturated",
        description="Maryland ACA premium tax credit TY2026",
    ),
    # ── TANF ─────────────────────────────────────────────────────────────
    "tanf.va": PresetConfig(
        program="tanf",
        source_class="govsynth.sources.us.tanf.TANFSource",
        source_kwargs={"state": "VA", "year": 2026},
        generator_class="govsynth.generators.tanf_eligibility.TANFEligibilityGenerator",
        generator_kwargs={"state": "VA", "year": 2026},
        profile_strategy="edge_saturated",
        description="Virginia TANF 2026 — standard of assistance by locality group (VDSS Ch. 300)",
    ),
    "tanf.md": PresetConfig(
        program="tanf",
        source_class="govsynth.sources.us.tanf.TANFSource",
        source_kwargs={"state": "MD", "year": 2026},
        generator_class="govsynth.generators.tanf_eligibility.TANFEligibilityGenerator",
        generator_kwargs={"state": "MD", "year": 2026},
        profile_strategy="edge_saturated",
        description="Maryland TCA 2026 — COMAR 07.03.03 with the January 2026 FIP schedule",
    ),
    "tanf.tx": PresetConfig(
        program="tanf",
        source_class="govsynth.sources.us.tanf.TANFSource",
        source_kwargs={"state": "TX", "year": 2026},
        generator_class="govsynth.generators.tanf_eligibility.TANFEligibilityGenerator",
        generator_kwargs={"state": "TX", "year": 2026},
        profile_strategy="edge_saturated",
        description="Texas TANF 2026 — budgetary and recognizable needs tests (TWH C-111 Rev. 26-4)",
    ),
    "tanf.ca": PresetConfig(
        program="tanf",
        source_class="govsynth.sources.us.tanf.TANFSource",
        source_kwargs={"state": "CA", "year": 2026},
        generator_class="govsynth.generators.tanf_eligibility.TANFEligibilityGenerator",
        generator_kwargs={"state": "CA", "year": 2026},
        profile_strategy="edge_saturated",
        description="California CalWORKs 2026 — MBSAC applicant test and October 2026 MAP",
    ),
    # ── LIHEAP ────────────────────────────────────────────────────────────
    "liheap.va": PresetConfig(
        program="liheap",
        source_class="govsynth.sources.us.liheap.LIHEAPSource",
        source_kwargs={"fiscal_year": 2026, "state": "VA"},
        generator_class="govsynth.generators.liheap_eligibility.LIHEAPEligibilityGenerator",
        generator_kwargs={"fiscal_year": 2026, "state": "VA"},
        profile_strategy="edge_saturated",
        description="Virginia LIHEAP FY2026 — 150% FPL heating/crisis, 60% SMI weatherization",
    ),
    "liheap.ca": PresetConfig(
        program="liheap",
        source_class="govsynth.sources.us.liheap.LIHEAPSource",
        source_kwargs={"fiscal_year": 2026, "state": "CA"},
        generator_class="govsynth.generators.liheap_eligibility.LIHEAPEligibilityGenerator",
        generator_kwargs={"fiscal_year": 2026, "state": "CA"},
        profile_strategy="edge_saturated",
        description="California LIHEAP FY2026 — 60% SMI for every component",
    ),
    "liheap.tx": PresetConfig(
        program="liheap",
        source_class="govsynth.sources.us.liheap.LIHEAPSource",
        source_kwargs={"fiscal_year": 2026, "state": "TX"},
        generator_class="govsynth.generators.liheap_eligibility.LIHEAPEligibilityGenerator",
        generator_kwargs={"fiscal_year": 2026, "state": "TX"},
        profile_strategy="edge_saturated",
        description="Texas LIHEAP FY2026 — 150% FPL for heating, cooling, crisis and weatherization",
    ),
    "liheap.md": PresetConfig(
        program="liheap",
        source_class="govsynth.sources.us.liheap.LIHEAPSource",
        source_kwargs={"fiscal_year": 2026, "state": "MD"},
        generator_class="govsynth.generators.liheap_eligibility.LIHEAPEligibilityGenerator",
        generator_kwargs={"fiscal_year": 2026, "state": "MD"},
        profile_strategy="edge_saturated",
        description="Maryland LIHEAP FY2026 — %SMI rate by household size + SNAP/TANF/SSI categorical eligibility",
    ),
    # ── SSI ───────────────────────────────────────────────────────────────
    "ssi.national": PresetConfig(
        program="ssi",
        source_class="govsynth.sources.us.ssi.SSISource",
        source_kwargs={"calendar_year": 2026},
        generator_class="govsynth.generators.ssi_eligibility.SSIEligibilityGenerator",
        generator_kwargs={"calendar_year": 2026},
        profile_strategy="edge_saturated",
        description="Federal SSI CY2026 — $994/$1,491 FBR, income exclusions, resources, SGA",
    ),
}


def list_presets() -> None:
    """Print all available presets with descriptions."""
    print(f"\n{'Preset':<22} {'Program':<10} {'Description'}")
    print("-" * 70)
    for name, cfg in sorted(PRESETS.items()):
        print(f"{name:<22} {cfg.program:<10} {cfg.description}")
    print()
