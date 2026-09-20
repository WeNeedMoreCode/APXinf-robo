import numpy as np
from safetensors import safe_open
from safetensors.numpy import load_file
CKPT = "/data/apxinf/weights/pi05_libero_finetuned/model.safetensors"
G = load_file("/data/apxinf/golden/frame0_v3.safetensors")
PRE = "model.paligemma_with_expert.paligemma.model.language_model.layers."
EPS = 1e-6
P = 712
x0 = G["x0_vis"].astype(np.float64); m0 = G["m0_vis"].astype(np.float64)
m0e = np.fromfile("/data/apxinf/dump712/ge_slot36.f16", dtype=np.float16).astype(np.float64).reshape(P, 2048)
with safe_open(CKPT, framework="pt") as f:
    get = lambda li, n: f.get_tensor(f"{PRE}{li}.{n}").float().numpy()
    ow, w2 = get(0, "self_attn.o_proj.weight"), get(0, "post_attention_layernorm.weight")
nrm = lambda x: x / np.sqrt((x*x).mean(-1, keepdims=True) + EPS)
res_t = x0 + m0 @ ow.T
res_e = x0 + m0e @ ow.T          # 引擎 m0（0.52%）经 f64 o_proj 的传播上界
n2_t, n2_e = nrm(res_t), nrm(res_e)
rel = lambda a, b: np.abs(a-b).max()/np.abs(b).max()*100
print(f"[传播] m0 引擎误差 0.52% → f64 o_proj+res: {rel(res_e, res_t):.2f}% → norm2: {rel(n2_e, n2_t):.2f}%")
n2_slot = np.fromfile("/data/apxinf/dump712/ge_slot44.f16", dtype=np.float16).astype(np.float64).reshape(P, 2048)
print(f"[实测] 图 norm2 槽 vs f64 norm2: {rel(n2_slot, n2_t):.2f}%  → 超出传播部分的 = o_proj/addrms 执行误差")
