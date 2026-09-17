"""Final control: ONE process, ONE env instance, same init state. Run official
semantics 25 steps, re-reset to the same init, run our semantics 25 steps.
Any behavioral difference is then attributable to the call chain alone."""
import os
import sys

os.environ.setdefault("MUJOCO_GL", "egl")
sys.path.insert(0, "/data/apxinf/robo_src")
sys.path.insert(1, "/data/apxinf/engine_py/apxinf")

import numpy as np
import torch
import torch_npu
from lerobot.policies.factory import make_pre_post_processors
from lerobot.policies.pi05 import PI05Policy
from lerobot.processor.env_processor import LiberoProcessorStep

from apxinf_robo.envs.libero import libero_images, libero_state_lerobot, make_env
from libero.libero import benchmark

torch_npu.npu.set_compile_mode(jit_compile=False)
MODEL = "/data/apxinf/weights/pi05_libero_finetuned"
TOK = "/data/apxinf/weights/paligemma-3b-pt-224"

policy = PI05Policy.from_pretrained(MODEL)
policy.model.gradient_checkpointing_disable()
policy.eval()
preprocess, postprocess = make_pre_post_processors(
    policy.config, MODEL,
    preprocessor_overrides={"device_processor": {"device": "npu"},
                            "tokenizer_processor": {"tokenizer_name": TOK}},
)
proc = LiberoProcessorStep()

suite = benchmark.get_benchmark_dict()["libero_object"]()
task = suite.tasks[0]
init0 = suite.get_task_init_states(0)[0]
prompt = task.language
env = make_env(task, seed=7)


def settle():
    env.reset()
    obs = env.set_init_state(init0)
    for _ in range(10):
        obs, _, _, _ = env.step([0.0] * 6 + [-1.0])
    return obs


def off_batch(o):
    return preprocess(proc._process_observation({
        "observation.images.image": torch.from_numpy(np.ascontiguousarray(o["agentview_image"]))[None].permute(0, 3, 1, 2),
        "observation.images.image2": torch.from_numpy(np.ascontiguousarray(o["robot0_eye_in_hand_image"]))[None].permute(0, 3, 1, 2),
        "observation.robot_state": {
            "eef": {"pos": torch.from_numpy(np.asarray(o["robot0_eef_pos"], np.float32))[None],
                    "quat": torch.from_numpy(np.asarray(o["robot0_eef_quat"], np.float32))[None],
                    "mat": None},
            "gripper": {"qpos": torch.from_numpy(np.asarray(o["robot0_gripper_qpos"], np.float32))[None],
                        "qvel": None},
            "joints": None,
        },
        "task": [prompt],
    }))


def our_batch(o):
    images = libero_images(o["agentview_image"], o["robot0_eye_in_hand_image"])
    return preprocess({
        "observation.images.image": np.ascontiguousarray(np.asarray(images[0]).transpose(2, 0, 1))[None],
        "observation.images.image2": np.ascontiguousarray(np.asarray(images[1]).transpose(2, 0, 1))[None],
        "observation.state": libero_state_lerobot(o)[None],
        "task": [prompt],
    })


with torch.inference_mode():
    # warm compile
    o = settle()
    policy.reset(); policy.select_action(off_batch(o))

    print("== OFFICIAL 25 steps ==", flush=True)
    o = settle()
    policy.reset()
    for s in range(25):
        sel = policy.select_action(off_batch(o))
        act = postprocess(sel).cpu().numpy().reshape(-1, 7)[0]
        o, _, _, _ = env.step(act)
        if s % 5 == 0:
            print(" off", s, "act", np.round(act, 2).tolist(),
                  "eef", np.asarray(o["robot0_eef_pos"]).round(3).tolist(), flush=True)

    print("== OURS 25 steps (replan 5) ==", flush=True)
    o = settle()
    plan = []
    for s in range(25):
        if s % 5 == 0:
            chunk = policy.predict_action_chunk(our_batch(o))
            plan = postprocess(chunk).cpu().numpy().reshape(-1, 7)
        act = plan[s % 5]
        o, _, _, _ = env.step(act)
        if s % 5 == 0:
            print(" our", s, "act", np.round(act, 2).tolist(),
                  "eef", np.asarray(o["robot0_eef_pos"]).round(3).tolist(), flush=True)
print("COMBINED_DONE")
