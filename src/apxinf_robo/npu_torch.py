"""NPU (torch_npu) engine implementation of the ``Policy`` contract.

Phase-1 of the Ascend NPU port (see ``syx_docs/designs/npu-torch-engine.md``):
``build_robot_policy(robot, model_dir, engine="npu-torch")`` reaches this module
through ``apxinf_robo.engine.load_policy`` -- the single routing point. The
upstream Rust/CUDA engine path is untouched.

The engine is LeRobot's PI0.5 implementation running on torch_npu with the
ModelZoo NPU adaptations (FP16, FRACTAL_NZ weights, ``npu_rotary_mul`` RoPE,
TorchAir graph compilation). Checkpoints are LeRobot-format; the reference is
``lerobot/pi05_libero_finetuned`` (ModelScope).

Contract notes (mirrors ``apxinf.policies.base.Policy``):

- ``infer`` returns ``actions`` (float32 ``[horizon, action_dim]``, unnormalized
  domain), ``normalized_actions``, ``timing`` (``model_ms`` measures the model
  call incl. its internal image preprocessing, unlike the Rust engine whose
  resize runs in the pre-pipeline), and ``metadata``.
- ``noise=`` is accepted for signature compatibility but not yet wired through
  (LeRobot samples internally); passing it raises. Tracking: roadmap phase-1.
"""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence

import numpy as np

__all__ = ["NpuTorchPi05Policy", "SUPPORTED_PRECISIONS"]

#: What this engine accepts for ``precision=``. The 310P3 has no BF16/FP8, and
#: the ModelZoo patch hardcodes float16 everywhere, so that is the only mode.
SUPPORTED_PRECISIONS = ("fp16", "auto", "float16")


class _SilentLogger:
    """Stand-in that keeps ``logger.warning_once(...)`` calls traceable.

    torch._dynamo refuses ``logging.Logger`` method calls outright (``Unsupported:
    Logger not supported``), which aborts TorchAir fullgraph compilation of the
    gemma forward -- the transformers ``fix/lerobot_openpi`` branch carries two
    ``warning_once`` calls that pi05 hits on every step. A plain object with
    no-op methods inlines to nothing under dynamo, so swapping the module-level
    ``logger`` restores compilability without touching the installed library.
    """

    def warning_once(self, *args, **kwargs): ...
    def warning(self, *args, **kwargs): ...
    def info(self, *args, **kwargs): ...
    def debug(self, *args, **kwargs): ...
    def error(self, *args, **kwargs): ...
    def critical(self, *args, **kwargs): ...


def _silence_transformers_loggers() -> None:
    """Idempotent: point gemma/siglip module loggers at the silent stand-in."""
    import transformers.models.gemma.modeling_gemma as gemma_mod
    import transformers.models.siglip.modeling_siglip as siglip_mod

    for mod in (gemma_mod, siglip_mod):
        if not isinstance(getattr(mod, "logger", None), _SilentLogger):
            mod.logger = _SilentLogger()


