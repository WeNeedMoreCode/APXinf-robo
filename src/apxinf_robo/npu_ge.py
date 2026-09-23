"""Ascend GE static-OM engine (route C) — serve-process + bucketed policy.

Phase-3 closed-loop entry point for the NPU port. The three-segment GE OM
chain (vision / prefix / flow, baked per token length) runs as long-lived
``ge_model_probe GEB_E2E_SERVE`` processes inside the ``apxinf_rust``
container; this policy (running wherever the eval harness lives,
``apxinf_npu``) talks to them through a shared-file spool on /data.

Why a spool directory instead of a socket: the engine binary is bound to the
9.0.1 CANN in the rust container while the harness needs the torch/libero
stack of the npu container -- the only transport both see is the shared
/data mount. Per-request overhead is a ~1.8MB write + 1ms poll, irrelevant
next to the ~310ms inference.

Token-length bucketing is load-bearing: real prompts vary in length with the
number of digits in the discretized state (144/145/146 on libero_object
tasks 0-3), a static OM accepts exactly one length, so each length gets its
own {prefix, flow} OM pair and its own serve process. A supervisor inside
the rust container (``/data/apxinf/serve/supervisor.sh``) lazily bakes
missing buckets (~4 min) and spawns the processes; this side just writes
``ctrl/ensure_<L>`` and waits for ``tl<L>/ready``.

The preprocessing chain (_to_frame / preprocess / _preprocess_images /
postprocess) is *the same code* the 9/10 torch baseline and the offline
replay recorder ran, by delegation to ``NpuTorchPi05Policy`` -- the torch
model is loaded but never computes; actions come from the engine.
"""

from __future__ import annotations

import os
import struct
import time
from pathlib import Path
from typing import Any, Dict, Mapping, Optional

import numpy as np

__all__ = ["GeServePi05Policy", "SUPPORTED_PRECISIONS"]

SUPPORTED_PRECISIONS = ("fp16", "auto", "float16")

REQ_MAGIC = 0x47514531
RESP_MAGIC = 0x47525331
HOR = 50     # chunk size (checkpoint config)
ADIM = 32    # padded action dim; deployable slice is 7
GD = 7       # LIBERO deployable action width

_SERVE_ROOT = Path(os.environ.get("APXINF_GE_SERVE_ROOT", "/data/apxinf/serve"))
_READY_TIMEOUT = float(os.environ.get("APXINF_GE_READY_TIMEOUT", "1800"))
_REQ_TIMEOUT = float(os.environ.get("APXINF_GE_REQ_TIMEOUT", "180"))
# 传输模式：spool（默认，跨容器文件轮询——引擎进程在 apxinf_rust）或
# inproc（进程内直调 PyO3 GeServeModel，免 spool 轮询 ~15ms）。
# ⚠ inproc 前提：宿主进程链接 9.0.1 CANN（LD_LIBRARY_PATH 带 ge_builder +
# toolkit lib64）且**不同时加载 torch_npu**（8.5.1 与 9.0.1 同进程互斥）；
# 另 GE 库在 python 宿主内的 TBE 子进程管理存在已知兼容障碍（见
# syx_docs summary 2026-09-23）——import/open 失败自动回落 spool。
_TRANSPORT = os.environ.get("APXINF_GE_TRANSPORT", "spool")
_OM_ROOT = Path(os.environ.get("APXINF_GE_OM_ROOT", str(_SERVE_ROOT.parent / "om_cache")))


class _InprocClient:
    """In-process engine client (PyO3 ``apxinf_py.GeServeModel``) — the
    crate library surface (``GeServe``), same frame implementation as the
    serve processes. ``request`` is signature- and byte-compatible with
    ``_BucketClient.request`` so the policy switches transports unchanged.
    """

    def __init__(self, length: int, model_dir: str, *, fast: bool = True):
        import apxinf_py  # ImportError -> caller falls back to spool

        self.L = length
        om_dir = _OM_ROOT / f"tl{length}"
        self._m = apxinf_py.GeServeModel.open(str(om_dir), length, model_dir, fast)

    def request(self, patches: np.ndarray, ids: np.ndarray, noise: np.ndarray):
        acts, (tv, tp, tf) = self._m.infer(
            np.ascontiguousarray(patches, dtype=np.float32),
            np.ascontiguousarray(ids, dtype=np.uint32),
            np.ascontiguousarray(noise, dtype=np.float32),
        )
        return acts, (tv, tp, tf)


