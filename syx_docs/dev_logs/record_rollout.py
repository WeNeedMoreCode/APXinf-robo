"""record_rollout.py — 离线 LIBERO 轨迹回放录制（M3 replay 闭环第一步）

真 env（libero_object task N，eval-libero 同协议 init[0]/seed7/10 步 settle）
+ torch policy（npu-torch，阶段 1 的 9/10 路径）跑若干步，每个 policy 调用记录：
  - 真实 token_ids（PaliGemma tokenizer + state 离散化；**长度随离散值位数
    浮动**——engine 静态 OM 须按等长帧过滤，replay_filter.py）
  - 捕获的 noise [50,32]（一次性稳定补丁挂 sample_noise——per-call 换闭包
    或挂 hook 都会触发 dynamo fullgraph 重编译撞 8 上限，2026-09-21 三轮实测）
  - torch 输出 normalized_actions [50,7]（= x_t 终态前 7 列——引擎侧
    actions[:50,:7] 直接对拍量，无 denorm 环节差）
  - patches [768,588]：调 policy._preprocess_images 自 reproduced（确定性
    纯函数 = SigLIP 输入；含 empty 视图 -1 pad 行，引擎侧 DROP_EMPTY 剔除）

模型调用侧 token 手动 pad 到 200（pad id=0 + mask=0）——形状恒定防重编译，
语义与 torch 全同（pad 被 mask ⇒ 等价 L 可见 token）。

产物 /data/apxinf/replay/replay_t{task}.safetensors：
  patches_{i} / token_ids_{i}（真实长度）/ noise_{i} / nact_{i} / state_{i}

跑法（apxinf_npu 容器）：
  MUJOCO_GL=egl ASCEND_RT_VISIBLE_DEVICES=7 REPLAY_MAX_STEPS=40 REPLAN=1 \
    python3 record_rollout.py 0
"""
import collections
import os
import sys

import numpy as np
import torch
import torch_npu  # noqa: F401

torch_npu.npu.set_compile_mode(jit_compile=False)
os.environ.setdefault("MUJOCO_GL", "egl")
os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
sys.path.insert(0, "/data/apxinf/robo_src")

import torch.nn.functional as F  # noqa: E402
from safetensors.numpy import save_file  # noqa: E402

from apxinf_robo.npu_torch import NpuTorchPi05Policy  # noqa: E402
from apxinf_robo.envs.libero import make_env, libero_images, libero_state_lerobot  # noqa: E402
from lerobot.utils.constants import OBS_LANGUAGE_TOKENS, OBS_LANGUAGE_ATTENTION_MASK  # noqa: E402

TASK = int(sys.argv[1]) if len(sys.argv) > 1 else 0
SUITE = os.environ.get("REPLAY_SUITE", "libero_object")
CKPT = "/data/apxinf/weights/pi05_libero_finetuned"
OUT = f"/data/apxinf/replay/replay_t{TASK}.safetensors"
REPLAN = int(os.environ.get("REPLAN", 1))
HORIZON = 50
MAX_STEPS = int(os.environ.get("REPLAY_MAX_STEPS", 520))
WAIT_STEPS = 10
SEED = 7

pol = NpuTorchPi05Policy(CKPT)
model = pol.policy.model
# 9/10 语义（golden_gen 同款）：只喂 2 真实视图，empty 缺省走 missing 路径
print("[rec] image_features:", pol._image_features, flush=True)
pol.image_keys = tuple(pol._image_features[:2])
pol._empty_features = tuple(pol._image_features[2:])

# ---- 稳定 sample_noise 捕获（一次性补丁）----
# ⚠ 不能走 pol.infer(noise=) 注入：它每次调用换一个新闭包挂
# model.sample_noise → dynamo fullgraph guard 失败 → 每帧重编译，
# 8 次撞 FailOnRecompileLimitHit（2026-09-21 实测）。改为进程启动时挂一次
# 稳定捕获函数（身份恒定只编译一次），记录 torch 实际采样的 f16 noise
# ——引擎回放喂同值，对齐比注入更精确。
_orig_sample_noise = model.sample_noise
noise_rec: list[np.ndarray] = []


def _rec_sample_noise(shape, device):
    out = _orig_sample_noise(shape, device)
    noise_rec.append(out.detach().float().cpu().numpy().reshape(-1, out.shape[-1]))
    return out


model.sample_noise = _rec_sample_noise

# ---- env + rollout（eval-libero run_episode 的 replan=5 镜像）----
from libero.libero import benchmark  # noqa: E402

suite = benchmark.get_benchmark_dict()[SUITE]()
task = suite.get_task(TASK)
prompt = str(task.language)
print(f"[rec] {SUITE} task {TASK}: {prompt!r}", flush=True)
env = make_env(task, SEED)
init_states = suite.get_task_init_states(TASK)

rng = np.random.default_rng(20260921)  # 预留：目前 noise 走捕获，不用注入
records = []
action_plan = collections.deque()
env.reset()
obs = env.set_init_state(init_states[0])
dummy = [0.0] * 6 + [-1.0]
for _ in range(WAIT_STEPS):
    obs, _, _, _ = env.step(dummy)

