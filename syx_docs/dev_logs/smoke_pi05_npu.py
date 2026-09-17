"""pi05 NPU smoke test: synthetic frame, no dataset download.

Validates: checkpoint load -> torch_npu forward -> timing. Mirrors what
NpuTorchPi05Policy does (syx_docs/designs/npu-torch-engine.md).
"""
import time

import numpy as np
import torch
import torch_npu

torch_npu.npu.set_compile_mode(jit_compile=False)

from lerobot.policies.factory import make_pre_post_processors
from lerobot.policies.pi05 import PI05Policy

MODEL = "/data/apxinf/weights/pi05_libero_finetuned"
TOK = "/data/apxinf/weights/paligemma-3b-pt-224"

print("== loading policy ==", flush=True)
t0 = time.time()
policy = PI05Policy.from_pretrained(MODEL)
# inference semantics: the NPU patch dropped the per-call .eval(), and this
# checkpoint ships gradient_checkpointing=True from training -- both make the
# GemmaModel forward trace a branch (use_cache warning) TorchAir cannot graph.
policy.model.gradient_checkpointing_disable()
policy.eval()
print(f"load: {time.time()-t0:.1f}s", flush=True)

preprocess, postprocess = make_pre_post_processors(
    policy.config,
    MODEL,
    preprocessor_overrides={
        "device_processor": {"device": "npu"},
        "tokenizer_processor": {"tokenizer_name": TOK},
    },
)
print("input_features:", policy.config.input_features, flush=True)
print("output_features:", policy.config.output_features, flush=True)
print("compile_model:", getattr(policy.config, "compile_model", None), flush=True)

# synthetic frame shaped exactly like a LeRobotDataset frame:
# batched [1, ...] with images in CHW (video-decode layout — the NPU patch's
# _preprocess_images assumes channels-first)
frame = {
    "observation.images.image": np.zeros((1, 3, 256, 256), np.uint8),
    "observation.images.image2": np.zeros((1, 3, 256, 256), np.uint8),
    "observation.images.empty_camera_0": np.zeros((1, 3, 224, 224), np.uint8),
    "observation.state": np.zeros((1, 8), np.float32),
    "task": ["put the black bowl on the stove"],
}
batch = preprocess(frame)

with torch.inference_mode():
    for i in range(3):
        t0 = time.time()
        out = policy.predict_action_chunk(batch)
        torch.npu.synchronize()
        print(f"warmup {i}: {time.time()-t0:.2f}s shape={tuple(out.shape)}", flush=True)

    times = []
    for i in range(10):
        t0 = time.time()
        out = policy.predict_action_chunk(batch)
        torch.npu.synchronize()
        times.append(time.time() - t0)
    print("times(ms):", [round(t * 1000, 1) for t in times], flush=True)
    print(f"P50: {sorted(times)[5]*1000:.1f}ms", flush=True)

    actions = postprocess(out)
    print("actions:", actions.detach().cpu().numpy()[:, :4], flush=True)
print("SMOKE_DONE", flush=True)
