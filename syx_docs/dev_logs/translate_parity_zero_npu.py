"""Zero-NPU, zero-weight translation parity (2026-09-17).

One real evaluation frame (reset + set_init_state + 10 settle steps, exactly
what run_episode produces) through both batch-building paths:

  OFFICIAL: off_obs -> LiberoProcessorStep -> preprocess      (mini_official.py,
            i.e. the semantics of lerobot's own LIBERO eval, 9/10 baseline)
  OURS:     libero_images + libero_state_lerobot -> NpuTorchPi05Policy.
            _to_frame -> preprocess                            (eval_libero.py)

Compares the frame (pre-preprocess) and the batch (post-preprocess) field by
field. No model weights, no NPU -- ~40s per run on CPU, so iteration on the
parity question costs seconds, not a 3-minute model load.

Run on the server:
  docker exec -i apxinf_npu bash -c 'cd /data/apxinf && \
    MUJOCO_GL=egl python3 translate_parity_zero_npu.py'
"""
import os
import sys

os.environ.setdefault("MUJOCO_GL", "egl")
sys.path.insert(0, "/data/apxinf/robo_src")
sys.path.insert(1, "/data/apxinf/engine_py/apxinf")

import numpy as np
import torch
from lerobot.policies.factory import make_pre_post_processors
from lerobot.processor.env_processor import LiberoProcessorStep
from lerobot.policies.pi05 import PI05Policy

from apxinf_robo.envs.libero import make_env, libero_images, libero_state_lerobot
from apxinf_robo.cli.eval_libero import libero_convention
from apxinf_robo.npu_torch import NpuTorchPi05Policy
from libero.libero import benchmark

MODEL = "/data/apxinf/weights/pi05_libero_finetuned"
TOK = "/data/apxinf/weights/paligemma-3b-pt-224"

print("== load checkpoint config (no weights) ==", flush=True)
from lerobot.policies.pretrained import PreTrainedConfig

cfg = PreTrainedConfig.from_pretrained(MODEL)
preprocess, postprocess = make_pre_post_processors(
    cfg, MODEL,
    preprocessor_overrides={"device_processor": {"device": "cpu"},
                            "tokenizer_processor": {"tokenizer_name": TOK}},
)

print("== env frame t=0 (reset + init + 10 settle, seed=7) ==", flush=True)
suite = benchmark.get_benchmark_dict()["libero_object"]()
task = suite.tasks[0]
init0 = suite.get_task_init_states(0)[0]
prompt = task.language
env = make_env(task, seed=7)
env.reset()
obs = env.set_init_state(init0)
for _ in range(10):
    obs, _, _, _ = env.step([0.0] * 6 + [-1.0])


# ---- OFFICIAL path (mini_official.py semantics) -----------------------------
proc = LiberoProcessorStep()


def off_obs(o):
    return proc._process_observation({
        "observation.images.image":
            torch.from_numpy(np.ascontiguousarray(o["agentview_image"]))[None]
            .permute(0, 3, 1, 2),
        "observation.images.image2":
            torch.from_numpy(np.ascontiguousarray(o["robot0_eye_in_hand_image"]))[None]
            .permute(0, 3, 1, 2),
        "observation.robot_state": {
            "eef": {"pos": torch.from_numpy(np.asarray(o["robot0_eef_pos"], np.float32))[None],
                    "quat": torch.from_numpy(np.asarray(o["robot0_eef_quat"], np.float32))[None],
                    "mat": None},
            "gripper": {"qpos": torch.from_numpy(np.asarray(o["robot0_gripper_qpos"], np.float32))[None],
                        "qvel": None},
            "joints": None,
        },
        "task": [prompt],
    })


off_frame = off_obs(obs)
off_batch = preprocess(off_frame)

# ---- OURS path (eval_libero + NpuTorchPi05Policy) ---------------------------
image_features, state_feature, model_state_dim = [], None, None
for name, feat in dict(cfg.input_features).items():
    if feat.type == "VISUAL":
        image_features.append(name)
    elif feat.type == "STATE" and state_feature is None:
        state_feature = name
        model_state_dim = int(feat.shape[0])
print("checkpoint features:", image_features, state_feature, model_state_dim, flush=True)

# Replicate NpuTorchPi05Policy.__init__'s discovery, minus the weight load.
conv = libero_convention()
pol = object.__new__(NpuTorchPi05Policy)
pol._image_features = image_features
pol._state_feature = state_feature
pol._model_state_dim = model_state_dim
pol.image_keys = tuple(conv.image_keys)  # wire dialect, as the preset passes it
pol._empty_features = image_features[len(pol.image_keys):]
pol.state_key = conv.state_key
pol.prompt_key = conv.prompt_key
print("wire convention:", conv.image_keys, conv.state_key, conv.prompt_key, flush=True)
images = libero_images(obs["agentview_image"], obs["robot0_eye_in_hand_image"])
state8 = libero_state_lerobot(obs)
wire = {
    conv.image_keys[0]: images[0],
    conv.image_keys[1]: images[1],
    conv.state_key: state8,
    conv.prompt_key: prompt,
}
ours_frame = pol._to_frame(wire)
ours_batch = preprocess(ours_frame)


# ---- compare -----------------------------------------------------------------
def as_t(x):
    if isinstance(x, torch.Tensor):
        return x.detach().cpu()
    return torch.as_tensor(np.asarray(x))


def cmp_dict(a, b, label):
    print(f"---- {label} ----", flush=True)
    ka, kb = set(map(str, a)), set(map(str, b))
    for k in sorted(ka | kb):
        if k not in ka:
            print(f"  [{k}] ONLY IN OURS; type={type(b[k]).__name__}")
            continue
        if k not in kb:
            print(f"  [{k}] ONLY IN OFFICIAL; type={type(a[k]).__name__}")
            continue
        try:
            va, vb = as_t(a[k]), as_t(b[k])
        except (TypeError, ValueError):
            print(f"  [{k}] non-numeric official={a[k]!r} ours={b[k]!r}")
            continue
        if va.shape != vb.shape:
            print(f"  [{k}] SHAPE official={tuple(va.shape)} ours={tuple(vb.shape)}")
            continue
        flag = "" if va.dtype == vb.dtype else f" DTYPE official={va.dtype} ours={vb.dtype}"
        # Compare in a common domain: uint8 -> [0,1] float, so a residual
        # maxdiff near zero means "same pixels", not "scale mismatch".
        va_n = va.float() / 255.0 if va.dtype == torch.uint8 else va.float()
        vb_n = vb.float() / 255.0 if vb.dtype == torch.uint8 else vb.float()
        d = (va_n - vb_n).abs()
        print(f"  [{k}] shape={tuple(va.shape)}{flag} "
              f"maxdiff={d.max().item():.3e} meandiff={d.mean().item():.3e}")


print("==== FRAME layer (before preprocess) ====", flush=True)
cmp_dict(off_frame, ours_frame, "official vs ours")
print("==== BATCH layer (after preprocess) ====", flush=True)
cmp_dict(off_batch, ours_batch, "official vs ours")

print("state vectors:")
print("  official:", np.round(as_t(off_batch[state_feature]).numpy().reshape(-1), 5).tolist())
print("  ours    :", np.round(as_t(ours_batch[state_feature]).numpy().reshape(-1), 5).tolist())
print("DONE")
