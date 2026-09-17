# 远程操作：SSH 连接与命令执行

> **何时读取**：需要在远程 Linux 服务器上执行命令、传文件、进 Docker 容器、配 SSH 密钥、或解决 github clone 被墙时。

## 推荐方案：两步走

**第一步**：用 Posh-SSH 完成密钥配对（一次性）
**第二步**：之后全部用原生 `ssh` 命令（稳定可靠）

不要用 Posh-SSH 执行日常命令——它的 session 机制不稳定，经常执行一两条就断连。
原生 `ssh` + 密钥认证每条命令独立，不会断连。

---

## ⚠️ Git Bash（Claude Code 的 bash 工具）的额外坑：中文 Windows 用户名

Claude Code 的 bash 工具跑的是 Git Bash，不是 PowerShell。**如果 Windows 用户名是中文**（如"素玄"），`~/.ssh` 解析成 `/c/Users/素玄/.ssh`，OpenSSH 打不开这个非 ASCII 路径：

```
Could not create directory '/c/Users/\313\330\320\376/.ssh'
Failed to add the host to the list of known hosts
Permission denied (publickey,password)
```

连锁问题：
1. `~/.ssh/config` 读不到 → 里面写的 `User root` 不生效 → ssh 拿本地 Windows 用户名（素玄）去连 → 服务端拒绝
2. `~/.ssh/known_hosts` 读不到 → host key 没法存
3. `~/.ssh/id_ed25519` 读不到 → 没有密钥可用

**PowerShell 走 `powershell.exe -Command` 不受这个影响**——它用 Windows 原生路径处理，能正常读 `%USERPROFILE%\.ssh`。所以配 key 用 PowerShell，日常命令用 Git Bash + 显式参数。

### 解法：key 拷到 ASCII 路径，命令显式指定

```bash
# 1. 拷 key 到 ASCII 路径
mkdir -p /c/sshkeys
cp ~/.ssh/id_ed25519 ~/.ssh/id_ed25519.pub /c/sshkeys/

# 2. 之后所有 ssh 命令都带这几个参数（缺一不可）
ssh -i /c/sshkeys/id_ed25519 \
    -o UserKnownHostsFile=/c/sshkeys/known_hosts \
    -o StrictHostKeyChecking=accept-new \
    root@192.168.13.119 '命令'
```

- `-i /c/sshkeys/id_ed25519`：绕过 `~/.ssh` 找 key
- `-o UserKnownHostsFile=/c/sshkeys/known_hosts`：host key 存到 ASCII 路径
- `root@host`：**显式指定用户**（config 里的 `User` 读不到，否则会用本地中文用户名连，被拒）
- `-o StrictHostKeyChecking=accept-new`：新 PC 首连自动接受 host key

### 一键配 key（密码用一次就丢，不落盘）

不用在 PowerShell 终端交互输密码。把整个配对流程写进 `.ps1`，从 Git Bash 调 `powershell.exe -File` 跑：

```powershell
# setup_key.ps1 —— 内容如下，用完即删
$secpwd = ConvertTo-SecureString "密码" -AsPlainText -Force
$cred = New-Object System.Management.Automation.PSCredential("root", $secpwd)
New-SSHSession -ComputerName 192.168.13.119 -Credential $cred -Force -ErrorAction Stop | Out-Null
$pubkey = (Get-Content "$env:USERPROFILE\.ssh\id_ed25519.pub" -Raw).Trim()
$r = Invoke-SSHCommand -Index 0 -Command "mkdir -p ~/.ssh && chmod 700 ~/.ssh && echo '$pubkey' >> ~/.ssh/authorized_keys && chmod 600 ~/.ssh/authorized_keys && echo KEY_ADDED"
Write-Output ($r.Output -join "`n")
Remove-SSHSession -Index 0 -ErrorAction SilentlyContinue | Out-Null
```

```bash
# 用 Write 工具把上面 .ps1 写到 $USERPROFILE\.ssh\setup_key.ps1，然后：
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "$USERPROFILE\.ssh\setup_key.ps1" 2>&1
rm -f "$USERPROFILE/.ssh/setup_key.ps1"   # 跑完删掉，密码不残留
```

配完后立即验证：`ssh -i /c/sshkeys/id_ed25519 -o UserKnownHostsFile=/c/sshkeys/known_hosts root@192.168.13.119 'echo ok'`。

---

## 第一步：安装 Posh-SSH 并配密钥（一次性）

```powershell
# 安装
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
Install-PackageProvider -Name NuGet -MinimumVersion 2.8.5.201 -Force -Scope CurrentUser
Install-Module Posh-SSH -Force -Scope CurrentUser
Import-Module Posh-SSH

# 生成密钥（如果已有则跳过）
ssh-keygen -t ed25519 -f $env:USERPROFILE\.ssh\id_ed25519 -N '""' -q

