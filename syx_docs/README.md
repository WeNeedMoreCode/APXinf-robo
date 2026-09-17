# syx_docs — APXinf-robo 昇腾 NPU 适配

非原生项目（APXinf-robo 是别人的仓库），文档按 syx-doc-system 约定隔离在 `syx_docs/`，不覆盖原作者 `docs/`。

## 项目目标

把 APXinf-robo（Rust 边缘推理引擎，CUDA-only）适配出昇腾 NPU 版推理引擎，目标硬件 Ascend 310P3。

## 文档地图

| 路径 | 内容 | 更新时机 |
|---|---|---|
| `setup.md` | 服务器连接（SSH 坑）、NPU 环境、容器/镜像、本地仓、构建要点 | living doc |
| `designs/npu-port-overview.md` | 引擎架构分析、硬件约束、ModelZoo 参考、A/B/C 技术路线对比 | living doc |
| `decisions/001-hybrid-route-with-native-seam.md` | 路线决策 ADR：混合 + 原生接口预留，锁定 310P3 | living doc |
| `plans/npu-port-roadmap.md` | 分阶段 roadmap + 技术相异点清单 | living doc |
| `references/modelzoo-pi05-npu-adaptation.md` | ModelZoo π0.5 NPU 补丁逐项分析（外部知识） | living doc |
| `dev_logs/*.sh` | 服务器上跑过的搭建/修复脚本镜像（本地留档） | 手动 |
| `dev_logs/summary/` | session 工作归档（YYYY-MM-DD_描述.md） | compact 触发 |
| `dev_logs/chat_exports/` | 对话备份 raw | 手动 /export |

## 关键事实速查

- 服务器：`root@192.168.13.119`，8 × 310P3，共享（用卡前看 `npu-smi info`）；容器 `apxinf_npu`，任务三件套见 setup.md 第 9 条
- 本地仓：`D:\compass\APXinf`，main @ 44db03b，子模块已 init
- ModelZoo π0.5 参考：`vla/pi05_openpi`（torch_npu + TorchAir，FP16，378ms/300I Duo 单芯）
- 310P3 无 BF16 / FP8 → 精度策略 FP16（INT8 后置）
- **成功率结案**（2026-09-17）：0/10 →(empty_camera mask 修复)→ 4/10 →(跨集 queue reset 修复)→ **9/10 = 官方 lerobot_eval 同日实测 9/10**。零 NPU 单帧对拍 `translate_parity_zero_npu.py`（40s/次）是翻译层标准工具
- **阶段 2 进行中**（2026-09-18）：ops 层 12 算子全真机验证（含 gelu→GeluV2、RoPE 组合版、BSH PFA）；executor 四层函数镜像完成（B）；**当前卡点：大矩阵 matmul 在 310P3 的可行路径**（ND 路径 MTE 越界、WeightNz 不支持 310P）——排查假设见 roadmap「C 阶段核心卡点」节（mat2 转置 stride 优先）
