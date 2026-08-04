# Buffers (SRAM cell + bank) — cocotb
#
#   make              # both suites; removes results/waves after
#   make sram_buffer
#   make buffers
#   make clean

SIM ?= icarus
TOPLEVEL_LANG ?= verilog
WAVES ?= 0

ROOT := $(abspath ..)
VENV := $(ROOT)/.venv
export PATH := $(VENV)/bin:$(PATH)
export PYTHONPATH := $(CURDIR):$(PYTHONPATH)
export COCOTB_REDUCED_LOG_FMT ?= 1

COCOTB_MAKEFILES := $(shell $(VENV)/bin/cocotb-config --makefiles)

.PHONY: all sram_buffer buffers clean
all: sram_buffer buffers

sram_buffer:
	$(MAKE) -f $(COCOTB_MAKEFILES)/Makefile.sim \
		SIM=$(SIM) TOPLEVEL_LANG=$(TOPLEVEL_LANG) WAVES=$(WAVES) \
		VERILOG_SOURCES="$(CURDIR)/ai_byte_sram_buffer.v $(CURDIR)/sram_buffer_dut.v" \
		COCOTB_TOPLEVEL=sram_buffer_dut \
		COCOTB_TEST_MODULES=test_sram_buffer \
		SIM_BUILD=sim_build_sram \
		COCOTB_RESULTS_FILE=results_sram.xml
	$(RM) results_sram.xml *.vcd *.fst

buffers:
	$(MAKE) -f $(COCOTB_MAKEFILES)/Makefile.sim \
		SIM=$(SIM) TOPLEVEL_LANG=$(TOPLEVEL_LANG) WAVES=$(WAVES) \
		VERILOG_SOURCES="$(CURDIR)/ai_byte_sram_buffer.v $(CURDIR)/ai_byte_buffers.v $(CURDIR)/buffers_dut.v" \
		COCOTB_TOPLEVEL=buffers_dut \
		COCOTB_TEST_MODULES=test_buffers \
		SIM_BUILD=sim_build_bank \
		COCOTB_RESULTS_FILE=results_bank.xml
	$(RM) results_bank.xml *.vcd *.fst

clean:
	$(RM) -rf sim_build_sram sim_build_bank results_*.xml *.vcd *.fst __pycache__
