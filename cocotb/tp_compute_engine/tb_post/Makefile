SIM ?= icarus
TOPLEVEL_LANG ?= verilog

VERILOG_SOURCES = ../../../src/ai_byte/post/alu_q88.v \
                   ../../../src/ai_byte/post/relu_int16.v \
                   ../../../src/ai_byte/post/pooling_int16.v \
                   ../../../src/ai_byte/post/scale_int16_to_int8.v \
                   ../../../src/ai_byte/post/block_wrapper.v
TOPLEVEL = block_wrapper
COCOTB_TEST_MODULES = test_block_wrapper

include $(shell cocotb-config --makefiles)/Makefile.sim
