#!/bin/bash
# build_pyo3_cp311_1013.sh — apxinf_npu 内 cp311 pyo3 重建（GEB_CKPT_SERVE_MIN 支持）
# 注意 PYO3_PYTHON=python3.11：共享 target 的 pyo3 build-script 缓存会被 rust 容器
# 3.12 污染（.so NEEDED libpython3.12 → import 段错误）
exec > /data/apxinf/build_pyo3_1013.log 2>&1
source /data/apxinf/rust_env.sh
export PYO3_PYTHON=python3.11
cd /data/apxinf/apxinf_engine
date -u +%T
cargo build --release -p apxinf-py --features ascend
echo "BUILD_RC=$?"
cp -f target/release/libapxinf_py.so /data/apxinf/engine_py/apxinf/apxinf_py.cpython-311-aarch64-linux-gnu.so
ls -l --time-style=+%F_%T /data/apxinf/engine_py/apxinf/apxinf_py.cpython-311-aarch64-linux-gnu.so
date -u +%T
