"""本地看看板（Mac / Windows 通用）：Mac `python3 preview.py`，Windows `py preview.py`，然后打开 http://localhost:8765"""
import functools, http.server, shutil
from pathlib import Path

DASH = Path(__file__).resolve().parent / "dashboard"
if not (DASH / "data.js").exists():  # 还没抓过真实数据时先用示例数据
    shutil.copyfile(DASH / "data.example.js", DASH / "data.js")
print("打开 http://localhost:8765 （Ctrl+C 停止）")
http.server.ThreadingHTTPServer(("127.0.0.1", 8765), functools.partial(http.server.SimpleHTTPRequestHandler, directory=DASH)).serve_forever()
