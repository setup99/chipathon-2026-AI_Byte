# Bridge west-edge vss_conn / vdd_conn into the stdcell PDN mesh.
# Power nets are SPECIAL; use dbSWire/dbSBox (not dbWireEncoder).

proc a02_um_to_dbu {um} {
    set block [ord::get_db_block]
    return [expr {int(round($um * [$block getDbUnitsPerMicron]))}]
}

proc a02_add_stripe {net_name layer_name x1_um y_center_um x2_um width_um} {
    set block [ord::get_db_block]
    set tech [ord::get_db_tech]
    set layer [$tech findLayer $layer_name]
    if { $layer == "NULL" } {
        error "layer $layer_name not found"
    }

    set net [$block findNet $net_name]
    if { $net == "NULL" } {
        error "net $net_name not found"
    }

    set half [a02_um_to_dbu [expr {$width_um / 2.0}]]
    set cx1 [a02_um_to_dbu $x1_um]
    set cx2 [a02_um_to_dbu $x2_um]
    set cy [a02_um_to_dbu $y_center_um]
    set ylo [expr {$cy - $half}]
    set yhi [expr {$cy + $half}]

    set swire [odb::dbSWire_create $net "ROUTED"]
    odb::dbSBox_create $swire $layer $cx1 $ylo $cx2 $yhi "STRIPE"
}

proc a02_stitch_connectors {} {
    # Only strap rows belonging to the same net may be bridged: pdngen puts
    # VDD at 28.41+75k and VSS at 34.41+75k, so a bridge on the neighbouring
    # row would land on top of the opposite net's strap.
    #   u_vss_conn spans y 6.36..78.64   -> VSS row 34.41
    #   u_vdd_conn spans y 106.36..178.64 -> VDD row 178.41
    # Metal5 only: the connectors carry M2..M5 internally, and a horizontal
    # Metal2 bridge would cross the opposite net's vertical Metal2 stripes.
    set bridge_x2 30.0
    set width 5.0

    foreach pair {
        {VSS 34.41}
        {VDD 178.41}
    } {
        lassign $pair net y
        a02_add_stripe $net "Metal5" 0.0 $y $bridge_x2 $width
    }

    puts "\[AI_BYTE\] stitched u_vss_conn / u_vdd_conn on Metal5 (x=0..${bridge_x2}um)"
}
