# Copyright 2026 AI_Byte
# Custom post-CTS timing repair: keep delay cells banned for setup buffering,
# then unset_dont_use delay cells only for hold repair.
#
# Requires EXTRA_EXCLUDED_CELLS to include gf180mcu_fd_sc_mcu7t5v0__dly*
# so repair_design / setup use buf_* instead of delay cells.
source $::env(SCRIPTS_DIR)/openroad/common/io.tcl
source $::env(SCRIPTS_DIR)/openroad/common/resizer.tcl

read_current_odb

set_propagated_clock [all_clocks]

set_dont_touch_objects

source $::env(SCRIPTS_DIR)/openroad/common/set_rc.tcl
estimate_parasitics -placement

set delay_cells "gf180mcu_fd_sc_mcu7t5v0__dly*"

set setup_args [list]
lappend setup_args -verbose
lappend setup_args -setup
lappend setup_args -setup_margin $::env(PL_RESIZER_SETUP_SLACK_MARGIN)
lappend setup_args -max_buffer_percent $::env(PL_RESIZER_SETUP_MAX_BUFFER_PCT)
append_if_not_flag setup_args PL_RESIZER_SETUP_BUFFERING -skip_buffering
append_if_not_flag setup_args PL_RESIZER_SETUP_BUFFER_REMOVAL -skip_buffer_removal
append_if_not_flag setup_args PL_RESIZER_SETUP_GATE_CLONING -skip_gate_cloning
append_if_exists_argument setup_args PL_RESIZER_SETUP_REPAIR_TNS_PCT -repair_tns
append_if_exists_argument setup_args PL_RESIZER_SETUP_MAX_UTIL_PCT -max_utilization

set hold_args [list]
lappend hold_args -verbose
lappend hold_args -hold
lappend hold_args -setup_margin $::env(PL_RESIZER_SETUP_SLACK_MARGIN)
lappend hold_args -hold_margin $::env(PL_RESIZER_HOLD_SLACK_MARGIN)
lappend hold_args -max_buffer_percent $::env(PL_RESIZER_HOLD_MAX_BUFFER_PCT)
append_if_flag hold_args PL_RESIZER_ALLOW_SETUP_VIOS -allow_setup_violations
append_if_exists_argument hold_args PL_RESIZER_HOLD_REPAIR_TNS_PCT -repair_tns
append_if_exists_argument hold_args PL_RESIZER_HOLD_MAX_UTIL_PCT -max_utilization

proc ai_byte_enable_hold_delay_cells {delay_cells} {
    puts "\[AI_BYTE\] unset_dont_use $delay_cells (allow delay cells for hold repair)"
    unset_dont_use $delay_cells
}

proc ai_byte_ban_delay_cells {delay_cells} {
    puts "\[AI_BYTE\] set_dont_use $delay_cells (ban delay cells again after hold)"
    set_dont_use $delay_cells
}

if { $::env(PL_RESIZER_FIX_HOLD_FIRST) == 1 } {
    ai_byte_enable_hold_delay_cells $delay_cells
    log_cmd repair_timing {*}$hold_args
    ai_byte_ban_delay_cells $delay_cells
    log_cmd repair_timing {*}$setup_args
} else {
    # Default: setup first while dly* remain dont_use (from EXTRA_EXCLUDED_CELLS)
    log_cmd repair_timing {*}$setup_args
    ai_byte_enable_hold_delay_cells $delay_cells
    log_cmd repair_timing {*}$hold_args
    ai_byte_ban_delay_cells $delay_cells
}

source $::env(SCRIPTS_DIR)/openroad/common/dpl.tcl

unset_dont_touch_objects

source $::env(SCRIPTS_DIR)/openroad/common/set_rc.tcl
estimate_parasitics -placement

write_views
