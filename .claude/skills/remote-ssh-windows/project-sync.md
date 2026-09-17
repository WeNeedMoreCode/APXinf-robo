# 项目同步：Syncthing 实时双向同步

> **何时读取**：需要让本地 Windows 和远程 Linux 的项目目录保持实时双向同步，使 Claude Code（本地）和 VS Code Remote SSH（远程）能看到同一份代码。

## ⚠️ Claude 行为约束（必读）

同步建立后，项目目录就是**同一个文件系统的两份镜像**。以下行为是错误的，必须避免：

| ❌ 不要 | ✅ 应该 |
|---------|--------|
| 本地已有文件，还要 SSH 去服务器"找"或"拉" | 直接 `Read` / `Edit` 本地文件，它就是服务器文件 |
| 改完本地代码后"等同步"再操作 | 直接 SSH 执行编译/测试，Syncthing 是实时的 |
| 反复检查同步状态（check-ignore / completion） | 只在 VPN 断了或明显异常时才检查 |
| 把本地和服务器当成两份独立的代码库 | 它们是同一份——本地改 = 服务器改，反之亦然 |

**核心原则：同步是透明的。你在本地看到的文件，服务器上一定存在。你需要做的只是在服务器上执行编译/测试命令，不需要任何"传文件"、"拉代码"、"确认同步"的操作。**

## 核心模式：本地改代码，远程跑测试

```
┌──────────────────────────────────────────────────┐
│  本地 Windows (git clone)                         │
│  ├─ Claude Code 读写代码                          │
│  ├─ VS Code 打开查看 diff                         │
│  └─ git commit / branch 管理                      │
│       │                                           │
│       │ Syncthing 实时双向同步                      │
│       │                                           │
│  远程 Linux (无 GUI)                               │
│  ├─ make / ATC 编译                               │
│  ├─ python eval 跑测试                             │
│  └─ VS Code Remote SSH 手动操作                    │
└──────────────────────────────────────────────────┘
```

**为什么不用 SSHFS / rclone mount**：

| 方案 | 文件感知 | Windows 稳定性 | 适合场景 |
|------|---------|---------------|---------|
| SSHFS | ❌ 无 inotify，IDE 不自动刷新 | 差，年久失修 | 临时文件浏览 |
| rclone mount | ❌ 同上 | 较好 | 数据传输、云存储 |
| **Syncthing** | ✅ 本地文件，IDE 原生感知 | **好**，成熟项目 | **持续开发** |

Syncthing 是 P2P 文件同步工具——两边各有一份完整拷贝，修改自动双向传播。VS Code 和 Claude Code 看到的都是本地文件，不需要网络 I/O，感知变更零延迟。

### 关键行为

- **双向**：任何一边的修改都会同步到另一边
- **实时**：文件 watcher 检测变更，秒级触发同步
- **冲突处理**：两边同时改同一个文件时，保留一个冲突副本（`.sync-conflict-*`）
- **`.git/` 同步**：默认会同步 `.git/` 目录——如果两边分支状态不同，**必须在 ignore 中排除**

## 首次搭建

### 1. 两边安装 Syncthing

**Windows**（winget）：
```bash
winget install -e --id Syncthing.Syncthing
```
安装后二进制在 `%LOCALAPPDATA%\Microsoft\WinGet\Packages\Syncthing.Syncthing_*\syncthing-windows-amd64-v2.*\syncthing.exe`。

**Linux**（服务器，ARM64 等情况 apt 可能只有老版本）：
```bash
# 如果 GitHub 被墙，本地下载后 SCP 传上去（见 operations.md 代理下载）
curl -L "https://gh-proxy.com/https://github.com/syncthing/syncthing/releases/download/v2.1.2/syncthing-linux-arm64-v2.1.2.tar.gz" -o /tmp/st.tar.gz
tar xzf /tmp/st.tar.gz
cp syncthing-linux-arm64-v2.1.2/syncthing /usr/local/bin/syncthing
```

**版本必须匹配**：Syncthing v1 和 v2 协议不兼容。用 `syncthing --version` 确认两边版本一致。

### 2. 生成初始配置

```bash
# 两边各自执行
syncthing generate --home=<config_dir>
```
- Linux: `--home=/root/.config/syncthing`（或其他非 root 用户目录）
- Windows: `--home=C:\Users\<user>\AppData\Local\Syncthing`

这会生成 `config.xml`、`cert.pem`、`key.pem`，并输出设备 ID（如 `DQPEOIB-UMWEKCK-W2IZDVB-6KFDXL5-UYO73DQ-A5DGDOA-O3HPGV3-CHRGLAA`）。

### 3. 启动守护进程

```bash
# Linux
nohup syncthing serve --no-browser --home=/root/.config/syncthing --gui-address=127.0.0.1:8384 > /tmp/syncthing.log 2>&1 &

# Windows (Git Bash)
nohup "path/to/syncthing.exe" serve --no-browser --home="C:\Users\...\Syncthing" --gui-address=127.0.0.1:18384 > /tmp/syncthing_win.log 2>&1 &
```

### 4. 互加设备

```bash
# 服务器上加 Windows 设备
syncthing --home=/root/.config/syncthing cli config devices add \
  --device-id=<windows_device_id> --name=win-local

# Windows 上加服务器设备（需指定 GUI 地址 + API key）
APIKEY=$(grep -oP '<apikey>\K[^<]+' "$SYNCTHING_HOME/config.xml")
syncthing --home="$SYNCTHING_HOME" cli \
  --gui-address=127.0.0.1:18384 --gui-apikey="$APIKEY" \
  config devices add \
  --device-id=<server_device_id> --name=server \
  --addresses="tcp://192.168.x.x:22000"
```

