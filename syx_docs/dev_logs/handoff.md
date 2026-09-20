# Handoff（2026-09-19 C2 性能攻坚第二轮收尾 / 压缩用）

## 状态一句话

**空隙根因已捕获并修复：SliceD 列切视图触发运行时 MemcopyAsync 物化**（每视图 1 次 ~380µs 拷贝 + 前置 4.5-12ms host 停顿；vision 81 次/执行 = q/k/v 切片、prefix 另有 rope lo/hi 切 70 次）。三个图组织修复（GEB_QKV3 独立投影 / GEB_ROPEFLAT flat 行交换 / GEB_ATTN=manual 三段统一）→ **全模型 2182 → ~431ms（5.06×），距 378ms 线 14%**：vision 68.06（0.1%）/ prefix 187.75（25.1%⚠）/ flow 17.51/步（1.6%）。顺带修 flow eager 陈旧索引 bug。ADR-002：调度上限疑虑解除。双仓已提交（子模块 230e24a / 外层 01f1802）。

## ① Compact 参数（贴到 /compact 后）

聚焦保留：**根因与证据链**（SliceD 列切视图 → 运行时 MemcopyAsync 物化 → host 慢路径 ~5.5ms/次；证据：82.4 拷贝/执行全在执行流 s370、每次前 4.5-12ms 全局空隙、**下个 kernel 恒为切片消费者 te_transpose**、PFA 模式同数 27×3=81 反证共同因子是 q/k/v 切片；flow 反例解释 = unknown 动态路径把切片物化成 kernel 不付税）；**111 输出假设反向击毙**（GEB_NO_AUX 死端 mean/rstd → LN 动态变体更糟 710ms）；**三修复**（GEB_QKV3=1 qkv 3×mm 独立权重输入[权重 host 切、不注册无消费者输入防 dataset 错位、eager 层内 12→16 项偏移]；GEB_ROPEFLAT=1 rope 换 flat 视图行交换[Reshape[p,wd]→[p·h·2,d/2]→GatherV2D Const 索引→mul/mul/add→back，GatherV2D 310P 仅 axis=0]；GEB_ATTN=manual 扩到 prefix/flow，scale 折 q 权重/bias）；**最终数字**（vision 68.06/0.1%、prefix 187.75/25.1%、flow 17.51/步/1.6%、全模型 ~431ms，OM {vision,prefix,flow}_r2.om）；**prefix 25.1% 漂移规律**（vision INTER=4304→0.1% / flow 4096→1.6% / prefix 16384→25% 随宽度单调，假设大 K fp16 累加序差，M3 判）；**flow eager 索引陈旧 bug**（const_i32 化后 4 输入槽消失 ainwt 16→12/pk 18→14，[832,256] 读 qkvwt 断言 panic 伪装 TBE 崩）；**msprof 顽固导出失败 + sqlite 恢复**（TaskInfo⋈HwtsBatch 按 (stream,task_id) JOIN，主链不在 HwtsBatch；timestamp 是提交时刻）。丢弃：A/B 过程中间数字、JOIN 脚本细节、msprof 修复尝试过程（结论在 skill #28-29 + ascend-msprof + summary round2）。

## ② Post-compact 首句（贴到压缩后第一句）

继续 APXinf 昇腾 NPU **C 路线 C2 收尾（攻坚第二轮已完成 5.06×，见 summary 2026-09-19_c2-perf-attack-round2）**。第一动作：**prefix 25.1% 漂移定位**（唯一遗留数值项，阻塞 M3 精度信心）——`GEB_SEG=prefix GEB_ATTN=manual GEB_QKV3=1 GEB_ROPEFLAT=1 GEB_DEPTH=2/4/8 GEB_BENCH=1 GEB_ROUNDS=3 GEB_PER=1` 扫描漂移随深度增长曲线（depth2 已知 8.5%）：若线性累积 → fp16 大 K 累加序差坐实（e2e M3 判定，probe 侧销案）；若某深度跳变 → GEB_DBG=1 逐层找首个分岔层。之后二选一：flow 尾巴（17.5ms/步仍有 ~1ms/层非算力开销，全模型有望 ~380 进线内）或直接验收线判定会谈进 M3（当前 ~431 vs 378 线 = 1.14×）。

## ③ Export 标题建议

D:\compass\APXinf\syx_docs\dev_logs\chat_exports\2026-09-19_c2-perf-attack-round2.md（新文件：C2 性能攻坚第二轮——切片视图运行时物化根因捕获、三段修复 5.06×、全模型 ~431ms）

