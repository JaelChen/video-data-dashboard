#!/bin/zsh
# 把 data/videos.db 备份一份到 iCloud 云盘「视频数据备份」，按日期命名，只留最近 30 份。
# 用 sqlite3 .backup 而不是 cp：写库途中复制也能拿到完整一致的文件。
set -euo pipefail
HERE="${0:A:h}"
DEST="$HOME/Library/Mobile Documents/com~apple~CloudDocs/视频数据备份"
mkdir -p "$DEST"
OUT="$DEST/videos-$(date +%F).db"
sqlite3 "$HERE/data/videos.db" ".backup '$OUT'"
[[ "$(sqlite3 "$OUT" 'PRAGMA integrity_check')" == "ok" ]] || { rm -f "$OUT"; echo "备份校验失败"; exit 1; }
# 按文件名（日期）倒序，删掉第 31 份及以后
ls -1 "$DEST"/videos-*.db | sort -r | tail -n +31 | while read -r f; do rm -f "$f"; done
echo "已备份到 iCloud：$OUT"
