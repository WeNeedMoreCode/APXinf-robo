#!/bin/bash
# push119.sh <local_file> <remote_path> — 119 分块上传（上行 >~700B 即 RST 的 workaround）
# 用法（本地 Git Bash）：bash push119.sh <local> <remote>
# gzip → 480B base64 分块 append → 服务器解码 gunzip → md5 对验（打印双方 md5）
set -e
SSH="ssh -F /dev/null -i /c/sshkeys/id_ed25519 -o UserKnownHostsFile=/c/sshkeys/known_hosts -o BatchMode=yes -o ConnectTimeout=20 -o KexAlgorithms=ecdh-sha2-nistp256 root@192.168.13.119"
LOCAL=$1; REMOTE=$2
B64=/tmp/push119.b64
gzip -9 -c "$LOCAL" | base64 -w0 > "$B64"
$SSH "rm -f /tmp/push119.rx"
n=$(wc -c < "$B64"); i=1
while [ $i -le $n ]; do
  c=$(cut -c "$i-$((i+479))" "$B64")
  $SSH "printf %s '$c' >> /tmp/push119.rx"
  i=$((i+480))
done
$SSH "base64 -d /tmp/push119.rx | gunzip > '$REMOTE' && md5sum '$REMOTE' | cut -d' ' -f1"
echo "local : $(md5sum "$LOCAL" | cut -d' ' -f1)"
