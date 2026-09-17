"""Verify exact-noise injection: same noise + same obs -> identical actions."""
import sys

sys.path.insert(0, "/data/apxinf/robo_src")
sys.path.insert(1, "/data/apxinf/engine_py/apxinf")

import numpy as np

from apxinf_robo import build_robot_policy

policy = build_robot_policy(
    "franka_libero",
    "/data/apxinf/weights/pi05_libero_finetuned",
    engine="npu-torch",
    precision="fp16",
    tokenizer_dir="/data/apxinf/weights/paligemma-3b-pt-224",
)

rng = np.random.default_rng(42)
obs = {
    "observation/image": rng.integers(0, 255, (256, 256, 3), dtype=np.uint8),
    "observation/wrist_image": rng.integers(0, 255, (256, 256, 3), dtype=np.uint8),
    "observation/state": rng.uniform(-1, 1, 8).astype(np.float32),
    "prompt": "put the black bowl on the stove",
}
noise = rng.standard_normal((1, 50, 7)).astype(np.float32)

# warmup (compile), no noise
policy.infer(obs)

a = policy.infer(obs, noise=noise)["actions"]
b = policy.infer(obs, noise=noise)["actions"]
c = policy.infer(obs)["actions"]  # internal sampling again

print("deterministic with same noise (fp16 tol):", np.allclose(a, b, atol=2e-3, rtol=0))
print("differs from internal sampling:", not np.allclose(a, c, atol=2e-3, rtol=0))
print("max |a-b|:", float(np.abs(a - b).max()))
print("max |a-c|:", float(np.abs(a - c).max()))
# Bitwise reproducibility is NOT guaranteed: aclnn kernels vary tiling/ordering
# between runs (observed 2^-10, one fp16 ulp). Same noise must agree to within
# that quantum, different noise must diverge well beyond it.
assert np.allclose(a, b, atol=2e-3, rtol=0), "same noise should reproduce actions"
assert not np.allclose(a, c, atol=2e-3, rtol=0), "different noise should change the output"

# shape rejection
try:
    policy.infer(obs, noise=rng.standard_normal((1, 10, 7)).astype(np.float32))
    raise AssertionError("bad noise shape should have raised")
except ValueError as e:
    print("shape guard OK:", e)

policy.close()
print("NOISE_TEST_DONE")
