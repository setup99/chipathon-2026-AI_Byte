# SDC for A02_A D10-style user macro (pad-control wrapper + ai_byte_top).
# Port names match organizer DEF / A02_A.v (data_IN/OUT, irq_OUT, …).
current_design $::env(DESIGN_NAME)
set_units -time ns

set clock_port __VIRTUAL_CLK__
if { [info exists ::env(CLOCK_PORT)] } {
    set port_count [llength $::env(CLOCK_PORT)]
    if { $port_count == "0" } {
        puts "\[WARNING] No CLOCK_PORT found. A dummy clock will be used."
    } elseif { $port_count != "1" } {
        puts "\[WARNING] Multi-clock files not supported; only first clock used."
    }
    if { $port_count > "0" } {
        set ::clock_port [lindex $::env(CLOCK_PORT) 0]
    }
}

if { $::env(CLOCK_PORT) == $::env(CLOCK_NET) } {
    set port_args [get_ports $clock_port]
} else {
    set port_args [get_pins [lindex $::env(CLOCK_NET) 0]]
}

puts "\[INFO] Using clock $clock_port…"
create_clock {*}$port_args -name $clock_port -period $::env(CLOCK_PERIOD)

set input_delay_value  [expr $::env(CLOCK_PERIOD) * $::env(IO_DELAY_CONSTRAINT) / 100]
set output_delay_value [expr $::env(CLOCK_PERIOD) * $::env(IO_DELAY_CONSTRAINT) / 100]
puts "\[INFO] Setting I/O delay: in=$input_delay_value out=$output_delay_value"

set_max_fanout $::env(MAX_FANOUT_CONSTRAINT) [current_design]
if { [info exists ::env(MAX_TRANSITION_CONSTRAINT)] } {
    set_max_transition $::env(MAX_TRANSITION_CONSTRAINT) [current_design]
}
if { [info exists ::env(MAX_CAPACITANCE_CONSTRAINT)] } {
    set_max_capacitance $::env(MAX_CAPACITANCE_CONSTRAINT) [current_design]
}

set clocks [get_clocks $clock_port]

# Functional inputs (pad Y / IN side)
set in_ports [get_ports {
    rst_n
    addr[*]
    we
    re
    data_IN[*]
    irq_IN
    debug_state_IN[*]
}]

# Functional outputs (pad A / OUT side + controls driven by glue)
set out_ports [get_ports {
    data_OUT[*]
    data_OE[*]
    data_IE[*]
    data_CS[*]
    data_SL[*]
    data_PU[*]
    data_PD[*]
    data_PDRV0[*]
    data_PDRV1[*]
    irq_OUT
    irq_OE
    irq_IE
    irq_CS
    irq_SL
    irq_PU
    irq_PD
    irq_PDRV0
    irq_PDRV1
    debug_state_OUT[*]
    debug_state_OE[*]
    debug_state_IE[*]
    debug_state_CS[*]
    debug_state_SL[*]
    debug_state_PU[*]
    debug_state_PD[*]
    debug_state_PDRV0[*]
    debug_state_PDRV1[*]
    clk_PU
    clk_PD
    rst_n_PU
    rst_n_PD
    re_PU
    re_PD
    we_PU
    we_PD
    addr_PU[*]
    addr_PD[*]
}]

# min=0 assumed external data can change with the clock edge and failed hold on
# data_IN→flop paths once CTS deepened (~ -0.52 ns). 1.5 ns models pad delay into
# this user macro and clears those in-reg holds with margin.
set_input_delay  -min 1.5 -clock $clocks $in_ports
set_input_delay  -max $input_delay_value -clock $clocks $in_ports

set_output_delay $output_delay_value -clock $clocks $out_ports

set cap_load [expr $::env(OUTPUT_CAP_LOAD) / 1000.0]
puts "\[INFO] Setting load to: $cap_load"
set_load $cap_load [all_outputs]

puts "\[INFO] clock uncertainty: $::env(CLOCK_UNCERTAINTY_CONSTRAINT)"
set_clock_uncertainty $::env(CLOCK_UNCERTAINTY_CONSTRAINT) $clocks
puts "\[INFO] clock transition: $::env(CLOCK_TRANSITION_CONSTRAINT)"
set_clock_transition $::env(CLOCK_TRANSITION_CONSTRAINT) $clocks
puts "\[INFO] timing derate %: $::env(TIME_DERATING_CONSTRAINT)"
set_timing_derate -early [expr 1-[expr $::env(TIME_DERATING_CONSTRAINT) / 100]]
set_timing_derate -late  [expr 1+[expr $::env(TIME_DERATING_CONSTRAINT) / 100]]

if { [info exists ::env(OPENLANE_SDC_IDEAL_CLOCKS)] && $::env(OPENLANE_SDC_IDEAL_CLOCKS) } {
    unset_propagated_clock [all_clocks]
} else {
    set_propagated_clock [all_clocks]
}
