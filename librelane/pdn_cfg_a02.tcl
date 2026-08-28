# A02-only PDN — lighter than workshop pdn_cfg.tcl.
# Chip straps stay on M2/M3; macro M4/M5 pins are contacted only via a
# dedicated macro grid (avoids flooding empty die with M4/M5 straps).

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

# ---- Stdcell / glue PDN on M2/M3 only ----
set arg_list [list]
if { $::env(PDN_ENABLE_PINS) } {
    lappend arg_list -pins "$::env(PDN_VERTICAL_LAYER) $::env(PDN_HORIZONTAL_LAYER)"
}

define_pdn_grid \
    -name stdcell_grid \
    -starts_with POWER \
    -voltage_domain CORE \
    {*}$arg_list

set stripe_args [list]
append_if_equals stripe_args PDN_EXTEND_TO "core_ring" -extend_to_core_ring
append_if_equals stripe_args PDN_EXTEND_TO "boundary" -extend_to_boundary

add_pdn_stripe \
    -grid stdcell_grid \
    -layer $::env(PDN_VERTICAL_LAYER) \
    -width $::env(PDN_VWIDTH) \
    -pitch $::env(PDN_VPITCH) \
    -offset $::env(PDN_VOFFSET) \
    -spacing $::env(PDN_VSPACING) \
    -starts_with POWER \
    {*}$stripe_args

add_pdn_stripe \
    -grid stdcell_grid \
    -layer $::env(PDN_HORIZONTAL_LAYER) \
    -width $::env(PDN_HWIDTH) \
    -pitch $::env(PDN_HPITCH) \
    -offset $::env(PDN_HOFFSET) \
    -spacing $::env(PDN_HSPACING) \
    -starts_with POWER \
    {*}$stripe_args

add_pdn_connect \
    -grid stdcell_grid \
    -layers "$::env(PDN_VERTICAL_LAYER) $::env(PDN_HORIZONTAL_LAYER)"

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

# Optional thin core ring on M2/M3 (no pad abutment — pads already on W12/W13 nets).
if { $::env(PDN_CORE_RING) == 1 } {
    set ring_args [list]
    append_if_flag ring_args PDN_CORE_RING_ALLOW_OUT_OF_DIE -allow_out_of_die
    append_if_flag ring_args PDN_CORE_RING_CONNECT_TO_PADS -connect_to_pads
    append_if_equals ring_args PDN_EXTEND_TO "boundary" -extend_to_boundary

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
        {*}$ring_args

    add_pdn_connect \
        -grid stdcell_grid \
        -layers "$pdn_core_vertical_layer $::env(PDN_HORIZONTAL_LAYER)"
    add_pdn_connect \
        -grid stdcell_grid \
        -layers "$pdn_core_horizontal_layer $::env(PDN_VERTICAL_LAYER)"
    add_pdn_connect \
        -grid stdcell_grid \
        -layers "$pdn_core_vertical_layer $pdn_core_horizontal_layer"
}

# ---- Macro: land on existing M4/M5 VDD/VSS pins only ----
define_pdn_grid \
    -macro \
    -instances i_chip_core.u_ai_byte \
    -name ai_byte_macro \
    -grid_over_pg_pins \
    -starts_with POWER \
    -halo "$::env(PDN_HORIZONTAL_HALO) $::env(PDN_VERTICAL_HALO)"

# Stitch chip M2/M3 straps up to macro power pins (M4/M5).
add_pdn_connect \
    -grid ai_byte_macro \
    -layers "Metal2 Metal4"
add_pdn_connect \
    -grid ai_byte_macro \
    -layers "Metal3 Metal5"
add_pdn_connect \
    -grid ai_byte_macro \
    -layers "Metal4 Metal5"
add_pdn_connect \
    -grid ai_byte_macro \
    -layers "$::env(PDN_VERTICAL_LAYER) $::env(PDN_HORIZONTAL_LAYER)"
