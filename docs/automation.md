# 自动化流程

目标是每天打开电脑后，数据就已经自动更新好了，不需要你记着去跑。核心只有一个命令：`update.py`（Mac 上是 `python3 update.py`，Windows 上是 `py update.py`）。不管哪个系统，自动化做的事都一样：每天找个时机替你运行一次这个命令。

## update.py 做了什么

```
update.py
  ├─ fetch.mjs / fetch_douyin.mjs / fetch_channels.mjs   用 ego lite 依次抓三个平台，共用一个浏览器窗口
  ├─ ingest.py                                          写库 → 导出看板数据
  └─（可选）上传到你的网站
```

某个平台抓取失败时（多半是登录过期），其他平台照样会入库，命令以退出码 2 结束，并打印一行「抓取失败：视频号」这样的提示。三个平台全部失败时，就不会再上传。

各平台前一天的数据一般要到早上才会更新完，所以建议每天上午 9 点以后再跑。

## Mac：launchd

```
launchd（每 30 分钟叫一次；开机、睡眠唤醒后也会补叫）
  └─ daily.sh       今天已经成功过，或者还不到 9 点 → 直接退出
       ├─ 在后台打开 ego lite，等它准备好，再等网络连通
       ├─ python3 update.py
       ├─ 成功 → 记下今天已完成，并把数据库备份到 iCloud
       └─ 失败 → 弹通知「抓取失败：视频号」，半小时后自动重试
```

为什么是每 30 分钟检查一次，而不是每天 10 点准时跑？Mac 合盖睡眠时 launchd 不会运行任务，定点任务在电脑睡着时就被错过了。改成每半小时检查一次、一天只真正跑一次，就能保证开盖后不久一定会跑。

**安装**（在项目目录运行）：

```bash
sed "s#__DIR__#$PWD#" launchd.plist.template > ~/Library/LaunchAgents/local.video-dashboard.daily.plist
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/local.video-dashboard.daily.plist
```

**立刻试跑一次**（先删掉「今天已跑过」的标记）：

```bash
rm -f data/.last_ok && launchctl kickstart gui/$(id -u)/local.video-dashboard.daily
tail -f data/update.log
```

**卸载**：

```bash
launchctl bootout gui/$(id -u)/local.video-dashboard.daily
rm ~/Library/LaunchAgents/local.video-dashboard.daily.plist
```

**iCloud 备份**：`backup.sh` 用 `sqlite3 .backup` 把数据库复制到 iCloud 云盘的「视频数据备份」文件夹，校验完整性后只保留最近 30 份。之所以不用 `cp`，是因为 `.backup` 在数据库正被写入时也能复制出一份完整的文件。macOS 默认不允许 launchd 启动的脚本写 iCloud 云盘，所以要给 zsh 开权限：系统设置 → 隐私与安全性 → 完全磁盘访问权限 → 点「+」→ 按 ⌘⇧G 输入 `/bin/zsh` → 添加后确认开关已打开。不开权限的话，每天的数据更新照常进行，只有备份这一步会失败，并弹通知提醒你。

## Windows：任务计划程序

Windows 用自带的「任务计划程序」。勾选「错过的任务尽快补跑」后，电脑在预定时间关着或睡着，开机后也会补上这一次。

**先手动跑一次**，确认三个平台都能抓到，同时也会生成 `data` 文件夹：

```powershell
cd C:\你的路径\video-data-dashboard
py update.py
```

**创建每日任务**：用 PowerShell 进入项目目录后运行下面这段，它会每天 10:00 运行一次，错过了就在开机后补跑，输出追加到 `data\update.log`：

```powershell
$action = New-ScheduledTaskAction -Execute "cmd.exe" -Argument "/c py -u update.py >> data\update.log 2>&1" -WorkingDirectory (Get-Location).Path
$trigger = New-ScheduledTaskTrigger -Daily -At 10:00
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable
Register-ScheduledTask -TaskName "VideoDashboardDaily" -Action $action -Trigger $trigger -Settings $settings
```

**立刻试跑**：`Start-ScheduledTask -TaskName VideoDashboardDaily`，然后打开 `data\update.log` 看结果。

**卸载**：`Unregister-ScheduledTask -TaskName VideoDashboardDaily`

Windows 版和 Mac 版有这几处不同：

- **ego lite 要提前开着。** Mac 版会自动在后台启动 ego lite，Windows 版不会。可以在 ego lite 的设置里打开开机自启；如果没有这个选项，就把它的快捷方式放进「启动」文件夹（按 Win+R，输入 `shell:startup`）。
- **失败不弹通知，也不会当天重试。** 可以每隔几天看一眼 `data\update.log`。看到「抓取失败」就去 ego lite 里重新登录，然后手动运行一次 `py update.py`。
- **没有自动备份。** 想备份的话，在没有运行更新的时候，把 `data\videos.db` 复制到 OneDrive 或其他地方即可。

Windows 流程作者还没有在真机上完整测试过，遇到问题欢迎提 issue。

## 常见问题

**收到「抓取失败：某平台」**：多半是这个平台的登录过期了。在 ego lite 里重新登录这个平台的后台（视频号要用微信扫码），然后手动运行一次 update。

**三个平台全都失败**：一般是网络没连上，或者 ego lite 没启动。

**在哪里看运行记录**：所有输出都在 `data/update.log`。Mac 版每次运行以「== 时间 开始」开头，以「成功」或「失败」结尾。

**作品配对出错**：两条发布被误合在一起，或者该合并的没合上，就编辑 `data/works_override.json`。例如 `{"douyin:视频ID": "xhs:笔记ID"}`，意思是把这条抖音并入那条小红书所在的作品。

## 部署到自己的网站（可选）

不部署也完全可以，运行 preview 就能在本地看。想在手机上随时打开的话，有两种做法。

**方法一：静态托管。** 把 `dashboard` 文件夹（含 `index.html` 和 `data.js`）上传到任意静态托管服务，比如 Vercel、Cloudflare Pages。缺点是每次更新都要重新上传一遍。另外记得给页面加访问保护，否则谁都能看到你的后台数据。

**方法二：上传接口（作者的做法）。** 在网站上做一个接口，update.py 每天把 `data/video_data.json` POST 过去，网站存进数据库，再在页面里以 `window.VIDEO_DATA = ...` 的形式提供给看板。接口约定如下：

- 请求：`POST <UPLOAD_URL>`，请求头带 `Authorization: Bearer <密钥>` 和 `Content-Type: application/json`，请求体就是 `video_data.json` 的内容。
- 服务端用常量时间比较密钥，密钥不对返回 401；请求体不是 JSON 或超过合理大小（比如 5MB）返回 400。
- 看板页面本身要有登录保护。

配置方法：

1. 复制 `config.example.env` 为 `config.env`，填好 `UPLOAD_URL`。
2. 把密钥单独存进 `.upload_key` 文件。Mac 上再运行 `chmod 600 .upload_key`，让只有你自己能读这个文件。

这两个文件都不会进 Git。如果看板页面本身放在网站的 Git 仓库里，就再填上 `SITE_REPO` 和 `SITE_PAGE`，这样 `index.html` 有改动时，update.py 会把它复制过去，并且只提交这一个文件。
