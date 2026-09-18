# syx_docs — APXinf-robo 昇腾 NPU 适配

非原生项目（APXinf-robo 是别人的仓库），文档按 syx-doc-system 约定隔离在 `syx_docs/`，不覆盖原作者 `docs/`。

## 项目目标

把 APXinf-robo（Rust 边缘推理引擎，CUDA-only）适配出昇腾 NPU 版推理引擎，目标硬件 Ascend 310P3。

## 文档地图

| 路径 | 内容 | 更新时机 |
|---|---|---|
| `setup.md` | 服务器连接（SSH 坑）、NPU 环境、容器/镜像、本地仓、构建要点 | living doc |
| `designs/npu-port-overview.md` | 引擎架构分析、硬件约束、ModelZoo 参考、A/B/C 技术路线对比 + 路线演进 | living doc |
| `decisions/` | 路线决策 ADR：001 混合路线+原生接口预留；002 阶段二执行图转 GE 原生 OM | living doc |
| `plans/npu-port-roadmap.md` | 分阶段 roadmap + 技术相异点清单 | living doc |
| `references/modelzoo-pi05-npu-adaptation.md` | ModelZoo π0.5 NPU 补丁逐项分析（外部知识） | living doc |
| `dev_logs/*.sh` | 服务器上跑过的搭建/修复脚本镜像（本地留档） | 手动 |
| `dev_logs/summary/` | session 工作归档（YYYY-MM-DD_描述.md） | compact 触发 |
| `dev_logs/chat_exports/` | 对话备份 raw | 手动 /export |

## 关键事实速查

- 服务器：`root@192.168.13.119`，8 × 310P3，共享（用卡前看 `npu-smi info`）；双容器分工见 setup.md「双容器分工与同步纪律」（rust 容器 9.0.1 = 开发+GE 构图主力，npu 容器 8.5.1 = torch_npu 基线）
- 本地仓：`D:\compass\APXinf`（外层）+ `apxinf/` 子模块（引擎改动推 fork/ascend-port，双仓两步提交）
- ModelZoo π0.5 参考：`vla/pi05_openpi`（torch_npu + TorchAir，FP16，378ms/300I Duo 单芯）
- 310P3 无 BF16 / FP8 → 精度策略 FP16（INT8 后置）
- **成功率结案**（2026-09-17）：0/10 →(empty_camera mask 修复)→ 4/10 →(跨集 queue reset 修复)→ **9/10 = 官方 lerobot_eval 同日实测 9/10**。零 NPU 单帧对拍 `translate_parity_zero_npu.py`（40s/次）是翻译层标准工具
- **阶段 2 状态**（2026-09-19）：M2 完成（真 checkpoint 全链路）→ 性能阶段 906.9→679.8ms（rope 平铺 + scratch 池）→ 验收线判定：ACLGraph matmul task ~475µs 调度税为架构级（decisions/002）→ **GE 原生 OM POC 完成**（零调度税 + 大 m tiling −18%，skill `ge-offline-om`）→ **C 路线全量施工中**（三段式计划见 roadmap C 路线节，目标 ≤378ms）
