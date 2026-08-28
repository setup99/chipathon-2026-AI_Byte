# A02 PDN: stock pdngen + west-edge connector stitch before PSM check.

source $::env(SCRIPTS_DIR)/openroad/common/io.tcl
read_current_odb

source $::env(SCRIPTS_DIR)/openroad/common/set_power_nets.tcl

read_pdn_cfg

set arg_list [list]
if { $::env(PDN_SKIPTRIM) } {
    lappend arg_list -skip_trim
}

if {[catch {log_cmd pdngen {*}$arg_list} errmsg]} {
    puts stderr $errmsg
    exit_unless_gui 1
}

source [file join [file dirname [info script]] stitch_a02_connectors.tcl]
a02_stitch_connectors

# The organizer DEF fixes the outline at 1110x1110 um; power metal beyond it
# has nowhere to go once this macro is dropped into the top level.
proc a02_assert_pdn_inside_die {} {
    set block [ord::get_db_block]
    set die [$block getDieArea]
    set dbu [expr {double([$block getDbUnitsPerMicron])}]
    set bad 0

    foreach net [$block getNets] {
        if { ![$net isSpecial] } { continue }
        foreach swire [$net getSWires] {
            foreach sbox [$swire getWires] {
                set x1 [$sbox xMin]
                set y1 [$sbox yMin]
                set x2 [$sbox xMax]
                set y2 [$sbox yMax]
                if { $x1 >= [$die xMin] && $y1 >= [$die yMin] &&
                     $x2 <= [$die xMax] && $y2 <= [$die yMax] } {
                    continue
                }
                incr bad
                if { $bad <= 10 } {
                    set lname "via"
                    if { ![$sbox isVia] } {
                        set lname [[$sbox getTechLayer] getName]
                    }
                    puts stderr [format \
                        "\[AI_BYTE\] outside DIEAREA: %s on %s (%.3f %.3f) (%.3f %.3f)" \
                        [$net getName] $lname \
                        [expr {$x1 / $dbu}] [expr {$y1 / $dbu}] \
                        [expr {$x2 / $dbu}] [expr {$y2 / $dbu}]]
                }
            }
        }
    }

    if { $bad > 0 } {
        puts stderr "\[AI_BYTE\] $bad power shapes fall outside DIEAREA — layout does not match the organizer DEF."
        exit_unless_gui 1
    }
    puts "\[AI_BYTE\] all power shapes inside DIEAREA."
}
a02_assert_pdn_inside_die

write_views
report_design_area_metrics

foreach {net} "$::env(VDD_NETS) $::env(GND_NETS)" {
    set report_file $::env(STEP_DIR)/$net-grid-errors.rpt

    set f [open $report_file "w"]
    puts $f ""
    close $f

    if { [catch {check_power_grid -net $net -error_file $report_file} err] } {
        puts stderr "\[WARNING\] Grid check for $net failed: $err"
    }
}
