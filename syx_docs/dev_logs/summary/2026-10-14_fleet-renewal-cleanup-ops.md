# 2026-10-14 战报——舰队换新（298694a 生产兑现）+ 孤儿大清理 + 运维工具化

终局一行：**goal 三项收口**——① **gear 舰队换新执行完成**（用户双授权后：全清 245 只容器孤儿回收 ~176GB → 杀老 supervisor + 当班 serve → 容器内起新 supervisor → **新二进制 298694a 生效，from_map_serve 687ms / ckpt 总段 6.57s 生产兑现**（旧 17s/22s），4 芯每芯恰 2p 零抢答，三谱系 spot [结果见文末]）；② 多 ckpt 卡点维持（weights/ 复核仍单只 π0.5）；③ 运维工具化三件套落地（fleet_watch / spot_eval 参数化 / start_gear_supervisor）。**过程大戏：换新三连坑取证 + 生产裸奔 36h 的 pid 复用假阳案 + 生产 spool 78 只超额抢答现场。**

## ① 孤儿大清理（用户授权「全清」）

**结构审计**（先于动作，manifest 留档 /tmp/orphan_manifest_1014.txt）：
- apxinf_rust 容器 init（`sleep infinity`, pid 1768275）名下 **245 只活残留 = 59 只 ge_model_probe + 186 只 python3.12**（后者 = 93 对 multiprocessing forkserver/resource_tracker，历次实验泄漏尸体），RSS 145.8GB；另有 1500+ 僵尸（不占内存）
- 其中 **78 只 serve 的 GEB_E2E_SERVE 指向生产 serve_gear/chip0-3**——生产 spool 一直存在 4-5 倍超额抢答（fleet_watch 实测每芯 8-9p vs 应有 2p；行为无害纯因代际恰好一致，属定时炸弹）；tl152/tl156 各 1 只
- 安全边界：生产当班（928122 系，ppid=supervisor）与回退桶当班（424778 系，ppid=1）均**不在容器 init 名下**，不在击杀范围

**执行**：三轮 kill -9 → `remaining_alive=0`；**available 126 → 302GB**。清后 v3 supervisor 自动 respawn 了回退桶（424778 系自然死亡，7 桶 2p 全新——自愈机制工作正常）。

## ② 换新三连坑（取证链，全部留档）

| 轮 | 症状 | 根因 |
|---|---|---|
| 1 | serve 秒退 `libascendcl.so not found` | 新 supervisor 从 ssh 非交互会话 setsid 启动，环境缺 CANN（老 supervisor 由带 env 的会话启动） |
| 2 | 过加载但 `geb init AclError -1` | 从回退桶 serve 抄的 env 是**容器内路径**；宿主 /usr/local/Ascend 只有 driver 无 toolkit，补 /data/apxinf/cann901_full 路径仍不够（GE 运行时要的不止 .so） |
| 3 | cgroup 取证一锤定音 | **supervisor + serve 全家住在 apxinf_rust 容器**（v3 supervisor/回退桶 serve 同容器实证）——正确姿势 = `docker exec -d apxinf_rust bash supervisor.sh` |

容器内重启后一次成功：bake 跳过（OM 已烤）→ 4 芯错峰 spawn（40s/芯）→ 全 ready 02:32-02:34，**每芯恰好 2p（main+helper）**，双 supervisor 心跳 OK。

### 冷启动计时（goal 留档项，chip0 实录）

```
GEB_CKPT io/copy: 5.887s（812 tensors）
GEB_CKPT from_map_serve: 687ms（total 6.574s）   ← 旧二进制数学段 17s（32× 兑现）
[serve] GEB_SERVE_FAST：styles 设备驻留 …
[serve] ready: /data/apxinf/serve_gear/chip0 L=200
```

### 生产裸奔 36h 案（顺带取证）

老 supervisor 的 pid 文件指向 444797 系（Oct 12 14:32 双实例竞态窗的产物，已死）——pid 号被无辜进程短暂持有/或纯死号，`alive()` 检查失真，daemon 从此不 respawn（supervisor.log 最后 daemon 行停在 Oct 12 12:53）。实际服务由同窗 spawn 的 928122 系承担（同代际，行为验证有效性不受影响——上轮 30/30 + spot 2/2 皆为它）。**教训：判活不能信 pid 文件 → fleet_watch 改 environ 指纹法**（`strings /proc/PID/environ` 匹配 GEB_E2E_SERVE，对 pid 复用与容器 pid 错位双免疫）。新 supervisor 的 daemon 本轮实测正常（失败轮 respawn 了 5 次）。

## ③ 运维工具化（goal ③）

| 工具 | 用法 | 说明 |
|---|---|---|
| `fleet_watch.sh` | `bash /data/apxinf/fleet_watch.sh` | 舰队健康快照：environ 指纹判活（4 芯 + 回退桶 7 桶）/双 supervisor 心跳（sleep 子进程）/内存/容器孤儿计数/supervisor.log 增量 |
| `spot_eval.sh` | `docker exec -d apxinf_npu bash /data/apxinf/spot_eval.sh [suite:tasks …]` | 参数化三谱系 spot（默认 object:0 spatial:4 goal:9），jsonl 按天戳 |
| `start_gear_supervisor.sh` | `bash /data/apxinf/start_gear_supervisor.sh` | **唯一正确启动姿势**：docker exec -d apxinf_rust + 容器内 pgrep 单实例检查（幂等） |

均已 md5 对验部署服务器；本地入库 `syx_docs/dev_logs/probe_dyn/`。

## ④ 多 checkpoint：卡点维持

`/data/apxinf/weights/` 复核 = paligemma + pi05_libero_finetuned，无第二只 π0.5。管线就绪（record → golden → sweep → transfer → eval 全参数化）。

## 服务器终态（02:35 UTC）

- **gear 舰队 = 新二进制 298694a**：4 芯每芯 2p、pidfile 同步、daemon 保活验证正常、冷启动 6.57s/芯
- 回退桶 tl151-157 = v3 supervisor 认养（02:11 自愈 respawn 的新一代），7/7
- 双 supervisor（v3 648516 + gear 3316640）心跳 OK；available 302GB
- 容器内活孤儿仅 8 只正当居民；僵尸 2347（根清需重启 apxinf_rust 容器——非必须，只占 pid 位）

## 遗留与观察项

- **2347 只僵尸**：容器 init（sleep infinity）不收尸的固有形态；重启 apxinf_rust 可清（build 容器，重启无生产影响——留用户需要时做）
- **新代际数值**：换新后 serve 全体进入 2026-10-14 代际（代际现象见 2026-10-13 战报）；行为面以三谱系 spot 为验收
- 老 supervisor daemon 失灵的精确机制未完全定罪（新 supervisor 同脚本工作正常 → 判老进程自身状态/双实例竞态损伤；不影响现役）

## 三谱系 spot 结果（02:34 启动，**3/3 全 success**）

| suite | task | 结果 | calls | 备注 |
|---|---|---|---|---|
| libero_object | t0 | **success 1.0** | 27 | model_ms 246.9/call（健康） |
| libero_spatial | t4 | **success 1.0** | 25 | 走 tl151-157 静态回退——**新回退桶代际**（02:11 v3 supervisor 自愈 respawn）链路验证 ✓ |
| libero_goal | t9 | **success 1.0** | — | 档表外 L=136 修复面复验 ✓ |

**新二进制 + 新代际行为验收通过**（02:49 全部完成，rc=0）。