Windows 端 CLI 需要 `--gui-address` **和** `--gui-apikey` 两个参数——API key 从 `config.xml` 中提取。

### 5. 添加同步文件夹

```bash
# 两边各自执行——文件夹 ID 必须一致
syncthing ... config folders add --id=<folder_id> --path=<local_path> --label=<label>
```

### 6. 分享文件夹给对方

`syncthing cli config folders add` **不支持指定共享设备**。需要分两步：先 `folders add`，再用 REST API 把对方 device 加到文件夹的 devices 列表里。

```python
import json, urllib.request

# 读取 API key
with open(config_path) as f:
    apikey = f.read().split('<apikey>')[1].split('<')[0]

# GET 文件夹配置
url = f'http://127.0.0.1:{port}/rest/config/folders/{folder_id}'
req = urllib.request.Request(url, headers={'X-API-Key': apikey})
cfg = json.loads(urllib.request.urlopen(req).read())

# 添加对方设备
cfg['devices'].append({'deviceID': '<other_device_id>', 'introducedBy': ''})

# PUT 回去
data = json.dumps(cfg).encode()
req2 = urllib.request.Request(url, data=data,
    headers={'X-API-Key': apikey, 'Content-Type': 'application/json'}, method='PUT')
urllib.request.urlopen(req2)
```

### 7. 验证连接和同步

```bash
# 查看连接状态
curl -s -H "X-API-Key: $APIKEY" http://127.0.0.1:8384/rest/system/connections

# 查看同步进度
curl -s -H "X-API-Key: $APIKEY" http://127.0.0.1:8384/rest/db/completion?folder=<folder_id>
```

`"connected": true` + `"completion": 100` = 同步完成。

## 踩坑记录

### Windows 中文用户名路径

Git Bash 中 Syncthing 的 `--home` 路径含中文字符（`C:\Users\素玄\...`）时，`syncthing.exe` 能正常处理（它是 Go 编译的 Windows 原生程序）。但如果通过 `python.exe` 脚本中写中文路径字符串，需要用 raw string `r"..."` 或确保源文件 UTF-8。

### Windows 上没有 Python

Windows 应用商店的 `python3.exe` 是空壳（不是真 Python），需要 `winget install Python.Python.3.12` 装真正的 Python。安装后可能被 Store 空壳遮挡——用全路径调用：`C:\Users\<user>\AppData\Local\Programs\Python\Python312\python.exe`。

### 服务器下载 GitHub Release 超时

大陆服务器直连 GitHub 经常超时。解法：**本地用代理下载 → SSH pipe 传到服务器**（见 operations.md）。

```bash
# 本地下载，走 gh-proxy
curl -L "https://gh-proxy.com/https://github.com/.../file.tar.gz" -o /tmp/file.tar.gz
# pipe 到服务器
cat /tmp/file.tar.gz | ssh ... 'cat > /tmp/file.tar.gz'
```

### SSHFS-Win 不适用（已弃用）

曾尝试 SSHFS-Win（`winget install SSHFS-Win.SSHFS-Win`），遇到以下问题全部弃用：
- Cygwin 版 sshfs 与 Git Bash (MSYS2) 路径系统不兼容
- `net use` 挂载 Windows 网络驱动器需要服务运行
- 无 inotify 支持，IDE 无法感知文件变更

结论：SSHFS 不适合持续开发场景，Syncthing 是正确的选择。

### 首次同步可能很慢

大型仓库（如 ModelZoo-PyTorch ~3.5GB）首次同步需要较长时间。可以先用 `--copy-range-method` 或外部硬盘传输做初始同步，再启动 Syncthing 做增量。

## 日常使用

同步跑起来后，日常开发不需要任何额外操作。注意一个延迟：文件 watcher 有 10s 累积延迟（`fsWatcherDelayS=10`），新建文件/目录写完后**等 10 秒**服务器才能看到。修改已有文件通常秒级生效。

1. **Claude Code 改本地文件** → 自动同步到服务器
2. **在服务器跑编译/测试**（SSH 命令，见 operations.md）→ 产物自动同步回本地
3. **VS Code Remote SSH 改服务器文件** → 自动同步回本地，Claude Code 立即可见

### 建议的 .stignore

放在项目根目录（两边各自），避免同步不需要的内容：

```
# 编译产物——本地没环境，同步下来也没用
*.o
*.so
*.om
build/
__pycache__/
*.pyc

# 数据集——只在服务器上，不需要拉到本地
datasets/
data/
*.tar.gz
*.zip
```

**为什么排除编译产物和数据集**：本地没有 NPU/GPU 环境，`.o` / `.so` / `.om` 拉下来毫无意义。数据集动辄几十 GB，服务器下载完触发全量同步到本地是浪费带宽和磁盘。

**为什么保留 `.git/`**：代码一致的镜像，git 状态就该一致。本地 commit，服务器自动看到；服务器 checkout，本地自动跟上。这样两边才是真正的同一份仓库。

### 暂停/恢复同步

```bash
# 暂停文件夹
syncthing ... cli config folders modelzoo-pytorch --paused

# 恢复
syncthing ... cli config folders modelzoo-pytorch --paused=false
```

### 停止 Syncthing

```bash
# Linux
pkill syncthing

# Windows
taskkill /f /im syncthing.exe
```
