# 自动化流程

目标：每天打开电脑后，数据就自动更新好了，不需要你记得去跑。出问题时会弹系统通知，告诉你是哪个平台出了问题。

## 整体流程

```
launchd（每 30 分钟叫一次，开机、睡眠唤醒后也会补叫）
  └─ daily.sh       今天已经成功过，或者还不到 9 点 → 直接退出
       ├─ 后台打开 ego lite，等它准备好，再等网络连通
       ├─ update.sh
       │    ├─ fetch.mjs / fetch_douyin.mjs / fetch_channels.mjs   三个平台依次抓取，共用一个浏览器窗口
       │    ├─ ingest.py                                          写库 → 导出看板数据
       │    └─（可选）上传到你的网站
       ├─ 成功 → 记下今天已完成，备份数据库到 iCloud
       └─ 失败 → 弹通知「抓取失败：视频号」，半小时后自动重试
```

为什么用「每 30 分钟检查一次」，而不是「每天 10 点准时跑」：Mac 合盖睡眠时 launchd 不会运行任务，到了时间点如果电脑在睡觉，这次就错过了。每半小时检查一次、一天只真正跑一次，就能保证开盖后不久一定会跑。

9 点之前不跑，是因为各平台前一天的数据一般要到早上才更新完。

## 安装每日任务

在项目目录运行：

```bash
sed "s#__DIR__#$PWD#" launchd.plist.template > ~/Library/LaunchAgents/local.video-dashboard.daily.plist
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/local.video-dashboard.daily.plist
```

立刻试跑一次（会忽略「今天已跑过」的标记）：

```bash
rm -f data/.last_ok && launchctl kickstart gui/$(id -u)/local.video-dashboard.daily
tail -f data/update.log
```

卸载：

```bash
launchctl bootout gui/$(id -u)/local.video-dashboard.daily
rm ~/Library/LaunchAgents/local.video-dashboard.daily.plist
```

## iCloud 备份

`backup.sh` 用 `sqlite3 .backup` 把数据库复制到 iCloud 云盘的「视频数据备份」文件夹，校验文件完整性，并只保留最近 30 份。用 `.backup` 而不是 `cp`，是为了在数据库正被写入时也能复制出一份完整的文件。

macOS 默认不允许 launchd 启动的脚本写入 iCloud 云盘，所以需要给 zsh 开权限：打开「系统设置 → 隐私与安全性 → 完全磁盘访问权限」，点「+」，按 ⌘⇧G 输入 `/bin/zsh`，添加后确认开关已打开。不开这个权限也能用，只是备份这一步会失败，并弹出通知提醒你。

## 常见问题

**收到「抓取失败：某平台」的通知**：多半是这个平台的登录过期了。打开 ego lite，重新登录这个平台的后台（视频号需要用微信扫码），然后在项目目录运行一次 `./update.sh`。

**三个平台全都失败**：一般是网络没连上或者 ego lite 没启动起来。脚本开跑前最多会等两分钟网络；如果还是不行，过半小时会自动重试。

**怎么看运行记录**：所有输出都在 `data/update.log` 里，每次运行以 `== 时间 开始` 开头、以 `成功` 或 `失败` 结尾。

**数据配错了作品**：两条发布被错误地合在一起，或者该合的没合上，就编辑 `data/works_override.json`。例如 `{"douyin:视频ID": "xhs:笔记ID"}`，意思是把这条抖音并到那条小红书所在的作品里。

## 部署到自己的网站（可选）

不部署也完全可以，`./preview.sh` 在本地就能看。如果想在手机上也能随时打开，有两种做法。

**方法一：静态托管。** 把 `dashboard/` 文件夹（含 `index.html` 和 `data.js`）上传到任意静态托管服务，比如 Vercel 或 Cloudflare Pages。缺点是每次更新都要重新上传一遍；而且要记得给网站加访问保护，否则你的后台数据谁都能看到。

**方法二：上传接口（作者的做法）。** 网站上做一个接口，`update.sh` 每天把 `data/video_data.json` POST 过去，网站把它存进数据库，再在页面里以 `window.VIDEO_DATA = ...` 的形式提供给看板。接口约定如下：

- `POST <UPLOAD_URL>`，请求头带 `Authorization: Bearer <密钥>` 和 `Content-Type: application/json`，请求体就是 `video_data.json` 的内容。
- 服务端要用常量时间比较密钥，密钥不对返回 401；请求体不是 JSON 或者超过合理大小（比如 5MB）返回 400。
- 看板页面的地址需要加登录保护。

配置方法：复制 `config.example.sh` 为 `config.sh`，填好 `UPLOAD_URL`；再把密钥单独存进 `.upload_key` 文件，并运行 `chmod 600 .upload_key`。这两个文件都不会进 Git。

如果看板页面本身放在网站的 Git 仓库里，再填上 `SITE_REPO` 和 `SITE_PAGE`。之后只有当 `index.html` 有改动时，`update.sh` 才会把页面复制过去，并且只提交这一个文件。
