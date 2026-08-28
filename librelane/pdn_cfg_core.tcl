# Core-only PDN for ai_byte_top (A02 pre-integration).
# Based on LibreLane stock pdn_cfg.tcl, but WITHOUT define_pdn_grid -macro -default.
#
# Reason: stock default macro grid applies to vss_conn/vdd_conn and fails with
# PDN-0232/0233 (Metal3/Metal4 OBS, no straps to generate inside those cells).
# Connectors are passive M2→M5 bridges; Metal5 overlaps stdcell straps + LVS
# connect-by-label joins them.

source $::env(SCRIPTS_DIR)/openroad/common/io.tcl
source $::env(SCRIPTS_DIR)/openroad/common/set_global_connections.tcl
set_global_connections

set secondary []
foreach vdd $::env(VDD_NETS) gnd $::env(GND_NETS) {
    if { $vdd != $::env(VDD_NET)} {
        lappend secondary $vdd
        set db_net [[ord::get_db_block] findNet $vdd]
        if {$db_net == "NULL"} {
            set net [odb::dbNet_create [ord::get_db_block] $vdd]
            $net setSpecial
            $net setSigType "POWER"
        }
    }
    if { $gnd != $::env(GND_NET)} {
        lappend secondary $gnd
        set db_net [[ord::get_db_block] findNet $gnd]
        if {$db_net == "NULL"} {
            set net [odb::dbNet_create [ord::get_db_block] $gnd]
            $net setSpecial
            $net setSigType "GROUND"
        }
    }
}

set_voltage_domain -name CORE -power $::env(VDD_NET) -ground $::env(GND_NET) \
    -secondary_power $secondary

if { $::env(PDN_MULTILAYER) == 1 } {
    set arg_list [list]
    if { $::env(PDN_ENABLE_PINS) } {
        lappend arg_list -pins "$::env(PDN_VERTICAL_LAYER) $::env(PDN_HORIZONTAL_LAYER)"
    }

    define_pdn_grid \
        -name stdcell_grid \
        -starts_with POWER \
        -voltage_domain CORE \
        {*}$arg_list

    set arg_list [list]
    append_if_equals arg_list PDN_EXTEND_TO "core_ring" -extend_to_core_ring
    append_if_equals arg_list PDN_EXTEND_TO "boundary" -extend_to_boundary

    add_pdn_stripe \
        -grid stdcell_grid \
        -layer $::env(PDN_VERTICAL_LAYER) \
        -width $::env(PDN_VWIDTH) \
        -pitch $::env(PDN_VPITCH) \
        -offset $::env(PDN_VOFFSET) \
        -spacing $::env(PDN_VSPACING) \
        -starts_with POWER \
        {*}$arg_list

    add_pdn_stripe \
        -grid stdcell_grid \
        -layer $::env(PDN_HORIZONTAL_LAYER) \
        -width $::env(PDN_HWIDTH) \
        -pitch $::env(PDN_HPITCH) \
        -offset $::env(PDN_HOFFSET) \
        -spacing $::env(PDN_HSPACING) \
        -starts_with POWER \
        {*}$arg_list

    add_pdn_connect \
        -grid stdcell_grid \
        -layers "$::env(PDN_VERTICAL_LAYER) $::env(PDN_HORIZONTAL_LAYER)"
} else {
    set arg_list [list]
    if { $::env(PDN_ENABLE_PINS) } {
        lappend arg_list -pins "$::env(PDN_VERTICAL_LAYER)"
    }

    define_pdn_grid \
        -name stdcell_grid \
        -starts_with POWER \
        -voltage_domain CORE \
        {*}$arg_list

    set arg_list [list]
    append_if_equals arg_list PDN_EXTEND_TO "core_ring" -extend_to_core_ring
    append_if_equals arg_list PDN_EXTEND_TO "boundary" -extend_to_boundary

    add_pdn_stripe \
        -grid stdcell_grid \
        -layer $::env(PDN_VERTICAL_LAYER) \
        -width $::env(PDN_VWIDTH) \
        -pitch $::env(PDN_VPITCH) \
        -offset $::env(PDN_VOFFSET) \
        -spacing $::env(PDN_VSPACING) \
        -starts_with POWER \
        {*}$arg_list
}

