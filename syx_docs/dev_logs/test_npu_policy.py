"""Phase-1 e2e: apxinf_robo.build_robot_policy with engine='npu-torch' on NPU.

Wire-format observation (LIBERO keys, HWC uint8) in -> deployable actions out.
"""
import sys
import time

sys.path.insert(0, "/data/apxinf/robo_src")
sys.path.insert(1, "/data/apxinf/engine_py/apxinf")  # project root: package lives at apxinf/apxinf

import numpy as np

from apxinf_robo import build_robot_policy

rng = np.random.default_rng(0)

policy = build_robot_policy(
    "franka_libero",
    "/data/apxinf/weights/pi05_libero_finetuned",
    engine="npu-torch",
    precision="fp16",
    tokenizer_dir="/data/apxinf/weights/paligemma-3b-pt-224",
)
print("metadata:", {k: v for k, v in policy.metadata.items() if k != "model_input_features"})
print("action_dim:", policy.action_dim, "action_horizon:", policy.action_horizon)

obs = {
    "observation/image": rng.integers(0, 255, (256, 256, 3), dtype=np.uint8),
    "observation/wrist_image": rng.integers(0, 255, (256, 256, 3), dtype=np.uint8),
    "observation/state": rng.uniform(-1, 1, 8).astype(np.float32),
    "prompt": "put the black bowl on the stove",
}

for i in range(3):
    t0 = time.time()
    result = policy.infer(obs)
    print(f"call {i}: {time.time()-t0:.2f}s timing={result['timing']}")

print("actions shape:", result["actions"].shape, result["actions"].dtype)
print("actions[0]:", result["actions"][0])
policy.close()
print("E2E_DONE")
