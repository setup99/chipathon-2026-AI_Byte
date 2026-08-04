SIM ?= icarus
TOPLEVEL_LANG ?= verilog

VERILOG_SOURCES = ../src/alu_q88.v \
                   ../src/relu_int16.v \
                   ../src/pooling_int16.v \
                   ../src/scale_int16_to_int8.v \
                   ../src/block_wrapper.v
TOPLEVEL = block_wrapper
COCOTB_TEST_MODULES = test_block_wrapper

include $(shell cocotb-config --makefiles)/Makefile.sim
