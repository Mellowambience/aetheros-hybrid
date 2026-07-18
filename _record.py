import asyncio, os
from playwright.async_api import async_playwright

OUT = r"C:\Users\nator\AetherOS_Hybrid\frames"
os.makedirs(OUT, exist_ok=True)
URL = "http://127.0.0.1:8900/aetherhaven_desktop.html"
SHOTS = []

async def shot(pg, name):
    await pg.screenshot(path=f"{OUT}/{name}.png")
    SHOTS.append(name)

async def main():
    async with async_playwright() as p:
        b = await p.chromium.launch(args=["--no-sandbox"])
        pg = await b.new_page(viewport={"width":1280,"height":800}, device_scale_factor=1)
        await pg.goto(URL, wait_until="networkidle")
        await pg.wait_for_timeout(2600)          # calm mode + presence settle
        await shot(pg, "f01_home")

        # open launcher (single nav surface) — screenshot the grid, then close
        await pg.evaluate("toggleLauncher()")
        await pg.wait_for_timeout(900)
        await pg.fill("#launcherSearch", "weather")
        await pg.wait_for_timeout(700)
        await shot(pg, "f02_launcher")
        await pg.evaluate("toggleLauncher()")
        await pg.wait_for_timeout(500)

        # expand weather panel (peek-on-demand)
        await pg.evaluate("showWin('weather');activate('weather');")
        await pg.wait_for_timeout(1500)
        await shot(pg, "f03_weather")

        # system map (truthful telemetry)
        await pg.evaluate("showWin('sysmap');activate('sysmap');")
        await pg.wait_for_timeout(1500)
        await shot(pg, "f04_sysmap")

        # outbox (human SEND gate)
        await pg.evaluate("showWin('outbox');activate('outbox');")
        await pg.wait_for_timeout(1200)
        await shot(pg, "f05_outbox")

        # expand-all to contrast with calm
        await pg.evaluate("setCalm(false)")
        await pg.wait_for_timeout(1200)
        await shot(pg, "f06_expand")

        # back to calm + open chat, send a command to show routing
        await pg.evaluate("setCalm(true);openBubble();")
        await pg.wait_for_timeout(700)
        await pg.fill("#bpInput", "add quest: ship the recap video")
        await pg.click("#bpSend")
        await pg.wait_for_timeout(2200)
        await shot(pg, "f07_chat")

        await b.close()
        print("FRAMES:", len(SHOTS), SHOTS)

asyncio.run(main())
