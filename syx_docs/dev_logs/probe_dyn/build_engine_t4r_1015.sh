#!/bin/bash
# build_engine_t4r_1015.sh — 引擎增量构建（apxinf_rust 容器内）
# 用法: build_engine_t4r_1015.sh [patch]  —— patch 传了先 git apply（免仓）
source /data/apxinf/rust_env.sh
cd /data/apxinf/apxinf_engine
if [ -n "$1" ] && [ -f "$1" ]; then
  git apply --check "$1" && git apply "$1" && echo "[build] patch applied: $1" \
    || { echo "[build] PATCH FAILED: $1"; exit 2; }
fi
cargo build --release --example ge_model_probe 2>&1 | tail -5
echo "BUILD_RC=$? $(date -u '+%F %T')"
ls -la target/release/examples/ge_model_probe