# 用 Posh-SSH 连一次（仅用于传公钥）
$secpwd = ConvertTo-SecureString "密码" -AsPlainText -Force
$cred = New-Object System.Management.Automation.PSCredential("用户名", $secpwd)
New-SSHSession -ComputerName 192.168.x.x -Credential $cred -Force | Out-Null

# 传公钥到远程
$pubkey = Get-Content "$env:USERPROFILE\.ssh\id_ed25519.pub" -Raw
$r = Invoke-SSHCommand -Index 0 -Command "mkdir -p ~/.ssh && chmod 700 ~/.ssh && echo '$pubkey' >> ~/.ssh/authorized_keys && chmod 600 ~/.ssh/authorized_keys && echo KEY_ADDED"
$r.Output -join ","   # 应该输出 KEY_ADDED

# 配好后清理 Posh-SSH session
Remove-SSHSession -Index 0 -ErrorAction SilentlyContinue
```

### ⚠️ Posh-SSH 的坑

如果必须用 Posh-SSH（密钥还没配好时），注意：

1. **输出是嵌套对象**：`Invoke-SSHCommand` 返回 PSCustomObject，必须用 `$r.Output -join "\n"` 展开
2. **Session 不稳定**：经常执行一两条命令就断，需要频繁重建 `New-SSHSession`
3. **及时切到原生 ssh**：密钥配好后立即停用 Posh-SSH

---

## 第二步：用原生 ssh 执行所有操作

密钥配好后，每条命令都是独立的 SSH 连接，不存在 session 断连问题：

```bash
# 在远程执行命令
ssh -i /c/sshkeys/id_ed25519 -o UserKnownHostsFile=/c/sshkeys/known_hosts root@192.168.x.x "命令"

# 在容器内执行命令
ssh -i /c/sshkeys/id_ed25519 -o UserKnownHostsFile=/c/sshkeys/known_hosts root@192.168.x.x "docker exec 容器名 命令"

# 读容器内文件
ssh ... "docker exec 容器名 cat /path/to/file"

# 搜索容器内文件
ssh ... "docker exec 容器名 grep -rn '关键词' /path/ 2>/dev/null"

# 修改容器内文件（sed）
ssh ... "docker exec 容器名 sed -i 's/旧内容/新内容/' /path/to/file"

# 查看修改结果
ssh ... "docker exec 容器名 sed -n '10,20p' /path/to/file"
```

---

## 常见场景模板

### 找文件
```bash
ssh ... "docker exec 容器名 find / -maxdepth 5 -name '目标文件' 2>/dev/null"
```

### 读代码片段（指定行号）
```bash
ssh ... "docker exec 容器名 sed -n '100,150p' /path/to/file.py"
```

### grep 搜索
```bash
ssh ... "docker exec 容器名 grep -n '模式' /path/to/file.py"
```

---

## ⚠️ 最大的坑：在远程跑多行脚本

单行命令（上面那些）没问题。但一旦要在远程跑**多行 shell 或 Python 脚本**，PowerShell 的引号解析会让你疯狂踩坑。**不要试图把脚本塞进 `ssh "...python -c '...'"` 的一行里**——PowerShell 会把 `$`、`()`、嵌套引号全部搞坏。

### 正确模式：本地写文件 → stdin pipe 到容器 → 执行

这是实测最稳的方式，用了无数次：

```powershell
# 1. 本地写脚本文件（用 Write 工具，不要用 PowerShell 字符串拼接）
#    例如写到 D:\...\my_script.py

# 2. 把内容 pipe 到容器的 tee，落到 /tmp
$content = Get-Content "D:\...\my_script.py" -Raw
$content | ssh ... "docker exec -i 容器名 tee /tmp/my_script.py > /dev/null"

# 3. 在容器里执行
ssh ... "docker exec 容器名 python3 /tmp/my_script.py"
```

**关键点**：`docker exec` 必须加 `-i`（否则 stdin 不通），`tee` 后面要 `> /dev/null`（否则脚本内容回显污染输出）。

### PowerShell 解析 `$` 和 `()` 的坑

PowerShell 会抢先解析字符串里的 `$` 和 `()`，导致远程的 bash 变量/命令替换失效或报错：

```powershell
# ❌ 错：PowerShell 把 $LD_LIBRARY_PATH 当成空变量解析了
ssh ... "docker exec 容器名 bash -c 'export LD_LIBRARY_PATH=新路径:`$LD_LIBRARY_PATH`'"
# 实际传到远程的 $LD_LIBRARY_PATH 变成空，原有的库路径全丢

# ❌ 错：PowerShell 把 () 当子表达式解析，git commit -m 里有括号就炸
```

**解法**：凡是含 `$`、`()`、复杂引号的命令，都用上面的"本地写文件 → tee → 执行"模式，绕开 PowerShell 的字符串解析。只在**纯文本单行命令**（cat/grep/sed/find）时才直接用 `ssh "..."`。

从 Git Bash 直接发 ssh 命令时不需要考虑 PowerShell 这层——上述问题只在 `powershell.exe -Command` 场景出现。日常操作优先用 Git Bash 原生 `ssh`。

### 后台启动服务（docker exec -d）

`docker exec -d`（detached）**不继承容器现有的环境变量**，所以 LD_LIBRARY_PATH 等会丢失。把所有需要的环境变量写进一个 `.sh` 脚本，再用 `docker exec -d` 跑：

```bash
# 1. 本地写 start.sh，里面完整 export LD_LIBRARY_PATH 等所有依赖路径
#    （先 docker exec env | grep LD_LIBRARY 查出容器原有路径，全部写进去）

