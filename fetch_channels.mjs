// 用 ego-browser 抓视频号助手近 30 天视频的数据，存到 data/raw/channels/。
// 运行：通过 update.py（ego-browser nodejs 的工作目录是 /，读不到环境变量，所以由它把项目路径 ROOT 写在脚本开头）
// 先点开「单篇视频」让页面发一次 post_list，记下它的请求头和参数，再用同样的头在页面里调列表和单条详情接口。
const fs = await import("node:fs/promises");
const RAW = ROOT + "data/raw/channels/"; // ROOT 由 update.py 在脚本开头注入
await fs.mkdir(RAW, { recursive: true });

const task = await taskSpace("multi-platform video data");
const page = task.page("p1");
await page.cdp("Network.enable", {});
await page.goto("https://channels.weixin.qq.com/platform/statistic/post");
// 登录过期时页面停在扫码页，等不到这个按钮；网慢时也最多等 20 秒
await page.waitForSelector('text="单篇视频"', { timeout: 20000 }).catch(() => {
  throw new Error("视频号助手没登录：请在 ego lite 里用微信扫码登录视频号助手");
});
await page.waitForTimeout(1000);
await page.events();
await page.click('text="单篇视频"', { label: "open single video tab" });
await page.waitForTimeout(4000);
const req = (await page.events()).find((e) => e.method === "Network.requestWillBeSent" && /statistic\/post_list/.test(e.params.request.url))?.params.request;
if (!req) throw new Error("没拿到视频号作品列表请求，可能需要在 ego lite 里重新扫码登录视频号助手");

const tpl = JSON.parse(req.postData);
const headers = Object.fromEntries(Object.entries(req.headers).filter(([k]) => /^(x-|finger|content-type)/i.test(k)));
const base = req.url.split("statistic/post_list")[0] + "statistic/";
const query = req.url.split("?")[1];
async function call(name, body) {
  const r = await page.fetch(`${base}${name}?${query}`, { method: "POST", headers, body: JSON.stringify({ ...tpl, ...body, timestamp: String(Date.now()) }), timeout: 15000 });
  const j = JSON.parse(r.body);
  if (j.errCode !== 0) throw new Error(`${name} 返回 ${j.errCode} ${j.errMsg}`);
  return j.data;
}

const now = Math.floor(Date.now() / 1000);
const day0 = now - (now + 8 * 3600) % 86400; // 北京时间今天零点
const list = (await call("post_list", { pageSize: 50, currentPage: 1, startTime: day0 - 30 * 86400, endTime: day0 + 86400 })).list || [];
const fetchedAt = Date.now();
await fs.writeFile(RAW + "_list.json", JSON.stringify({ fetchedAt, list }));

for (const p of list) {
  const out = { fetchedAt };
  // 单条详情拿不到不影响列表里的完播率等指标，所以只记下错误
  try { out.lost_rate = await call("get_feed_lost_rate", { feedId: p.objectId }); } catch (e) { out.lost_rate_err = String(e); }
  try {
    const start = p.createTime - (p.createTime + 8 * 3600) % 86400;
    out.by_source = await call("feed_aggreagate_data_by_tab_type", { feedId: p.objectId, startTs: String(start), endTs: String(day0), interval: 3 });
    out.by_source_start = start;
  } catch (e) { out.by_source_err = String(e); }
  await fs.writeFile(RAW + p.objectId + ".json", JSON.stringify(out));
  console.log("channels ok", p.objectId, (p.desc?.description || "").slice(0, 20), Object.keys(out).join(","));
}
await task.finish({ keep: [] });
