"""WQBMV2 310P runtime eager 判决（goal: qmd x_scale 静态化探明的旁证链）。

GE 离线图把 WeightQuantBatchMatmulV2 拒了（rc=-7，在线 AscendC 编译 fallback
也死）。本脚本在 torch_npu eager（aclnn 路径，同一 kernel binary + host check）
上直接调 weight_quant_batchmatmul，判决二分：
  eager 能跑   → 310P kernel/运行时支持，GE 离线拒因在 desc/绑定面（可修）
  eager 也拒   → 310P 运行时不支持该 op（注册表在、binary 缺）→ 路线关闭

用法：docker exec -e ASCEND_RT_VISIBLE_DEVICES=2 apxinf_npu python3 wq_eager_test.py
"""
import torch
import torch_npu

M, K, N = 50, 2048, 256  # flow k/v 投影形状（最小）

print("=== schemas ===")
for name in ("npu_weight_quant_batchmatmul", "npu_quant_matmul"):
    try:
        op = getattr(torch.ops.npu, name)
        print(name, ":", op.default._schema)
    except Exception as e:  # noqa: BLE001
        print(name, "schema 失败:", repr(e))

torch.manual_seed(0)
x = torch.randn(M, K, dtype=torch.float16)
w = torch.randn(N, K, dtype=torch.float16)
# per-out-channel 量化（w_q = round(w/s)，s = amax_row/127）
s = (w.abs().amax(dim=1) / 127.0).clamp_min(1e-12)
wq = (w / s[:, None]).round().clamp(-127, 127).to(torch.int8)
y_ref = (x.float() @ (wq.float() * s[:, None]).float().t()).half()

dev = "npu"
x_n, wq_n = x.to(dev), wq.to(dev)
y_ref_n = y_ref.to(dev)

s_n = s.to(torch.float16).to(dev)
variants = {
    # torch op 无 transpose attr：布局由 weight 形态推（[k,n] 连续 = 不转置
    # 语义；[n,k] = 转置语义——vllm-ascend 实际用 [k,n] 传）
    "w[n,k] scale[n]":   (wq_n, s_n),
    "w[n,k] scale[n,1]": (wq_n, s_n.unsqueeze(1)),
    "w[k,n] scale[n]":   (wq_n.t().contiguous(), s_n),
}

for tag, (w_arg, s_arg) in variants.items():
    try:
        y = torch.ops.npu.npu_weight_quant_batchmatmul(x_n, w_arg, s_arg)
        md = (y.float() - y_ref_n.float()).abs().max().item()
        rel = md / y_ref_n.float().abs().max().item()
        print(f"[{tag}] OK  shape={tuple(y.shape)} dtype={y.dtype} max_diff={md:.4f} rel={rel:.4%}")
    except Exception as e:  # noqa: BLE001
        print(f"[{tag}] FAIL: {type(e).__name__}: {str(e)[:300]}")