# 2. pipe 进容器并后台执行
cat /path/to/start.sh | ssh ... "docker exec -i 容器名 tee /tmp/start.sh > /dev/null"
ssh ... "docker exec 容器名 chmod +x /tmp/start.sh"
ssh ... "docker exec -d 容器名 bash /tmp/start.sh"

# 3. 轮询日志确认服务就绪（而不是阻塞等待）
ssh ... "docker exec 容器名 tail -5 /tmp/service.log"
```

注意：`docker exec -d ... > /tmp/log 2>&1` 的重定向要写在**脚本内部**（脚本最后一行 `python ... > /tmp/log 2>&1`），写在 `docker exec -d` 命令行外面会被吞掉。

### 中文/BOM 坑

PowerShell 通过管道传内容时，某些情况下会给文件加 **UTF-8 BOM**（文件开头多出 `EF BB BF` / U+FEFF）。Python 配置文件带 BOM 会报 `SyntaxError: invalid non-printable character U+FEFF`。

**解法**：不要用 PowerShell 管道写 `.py` 配置文件，改用容器内的 `bash -c "cat > file << 'EOF' ... EOF"` heredoc（注意 heredoc 里的 `$` 要确认是否需要转义），或在容器内用 `python3 -c` 直接 `open().write()` 写文件。

---

## 检查/管理远程进程

```bash
# 看某进程是否在跑
ssh ... "docker exec 容器名 ps aux | grep 进程名 | grep -v grep"

# 杀进程
ssh ... "docker exec 容器名 pkill -f 进程名"
```

---

## 远程服务器拉 github 仓（大陆服务器常被墙）

服务器在大陆时，直连 github clone 经常失败：

```
fatal: unable to access 'https://github.com/owner/repo.git/': GnuTLS recv error (-110): The TLS connection was non-properly terminated.
```

根因是网络层 TLS 被中断，不是 git 配置问题。

### 走 github 镜像代理 clone

用公开的 github 代理，URL 前面加代理前缀：

```bash
# 代理 URL = 代理前缀 + 完整 github URL
git clone https://gh-proxy.com/https://github.com/owner/repo.git
```

**怎么验证代理通不通**——对代理发 HEAD 请求打一个 github 的 smart-git 端点：
```bash
curl -sI -m 6 -o /dev/null -w "%{http_code}\n" \
  "https://gh-proxy.com/https://github.com/owner/repo/info/refs?service=git-upload-pack"
```
- 返回 `405`（Method Not Allowed）→ **代理活着、能转发**（smart-git 端点本身不接受 HEAD，但代理通了）
- 返回 `000` 或超时 → 代理不通，换一个

**实测 2026-07 能用的代理**（这类代理寿命短，挂了就换）：
- `https://gh-proxy.com/`
- `https://ghproxy.net/`

代理也可以用来下载 GitHub Release 的二进制文件（如 Syncthing ARM64 包）：
```bash
curl -L "https://gh-proxy.com/https://github.com/user/repo/releases/download/v1.0/file.tar.gz" -o file.tar.gz
```

### 配全局 insteadOf，让以后 git pull 自动走代理

clone 时可以临时用代理 URL，但 clone 完 `git pull` 时 remote 还指向直连 github 会失败。配全局 `insteadOf` 让 fetch 自动重写到代理，push 保持直连：

```bash
git config --global url."https://gh-proxy.com/https://github.com/".insteadOf "https://github.com/"
git config --global url."https://github.com/".pushInsteadOf "https://gh-proxy.com/https://github.com/"
```

效果：
- `git fetch` / `git pull` / `git clone`：URL 自动重写到 `gh-proxy.com/...`，能通
- `git push`：`pushInsteadOf` 把代理 URL 反写回直连 github（push 一般在能直连的机器上做，不在被墙服务器上）

remote 的 origin URL 保持干净的 `https://github.com/owner/repo.git`，配置里不残留代理。clone 时也可以直接用直连 URL 写 `git clone https://github.com/...`，`insteadOf` 会自动重写。

### gitcode（国内托管）不需要代理，但要 token 认证

gitcode.com 直连通，私有仓 clone 报 `could not read Username for 'https://gitcode.com'`。用 access token：

```bash
umask 077
echo "https://用户名:TOKEN@gitcode.com" > ~/.git-credentials
chmod 600 ~/.git-credentials
git config --global credential.helper store
# 之后 git clone https://gitcode.com/owner/repo.git 不再要密码
```

token 只写进权限 600 的 `~/.git-credentials`，不进 `.git/config`、不进命令历史。