class _BucketClient:
    """One token-length bucket: request/response against its serve process.

    Spawning is the supervisor's job (different container); this side only
    publishes ``ctrl/ensure_<L>`` and waits for a ``ready`` file whose mtime
    is newer than the request -- a stale ready from a dead previous process
    is thereby detected and respawned.
    """

    def __init__(self, length: int, *, ready_timeout: float = _READY_TIMEOUT):
        self.L = length
        self.dir = _SERVE_ROOT / f"tl{length}"
        self.seq = 0
        self.ready_timeout = ready_timeout
        ctrl_dir = _SERVE_ROOT / "ctrl"
        ctrl_dir.mkdir(parents=True, exist_ok=True)
        self._ensure_ready()

    def _ensure_ready(self) -> None:
        ready = self.dir / "ready"
        # 两轮：并发启动风暴下 engine 偶发加载崩，supervisor 守护 respawn
        # 需要一个再触发（ensure 重写）+ 启动窗口
        for attempt in range(2):
            mark = time.time()
            (_SERVE_ROOT / "ctrl" / f"ensure_{self.L}").write_text("")
            deadline = mark + self.ready_timeout / 2
            while True:
                try:
                    if ready.stat().st_mtime >= mark - 1.0:
                        return
                except FileNotFoundError:
                    pass
                if time.time() > deadline:
                    break
                time.sleep(0.5)
        raise RuntimeError(
            f"serve bucket tl{self.L} 未就绪（等 {self.ready_timeout:.0f}s ×2）——"
            "检查 apxinf_rust 内 supervisor 是否在跑、"
            f"{self.dir}/stdout.log 与 {_SERVE_ROOT}/supervisor.log"
        )

    def request(self, patches: np.ndarray, ids: np.ndarray, noise: np.ndarray):
        """One inference round-trip. patches [768,588] f32 / ids [L] / noise [50,32] f32.

        On timeout the request is re-sent once with a fresh seq: an engine
        that died mid-request loses the req file to its own startup cleanup,
        and the daemon-respawned successor needs a live one.
        """
        for retry in range(2):
            self.seq += 1
            body = struct.pack("<II", REQ_MAGIC, self.L)
            body += np.ascontiguousarray(patches, dtype=np.float32).tobytes()
            body += np.ascontiguousarray(ids, dtype=np.uint32).tobytes()
            body += np.ascontiguousarray(noise, dtype=np.float32).tobytes()
            tmp = self.dir / f".req_{self.seq:06d}.tmp"
            req = self.dir / f"req_{self.seq:06d}.bin"
            tmp.write_bytes(body)
            os.replace(tmp, req)  # atomic hand-off
            resp = self.dir / f"resp_{self.seq:06d}.bin"
            t0 = time.time()
            while not resp.exists():
                if time.time() - t0 > _REQ_TIMEOUT:
                    break
                time.sleep(0.002)
            else:
                raw = resp.read_bytes()
                req.unlink(missing_ok=True)
                resp.unlink(missing_ok=True)
                magic, status = struct.unpack_from("<II", raw, 0)
                if magic != RESP_MAGIC or status != 0:
                    raise RuntimeError(
                        f"serve tl{self.L} 响应异常 magic={magic:#x} status={status}"
                    )
                tv, tp, tf = struct.unpack_from("<fff", raw, 8)
                acts = (
                    np.frombuffer(raw, dtype=np.float32, count=HOR * GD, offset=20)
                    .reshape(HOR, GD)
                    .copy()
                )
                return acts, (tv, tp, tf)
        raise RuntimeError(
            f"serve tl{self.L} 请求超时 ×2（进程死或卡死——看 {self.dir}/stdout.log）"
        )


