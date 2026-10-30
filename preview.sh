#!/bin/zsh
# 本地看看板：没有真实数据时先用示例数据
cd "${0:A:h}/dashboard"
[[ -f data.js ]] || cp data.example.js data.js
echo "打开 http://localhost:8765"
python3 -m http.server 8765