class NpuTorchPi05Policy:
    """A LeRobot PI0.5 checkpoint on Ascend NPU, shaped like an ApxInf policy."""

    def __init__(
        self,
        model_dir,
        *,
        image_keys: Optional[Sequence[str]] = None,
        state_key: Optional[str] = None,
        prompt_key: str = "prompt",
        action_dim: Optional[int] = None,
        metadata: Optional[Mapping[str, Any]] = None,
        precision: str = "fp16",
        device: str = "npu",
        tokenizer_dir=None,
        discrete_state: Optional[bool] = None,
        **kwargs: Any,
    ) -> None:
        # ``tokenizer_path`` is what the upstream CLIs call it.
        if tokenizer_dir is None:
            tokenizer_dir = kwargs.pop("tokenizer_path", None)
        import torch
        import torch_npu  # noqa: F401  (registers the npu backend)

        torch_npu.npu.set_compile_mode(jit_compile=False)

        if precision not in SUPPORTED_PRECISIONS:
            raise ValueError(
                f"npu-torch engine supports {list(SUPPORTED_PRECISIONS)}; got {precision!r}"
            )
        model_type = kwargs.pop("model_type", None) or "pi05"
        if model_type not in ("pi05", "pi0", "pi05_libero"):
            raise ValueError(
                f"npu-torch engine implements the pi05 family; got model_type {model_type!r}"
            )
        if "npu" not in str(device):
            # The CLIs default --device cuda:0; this engine has exactly one home.
            print(f"npu-torch: mapping device {device!r} -> 'npu'")
            device = "npu"
        if discrete_state:
            raise NotImplementedError(
                "discrete_state is an openpi-checkpoint feature; the npu-torch "
                "engine loads LeRobot-format checkpoints only"
            )
        unknown = set(kwargs) - {"engine"}
        if unknown:
            raise TypeError(f"npu-torch engine got unexpected options: {sorted(unknown)}")

        from lerobot.policies.factory import make_pre_post_processors
        from lerobot.policies.pi05 import PI05Policy

        _silence_transformers_loggers()

        self._torch = torch
        model_dir = Path(model_dir)
        self.device = device

        # The ModelZoo patch forces .to(float16).to("npu") inside the policy's
        # own __init__, and casts every nn.Linear weight to FRACTAL_NZ in
        # from_pretrained, so a plain load lands fully on-device in fp16.
        self.policy = PI05Policy.from_pretrained(str(model_dir))
        # Inference semantics. The NPU patch drops the per-call ``.eval()`` for
        # speed, and fine-tuned checkpoints ship ``gradient_checkpointing=True``
        # from training -- left on, the GemmaModel forward takes a branch whose
        # warning call breaks TorchAir fullgraph tracing. Do it once here.
        self.policy.model.gradient_checkpointing_disable()
        self.policy.eval()

        if tokenizer_dir is None:
            # paligemma tokenizer is a separate download on ModelScope; without
            # it the tokenizer processor tries the Hub. Default to sibling dir.
            tokenizer_dir = model_dir.parent / "paligemma-3b-pt-224"
        self.tokenizer_dir = tokenizer_dir
        self.preprocess, self.postprocess = make_pre_post_processors(
            self.policy.config,
            str(model_dir),
            preprocessor_overrides={
                "device_processor": {"device": "npu"},
                "tokenizer_processor": {"tokenizer_name": str(tokenizer_dir)},
            },
        )

        # Model-side input feature names, discovered from the checkpoint config.
        # LeRobot names inputs after the fine-tune dataset's columns; the wire
        # keys we were given (LIBERO dialect, a robot preset, ...) map onto
        # them positionally, in the order the checkpoint consumes views.
        self._image_features: List[str] = []
        self._state_feature: Optional[str] = None
        self._model_state_dim: Optional[int] = None
        for name, feat in dict(self.policy.config.input_features).items():
            if feat.type == "VISUAL":
                self._image_features.append(name)
            elif feat.type == "STATE" and self._state_feature is None:
                self._state_feature = name
                shape = getattr(feat, "shape", None)
                self._model_state_dim = int(shape[0]) if shape else None
        if not self._image_features:
            raise ValueError("checkpoint config declares no VISUAL input features")

        self.image_keys: Sequence[str] = tuple(image_keys) if image_keys else tuple(
            self._image_features
        )
        # Checkpoints fine-tuned on fewer cameras than the architecture consumes
        # (e.g. LIBERO's 2 views vs pi05's 3 slots) carry placeholder features
        # like ``empty_camera_0``. Views with no wire key get zero images.
        if len(self.image_keys) > len(self._image_features):
            raise ValueError(
                f"checkpoint consumes {len(self._image_features)} views "
                f"({self._image_features}); got {len(self.image_keys)} image_keys"
            )
        self._empty_features = self._image_features[len(self.image_keys):]
        if self._state_feature is not None:
            self.state_key = state_key or self._state_feature
        else:
            self.state_key = state_key
        self.prompt_key = prompt_key

        out_features = dict(self.policy.config.output_features)
        chunk = int(getattr(self.policy.config, "chunk_size", 10))
        self._action_horizon = chunk
        self._model_action_dim = int(
            out_features["action"].shape[0] if "action" in out_features else -1
        )
        self._action_dim = int(action_dim) if action_dim is not None else self._model_action_dim

        self.metadata: Dict[str, Any] = {
            "engine": "npu-torch",
            "model_type": "pi05",
            "precision": "fp16",
            "device": "npu",
            "image_keys": list(self.image_keys),
            "state_key": self.state_key,
            "prompt_key": self.prompt_key,
            "discrete_state": False,
            "action_horizon": self._action_horizon,
            "action_dim": self._action_dim,
            "model_input_features": {
                "images": self._image_features,
                "state": self._state_feature,
            },
            **(dict(metadata) if metadata else {}),
        }

    # -- Policy protocol ----------------------------------------------------

    @property
    def action_dim(self) -> int:
        return self._action_dim

    @property
    def action_horizon(self) -> int:
        return self._action_horizon

    def _to_frame(self, observation: Mapping[str, Any]) -> Dict[str, Any]:
        """Wire-keyed observation dict -> LeRobot frame dict.

        Placeholder camera features with no wire key are **omitted on
        purpose**: ``PI05Policy._preprocess_images`` fills missing visual keys
        with a constant -1 pad image and a zero mask, which drops that camera
        from the cross-attention -- the semantics this checkpoint was
        fine-tuned with (``empty_camera_0``). Feeding an explicit zero image
        flips the mask to 1, so a real siglip embedding of a black frame leaks
        into the conditioning and systematically derails the policy
        (libero_object 0/10 vs official 9/10; root cause 2026-09-17).
        """
        frame: Dict[str, Any] = {}
        for wire, feature in zip(self.image_keys, self._image_features):
            if wire not in observation:
                raise KeyError(f"observation is missing image key {wire!r}")
            img = np.asarray(observation[wire])
            if img.ndim == 3:  # HWC wire input -> batched CHW frame
                img = img.transpose(2, 0, 1)[None]
            # LeRobot frames are float32 [0,1] CHW (lerobot's own eval does
            # uint8->float32->/255 before the policy). The NPU patch's
            # `img * 2 - 1` siglip normalization assumes that range; raw
            # uint8 [0,255] would produce [-1, 509] and silently destroy
            # the policy.
            if img.dtype == np.uint8:
                img = img.astype(np.float32) / 255.0
            frame[feature] = img

        if self._state_feature is not None:
            if self.state_key not in observation:
                raise KeyError(f"observation is missing state key {self.state_key!r}")
            state = np.asarray(observation[self.state_key], dtype=np.float32)
            want = self._model_state_dim
            if want is not None and state.shape[-1] != want:
                raise ValueError(
                    f"state width {state.shape[-1]} != checkpoint's {want}. "
                    "LeRobot LIBERO checkpoints expect pos(3)+axis-angle(3)+both "
                    "finger qpos(2) -- e.g. apxinf_robo.envs.libero."
                    "libero_state_lerobot. The 7-value openpi-style state "
                    "(one finger) cannot be completed here: the second finger "
                    "value is information the caller dropped."
                )
            frame[self._state_feature] = state[None] if state.ndim == 1 else state
        prompt = observation.get(self.prompt_key)
        if prompt is None:
            for alt in ("task", "prompt"):
                prompt = observation.get(alt)
                if prompt is not None:
                    break
        if not isinstance(prompt, str):
            raise KeyError(f"observation is missing prompt key {self.prompt_key!r}")
        frame["task"] = [prompt]
        return frame

    def infer(
        self, observation: Mapping[str, Any], *, noise: Optional[np.ndarray] = None
    ) -> Dict[str, Any]:
        torch = self._torch
        started = time.perf_counter()
        frame = self._to_frame(observation)
        batch = self.preprocess(frame)

        # Exact-noise injection: LeRobot samples the flow-matching initial
        # latent inside sample_actions via ``model.sample_noise(shape, device)``.
        # The sampler works in the model's *padded* action space (chunk x 32);
        # the caller names the deployable dims, the rest is zero-filled.
        # Swapping that bound method makes the run deterministic without
        # touching the lerobot source.
        sampler_patch = None
        if noise is not None:
            noise_t = torch.from_numpy(np.ascontiguousarray(noise, dtype=np.float32))
            if noise_t.ndim == 2:  # [H, D] -> [1, H, D]
                noise_t = noise_t[None]
            if noise_t.shape[1] != self._action_horizon:
                raise ValueError(
                    f"noise horizon {noise_t.shape[1]} != action_horizon "
                    f"{self._action_horizon}"
                )

            def _exact_noise(shape, device, _noise=noise_t):
                shape = tuple(shape)
                out = torch.zeros(shape, dtype=torch.float16, device=device)
                d = min(shape[-1], _noise.shape[-1])
                out[..., :d] = _noise[..., :d].to(device=device, dtype=torch.float16)
                return out

            model = self.policy.model
            sampler_patch = (model, model.sample_noise)
            model.sample_noise = _exact_noise

        try:
            model_started = time.perf_counter()
            with torch.inference_mode():
                # Full chunk, not select_action's n_action_steps slice: the ApxInf
                # contract returns [horizon, action_dim] and lets the caller replan.
                normalized = self.policy.predict_action_chunk(batch)
            torch.npu.synchronize()
            model_ms = (time.perf_counter() - model_started) * 1000.0
            if os.environ.get("APXINF_NPU_TIMING"):
                print(f"[npu-torch] model_ms={model_ms:.0f}", flush=True)
        finally:
            if sampler_patch is not None:
                model, original = sampler_patch
                model.sample_noise = original

        normalized_np = normalized.detach().cpu().numpy()
        actions = self.postprocess(normalized).detach().cpu().numpy().astype(np.float32)
        if actions.ndim == 3:  # [B, H, D] with B == 1
            actions = actions[0]
        if actions.ndim != 2:
            raise RuntimeError(f"unexpected action rank {actions.shape}")
        total_ms = (time.perf_counter() - started) * 1000.0

        return {
            "actions": actions,
            "normalized_actions": np.asarray(normalized_np, dtype=np.float32).squeeze(0),
            "timing": {"model_ms": model_ms, "total_ms": total_ms},
            "metadata": self.metadata,
        }

    __call__ = infer

    def infer_step(self, observation: Mapping[str, Any]) -> np.ndarray:
        """Official LeRobot execution semantics: one action per call.

        Delegates to ``PI05Policy.select_action``, whose internal action queue
        replans only when exhausted (every ``n_action_steps`` steps) and pops
        one action otherwise. That is the exact protocol this checkpoint was
        evaluated with upstream (LeRobot ``lerobot_eval``), and on it the
        checkpoint reproduces its published LIBERO success rates; the
        chunk-returning :meth:`infer` re-samples flow noise per replan, which
        this checkpoint is sensitive to. Rollout loops that want the official
        behaviour call this every simulator step.
        """
        torch = self._torch
        batch = self.preprocess(self._to_frame(observation))
        with torch.inference_mode():
            sel = self.policy.select_action(batch)
        return (
            self.postprocess(sel).detach().cpu().numpy().reshape(-1)
            .astype(np.float32)
        )

    def reset(self) -> None:
        """Episode boundary: drop LeRobot's internal action queue.

        ``select_action`` replans only when its queue is exhausted, and that
        queue lives on the policy instance across episodes. Without a reset
        the first steps of episode N+1 replay stale actions from episode N's
        tail (up to n_action_steps - 1 of them) -- the official eval loop
        this checkpoint was published with calls ``policy.reset()`` at every
        episode start.
        """
        if hasattr(self.policy, "reset"):
            self.policy.reset()

    def warmup(self) -> None:
        """Compile the TorchAir graphs once, off the latency ledger.

        First real call otherwise pays ~100s of graph compilation; harnesses
        that average per-call time across an episode (eval-libero) fold that
        one-off cost into every call's mean. A zeros observation exercises the
        same shapes, which is all dynamic=False compilation keys on.
        """
        obs = {key: np.zeros((256, 256, 3), np.uint8) for key in self.image_keys}
        if self.state_key is not None and self._model_state_dim is not None:
            obs[self.state_key] = np.zeros(self._model_state_dim, np.float32)
        obs[self.prompt_key] = "warmup"
        self.infer(obs)

    def close(self) -> None:
        torch = self._torch
        self.policy = None
        self.preprocess = self.postprocess = None
        if torch is not None:
            torch.npu.synchronize()
            torch.npu.empty_cache()

    def __enter__(self) -> "NpuTorchPi05Policy":
        return self

    def __exit__(self, *exc_info) -> None:
        self.close()
