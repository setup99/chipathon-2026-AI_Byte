COCOTB_MAKEFILES := $(shell cocotb-config --makefiles)
SIM               = icarus
TOPLEVEL_LANG     = verilog
VERILOG_SOURCES   = ../../../src/ai_byte/eml/mitchell_log2_q88.v
VERILOG_SOURCES  += ../../../src/ai_byte/eml/mitchell_exp2_q88.v
VERILOG_SOURCES  +=../../../src/ai_byte/eml/eml_tile_q88.v
VERILOG_SOURCES  += ../../../src/ai_byte/eml/eml_recip_sqrt_q88_shared.v
VERILOG_SOURCES  += ../../../src/ai_byte/eml/eml_sigmoid_tanh_q88_shared.v
VERILOG_SOURCES  += ../../../src/ai_byte/eml/eml_feedback_cell_q88_shared.v
VERILOG_SOURCES  += ../../../src/ai_byte/eml/eml_softmax_q88_serial.v
#VERILOG_SOURCES  += ../../src/ai_byte/eml/tb_top_softmax_serial.v
VERILOG_SOURCES  += ../../../src/ai_byte/eml/eml_wrapper_q88_serial.v
TOPLEVEL          = eml_wrapper_q88_serial
MODULE            = test_wrapper_all_functions_q88
COMPILE_ARGS      = -g2012
include $(COCOTB_MAKEFILES)/Makefile.sim
