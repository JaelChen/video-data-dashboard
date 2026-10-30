#!/bin/zsh
# 由 launchd 每 30 分钟叫一次（睡眠期间错过的，开盖后会补叫一次）；
# 每天只真正跑一次 update.py，9 点前不跑（平台数据隔天才更新）。失败时弹系统通知。
HERE="${0:A:h}"
export PATH="$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"
STAMP="$HERE/data/.last_ok"
LOG="$HERE/data/update.log"
TODAY=$(date +%F)

[[ "$(cat "$STAMP" 2>/dev/null)" == "$TODAY" ]] && exit 0
(( $(date +%H) < 9 )) && exit 0

notify() { osascript -e "display notification \"$1\" with title \"视频数据更新\"" >/dev/null 2>&1 }

{
  echo "== $(date '+%F %T') 开始"
  # ego lite 没开就在后台启动它，最多等 60 秒到浏览器服务可用
  open -ga "ego lite"
  for i in {1..30}; do
    ego-browser nodejs -e 'console.log("ready")' >/dev/null 2>&1 && break
    sleep 2
  done
  # 刚开盖时 Wi-Fi 可能还没连上，最多等 2 分钟到能连通外网
  for i in {1..40}; do
    curl -s -o /dev/null -m 3 https://www.baidu.com && break
    sleep 3
  done
  if python3 "$HERE/update.py"; then
    echo "$TODAY" > "$STAMP"
    echo "== $(date '+%F %T') 成功"
    "$HERE/backup.sh" || notify "数据已更新，但备份到 iCloud 失败。详情见 data/update.log"
  else
    echo "== $(date '+%F %T') 失败"
    "$HERE/backup.sh" || true
    msg=$(awk '/^== .*开始$/{m=""} /抓取失败：/{m=$0} END{print m}' "$LOG")  # 只看本次运行的
    notify "${msg:-更新失败}。可能需要在 ego lite 里重新登录，详情见 data/update.log"
  fi
} >> "$LOG" 2>&1
