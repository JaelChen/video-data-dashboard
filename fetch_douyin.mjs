// 用 ego-browser 抓抖音创作者中心近 30 天视频作品的数据，存到 data/raw/douyin/。
// 运行：通过 ./update.sh（ego-browser nodejs 的工作目录是 /，读不到环境变量，所以由它注入项目路径 ROOT）。接口带页面签名，走页面加载 + CDP 读响应体。
const fs = await import("node:fs/promises");
const RAW = ROOT + "data/raw/douyin/"; // ROOT 由 update.sh 在脚本开头注入
await fs.mkdir(RAW, { recursive: true });

const task = await taskSpace("multi-platform video data");
const page = task.page("p1");
await page.cdp("Network.enable", {});

async function bodies(re) {
  const out = [];
  for (const e of (await page.events()).filter((e) => e.method === "Network.responseReceived" && re.test(e.params?.response?.url || ""))) {
    try {
      out.push({ url: e.params.response.url, json: JSON.parse((await page.cdp("Network.getResponseBody", { requestId: e.params.requestId })).body) });
    } catch {}
  }
  return out;
}

await page.events();
await page.goto("https://creator.douyin.com/creator-micro/data-center/content");
await page.waitForTimeout(7000);
const listRes = (await bodies(/web\/api\/creator\/item\/list/))[0]?.json;
if (!listRes?.items) throw new Error("没拿到抖音作品列表，可能需要在 ego lite 里重新登录抖音创作者中心");
const since = Date.now() / 1000 - 30 * 86400;
// shortcut: 只取列表第一页（count=10），近 30 天发得多了要翻页
const items = listRes.items.filter((i) => i.video_info && Number(i.create_time) >= since);
const fetchedAt = Date.now();
await fs.writeFile(RAW + "_list.json", JSON.stringify({ fetchedAt, items }));

for (const it of items) {
  await page.events();
  await page.goto(`https://creator.douyin.com/creator-micro/work-management/work-detail/${it.id}?enter_from=item_data`);
  await page.waitForTimeout(6000);
  for (const tab of ["流量分析", "观众分析"]) {
    try { await page.click(`text="${tab}"`, { label: "open " + tab }); await page.waitForTimeout(3000); } catch {}
  }
  const out = { fetchedAt };
  for (const { url, json } of await bodies(/data\/item\/summarize|realtime\/analysis\/data_center|item\/play\/source|fans\/item\/portrait|item_analysis\/metrics_trend/)) {
    const q = new URL(url).searchParams;
    const key = /metrics_trend/.test(url) ? `trend_${q.get("metrics")}_${q.get("time_unit")}` : url.split("?")[0].split("/").filter(Boolean).slice(-2).join("_");
    out[key] = json;
  }
  await fs.writeFile(RAW + it.id + ".json", JSON.stringify(out));
  console.log("douyin ok", it.id, it.description.slice(0, 20), Object.keys(out).join(","));
}
// 不关窗口：后面的脚本接着用同一个窗口，最后由 fetch_channels.mjs 关闭
