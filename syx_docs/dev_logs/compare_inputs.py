"""Byte-level compare: our wire->frame path vs the official LiberoProcessorStep
path, same simulator frame, after the shared preprocess pipeline."""
import os
import sys

os.environ.setdefault("MUJOCO_GL", "egl")
sys.path.insert(0, "/data/apxinf/robo_src")
sys.path.insert(1, "/data/apxinf/engine_py/apxinf")

import numpy as np
import torch
from lerobot.policies.factory import make_pre_post_processors
from lerobot.policies.pi05 import PI05Policy
from lerobot.processor.env_processor import LiberoProcessorStep

from apxinf_robo.envs.libero import libero_state_lerobot, make_env
from libero.libero import benchmark

MODEL = "/data/apxinf/weights/pi05_libero_finetuned"
TOK = "/data/apxinf/weights/paligemma-3b-pt-224"
PROMPT = None  # filled from task.language

cfg = PI05Policy.from_pretrained.__globals__  # noqa -- just to keep linters quiet
from lerobot.policies.pi05.configuration_pi05 import PI05Config  # noqa: E402

policy = PI05Policy.from_pretrained(MODEL)
policy_cfg = policy.config
preprocess, _ = make_pre_post_processors(
    policy_cfg, MODEL,
    preprocessor_overrides={"device_processor": {"device": "cpu"},
                            "tokenizer_processor": {"tokenizer_name": TOK}},
)

suite = benchmark.get_benchmark_dict()["libero_10"]()
task = suite.tasks[0]
prompt = task.language
print("task:", prompt)

env = make_env(task, seed=7)
obs = env.reset()

# ---- official path: LiberoProcessorStep on torch batched tensors ----
raw = {
    "observation.images.image": torch.from_numpy(
        np.ascontiguousarray(obs["agentview_image"])
    )[None],  # (1,H,W,C) uint8
    "observation.images.image2": torch.from_numpy(
        np.ascontiguousarray(obs["robot0_eye_in_hand_image"])
    )[None],
    "observation.robot_state": {
        "eef": {"pos": torch.from_numpy(np.asarray(obs["robot0_eef_pos"], np.float32))[None],
                "quat": torch.from_numpy(np.asarray(obs["robot0_eef_quat"], np.float32))[None],
                "mat": None},
        "gripper": {"qpos": torch.from_numpy(np.asarray(obs["robot0_gripper_qpos"], np.float32))[None],
                    "qvel": None},
        "joints": None,
    },
    "task": [prompt],
}
proc = LiberoProcessorStep()
# LiberoProcessorStep flips dims [2,3] -> expects CHW; convert our HWC first
for k in ("observation.images.image", "observation.images.image2"):
    raw[k] = raw[k].permute(0, 3, 1, 2)
official_frame = proc._process_observation(raw)

# ---- our path: wrapper _to_frame equivalent ----
wire = {
    "observation/image": obs["agentview_image"],
    "observation/wrist_image": obs["robot0_eye_in_hand_image"],
    "observation/state": libero_state_lerobot(obs),
    "prompt": prompt,
}
img0 = np.asarray(wire["observation/image"])[::-1, ::-1].transpose(2, 0, 1)[None]
img1 = np.asarray(wire["observation/wrist_image"])[::-1, ::-1].transpose(2, 0, 1)[None]
our_frame = {
    "observation.images.image": img0,
    "observation.images.image2": img1,
    "observation.state": wire["observation/state"][None],
    "task": [prompt],
}

# ---- byte compare ----
for k in ("observation.images.image", "observation.images.image2"):
    a = official_frame[k].numpy(); b = np.asarray(our_frame[k])
    print(k, "official", a.shape, a.dtype, "| ours", b.shape, b.dtype,
          "| equal:", np.array_equal(a.astype(np.uint8), b.astype(np.uint8)))
sa = official_frame["observation.state"].numpy(); sb = np.asarray(our_frame["observation.state"])
print("state official:", sa, "\nstate ours:  ", sb, "\nstate equal:", np.allclose(sa, sb, atol=1e-6))

bo = preprocess(dict(official_frame)); bu = preprocess(dict(our_frame))
for name, b in (("official", bo), ("ours", bu)):
    st = b["observation.state"] if "observation.state" in b else None
    toks = b.get("observation.language.tokens")
    print(name, "tokens:", None if toks is None else toks.shape,
          "state:", None if st is None else st.shape)

tok_o = bo["observation.language.tokens"].numpy(); tok_u = bu["observation.language.tokens"].numpy()
print("tokens equal:", np.array_equal(tok_o, tok_u))
print("state-after-prep equal:",
      np.allclose(bo["observation.state"].numpy(), bu["observation.state"].numpy(), atol=1e-6))
print("COMPARE_DONE")
