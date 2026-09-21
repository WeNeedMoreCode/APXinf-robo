# M3 离线 LIBERO 轨迹回放闭环打通：真实输入三段链 ×32 帧对拍

日期：2026-09-22（凌晨班）　前置：[e2e 稳态 bench 310ms](2026-09-21_m3-e2e-steady-bench.md)（延迟验收线已达成；M3 剩余 = LIBERO 对标）

## 一句话

**"离线轨迹回放"最小闭环打通**：真 env（libero_object task0）rollout 40 调用录制（真实 tokenizer ids / SigLIP patches / 捕获 noise / torch normalized_actions）→ 等长过滤 32 帧（L=144）→ 按长重烤 prefix/flow OM → 引擎三段链逐帧回放对拍：**rel P50=194%（min 170.6 / max 226.9，abs max_diff 4-5 on |nact|max≈2.3），32 帧紧簇无离群**；逐帧延迟 ≈307ms 与稳态 bench 自洽。M3 集成四件中的输入三件（tokenizer/patch 管线/噪声对齐）已接真值——行为裁判仍待闭环 env。

## 录制（record_rollout.py，apxinf_npu，chip7）

- 协议 = eval-libero 镜像：task0 init[0]、seed7、10 步 settle、REPLAN=1 × 40 步（REPLAY_MAX_STEPS 截断，success 不作目标）
- 每调用记录：`token_ids`（batch 直读，真实长度）、`noise`（**一次性稳定补丁**挂 `model.sample_noise` 捕获设备侧 f16）、`nact`（normalized_actions [50,7]，= x_t 终态前 7 列）、`patches`（`_preprocess_images` 自 reproduce + unfold 14/14，含 empty 视图 -1 pad 行）
- 模型调用侧 token 手动 pad 到 200（pad id=0 + mask=0）——形状恒定防重编译，语义与 torch 全同

### dynamo 重编译死因三轮排除（过程教训）

| 轮 | 改动 | 结果 | 裁决 |
|---|---|---|---|
| 1 | `pol.infer(obs, noise=)` 注入 | 第 9 调用 FailOnRecompileLimitHit | 嫌疑：per-call 换 sample_noise 闭包 |
| 2 | 一次性稳定捕获补丁（仍带 hooks） | 同样第 9 调用崩 | 闭包洗清 → 真凶另有 |
| 3 | + token pad 200（仍带 hooks） | 同样第 9 调用崩 | token 形状洗清（processor 本就 pad 200） |
| 4 | **彻底去 hooks**（ids 从 batch 读、patches reproduce） | **40 调用零崩** | **真凶 = forward hooks**（with_kwargs 挂在 torchair fullgraph 编译区内） |

## 真实 token 长度约束（静态 OM 的新事实）

- task0 真 prompt（"Task: …, State: 32 个离散数;\nAction: "）**token 长度随离散值位数浮动：144（32/40 帧）/145（8/40）**（CPU tokenizer 独立验证 133-143 分布）
- torch 语义：pad 到 200 + attention mask=0（pad 被 mask ⇒ 数学等价 L 可见 token）；引擎静态 OM 全可见 ≠ 被遮蔽 → **等长帧过滤 + 按长重烤**（replay_filter.py：L=144 留 32/40 = 80% 覆盖）
- **生产开放项**：变长应对三选——按长分桶 OM 缓存 / GE 动态 shape / prompt 工程（定宽 state 格式化换恒定长度，风险=偏离训练分布）

## 回放（GEB_E2E_REPLAY，apxinf_rust，chip6，tl144 OM）

| 段 | 32 帧耗时 | per-frame | 备注 |
|---|---|---|---|
| vision | 2.10s | 65.7ms | patches 逐帧 h2d 换绑，aux 只分配不下载 |
| prefix | 4.10s | 128ms | x0 逐帧重组（vision_out + token 查表×√2048），36 路 kv d2h |
| flow | 3.64s | 113ms | pk/pv 逐帧换绑 + noise 重启 10 步（styles 缓存跨帧不变） |
| 合计 | | **≈307ms** | 与稳态 bench 310ms 自洽 ✓ |

