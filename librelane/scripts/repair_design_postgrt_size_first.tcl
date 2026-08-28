# Exp8a: post-GRT design repair — size-up slew drivers, then stock repair_design.
#
# Macro-only RSZ-0074 workaround: repair_design can abort when a newly inserted
# buffer is not yet in the global-route Steiner tree. On RSZ-0074 we refresh
# global routes and retry (core-sized designs complete without this).

source $::env(SCRIPTS_DIR)/openroad/common/io.tcl
source $::env(SCRIPTS_DIR)/openroad/common/resizer.tcl

read_current_odb

set_propagated_clock [all_clocks]

set_dont_touch_objects

source $::env(SCRIPTS_DIR)/openroad/common/set_rc.tcl

# replace_cell marks nets in OpenROAD's parasitics_invalid_ set. A full
# estimate_parasitics -global_routing does not clear that bookkeeping, and
# repair_design then aborts with EST-0104. -placement clears the invalid set;
# follow with -global_routing so STA sees route-based RC.
proc aibyte_estimate_grt_parasitics {} {
    estimate_parasitics -placement
    estimate_parasitics -global_routing
}

proc aibyte_refresh_grt {} {
    source $::env(SCRIPTS_DIR)/openroad/common/grt.tcl
    aibyte_estimate_grt_parasitics
}

source $::env(SCRIPTS_DIR)/openroad/common/grt.tcl
aibyte_estimate_grt_parasitics

proc aibyte_next_drive_cell { cell_name } {
    if { ![regexp {^(.*)_([0-9]+)$} $cell_name -> stem str] } {
        return ""
    }
    set str [expr { int($str) }]
    foreach c {2 3 4 8 12 16 20 32} {
        if { $c > $str } {
            set trial "${stem}_${c}"
            if { [llength [get_lib_cells -quiet $trial]] > 0 } {
                return $trial
            }
        }
    }
    return ""
}

proc aibyte_skip_inst { inst } {
    if { $inst eq "" } {
        return 1
    }
    set inst [lindex $inst 0]
    if { [catch { set ref [get_property $inst ref_name] }] } {
        return 1
    }
    if { [string match "*clkbuf*" $ref] || [string match "*dly*" $ref] } {
        return 1
    }
    return 0
}

proc aibyte_driver_inst { pin } {
    set pin [lindex $pin 0]
    if { [catch { set dir [get_property $pin direction] }] } {
        return ""
    }
    if { $dir eq "output" || $dir eq "inout" } {
        return [lindex [get_cells -of_objects $pin] 0]
    }
    set net [lindex [get_nets -of_objects $pin] 0]
    if { $net eq "" } {
        return ""
    }
    foreach p [get_pins -quiet -of_objects $net -filter {direction == output}] {
        set cell [lindex [get_cells -of_objects $p] 0]
        if { $cell ne "" } {
            return $cell
        }
    }
    return ""
}

# sta::check_slew_limits (SWIG) — bare check_slew_limits is not a Tcl command.
proc aibyte_max_slew_violator_pins {} {
    set viol_pins {}
    foreach corner [sta::corners] {
        if { [catch {
            set pins [sta::check_slew_limits NULL 1 $corner max]
        } err] } {
            puts "\[AI_BYTE Exp8a\] sta::check_slew_limits failed ($err)"
            continue
        }
        foreach p $pins {
            lappend viol_pins $p
        }
    }
    return [lsort -unique $viol_pins]
}

proc aibyte_replace_cell_upsize { inst {target ""} } {
    set inst [lindex $inst 0]
    if { $inst eq "" || [aibyte_skip_inst $inst] } {
        return 0
    }
    set cur [get_property $inst ref_name]
    if { $target eq "" } {
        set target [aibyte_next_drive_cell $cur]
    }
    if { $target eq "" || $target eq $cur } {
        return 0
    }
    set libcell [lindex [get_lib_cells -quiet $target] 0]
    if { $libcell eq "" } {
        puts "\[AI_BYTE Exp8a\] skip $inst: lib cell $target not found"
        return 0
    }
    set iname [get_full_name $inst]
    puts "\[AI_BYTE Exp8a\] hub upsize $iname : $cur -> $target"
    if { [catch { replace_cell $inst $libcell } err] } {
        puts "\[AI_BYTE Exp8a\] replace_cell failed on $iname: $err"
        return 0
    }
    return 1
}

