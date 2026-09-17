"""Dump official-frame construction from the same init state, for byte-compare
against what the real eval feeds the wrapper. No model, no NPU, ~30s."""
import os
import sys

os.environ.setdefault("MUJOCO_GL", "egl")
sys.path.insert(0, "/data/apxinf/robo_src")
sys.path.insert(1, "/data/apxinf/engine_py/apxinf")

import numpy as np
import torch
from lerobot.processor.env_processor import LiberoProcessorStep

from apxinf_robo.envs.libero import libero_images, libero_state_lerobot, make_env
from libero.libero import benchmark

OUT = "/data/apxinf/dump_official"
os.makedirs(OUT, exist_ok=True)

suite = benchmark.get_benchmark_dict()["libero_object"]()
task = suite.tasks[0]
init0 = suite.get_task_init_states(0)[0]

env = make_env(task, seed=7)
env.reset()
obs = env.set_init_state(init0)
for _ in range(10):
    obs, _, _, _ = env.step([0.0] * 6 + [-1.0])

# official construction
t = {
    "observation.images.image": torch.from_numpy(np.ascontiguousarray(obs["agentview_image"]))[None].permute(0, 3, 1, 2),
    "observation.images.image2": torch.from_numpy(np.ascontiguousarray(obs["robot0_eye_in_hand_image"]))[None].permute(0, 3, 1, 2),
    "observation.robot_state": {
        "eef": {"pos": torch.from_numpy(np.asarray(obs["robot0_eef_pos"], np.float32))[None],
                "quat": torch.from_numpy(np.asarray(obs["robot0_eef_quat"], np.float32))[None],
                "mat": None},
        "gripper": {"qpos": torch.from_numpy(np.asarray(obs["robot0_gripper_qpos"], np.float32))[None],
                    "qvel": None},
        "joints": None,
    },
    "task": [task.language],
}
off = LiberoProcessorStep()._process_observation(t)
np.save(f"{OUT}/off_img0.npy", off["observation.images.image"].numpy())
np.save(f"{OUT}/off_img1.npy", off["observation.images.image2"].numpy())
np.save(f"{OUT}/off_state.npy", off["observation.state"].numpy())

# eval-harness construction (exactly what eval_libero does)
images = libero_images(obs["agentview_image"], obs["robot0_eye_in_hand_image"])
np.save(f"{OUT}/harness_img0.npy", np.asarray(images[0]).transpose(2, 0, 1)[None])
np.save(f"{OUT}/harness_img1.npy", np.asarray(images[1]).transpose(2, 0, 1)[None])
np.save(f"{OUT}/harness_state.npy", libero_state_lerobot(obs)[None])
with open(f"{OUT}/prompt.txt", "w") as f:
    f.write(task.language)
print("DUMPED", OUT)
