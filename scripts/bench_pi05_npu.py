"""Benchmark PI0.5 on Ascend NPU through the apxinf_robo L2 API.

NPU counterpart of ``scripts/bench_pi05.py`` (which targets the Rust/CUDA
engine). Measures the full ``build_robot_policy(..., engine="npu-torch")``
path: wire-format observation -> ``infer`` -> deployable actions, reporting
``model_ms`` (model call incl. its internal image prep) and ``total_ms``
(wrapper + preprocess + model + postprocess).

Examples:

    python scripts/bench_pi05_npu.py --model-dir /data/apxinf/weights/pi05_libero_finetuned \
        --tokenizer-dir /data/apxinf/weights/paligemma-3b-pt-224 \
        --warmup 10 --samples 30 --out devlocal/benchmark/npu.json

Set the target chip with ASCEND_RT_VISIBLE_DEVICES (default 0).
"""

from __future__ import annotations

import argparse
import json
import pathlib
import statistics
import sys
import time

import numpy as np


def parse_args(argv=None):
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--model-dir", type=pathlib.Path, required=True)
    p.add_argument("--tokenizer-dir", type=pathlib.Path, default=None)
    p.add_argument("--robot", default="franka_libero", help="robot preset (wire keys)")
    p.add_argument("--prompt", default="put the black bowl on the stove")
    p.add_argument("--warmup", type=int, default=10)
    p.add_argument("--samples", type=int, default=30)
    p.add_argument("--out", type=pathlib.Path, default=None, help="write JSON stats here")
    p.add_argument(
        "--seed", type=int, default=0, help="rng seed for the synthetic observation"
    )
    return p.parse_args(argv)


def percentile(sorted_values, q):
    if not sorted_values:
        return float("nan")
    idx = min(len(sorted_values) - 1, max(0, round(q / 100 * (len(sorted_values) - 1))))
    return sorted_values[idx]


def main() -> None:
    args = parse_args()

    from apxinf_robo import build_robot_policy

    policy = build_robot_policy(
        args.robot,
        args.model_dir,
        engine="npu-torch",
        precision="fp16",
        tokenizer_dir=args.tokenizer_dir,
    )
    meta = dict(policy.metadata)
    print("engine:", meta.get("engine"), "| robot:", meta.get("robot"))

    rng = np.random.default_rng(args.seed)
    obs = {
        "observation/image": rng.integers(0, 255, (256, 256, 3), dtype=np.uint8),
        "observation/wrist_image": rng.integers(0, 255, (256, 256, 3), dtype=np.uint8),
        "observation/state": rng.uniform(-1, 1, 8).astype(np.float32),
        "prompt": args.prompt,
    }

    started = time.perf_counter()
    for _ in range(args.warmup):
        policy.infer(obs)
    warmup_s = time.perf_counter() - started

    model_ms, total_ms = [], []
    for _ in range(args.samples):
        result = policy.infer(obs)
        model_ms.append(result["timing"]["model_ms"])
        total_ms.append(result["timing"]["total_ms"])
    actions = result["actions"]

    def stats(values):
        s = sorted(values)
        return {
            "p50": round(percentile(s, 50), 2),
            "p90": round(percentile(s, 90), 2),
            "mean": round(statistics.fmean(s), 2),
            "min": round(s[0], 2),
            "max": round(s[-1], 2),
        }

    report = {
        "engine": "npu-torch",
        "model_dir": str(args.model_dir),
        "robot": args.robot,
        "precision": "fp16",
        "samples": args.samples,
        "warmup_s": round(warmup_s, 1),
        "action_shape": list(actions.shape),
        "model_ms": stats(model_ms),
        "total_ms": stats(total_ms),
        "metadata": meta,
    }
    print(json.dumps(report, indent=2, default=str))
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(report, indent=2, default=str))
        print(f"wrote {args.out}")
    policy.close()


if __name__ == "__main__":
    sys.exit(main())
