"""Inspect what the pi05 preprocess pipeline emits (shapes/dtypes), no model load."""
import numpy as np
import torch
from lerobot.policies.factory import make_pre_post_processors
from lerobot.policies.pi05.configuration_pi05 import PI05Config

MODEL = "/data/apxinf/weights/pi05_libero_finetuned"
TOK = "/data/apxinf/weights/paligemma-3b-pt-224"

cfg = PI05Config()
preprocess, postprocess = make_pre_post_processors(
    cfg, MODEL,
    preprocessor_overrides={"device_processor": {"device": "cpu"},
                            "tokenizer_processor": {"tokenizer_name": TOK}},
)

frame = {
    "observation.images.image": np.zeros((1, 256, 256, 3), np.uint8),
    "observation.images.image2": np.zeros((1, 256, 256, 3), np.uint8),
    "observation.images.empty_camera_0": np.zeros((1, 224, 224, 3), np.uint8),
    "observation.state": np.zeros((1, 8), np.float32),
    "task": ["put the black bowl on the stove"],
}
batch = preprocess(frame)
def show(d, prefix=""):
    for k, v in d.items():
        if isinstance(v, dict):
            show(v, prefix + k + ".")
        elif hasattr(v, "shape"):
            print(f"{prefix}{k}: shape={tuple(v.shape)} dtype={v.dtype}")
        else:
            r = repr(v)
            print(f"{prefix}{k}: {r[:80]}")
show(batch)
print("image_resolution:", cfg.image_resolution)
