"""WQBMV2 GE 离线拒因复现：直接调 CANN 的 check_op_cap / compile 入口。

rust 容器（9.0.1）GE 图构建时 WQBMV2 走到 "start compile Ascend C operator"
后死——本脚本绕过 GE，直接用 opp 的 wrapper python 复现同一个检查/编译，
让真实报错冒出来（eager 8.5.1 同 desc 是通的——查 9.0.1 离线链差在哪）。

用法：docker exec -e ASCEND_RT_VISIBLE_DEVICES=2 apxinf_rust python3 wq_cap_check.py
"""
import os
import sys
import traceback

CANN = "/usr/local/Ascend/cann-9.0.1"
sys.path.insert(0, CANN + "/python/site-packages")
sys.path.insert(0, CANN + "/opp/built-in/op_impl/ai_core/tbe/impl")

M, K, N = 50, 2048, 256


def desc(shape, dtype, fmt="ND"):
    return {
        "shape": shape,
        "ori_shape": shape,
        "format": fmt,
        "ori_format": fmt,
        "dtype": dtype,
        "mode": "all",
        "range": [(1, s) for s in shape],
    }


x = desc((M, K), "float16")
w_kn = desc((K, N), "int8")   # eager 判决契约：weight [k,n]
aq_n = desc((N,), "float16")  # antiquant_scale [n]
y = desc((M, N), "float16")

from ops_nn.dynamic import weight_quant_batch_matmul_v2 as wmod  # noqa: E402

print("=== op_select_format（能力检查，GE build 第一关）===")
for tag, tw in (("w[k,n] tw=False", False), ("w[n,k] tw=True", True)):
    w_arg = w_kn if not tw else desc((N, K), "int8")
    try:
        r = wmod.op_select_format(x, w_arg, aq_n, transpose_x=False, transpose_weight=tw)
        print(f"[{tag}] -> {r}")
    except Exception as e:  # noqa: BLE001
        print(f"[{tag}] RAISE {type(e).__name__}: {str(e)[:400]}")

print("=== 完整 AscendC 编译（'start compile' 后死的那一步）===")
try:
    wmod.weight_quant_batch_matmul_v2(x, w_kn, aq_n, y_out_=y, transpose_weight=False)
    print("[compile] OK")
except Exception:
    tb = traceback.format_exc()
    print("[compile] FAIL, tail:")
    print("\n".join(tb.splitlines()[-25:]))
