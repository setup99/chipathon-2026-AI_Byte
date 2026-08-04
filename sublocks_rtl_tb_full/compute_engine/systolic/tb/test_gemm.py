import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, Timer
import random
import os

# -----------------------------------------------------------------------------
# Helpers & Reference Model
# -----------------------------------------------------------------------------
def get_dut_param(dut, param_name, default_val):
    try:
        return int(getattr(dut, param_name).value)
    except AttributeError:
        return int(os.environ.get(f"PARAM_{param_name}", default_val))

def convergent_round(acc, frac):
    if frac == 0: return acc
    half_point = 1 << (frac - 1)
    frac_mask = (1 << frac) - 1
    fractional_part = acc & frac_mask
    integer_part = acc >> frac 
    
    if fractional_part > half_point: return integer_part + 1
    elif fractional_part < half_point: return integer_part
    else:
        return integer_part + 1 if (integer_part & 1) == 1 else integer_part

def compute_reference_model_gemm(weights, inputs, frac=0, out_width=16):
    """
    Computes Y = W * X where W is M x N and X is N x P.
    Weights & inputs are INT8, outputs are INT16.
    """
    M = len(weights)
    N = len(weights[0])
    P = len(inputs[0])
    
    y_out = [[0]*P for _ in range(M)]
    max_val = (1 << (out_width - 1)) - 1
    min_val = -(1 << (out_width - 1))

    for r in range(M):
        for c in range(P):
            acc = 0
            for k in range(N):
                acc += weights[r][k] * inputs[k][c]
            shifted = convergent_round(acc, frac)
            y_out[r][c] = max(min(shifted, max_val), min_val) # Saturate
            
    return y_out

OP_CONV = 0b0101 # 4x4 Systolic Convolution

# -----------------------------------------------------------------------------
# Core Coroutines (Setup, Driver, Monitor)
# -----------------------------------------------------------------------------
async def reset_dut(dut):
    dut.rst.value = 1
    dut.start.value = 0
    dut.op_sel.value = 0
    dut.w_load.value = 0
    dut.x_in_data.value = 0
    await Timer(10, units="ns")
    await RisingEdge(dut.clk)
    dut.rst.value = 0
    await RisingEdge(dut.clk)

async def setup_test(dut):
    cocotb.start_soon(Clock(dut.clk, 10, units="ns").start())
    
    cfg = {
        "M": get_dut_param(dut, "M", 4),
        "P": get_dut_param(dut, "P", 4),
        "N": get_dut_param(dut, "N", 4),
        "IN_WIDTH": get_dut_param(dut, "IN_WIDTH", 8),
        "OUT_WIDTH": get_dut_param(dut, "OUT_WIDTH", 16),
        "FRAC": get_dut_param(dut, "FRAC", 0)
    }
    # Dynamic bounds for INT8 inputs [-128, 127]
    in_w = cfg["IN_WIDTH"]
    cfg["MIN_VAL"] = -(1 << (in_w - 1))
    cfg["MAX_VAL"] = (1 << (in_w - 1)) - 1
    
    await reset_dut(dut)
    return cfg

async def start_dut(dut, op_sel=OP_CONV):
    dut.op_sel.value = op_sel
    dut.start.value = 1
    await RisingEdge(dut.clk)
    dut.start.value = 0

async def load_weights(dut, weights, in_width=8):
    M = len(weights)
    N = len(weights[0])
    dut.w_load.value = 1
    for r in range(M):
        for c in range(N):
            dut.w_load_row.value = r
            dut.w_load_col.value = c
            dut.w_load_data.value = int(weights[r][c]) & ((1 << in_width) - 1)
            await RisingEdge(dut.clk)
    dut.w_load.value = 0

async def stream_input_x(dut, inputs, in_width=8):
    """
    Streams inputs of shape N x P.
    At each cycle, feeds P values of size in_width bits in parallel.
    """
    N = len(inputs)
    P = len(inputs[0])
    
    for k in range(N):
        val = 0
        for c in range(P):
            uval = int(inputs[k][c]) & ((1 << in_width) - 1)
            val |= (uval << (c * in_width))
        dut.x_in_data.value = val
        await RisingEdge(dut.clk)
        
    dut.x_in_data.value = 0