class GeServePi05Policy:
    """PI0.5 on the Ascend GE static-OM engine, shaped like an ApxInf policy.

    Pre/post-processing is delegated to ``NpuTorchPi05Policy`` (identical
    code path to the 9/10 torch baseline and the replay recorder); the model
    call goes to a bucketed serve process instead of torch.
    """

    def __init__(
        self,
        model_dir,
        *,
        tokenizer_dir=None,
        precision: str = "fp16",
        device: str = "npu",
        serve_root: Optional[str] = None,
        **kwargs: Any,
    ) -> None:
        global _SERVE_ROOT
        if serve_root is not None:
            _SERVE_ROOT = Path(serve_root)
        if precision not in SUPPORTED_PRECISIONS:
            raise ValueError(
                f"npu-ge engine supports {list(SUPPORTED_PRECISIONS)}; got {precision!r}"
            )
        # Everything else (image_keys/state_key/prompt_key/action_dim/
        # metadata/model_type/tokenizer_path) is the wire contract, owned by
        # the preprocessing host exactly as in the torch engine.
        kwargs.pop("engine", None)

        # Preprocessing host: loads the torch policy (onto NPU, unused for
        # compute) so _to_frame/preprocess/_preprocess_images/postprocess are
        # *by construction* the recorder's exact code paths.
        from .npu_torch import NpuTorchPi05Policy

        self._torch_pol = NpuTorchPi05Policy(
            model_dir, tokenizer_dir=tokenizer_dir, precision=precision, **kwargs
        )
        self._torch = self._torch_pol._torch
        self._model_dir = str(model_dir)
        self._buckets: Dict[int, Any] = {}

        self.metadata: Dict[str, Any] = dict(self._torch_pol.metadata)
        self.metadata.update({"engine": "npu-ge", "precision": "fp16"})

    # -- bucket routing ----------------------------------------------------

    def _bucket(self, length: int):
        """Transport-aware bucket client (APXINF_GE_TRANSPORT=inproc|spool).

        inproc = in-process PyO3 engine (crate library surface). Falls back
        to the spool bucket on import/availability failure so eval keeps
        running in the torch_npu container, where the 9.0.1-linked extension
        cannot coexist with the 8.5.1 torch_npu runtime.
        """
        client = self._buckets.get(length)
        if client is None:
            client = self._make_client(length)
            self._buckets[length] = client
        return client

    def _make_client(self, length: int):
        if _TRANSPORT == "inproc":
            try:
                return _InprocClient(length, self._model_dir)
            except Exception as exc:  # ImportError or engine-side failure
                print(
                    f"[npu-ge] inproc 客户端不可用（{exc!r}），回落 spool 桶 tl{length}"
                )
        return _BucketClient(length)

    # -- Policy protocol ----------------------------------------------------

    @property
    def action_dim(self) -> int:
        return self._torch_pol.action_dim

    @property
    def action_horizon(self) -> int:
        return self._torch_pol.action_horizon

    def _frame_inputs(self, observation: Mapping[str, Any]):
        """obs -> (patches [768,588] f32, token_ids [L] uint32).

        Mirrors record_rollout.py verbatim: the processor's ids come out at
        the true prompt length (the recorder padded to 200 only to keep
        torchair from recompiling -- the engine takes the real L).
        """
        import torch
        import torch.nn.functional as F
        from lerobot.utils.constants import OBS_LANGUAGE_TOKENS

        pol = self._torch_pol
        frame = pol._to_frame(dict(observation))
        batch = pol.preprocess(frame)
        ids_t = batch[OBS_LANGUAGE_TOKENS]
        # processor 输出恒 pad 到 max_length=200（pad_token_id=0 + mask=0）。
        # 静态 OM 全可见 ≠ 被 mask：数学等价于只喂 L 个可见 token——截非零
        # 前缀按真长挑桶（replay_filter.py 同式；pad 只在尾部，真文本不含
        # id 0）。喂 pad 全可见会让 embedding[0] 投影进 attention（语义
        # 污染，离线对拍分不出来但行为不可信）。
        ids_full = ids_t[0].detach().to(torch.long).cpu().numpy()
        ell = int((ids_full != 0).sum())
        assert 0 < ell <= ids_full.shape[0], f"token 非零计数异常 {ell}"
        ids = ids_full[:ell].astype(np.uint32)
        # SigLIP inputs, self-reproduced (deterministic pure function; the
        # empty view is -1 padded by _preprocess_images' missing path, the
        # engine drops those rows via GEB_PREFIX_DROP_EMPTY)
        imgs, _ = pol.policy._preprocess_images(batch)
        pv = torch.cat([t.detach() for t in imgs], dim=0).float().cpu()  # [V,3,224,224]
        flat = pv.reshape(-1, 3, pv.shape[-2], pv.shape[-1])
        u = F.unfold(flat, kernel_size=14, stride=14)                    # [V,588,256]
        patches = u.permute(0, 2, 1).reshape(-1, u.shape[1]).numpy()      # rows (c,kh,kw)
        assert patches.shape == (768, 588) and ids.shape == (ell,), patches.shape
        return patches, ids

    def infer(
        self, observation: Mapping[str, Any], *, noise: Optional[np.ndarray] = None
    ) -> Dict[str, Any]:
        torch = self._torch
        pol = self._torch_pol
        started = time.perf_counter()
        patches, ids = self._frame_inputs(observation)
        length = int(ids.shape[0])
        if noise is None:
            # LeRobot sample_noise semantics: plain standard normal
            # (modeling_pi05 PI0FlowMatching.sample_noise).
            noise = torch.normal(0.0, 1.0, size=(HOR, ADIM)).numpy().astype(np.float32)
        client = self._bucket(length)
        model_started = time.perf_counter()
        nact, (tv, tp, tf) = client.request(patches, ids, noise)
        model_ms = (time.perf_counter() - model_started) * 1000.0
        # postprocess = unnormalize (the engine's output IS the normalized
        # x_t slice; there is no further denorm inside the engine)
        normalized = torch.from_numpy(nact)[None].to(pol.device)
        acts = pol.postprocess(normalized).detach().cpu().numpy().astype(np.float32)
        if acts.ndim == 3:  # [B, H, D] with B == 1
            acts = acts[0]
        total_ms = (time.perf_counter() - started) * 1000.0
        return {
            "actions": acts,
            "normalized_actions": nact,
            "timing": {
                "model_ms": model_ms,
                "total_ms": total_ms,
                "engine_ms": {"vision": tv, "prefix": tp, "flow": tf},
            },
            "metadata": self.metadata,
        }

    __call__ = infer

    def reset(self) -> None:
        """Episode boundary; this policy is stateless (fresh noise per replan)."""

    def close(self) -> None:
        """Drop the torch preprocessing host; serve processes stay (supervisor-owned)."""
        close = getattr(self._torch_pol, "close", None)
        if callable(close):
            close()

    def __enter__(self) -> "GeServePi05Policy":
        return self

    def __exit__(self, *exc_info) -> None:
        self.close()
