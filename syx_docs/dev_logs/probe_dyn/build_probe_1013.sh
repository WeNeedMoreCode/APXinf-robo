#!/bin/bash
# build_probe_1013.sh — release 构建 serve 二进制（rust 容器，后台）
exec > /data/apxinf/build_probe_1013.log 2>&1
source /data/apxinf/rust_env.sh
cd /data/apxinf/apxinf_engine
date -u +%T
cargo build --release -p apxinf-model --example ge_model_probe --features ascend
echo "BUILD_RC=$?"
ls -l --time-style=+%T target/release/examples/ge_model_probe
date -u +%T