steps = 0
success = False
while steps < MAX_STEPS:
    if not action_plan:
        images = libero_images(obs["agentview_image"], obs["robot0_eye_in_hand_image"])
        state = libero_state_lerobot(obs)
        obs_in = {
            pol.image_keys[0]: np.ascontiguousarray(images[0]),
            pol.image_keys[1]: np.ascontiguousarray(images[1]),
            pol.state_key: state,
            "prompt": prompt,
        }
        # ⚠ token 长度随 state 离散值位数浮动（task0 实测 133-143）→ 动态
        # shape 触发 dynamo 每长度重编译，8 个长度即 FailOnRecompileLimitHit。
        # 修法：preprocess 后手动 pad 到 200（pad id=0 + attention mask=0）
        # ——形状恒定只编译一次，且语义与 torch 全同（pad 被 mask ⇒ 数学等价
        # 于 L 可见 token，正是引擎 replay_filter 剔 pad 的口径）。不走
        # pol.infer 是因为它不给 batch 插手的缝；以下镜像其内部 20 行。
        frame = pol._to_frame(obs_in)
        batch = pol.preprocess(frame)
        ids_t = batch[OBS_LANGUAGE_TOKENS]
        msk_t = batch[OBS_LANGUAGE_ATTENTION_MASK]
        ell = int(ids_t.shape[1])
        assert ell <= 200, f"token 超长 {ell}（max_length 语义应截断）"
        # 记录真实长度 ids（pad 前）+ patches（与 predict_action_chunk 内部
        # _preprocess_images 同源——确定性纯函数，无需 hook）
        ids_real = ids_t.detach().float().cpu().numpy().reshape(-1)
        imgs, _ = pol.policy._preprocess_images(batch)
        pv = torch.cat([t.detach() for t in imgs], dim=0).float().cpu()  # [V,3,224,224]
        flat = pv.reshape(-1, 3, pv.shape[-2], pv.shape[-1])
        u = F.unfold(flat, kernel_size=14, stride=14)                 # [V,588,256]
        patches = u.permute(0, 2, 1).reshape(-1, u.shape[1]).numpy()  # 行 (c,kh,kw)
        if ell < 200:
            pad_ids = torch.zeros((1, 200), dtype=ids_t.dtype, device=ids_t.device)
            pad_msk = torch.zeros((1, 200), dtype=msk_t.dtype, device=msk_t.device)
            pad_ids[:, :ell] = ids_t
            pad_msk[:, :ell] = msk_t
            batch[OBS_LANGUAGE_TOKENS] = pad_ids
            batch[OBS_LANGUAGE_ATTENTION_MASK] = pad_msk
        with torch.inference_mode():
            normalized = pol.policy.predict_action_chunk(batch)
        torch.npu.synchronize()
        normalized_np = normalized.detach().cpu().numpy()
        acts = pol.postprocess(normalized).detach().cpu().numpy().astype(np.float32)
        if acts.ndim == 3:
            acts = acts[0]
        nact = np.asarray(normalized_np, dtype=np.float32).squeeze(0)
        assert acts.shape == (HORIZON, 7) and nact.shape == (HORIZON, 7), (acts.shape, nact.shape)
        assert noise_rec and noise_rec[-1].shape == (HORIZON, 32), "noise 捕获计数/形状不符"
        records.append((ids_real, patches, noise_rec[-1].copy(), nact, state.copy()))
        action_plan.extend(acts[:REPLAN])
        print(f"[rec] replan #{len(records)} @step{steps} ids_len={ell}", flush=True)
    a = action_plan.popleft()
    obs, _, done, _ = env.step(a.tolist())
    steps += 1
    if done:
        success = True
        break
env.close()
model.sample_noise = _orig_sample_noise
print(f"[rec] episode done: success={success} steps={steps} replans={len(records)}", flush=True)

# ---- 落盘 ----
out = {}
lens = []
for i, (ids_real, patches, noise, nact, state) in enumerate(records):
    lens.append(int(ids_real.size))
    out[f"patches_{i}"] = patches.astype(np.float32)
    out[f"token_ids_{i}"] = ids_real.astype(np.float32)
    out[f"noise_{i}"] = noise
    out[f"nact_{i}"] = nact
    out[f"state_{i}"] = state
    print(f"[rec] frame {i}: ids_len={ids_real.size} head={ids_real[:12].tolist()} "
          f"nact|max|={float(np.abs(nact).max()):.3f}", flush=True)
out["meta_success"] = np.array([1.0 if success else 0.0], dtype=np.float32)
out["meta_steps"] = np.array([float(steps)], dtype=np.float32)
from collections import Counter  # noqa: E402

print(f"[rec] token 长度分布: {Counter(lens).most_common()}", flush=True)
os.makedirs(os.path.dirname(OUT), exist_ok=True)
save_file(out, OUT)
print(f"saved: {OUT} ({len(records)} 帧)", flush=True)