if { $::env(PDN_ENABLE_RAILS) == 1 } {
    add_pdn_stripe \
        -grid stdcell_grid \
        -layer $::env(PDN_RAIL_LAYER) \
        -width $::env(PDN_RAIL_WIDTH) \
        -followpins

    add_pdn_connect \
        -grid stdcell_grid \
        -layers "$::env(PDN_RAIL_LAYER) $::env(PDN_VERTICAL_LAYER)"
}

if { $::env(PDN_CORE_RING) == 1 } {
    if { $::env(PDN_MULTILAYER) != 1 } {
        throw APPLICATION "PDN_CORE_RING cannot be used when PDN_MULTILAYER is set to false."
    }

    set arg_list [list]
    append_if_flag arg_list PDN_CORE_RING_ALLOW_OUT_OF_DIE -allow_out_of_die
    append_if_flag arg_list PDN_CORE_RING_CONNECT_TO_PADS -connect_to_pads
    append_if_equals arg_list PDN_EXTEND_TO "boundary" -extend_to_boundary

    set pdn_core_vertical_layer $::env(PDN_VERTICAL_LAYER)
    set pdn_core_horizontal_layer $::env(PDN_HORIZONTAL_LAYER)

    if { [info exists ::env(PDN_CORE_VERTICAL_LAYER)] } {
        set pdn_core_vertical_layer $::env(PDN_CORE_VERTICAL_LAYER)
    }
    if { [info exists ::env(PDN_CORE_HORIZONTAL_LAYER)] } {
        set pdn_core_horizontal_layer $::env(PDN_CORE_HORIZONTAL_LAYER)
    }

    add_pdn_ring \
        -grid stdcell_grid \
        -layers "$pdn_core_vertical_layer $pdn_core_horizontal_layer" \
        -widths "$::env(PDN_CORE_RING_VWIDTH) $::env(PDN_CORE_RING_HWIDTH)" \
        -spacings "$::env(PDN_CORE_RING_VSPACING) $::env(PDN_CORE_RING_HSPACING)" \
        -core_offset "$::env(PDN_CORE_RING_VOFFSET) $::env(PDN_CORE_RING_HOFFSET)" \
        {*}$arg_list

    if { [info exists ::env(PDN_CORE_VERTICAL_LAYER)] } {
        add_pdn_connect \
            -grid stdcell_grid \
            -layers "$::env(PDN_CORE_VERTICAL_LAYER) $::env(PDN_HORIZONTAL_LAYER)"
    }
    if { [info exists ::env(PDN_CORE_HORIZONTAL_LAYER)] } {
        add_pdn_connect \
            -grid stdcell_grid \
            -layers "$::env(PDN_CORE_HORIZONTAL_LAYER) $::env(PDN_VERTICAL_LAYER)"
    }
    if { [info exists ::env(PDN_CORE_VERTICAL_LAYER)] && [info exists ::env(PDN_CORE_HORIZONTAL_LAYER)] } {
        add_pdn_connect \
            -grid stdcell_grid \
            -layers "$::env(PDN_CORE_VERTICAL_LAYER) $::env(PDN_CORE_HORIZONTAL_LAYER)"
    }
}

# Intentionally no define_pdn_grid -macro (default or connector-specific).
# Passive vss_conn/vdd_conn have full Metal3/Metal4 OBS; a per-macro grid
# produces zero shapes (PDN-0232) and aborts with PDN-0233.
# Connector stitch: post-pdngen Metal5/Metal2 bridges in pdn_a02.tcl (AIByte.GeneratePDN).
