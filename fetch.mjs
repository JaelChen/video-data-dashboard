// 用 ego-browser 抓取小红书创作者后台的视频笔记数据，存到 data/raw/。
// 运行：通过 update.py（ego-browser nodejs 的工作目录是 /，读不到环境变量，所以由它把项目路径 ROOT 写在脚本开头）
// 接口需要页面签名，直接 fetch 会 406，所以走页面加载 + CDP 读响应体。
const fs = await import("node:fs/promises");
const RAW = ROOT + "data/raw/"; // ROOT 由 update.py 在脚本开头注入
await fs.mkdir(RAW, { recursive: true });

const task = await taskSpace("multi-platform video data");
const page = task.page("p1");
await page.cdp("Network.enable", {});

async function capture(url, re) {
  await page.events();
  await page.goto(url);
  await page.waitForTimeout(6000);
  const ev = (await page.events()).filter(
    (e) => e.method === "Network.responseReceived" && re.test(e.params?.response?.url || ""),
  );
  const out = {};
  for (const e of ev) {
    const key = e.params.response.url.split("/datacenter/note/")[1].split("?")[0].replace(/\//g, "_");
    try {
      out[key] = JSON.parse((await page.cdp("Network.getResponseBody", { requestId: e.params.requestId })).body);
    } catch (err) {
      out[key] = { err: String(err).slice(0, 120) };
    }
  }
  return out;
}

// 内容分析页默认近 30 天；shortcut: 只取第一页（10 条），发帖多了要翻页。
const listRes = await capture("https://creator.xiaohongshu.com/statistics/data-analysis", /datacenter\/note\/analyze\/list/);
const notes = listRes.analyze_list?.data?.note_infos;
if (!notes) throw new Error("没拿到笔记列表，可能未登录：" + JSON.stringify(listRes).slice(0, 300));
const fetchedAt = Date.now();
await fs.writeFile(RAW + "_list.json", JSON.stringify({ fetchedAt, notes }));

for (const n of notes.filter((n) => n.type === 2)) {
  const out = await capture("https://creator.xiaohongshu.com/statistics/note-detail?noteId=" + n.id, /datacenter\/note\/(base|audience|analyze\/audience)/);
  out.fetchedAt = fetchedAt;
  await fs.writeFile(RAW + n.id + ".json", JSON.stringify(out));
  console.log("ok", n.id, n.title, Object.keys(out));
}
// 不关窗口：后面的脚本接着用同一个窗口，最后由 fetch_channels.mjs 关闭
