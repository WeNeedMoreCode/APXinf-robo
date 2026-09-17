"""Watch our chain die: 60-step rollout with our eval semantics, dumping a PNG
every 10 steps + per-step action/eef logs. Visual forensics."""
import os
import sys

os.environ.setdefault("MUJOCO_GL", "egl")
sys.path.insert(0, "/data/apxinf/robo_src")
sys.path.insert(1, "/data/apxinf/engine_py/apxinf")

import numpy as np
from PIL import Image

from apxinf_robo import build_robot_policy
from apxinf_robo.envs.libero import libero_images, libero_state_lerobot, make_env
from libero.libero import benchmark

OUT = "/data/apxinf/mini_rollout"
os.makedirs(OUT, exist_ok=True)

suite = benchmark.get_benchmark_dict()["libero_object"]()
task = suite.tasks[0]
prompt = task.language
init0 = suite.get_task_init_states(0)[0]

policy = build_robot_policy(
    "franka_libero", "/data/apxinf/weights/pi05_libero_finetuned",
    engine="npu-torch", precision="fp16",
    tokenizer_dir="/data/apxinf/weights/paligemma-3b-pt-224",
)
policy.warmup()

env = make_env(task, seed=7)
env.reset()
obs = env.set_init_state(init0)
for _ in range(10):
    obs, _, _, _ = env.step([0.0] * 6 + [-1.0])

REPLAN = 5
plan = []
log = []
for step in range(60):
    if step % REPLAN == 0:
        images = libero_images(obs["agentview_image"], obs["robot0_eye_in_hand_image"])
        result = policy.infer({
            "observation/image": images[0],
            "observation/wrist_image": images[1],
            "observation/state": libero_state_lerobot(obs),
            "prompt": prompt,
        })
        plan = list(result["actions"][:REPLAN])
    act = plan[step % REPLAN]
    obs, _, _, info = env.step(act)
    done = env.check_success() if hasattr(env, "check_success") else info.get("is_success")
    log.append((step, act.tolist(), np.asarray(obs["robot0_eef_pos"]).round(3).tolist(),
                np.asarray(obs["robot0_gripper_qpos"]).round(3).tolist(), bool(done)))
    if step % 10 == 0:
        Image.fromarray(np.ascontiguousarray(obs["agentview_image"])).save(f"{OUT}/step{step:03d}.png")
    if done:
        print(f"SUCCESS at step {step}!", flush=True)
        break

for row in log[::5]:
    print("step", row[0], "act", np.round(row[1], 3).tolist(), "eef", row[2],
          "grip", row[3], "success", row[4], flush=True)
print("MINI_DONE")
