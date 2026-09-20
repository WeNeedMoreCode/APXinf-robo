import numpy as np
from safetensors import safe_open
from safetensors.numpy import load_file
CKPT = "/data/apxinf/weights/pi05_libero_finetuned/model.safetensors"
G = load_file("/data/apxinf/golden/frame0_v3.safetensors")
PRE = "model.paligemma_with_expert.paligemma.model.language_model.layers."
EPS = 1e-6
P = 712
x0 = G["x0_vis"].astype(np.float64); m0 = G["m0_vis"].astype(np.float64)
with safe_open(CKPT, framework="pt") as f:
    get = lambda li, n: f.get_tensor(f"{PRE}{li}.{n}").float().numpy()
    ow, w2 = get(0, "self_attn.o_proj.weight"), get(0, "post_attention_layernorm.weight")
res = x0 + m0 @ ow.T
n2 = res / np.sqrt((res*res).mean(-1, keepdims=True) + EPS) * 1.0  # g2=ones（fold 进权重）
slot = np.fromfile("/data/apxinf/dump712/ge_slot44.f16", dtype=np.float16).astype(np.float64).reshape(P, 2048)
d = slot - n2
gm = np.abs(n2).max()
print(f"[总] norm2 槽 vs f64: max|d|/|max| = {np.abs(d).max()/gm*100:.2f}%")
# (a) 行结构：每行误差的 L2 占该行 L2 的比例
row_err = np.linalg.norm(d, axis=1) / np.linalg.norm(n2, axis=1)
print(f"[行] 每行相对误差：中位 {np.median(row_err)*100:.2f}%  max {row_err.max()*100:.2f}%  min {row_err.min()*100:.2f}%")
# (b) 纯行缩放残差：d ≈ c_row * n2 能解释多少
c = (d * n2).sum(1) / (n2 * n2).sum(1)
resid = d - c[:, None] * n2
print(f"[行缩放] 行尺度系数范围 [{c.min()*100:.2f}%, {c.max()*100:.2f}%]；去掉行缩放后残差 {np.abs(resid).max()/gm*100:.2f}%")
# (c) 列结构：误差按通道的集中度
col = np.abs(d).mean(0)
top10 = np.sort(col)[-10:]
print(f"[列] 通道 |d| 均值：top10 是中位的 {top10[0]/np.median(col):.0f}~{top10[-1]/np.median(col):.0f} 倍；top10 通道占比 {top10.sum()/col.sum()*100:.1f}% 总误差")
# 对照：m0 的误差结构（同样的分析，看 0.52% 那级的形态）
m0e = np.fromfile("/data/apxinf/dump712/ge_slot36.f16", dtype=np.float16).astype(np.float64)
dm = m0e.reshape(P, 2048) - m0
cm = (dm * m0).sum(1) / (m0 * m0).sum(1)
colm = np.abs(dm).mean(0)
print(f"[m0对照] 行尺度 [{cm.min()*100:.2f}%, {cm.max()*100:.2f}%]；通道 top10/中位 {np.sort(colm)[-10:][0]/np.median(colm):.0f}~{np.sort(colm)[-1]/np.median(colm):.0f}×")
