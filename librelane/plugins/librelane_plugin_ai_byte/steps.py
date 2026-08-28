"""Custom OpenROAD steps for AI_BYTE LibreLane runs."""

from __future__ import annotations

import os

from librelane.steps import Step
from librelane.steps.openroad import GeneratePDN, RepairDesignPostGRT, ResizerTimingPostCTS


def _repo_script(*parts: str) -> str:
    path = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "..", "scripts", *parts)
    )
    if not os.path.isfile(path):
        raise FileNotFoundError(f"AI_BYTE Tcl not found: {path}")
    return path


@Step.factory.register()
class GeneratePDNWithConnectorStitch(GeneratePDN):
    """PDN generation plus west-edge vss_conn / vdd_conn Metal5+Metal2 bridges."""

    id = "AIByte.GeneratePDN"
    name = "Generate PDN (A02 connector stitch)"

    def get_script_path(self) -> str:
        return _repo_script("pdn_a02.tcl")


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
    Post-GRT repair: upsize max-slew drivers (replace_cell), then stock
    repair_design with GRT refresh/retry on RSZ-0074 (macro wrapper).
    """

    id = "AIByte.RepairDesignPostGRTSizeFirst"
    name = "Repair Design (Post-GRT, size-first)"

    def get_script_path(self) -> str:
        return _repo_script("repair_design_postgrt_size_first.tcl")
