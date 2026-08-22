"""Custom OpenROAD steps for AI_BYTE LibreLane runs."""

from __future__ import annotations

import os

from librelane.steps import Step
from librelane.steps.openroad import RepairDesignPostGRT, ResizerTimingPostCTS


def _repo_script(*parts: str) -> str:
    path = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "..", "scripts", *parts)
    )
    if not os.path.isfile(path):
        raise FileNotFoundError(f"AI_BYTE Tcl not found: {path}")
    return path


@Step.factory.register()
class ResizerTimingPostCTSHoldDly(ResizerTimingPostCTS):
    """
    Post-CTS timing repair that keeps delay cells banned for setup, then
    temporarily unset_dont_use gf180mcu delay cells for hold repair only.
    """

    id = "AIByte.ResizerTimingPostCTSHoldDly"
    name = "Resizer Timing (Post-CTS, hold uses dly*)"

    def get_script_path(self) -> str:
        return _repo_script("rsz_timing_postcts_hold_dly.tcl")


@Step.factory.register()
class RepairDesignPostGRTSizeFirst(RepairDesignPostGRT):
    """
    Exp8a: post-GRT size-up of max-slew drivers via replace_cell, then
    normal repair_design. (Cannot ban all buf_* — OpenROAD RSZ-0022.)
    """

    id = "AIByte.RepairDesignPostGRTSizeFirst"
    name = "Repair Design (Post-GRT, size-first)"

    def get_script_path(self) -> str:
        return _repo_script("repair_design_postgrt_size_first.tcl")
