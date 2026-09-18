# Handoff（2026-09-19 C2 三段 OM 全量落地 / 性能优化前夜，compact 用）

## 状态一句话

**C2 ⑤⑥⑦ 全部落地**（f0787fa）：三段静态 OM（vision 27 层 / prefix 18 层+每层 k/v 输出 / flow 18 层单步 OM）编译+运行+OM 落盘全通（/data/apxinf/om_cache/）；flow 全深对拍 **1.6%**；vision/prefix 组件级逐位验证、全深为 tiling 变体差（104%/30%，口径待 fp32 oracle）。**bench：vision 723ms + prefix 750ms + flow 70.9ms/步 ≈ 2182ms 全模型——距 378ms 验收线 5.8×，不达标**。下一步 = msprof op 级定位慢 kernel（对照 C1 单层 10.28ms 的构成差）。

## ① Compact 参数（贴到 /compact 后）

聚焦保留：**C2 战果与数据**（三段 bench 723/750/70.9ms；flow parity 1.6%；OM 缓存三件在 /data/apxinf/om_cache/；全模型外推 2182ms vs 验收线 378ms）；**skill 陷阱表 #12-18**（BroadcastToD 崩→TileD；DYNAMIC_INPUT 端口工厂不预建→符号直链 AddDynamicInputDesc、端口 x0/x1 从 0 起；Reshape 输出绑图输出→desc [-1] 动态→malloc 207001→图输出只绑静态 desc 节点；AddLayerNorm [768,1152] kernel 100× 放大→LayerNormV4；LayerNormV4 mean/rstd 死端会让 y 爆→绑图输出；Reshape→SliceD 与 mm(rank-3)→下游组合崩→全链 rank-2+Reshape 桥；GE vs eager 全深逐层 tiling 变体差→oracle 口径）；**ge_model_probe.rs 使用面**（GEB_SEG=vision|prefix|flow / GEB_DEPTH / GEB_TOKENS / GEB_BENCH / GEB_SAVE/GEB_LOAD / GEB_OPTEST=btd|rsh|sld|gat|cat|aln|gln|gat2|tld|catx|p1-p7|v1-v5|r1|q1|lnv4*|glnn|rshn|v3n|tldn 单算/组合/数值验证矩阵 / GEB_TRACE）；**ge_builder 新 FFI**（geb_dyn_inputs/geb_dyn_probe/geb_link_idx；.so 需重编后 cp 到 /data/apxinf/ascendc/ge_builder/build/）；**性能疑点清单**（TileD/SliceD/Reshape 拷贝类 kernel 开销未 profile；LN 辅输出 108 个；336/195 输入的绑定开销；编译器融合未知）；**eager take_rows qkv/gate_up 切分 bug 取证**（交织布局 flat 切分数学错误，从未被数值对拍暴露——修复后置）；服务器三件套 + tar 后 touch（.rs 和 .cpp 都要）；子模块双仓两步提交（push fork）。丢弃：本轮 optest 逐轮试错过程（用例保留在例程 GEB_OPTEST，结论在 skill #12-18）。

## ② Post-compact 首句（贴到压缩后第一句）

继续 APXinf 昇腾 NPU **C 路线 C2 后半：三段 OM 性能攻坚**（C2 三段已落地见 roadmap C2 ✅ 段 f0787fa：编译/运行/缓存全通但 bench 2182ms 距验收线 5.8×；陷阱在 ge-offline-om skill #12-18，先读）。第一动作：**msprof profile 三段 OM 的 task 时长分布**（Rust 侧挂 wrapper 脚本跑 ge_model_probe 的 GEB_LOAD 模式，看 vision 27 层 723ms 里 TileD/SliceD/Reshape/PFA/LN 各占多少——对照 C1 单层 10.28ms 的构成，找拷贝类 kernel 的低效点），然后逐热点换快替代（bias 广播试 GE BiasAdd 注册名、SliceD 合并、TileD 换 GatherV2D 行复制等），目标把 vision/prefix 拉回 ~100/200ms 量级后再判验收线。vision/prefix 的 parity 口径升级（host fp32 oracle）可并行做。

## ③ Export 标题建议

D:\compass\APXinf\syx_docs\dev_logs\chat_exports\2026-09-19_c2-three-segment-om-compiled-but-slow.md（新文件：C2 三段 OM 全量落地——编译/缓存/flow parity 1.6%，bench 2182ms 不达标 5.8×，陷阱 #12-18 取证：BroadcastToD 崩/DYNAMIC_INPUT 端口符号直链/Reshape 动态输出/AddLayerNorm kernel bug/LayerNormV4 死端）