**对拍**：`rel P50=194.1% min=170.6% max=226.9%`（abs max_diff 3.9-5.2，|nact|max≈2.3-2.6）——与 golden frame0 的 363% 同源量级（fp16 全链残差 + 10 步 flow 混沌放大；stage-1 replan 研究已证本 checkpoint 对噪声实现敏感、不同实现失败集不同但成功率同分布）。**紧簇无离群 = 管线一致性证据**（若 token/patch 错位等集成 bug 会显形为离群帧或崩值）。

tl144 OM（prefix parity worst 1.0% / 103.3ms@656 行；flow 7.62ms/步）落 `/data/apxinf/om_cache/tl144/`（vision 复用 t712fix）。

## 追记（同日凌晨：第二桶 + 跨任务）

- **tl145 第二桶**（prefix 106.6ms@657 / flow 7.60ms）：task0 的 L=145 帧 8 个回放 **rel P50=179.2%（161.6-197.3）**——桶机制验证 ✓
- **跨任务桶共享**：task1（"put the cream cheese…"）长度分布 145(28)/146(12)——桶心随任务漂移；其 28 个 L=145 帧直接吃 tl145 桶回放 **rel P50=222.5%（160-330）**，同类量级（略宽 = 不同任务/分布）
- 录制器跨任务复用 ✓（task1 40 调用零崩）；磁盘 1.1T 余量 = 分桶路线便宜（每桶 ≈4.4GB）
- 覆盖小结（终态）：**三桶 tl144/145/146 全验，task0 40/40 + task1 40/40 = 80/80 帧全覆盖回放**——tl146 = task1 ×12 P50=197.7%（161-259）；四组对拍 P50 带 179-223% 全同类（fp16 残差 + 混沌放大，无集成性离群）。**闭环 policy 的桶集 = 遇到新长度按需补烤**（bake_one.sh ~4 分钟/桶对，磁盘 1.1T 余）

## 下一步（M3 收官路径）

### 闭环集成施工图（下 session 直开）

1. **引擎常驻驱动**：probe 加 `GEB_E2E_SERVE` 模式（或 pyo3——先用 probe 内加模式，零新构建依赖）：常驻进程，请求文件/FIFO 进（patches+token_ids+noise），actions npy 出。多桶并存 = Seg 槽多实例（ge_builder 多模型槽已预留）——每桶一套 {prefix,flow} OM + vision 共享单实例
2. **policy 适配层**（Python，镜像 record_rollout.py 语义）：wire obs → `_to_frame`（HWC→CHW /255 + state 8 维 + prompt）→ `pol.preprocess` → token ids（**L = count_nonzero(ids) 选桶 tl{L}**；桶缺失 = lazy 补烤 ~4 min——eval 无墙钟约束可接受；延迟敏感部署再上动态 shape/定宽 state）→ `_preprocess_images` → unfold 14/14 → 引擎调用 → `x_t[:, :, :7]` 返回
3. **noise**：运行期自采样（回放对拍才需配对 torch）；**actions 反量化不存在**（= x_t 切片，已核清）
4. 接 `eval-libero --backend in-process`：引擎 policy 注册成 npu-torch 同形 Backend（replan=5 起步，9/10 对照 replan 研究）
5. （行为不达标才做）RMSNorm fp32 上浮对齐——194% rel 残差主源；后置优化不变（pk/pv 直连、styles 设备化、懒加载）

## 工具与坑

- `GEB_E2E_REPLAY=<safetensors>`（须配 GEB_TOKENS=等长、GEB_OM_DIR=对应长 OM 目录；GEB_TOKENS=200 时才可带 GEB_E2E_GOLDEN 金丝雀）
- ⚠ **`export` 带点 env 名在 bash 非法**（`export GEB_INIT_OPT_ge.x=…` 报 not a valid identifier）——必须 `env "GEB_INIT_OPT_ge.x=…" cargo run …`（run_replay.sh 首版踩了自家文档记过的坑；本次无碍因融合状态烤在 OM 里、加载不重融合，已修脚本）
- ⚠ torchair fullgraph 编译区内**不要挂 forward hooks**（每调用重编译 → 8 次撞 FailOnRecompileLimitHit）；同因：不要 per-call 换被追踪的 method/闭包