async def monitor_output_y(dut, expected_y, cfg):
    """
    Collects streamed row outputs (y_row_idx/y_row_data/y_row_valid) one row
    at a time as they arrive, then compares the assembled matrix against
    expected_y once `done` is asserted. `done` is guaranteed to fire one
    cycle after the last row's pulse, so every row has already been
    captured by the time the loop sees done==1.
    """
    M = cfg["M"]
    P = cfg["P"]
    out_w = cfg["OUT_WIDTH"]

    y_actual = [[None]*P for _ in range(M)]

    while True:
        await RisingEdge(dut.clk)
        if dut.y_row_valid.value == 1:
            r = int(dut.y_row_idx.value)
            row_val = int(dut.y_row_data.value)
            for c in range(P):
                val = (row_val >> (c * out_w)) & ((1 << out_w) - 1)
                # Convert to signed
                if val >= (1 << (out_w - 1)):
                    val -= (1 << out_w)
                y_actual[r][c] = val
        if dut.done.value == 1:
            break

    assert y_actual == expected_y, f"Mismatch! Expected:\n{expected_y}\nGot:\n{y_actual}"

# -----------------------------------------------------------------------------
# Test Cases
# -----------------------------------------------------------------------------
@cocotb.test()
async def test_gemm_standard_random(dut):
    """Test standard GEMM with random INT8 weights and inputs producing INT16 outputs."""
    cfg = await setup_test(dut)
    M, P, N = cfg["M"], cfg["P"], cfg["N"]
    
    weights = [[random.randint(cfg["MIN_VAL"]//N, cfg["MAX_VAL"]//N) for _ in range(N)] for _ in range(M)]
    inputs = [[random.randint(cfg["MIN_VAL"]//N, cfg["MAX_VAL"]//N) for _ in range(P)] for _ in range(N)]
    expected_y = compute_reference_model_gemm(weights, inputs, cfg["FRAC"], cfg["OUT_WIDTH"])
    
    await load_weights(dut, weights, cfg["IN_WIDTH"])
    await start_dut(dut, OP_CONV)
    
    monitor_thread = cocotb.start_soon(monitor_output_y(dut, expected_y, cfg))
    driver_thread = cocotb.start_soon(stream_input_x(dut, inputs, cfg["IN_WIDTH"]))
    await cocotb.triggers.Combine(monitor_thread, driver_thread)

@cocotb.test()
async def test_gemm_fc_mapping(dut):
    """Test mapping of a Fully Connected (FC) layer with batch size P using INT8 inputs and INT16 outputs."""
    cfg = await setup_test(dut)
    M, P, N = cfg["M"], cfg["P"], cfg["N"]
    
    weights = [[random.randint(cfg["MIN_VAL"]//N, cfg["MAX_VAL"]//N) for _ in range(N)] for _ in range(M)]
    inputs = [[random.randint(cfg["MIN_VAL"]//N, cfg["MAX_VAL"]//N) for _ in range(P)] for _ in range(N)]
    expected_y = compute_reference_model_gemm(weights, inputs, cfg["FRAC"], cfg["OUT_WIDTH"])
    
    await load_weights(dut, weights, cfg["IN_WIDTH"])
    await start_dut(dut, OP_CONV)
    
    monitor_thread = cocotb.start_soon(monitor_output_y(dut, expected_y, cfg))
    driver_thread = cocotb.start_soon(stream_input_x(dut, inputs, cfg["IN_WIDTH"]))
    await cocotb.triggers.Combine(monitor_thread, driver_thread)

@cocotb.test()
async def test_gemm_conv_mapping(dut):
    """Test mapping of a 2D Convolution layer via im2col with INT8 inputs and INT16 outputs."""
    cfg = await setup_test(dut)
    M, P, N = cfg["M"], cfg["P"], cfg["N"]
    
    weights = [[random.randint(cfg["MIN_VAL"]//N, cfg["MAX_VAL"]//N) for _ in range(N)] for _ in range(M)]
    inputs = [[random.randint(cfg["MIN_VAL"]//N, cfg["MAX_VAL"]//N) for _ in range(P)] for _ in range(N)]
    expected_y = compute_reference_model_gemm(weights, inputs, cfg["FRAC"], cfg["OUT_WIDTH"])
    
    await load_weights(dut, weights, cfg["IN_WIDTH"])
    await start_dut(dut, OP_CONV)
    
    monitor_thread = cocotb.start_soon(monitor_output_y(dut, expected_y, cfg))
    driver_thread = cocotb.start_soon(stream_input_x(dut, inputs, cfg["IN_WIDTH"]))
    await cocotb.triggers.Combine(monitor_thread, driver_thread)

@cocotb.test()
async def test_gemm_mid_stream_reset(dut):
    """Aborts a transfer halfway with a reset, then verifies pipeline recovery."""
    cfg = await setup_test(dut)
    M, P, N = cfg["M"], cfg["P"], cfg["N"]
    
    weights = [[10 for _ in range(N)] for _ in range(M)]
    inputs = [[5 for _ in range(P)] for _ in range(N)]
    
    await load_weights(dut, weights, cfg["IN_WIDTH"])
    await start_dut(dut, OP_CONV)
    
    driver_task = cocotb.start_soon(stream_input_x(dut, inputs, cfg["IN_WIDTH"]))
    for _ in range(N // 2):
        await RisingEdge(dut.clk)
        
    dut._log.info("Cancelling active driver task and triggering mid-stream hard reset...")
    driver_task.cancel()
    await reset_dut(dut)
    
    dut._log.info("Attempting clean transfer post-reset...")
    expected_y = compute_reference_model_gemm(weights, inputs, cfg["FRAC"], cfg["OUT_WIDTH"])
    
    await load_weights(dut, weights, cfg["IN_WIDTH"])
    await start_dut(dut, OP_CONV)
    
    monitor_thread = cocotb.start_soon(monitor_output_y(dut, expected_y, cfg))
    driver_thread = cocotb.start_soon(stream_input_x(dut, inputs, cfg["IN_WIDTH"]))
    await cocotb.triggers.Combine(monitor_thread, driver_thread)

@cocotb.test()
async def test_gemm_rounding_saturation(dut):
    """Test exact rounding and saturation bounds in INT16."""
    cfg = await setup_test(dut)
    M, P, N = cfg["M"], cfg["P"], cfg["N"]
    out_w = cfg["OUT_WIDTH"]
    
    weights = [[127 if r == c else 0 for c in range(N)] for r in range(M)]
    inputs = [[127 for _ in range(P)] for _ in range(N)]
    
    expected_y = compute_reference_model_gemm(weights, inputs, cfg["FRAC"], out_w)
    
    await load_weights(dut, weights, cfg["IN_WIDTH"])
    await start_dut(dut, OP_CONV)
    
    monitor_thread = cocotb.start_soon(monitor_output_y(dut, expected_y, cfg))
    driver_thread = cocotb.start_soon(stream_input_x(dut, inputs, cfg["IN_WIDTH"]))
    await cocotb.triggers.Combine(monitor_thread, driver_thread)

@cocotb.test()
async def test_gemm_op_sel_filtering(dut):
    """Test OP_SEL decoding: non-systolic opcodes are ignored while OP_CONV (0b0101) triggers computation."""
    cfg = await setup_test(dut)
    M, P, N = cfg["M"], cfg["P"], cfg["N"]
    
    weights = [[1 for _ in range(N)] for _ in range(M)]
    inputs = [[2 for _ in range(P)] for _ in range(N)]
    expected_y = compute_reference_model_gemm(weights, inputs, cfg["FRAC"], cfg["OUT_WIDTH"])
    
    await load_weights(dut, weights, cfg["IN_WIDTH"])
    
    dut._log.info("Testing non-systolic OP_SEL = 0b0001 (ALU_ADD)...")
    await start_dut(dut, op_sel=0b0001)
    await RisingEdge(dut.clk)
    assert dut.busy.value == 0, "Accelerator should NOT become busy on non-systolic OP_SEL!"
    
    dut._log.info("Testing valid OP_SEL = 0b0101 (OP_CONV)...")
    await start_dut(dut, op_sel=OP_CONV)
    monitor_thread = cocotb.start_soon(monitor_output_y(dut, expected_y, cfg))
    driver_thread = cocotb.start_soon(stream_input_x(dut, inputs, cfg["IN_WIDTH"]))
    await cocotb.triggers.Combine(monitor_thread, driver_thread)
