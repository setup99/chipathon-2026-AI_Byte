COCOTB_MAKEFILES := $(shell cocotb-config --makefiles)
SIM               = icarus
TOPLEVEL_LANG     = verilog
VERILOG_SOURCES   = ../src/mitchell_log2_q88.v
VERILOG_SOURCES  += ../src/mitchell_exp2_q88.v
VERILOG_SOURCES  += ../src/eml_tile_q88.v
VERILOG_SOURCES  += ../src/eml_sigmoid_q88_shared.v
VERILOG_SOURCES  += ../src/eml_tanh_q88_shared.v
VERILOG_SOURCES  += ../src/eml_recip_q88_shared.v
VERILOG_SOURCES  += ../src/eml_sqrt_q88_shared.v
VERILOG_SOURCES  += ../src/eml_feedback_cell_q88_shared.v
VERILOG_SOURCES  += ../src/eml_softmax_q88_serial.v
#VERILOG_SOURCES  += ../src/tb_top_softmax_serial.v
VERILOG_SOURCES  += ../src/eml_wrapper_q88_serial.v
TOPLEVEL          = eml_wrapper_q88_serial
MODULE            = test_wrapper_all_functions_q88
COMPILE_ARGS      = -g2012
include $(COCOTB_MAKEFILES)/Makefile.sim
