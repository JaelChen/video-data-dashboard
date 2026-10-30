#!/bin/zsh
# 一键更新：抓小红书、抖音、视频号 → 写入 data/videos.db → 导出看板数据 →（可选）上传到你自己的网站。
# 个人设置写在 config.sh（不进 Git，参考 config.example.sh）；不配置就只在本地更新，用 ./preview.sh 看。
# 某个平台抓失败（多半是登录过期）不影响其他平台，照样入库和上传，最后以失败退出，好让 daily.sh 弹通知。
set -uo pipefail
HERE="${0:A:h}"
cd "$HERE"
UPLOAD_URL="" SITE_URL="" SITE_REPO="" SITE_PAGE=""
[[ -f config.sh ]] && source config.sh
KEY="$HERE/.upload_key"

# ego-browser nodejs 的工作目录是 /，也读不到环境变量，所以把项目路径写在脚本最前面一起送进去
ROOT="$HERE/"; ROOT_JS="const ROOT = ${(qqq)ROOT};"
fetch() { { print -r -- "$ROOT_JS"; cat "$1"; } | ego-browser nodejs }
failed=()
fetch fetch.mjs || failed+=(小红书)
fetch fetch_douyin.mjs || failed+=(抖音)
fetch fetch_channels.mjs || failed+=(视频号)
# 三个都没抓到（多半是网络或 ego lite 没起来），库里没有新东西，不必再上传
(( ${#failed} == 3 )) && { echo "抓取失败：${failed[*]}"; exit 2; }
python3 ingest.py || exit 1

if [[ -n "$UPLOAD_URL" ]]; then
  [[ -s "$KEY" ]] || { echo "缺少上传密钥 $KEY"; exit 1; }
  # 密钥只从文件读，不打印
  curl -fsS -X POST "$UPLOAD_URL" \
    -H "Authorization: Bearer $(cat "$KEY")" -H "Content-Type: application/json" \
    --data-binary @data/video_data.json || { echo "上传失败"; exit 1; }
  echo; echo "已上传${SITE_URL:+，$SITE_URL 已是最新数据}"
fi

# 看板页面放在另一个网站仓库里时：页面改了才复制过去，只提交这一个文件
if [[ -n "$SITE_REPO" ]]; then
  cp dashboard/index.html "$SITE_REPO/$SITE_PAGE"
  cd "$SITE_REPO"
  if ! git diff --quiet -- "$SITE_PAGE"; then
    git commit -m "video: 更新看板页面 $(date '+%Y-%m-%d %H:%M')" -- "$SITE_PAGE" || exit 1
    git push origin main || exit 1
    echo "看板页面已推送"
  fi
fi
if (( ${#failed} )); then echo "抓取失败：${failed[*]}"; exit 2; fi