# Post-route SS slew hubs (RUN_2026-08-28 max_ss checks.rpt). Upsize buf_1 -> buf_2
# before the generic violator scan so repair_design sees stronger drivers.
proc aibyte_upsize_named_slew_hubs {} {
    set hubs {
        {fanout1327 gf180mcu_fd_sc_mcu7t5v0__buf_2}
        {fanout1324 gf180mcu_fd_sc_mcu7t5v0__buf_2}
        {fanout1325 gf180mcu_fd_sc_mcu7t5v0__buf_2}
        {fanout1326 gf180mcu_fd_sc_mcu7t5v0__buf_2}
        {fanout1737 gf180mcu_fd_sc_mcu7t5v0__buf_2}
        {fanout2011 gf180mcu_fd_sc_mcu7t5v0__buf_2}
        {fanout2290 gf180mcu_fd_sc_mcu7t5v0__buf_2}
        {fanout2005 gf180mcu_fd_sc_mcu7t5v0__buf_2}
        {fanout1999 gf180mcu_fd_sc_mcu7t5v0__buf_2}
        {fanout1994 gf180mcu_fd_sc_mcu7t5v0__buf_2}
        {fanout2417 gf180mcu_fd_sc_mcu7t5v0__buf_2}
        {fanout1699 gf180mcu_fd_sc_mcu7t5v0__buf_2}
    }
    set resized 0
    foreach entry $hubs {
        lassign $entry iname target
        set inst [get_cells -quiet $iname]
        if { $inst eq "" } {
            puts "\[AI_BYTE Exp8a\] hub $iname not found (skipped)"
            continue
        }
        incr resized [aibyte_replace_cell_upsize $inst $target]
    }
    puts "\[AI_BYTE Exp8a\] Named hub upsize: $resized instance(s)"
    return $resized
}

proc aibyte_upsize_slew_drivers { {max_passes 3} } {
    set total_resized 0
    for { set pass 1 } { $pass <= $max_passes } { incr pass } {
        set viol_pins [aibyte_max_slew_violator_pins]
        if { [llength $viol_pins] == 0 } {
            puts "\[AI_BYTE Exp8a\] Pass $pass: no max-slew violators"
            break
        }

        set resized_this_pass 0
        set seen_insts [dict create]
        foreach pin $viol_pins {
            set inst [aibyte_driver_inst $pin]
            if { [aibyte_skip_inst $inst] } {
                continue
            }
            set iname [get_full_name $inst]
            if { [dict exists $seen_insts $iname] } {
                continue
            }
            dict set seen_insts $iname 1

            set cur [get_property $inst ref_name]
            set nxt [aibyte_next_drive_cell $cur]
            if { $nxt eq "" } {
                continue
            }
            set libcell [lindex [get_lib_cells -quiet $nxt] 0]
            if { $libcell eq "" } {
                continue
            }
            puts "\[AI_BYTE Exp8a\] upsize $iname : $cur -> $nxt"
            if { [catch { replace_cell $inst $libcell } err] } {
                puts "\[AI_BYTE Exp8a\] replace_cell failed on $iname: $err"
                continue
            }
            incr resized_this_pass
            incr total_resized
        }

        puts "\[AI_BYTE Exp8a\] Pass $pass: resized $resized_this_pass instance(s)"
        if { $resized_this_pass == 0 } {
            break
        }
        aibyte_estimate_grt_parasitics
    }
    puts "\[AI_BYTE Exp8a\] Size-up total: $total_resized instance(s)"
    return $total_resized
}

proc aibyte_repair_design_resilient { arg_list {max_attempts 6} } {
    for { set attempt 1 } { $attempt <= $max_attempts } { incr attempt } {
        puts "\[AI_BYTE Exp8a\] repair_design attempt $attempt/$max_attempts"
        if { ![catch { repair_design {*}$arg_list } err] } {
            puts "\[AI_BYTE Exp8a\] repair_design completed"
            return 0
        }
        if { ![string match *RSZ-0074* $err] } {
            return $err
        }
        puts "\[AI_BYTE Exp8a\] RSZ-0074 — refreshing global routes before retry"
        aibyte_refresh_grt
    }
    puts "\[AI_BYTE Exp8a\] WARNING: repair_design still failing RSZ-0074 after $max_attempts attempts"
    return "RSZ-0074"
}

puts "\[AI_BYTE Exp8a\] Size-first: upsize named slew hub buffers (buf_1 -> buf_2)"
set hub_resized [aibyte_upsize_named_slew_hubs]
if { $hub_resized > 0 } {
    aibyte_estimate_grt_parasitics
}

puts "\[AI_BYTE Exp8a\] Size-first: upsize remaining slew drivers via replace_cell"
aibyte_upsize_slew_drivers 3

# Re-GRT after upsizes so repair_design sees consistent routes.
aibyte_refresh_grt

puts "\[AI_BYTE Exp8a\] Follow-up repair_design (buffers allowed)"
set arg_list [list]
lappend arg_list -verbose
lappend arg_list -max_wire_length $::env(GRT_DESIGN_REPAIR_MAX_WIRE_LENGTH)
lappend arg_list -slew_margin $::env(GRT_DESIGN_REPAIR_MAX_SLEW_PCT)
lappend arg_list -cap_margin $::env(GRT_DESIGN_REPAIR_MAX_CAP_PCT)
if { [info exists ::env(GRT_DESIGN_REPAIR_MAX_UTILIZATION)] } {
    lappend arg_list -max_utilization $::env(GRT_DESIGN_REPAIR_MAX_UTILIZATION)
}

set repair_err [aibyte_repair_design_resilient $arg_list 6]
if { $repair_err ne 0 && $repair_err ne "RSZ-0074" } {
    error $repair_err
}

source $::env(SCRIPTS_DIR)/openroad/common/dpl.tcl
unset_dont_touch_objects
if { $::env(GRT_DESIGN_REPAIR_RUN_GRT) } {
    source $::env(SCRIPTS_DIR)/openroad/common/grt.tcl
}

write_views
