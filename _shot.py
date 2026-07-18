import asyncio
from playwright.async_api import async_playwright

async def main():
    async with async_playwright() as p:
        b = await p.chromium.launch(args=["--no-sandbox","--force-color-profile=srgb"])
        pg = await b.new_page(viewport={"width":1100,"height":1500}, device_scale_factor=2)
        pg.set_default_timeout(15000)
        await pg.goto("http://127.0.0.1:8900/recap.html", wait_until="networkidle")
        await pg.wait_for_timeout(1500)
        await pg.screenshot(path=r"C:\Users\nator\AetherOS_Hybrid\recap.png", full_page=True)
        await b.close()
        print("OK screenshot written")

asyncio.run(main())
