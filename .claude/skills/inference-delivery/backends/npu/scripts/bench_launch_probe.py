"""Minimal kernel-launch-latency probe for NPU board comparison. Self-contained.

Companion script of references/LAUNCH_OVERHEAD.md. Isolates the per-op
launch/dispatch cost from compute and from python overhead, with control
groups so each factor gets its own number:

  cpu_micro          [8] add on CPU x N            -> python+torch dispatch only
  npu_micro_stream   [8] add on NPU x N, one sync  -> dispatch + launch (pipelined)
  npu_micro_sync     [8] add on NPU, sync each op  -> full round trip per op
  npu_small_mm       [8,8]@[8,8] x N, one sync     -> tiny kernels, launch-bound
  npu_big_mm         [1024,1024] matmul x N        -> compute-bound (AI Core ruler)

Reading: if big_mm is ~1x across boards (compute equal) while the micro /
small groups are ~2x, the gap of small-kernel segments in your pipeline is
the launch path, not silicon. Pure launch postage = npu_micro_stream minus
cpu_micro. The "should not move" rulers (cpu_micro, npu_big_mm) moving
means the experiment is dirty, not that you found something.

Run on each board (CANN env sourced), then diff the outputs:

  python bench_launch_probe.py [--iters 500]

Only needs torch + torch_npu + numpy; no model, no capture files.
"""

import argparse
import time

import numpy as np
import torch
import torch_npu

# precompiled kernels only: on boards with a broken tbe online-compile path
# (RC-class), any new shape triggering online compilation fails with 500002
torch.npu.set_compile_mode(jit_compile=False)


def timeit(fn, n, inner=50):
    """Median per-op microseconds over blocks of `inner` calls (blocks beat
    single-op timing at ~10us scale); inner=1 for the expensive cases."""
    for _ in range(20):
        fn()
    torch.npu.synchronize()
    ts = []
    for _ in range(n // 10 + 1):
        t0 = time.perf_counter()
        for _ in range(10):
            fn()
        torch.npu.synchronize()
        ts.append((time.perf_counter() - t0) / (10 * inner))
    ts = np.array(ts) * 1e6
    return np.median(ts), np.percentile(ts, 90)


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--iters", type=int, default=500)
    args = ap.parse_args()
    n = args.iters

    x8c = torch.ones(8)
    x8 = torch.ones(8, device="npu")
    a8 = torch.ones(8, 8, device="npu")
    b8 = torch.ones(8, 8, device="npu")
    abig = torch.ones(1024, 1024, device="npu")
    bbig = torch.ones(1024, 1024, device="npu")

    def cpu_micro():
        for _ in range(50):
            y = x8c + 1

    def npu_micro_stream():
        for _ in range(50):
            y = x8 + 1  # launch 50 kernels, sync happens in timeit

    def npu_small_mm():
        for _ in range(50):
            y = a8 @ b8

    def npu_big_mm():
        y = abig @ bbig

    print(f"bench_launch_probe (us/op, median (p90); n={n})")
    for name, fn, inner in (("cpu_micro", cpu_micro, 50),
                            ("npu_micro_stream", npu_micro_stream, 50),
                            ("npu_small_mm", npu_small_mm, 50),
                            ("npu_big_mm", npu_big_mm, 1)):
        med, p90 = timeit(fn, n, inner)
        print(f"  {name:17s}: {med:9.2f}  ({p90:9.2f})", flush=True)
    # sync-every-op is a different loop shape (sync INSIDE), time separately
    def npu_micro_sync():
        y = x8 + 1
        torch.npu.synchronize()

    torch.npu.synchronize()
    ts = []
    for _ in range(n):
        t0 = time.perf_counter()
        npu_micro_sync()
        ts.append(time.perf_counter() - t0)
    ts = np.array(ts) * 1e6
    print(f"  {'npu_micro_sync':17s}: {np.median(ts):9.2f}  ({np.percentile(ts, 90):9.2f})",
          flush=True)


if __name__ == "__main__":
    main()
