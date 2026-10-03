import asyncio
import json
import os
import re
import time
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application
from playwright.async_api import async_playwright

BOT_TOKEN       = "8885622806:AAEzNbdnJJWd5AGC6pC8LUBcOs2SRzKXlds"
CHANNEL_ID      = os.getenv("CHANNEL_ID", "-1004427004477")
NEW_CHANNEL_ID  = os.getenv("NEW_CHANNEL_ID", "-1003250473765")
PRIVATE_CHANNEL_ID = os.getenv("PRIVATE_CHANNEL_ID", "-1003956267456")
ADMIN_ID        = int(os.getenv("ADMIN_ID", "8473160748"))
PANEL_USER      = os.getenv("PANEL_USER", "5260101")
PANEL_PASS      = os.getenv("PANEL_PASS", "Shoaibpanel@123!!!")
LOGIN_URL       = "https://mysmsportal.com/index.php"
OTP_SUMMARY_URL = "https://mysmsportal.com/index.php?opt=shw_sts_today"
POLL_INTERVAL   = int(os.getenv("POLL_INTERVAL", "2"))

cookies_file = "panel_cookies.json"
seen_file = "seen_messages.json"
bot_ref = None
last_alert_time = 0

# Use a dict to preserve insertion order for deduplication
seen_messages = {}

# Browser state
pw = None
browser = None
context = None
page = None

# ========== SEEN MESSAGES — FILE BASED (no duplicates even after restart) ==========
def load_seen():
    try:
        with open(seen_file, 'r') as f:
            data = json.load(f)
            # Load into dict to preserve order
            return {k: True for k in data[-800:]}
    except:
        return {}

def save_seen(seen):
    try:
        with open(seen_file, 'w') as f:
            json.dump(list(seen.keys())[-800:], f)
    except:
        pass

seen_messages = load_seen()

# ========== PREMIUM FORMAT HELPERS ==========
def escape_markdown(text):
    escape_chars = ['_', '*', '[', ']', '(', ')', '~', '`', '>', '#', '+', '-', '=', '|', '{', '}', '.', '!']
    for char in escape_chars:
        text = str(text).replace(char, f'\\{char}')
    return text

def region_to_flag(region):
    return "".join(chr(127397 + ord(c)) for c in region.upper())

def get_country(ph):
    try:
        import phonenumbers
        p = phonenumbers.parse("+" + str(ph).lstrip("+"))
        cc = "+" + str(p.country_code)
        region = phonenumbers.region_code_for_number(p)
        if region:
            return region_to_flag(region), cc
    except:
        pass
    return "🌐", "+???"

async def safe_send(bot, chat_id, text, reply_markup=None):
    """Single attempt — no retries to avoid delay"""
    try:
        if reply_markup:
            await bot.send_message(chat_id, text, parse_mode="MarkdownV2", reply_markup=reply_markup, read_timeout=10, write_timeout=10)
        else:
            await bot.send_message(chat_id, text, parse_mode="Markdown", read_timeout=10, write_timeout=10)
        return True
    except Exception as e:
        print(f"Send err [{chat_id}]: {e}", flush=True)
        return False

async def send_to_all_channels(text, reply_markup):
    """Send to all 3 channels simultaneously — no waiting one by one"""
    tasks = [
        safe_send(bot_ref, CHANNEL_ID, text, reply_markup),
        safe_send(bot_ref, NEW_CHANNEL_ID, text, reply_markup),
        safe_send(bot_ref, PRIVATE_CHANNEL_ID, text, reply_markup),
    ]
    await asyncio.gather(*tasks)

async def admin_alert(bot, text):
    global last_alert_time
    now = time.time()
    if now - last_alert_time < 3600:
        return
    last_alert_time = now
    await safe_send(bot, ADMIN_ID, text)

def mask(p):
    p = p.strip()
    return p if len(p) <= 6 else f"{p[:4]}*****{p[-3:]}"

def extract_otp(t):
    m = re.search(r'\b(\d{4,8})\b', t)
    return m.group(1) if m else "N/A"

# ========== BROWSER MANAGEMENT ==========
async def start_browser():
    global pw, browser, context, page
    try:
        if page: await page.close()
        if context: await context.close()
        if browser: await browser.close()
        if pw: await pw.stop()
    except: pass

    pw = await async_playwright().start()
    browser = await pw.chromium.launch(
        headless=True,
        args=[
            '--no-sandbox', '--disable-setuid-sandbox', '--disable-dev-shm-usage',
            '--disable-gpu', '--disable-software-rasterizer', '--disable-extensions',
            '--disable-default-apps', '--disable-sync', '--disable-translate',
            '--disable-background-networking', '--disable-background-timer-throttling',
            '--disable-renderer-backgrounding', '--disable-blink-features=AutomationControlled',
            '--mute-audio', '--no-first-run', '--no-zygote',
            '--memory-pressure-off', '--single-process',
            '--aggressive-cache-discard', '--max_old_space_size=256',
        ]
    )
    context = await browser.new_context(
        viewport={'width': 1024, 'height': 768},
        user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36',
        locale='en-US', device_scale_factor=1, is_mobile=False, has_touch=False, java_script_enabled=True
    )
    await context.add_init_script("""
        Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
        Object.defineProperty(navigator, 'languages', {get: () => ['en-US', 'en']});
        Object.defineProperty(navigator, 'platform', {get: () => 'Win32'});
        window.chrome = {runtime: {}};
    """)
    await context.route("**/*", lambda route:
        route.abort() if route.request.resource_type in ['image', 'stylesheet', 'font', 'media'] else route.continue_()
    )
    page = await context.new_page()
    try:
        with open(cookies_file) as f:
            await context.add_cookies(json.load(f))
    except: pass
    print("🌐 Browser started", flush=True)

async def save_cookies():
    try:
        with open(cookies_file, 'w') as f:
            json.dump(await context.cookies(), f)
    except: pass

async def do_login():
    try:
        print("🔐 Logging in...", flush=True)
        await page.goto(LOGIN_URL, timeout=25000, wait_until='domcontentloaded')
        await asyncio.sleep(0.8)
        u = page.locator('input[type="text"]').first
        await u.click(); await u.fill(PANEL_USER)
        await asyncio.sleep(0.2)
        p = page.locator('input[type="password"]').first
        await p.click(); await p.fill(PANEL_PASS)
        await asyncio.sleep(0.2)
        await page.locator('button, input[type="submit"]').first.click()
        await asyncio.sleep(1.5)
        await save_cookies()
        print("✅ Login OK", flush=True)
        return True
    except Exception as e:
        print(f"❌ Login failed: {e}", flush=True)
        return False

# ========== ULTRA FAST POLL LOOP ✅ ==========
async def run_bot():
    global seen_messages

    await start_browser()

    # Initial login check
    try:
        await page.goto(OTP_SUMMARY_URL, timeout=20000, wait_until='domcontentloaded')
        await asyncio.sleep(0.5)
        content = await page.content()
        if 'Please enter your login details' in content:
            await do_login()
            await page.goto(OTP_SUMMARY_URL, timeout=20000, wait_until='domcontentloaded')
    except:
        await do_login()
        await page.goto(OTP_SUMMARY_URL, timeout=20000, wait_until='domcontentloaded')

    print(f"✅ BOT ONLINE — Har {POLL_INTERVAL}s check ⚡", flush=True)
    await safe_send(bot_ref, ADMIN_ID, f"✅ Bot chalu — har {POLL_INTERVAL}s mein check karega!")

    err_count = 0
    crash_count = 0
    first_run = True  # Pehli baar sirf scan karo, send mat karo (restart duplicate fix)

    while True:
        try:
            # ⚡ FAST: page.reload() instead of full goto() — 2x faster
            try:
                if first_run:
                    pass  # Already on the page from login
                else:
                    await page.reload(timeout=15000, wait_until='domcontentloaded')
            except Exception as e:
                if 'crashed' in str(e).lower() or 'closed' in str(e).lower():
                    crash_count += 1
                    print(f"💥 Crash ({crash_count}) — restart...", flush=True)
                    await start_browser()
                    await do_login()
                    await page.goto(OTP_SUMMARY_URL, timeout=20000, wait_until='domcontentloaded')
                    if crash_count >= 3:
                        await admin_alert(bot_ref, f"⚠️ Browser crash ({crash_count}x)")
                        crash_count = 0
                    continue
                raise

            crash_count = 0

            content = await page.content()
            if 'Please enter your login details' in content:
                print("🔄 Session expired — re-login", flush=True)
                if not await do_login():
                    await asyncio.sleep(3)
                    continue
                await page.goto(OTP_SUMMARY_URL, timeout=20000, wait_until='domcontentloaded')

            rows = page.locator('table tbody tr')
            total = await rows.count()
            print(f"📊 {total} rows", flush=True)

            for i in range(total):
                row = rows.nth(i)
                cols = row.locator('td')
                if await cols.count() < 5:
                    continue

                # Click into detail page
                form = row.locator('form').first
                clicked = False
                if await form.count() > 0:
                    try: await form.click(); clicked = True
                    except: pass
                if not clicked:
                    btn = row.locator('button:has-text("Select"), input[value*="Select"]').first
                    if await btn.count() > 0:
                        try: await btn.click(); clicked = True
                        except: pass
                if not clicked:
                    continue

                try:
                    await page.wait_for_load_state('domcontentloaded', timeout=8000)
                    detail_rows = page.locator('table tbody tr')
                    new_count = 0
                    for j in range(await detail_rows.count()):
                        dcols = detail_rows.nth(j).locator('td')
                        if await dcols.count() >= 5:
                            dt = (await dcols.nth(0).inner_text()).strip()
                            ph = (await dcols.nth(1).inner_text()).strip()
                            se = (await dcols.nth(2).inner_text()).strip()
                            ms = (await dcols.nth(-1).inner_text()).strip()
                            if ms and len(ms) > 3 and dt:
                                otp = extract_otp(ms)
                                masked = mask(ph)
                                
                                # Fix: Normalize phone to digits only so format changes don't cause dupes
                                clean_ph = re.sub(r'\D', '', ph)
                                key = f"{clean_ph}|{otp}" if otp != "N/A" else f"{clean_ph}|{ms[:30]}"
                                
                                if key not in seen_messages:
                                    seen_messages[key] = True

                                    if first_run:
                                        # Pehli baar sirf mark karo, send NAHI (restart pe duplicate fix)
                                        continue

                                    new_count += 1

                                    # Premium Format
                                    flag, ccode = get_country(ph)
                                    clean_masked = escape_markdown(masked)
                                    clean_ccode = escape_markdown(ccode)
                                    line1 = f"{flag} {clean_ccode} \\| 🟢 {clean_masked} \\#EN"

                                    clean_sender = escape_markdown(se)
                                    if otp and otp != "N/A":
                                        clean_otp = escape_markdown(otp)
                                        line2 = f"🔥 {clean_sender} \\- `{clean_otp}`"
                                    else:
                                        line2 = f"🔥 {clean_sender} \\- SMS Received"

                                    message_text = f"{line1}\n{line2}"

                                    CHANNEL_URL = "https://t.me/dolaotp"
                                    if otp and otp != "N/A":
                                        otp_btn = InlineKeyboardButton(f"🛡️ {otp}", api_kwargs={'copy_text': {'text': str(otp)}})
                                    else:
                                        otp_btn = InlineKeyboardButton("🛡️ SMS", callback_data="ignore")
                                    keyboard = [
                                        [InlineKeyboardButton("🔔 Channel", url=CHANNEL_URL), otp_btn],
                                        [InlineKeyboardButton("📞 Get Number", url=CHANNEL_URL)]
                                    ]
                                    reply_markup = InlineKeyboardMarkup(keyboard)

                                    # ⚡ Send to ALL channels at once (parallel — no waiting)
                                    await send_to_all_channels(message_text, reply_markup)
                                    print(f"✅ SENT: {masked} | {otp}", flush=True)

                    if new_count > 0:
                        save_seen(seen_messages)  # Save to file after new messages

                    # Go back to summary for next row
                    await page.go_back()
                    await page.wait_for_load_state('domcontentloaded', timeout=8000)
                except Exception as e:
                    print(f"Detail err: {e}", flush=True)
                    try: await page.goto(OTP_SUMMARY_URL, timeout=15000, wait_until='domcontentloaded')
                    except: pass

            if first_run:
                first_run = False
                save_seen(seen_messages)
                print(f"🔒 First scan done — {len(seen_messages)} old messages marked (no duplicates now)", flush=True)

            # Trim memory safely keeping the newest items at the end
            if len(seen_messages) > 1000:
                keys_to_keep = list(seen_messages.keys())[-800:]
                seen_messages = {k: True for k in keys_to_keep}

            err_count = 0

        except Exception as e:
            err_count += 1
            print(f"Poll err ({err_count}/5): {e}", flush=True)
            if 'crashed' in str(e).lower() or 'closed' in str(e).lower():
                await start_browser()
                await do_login()
                try: await page.goto(OTP_SUMMARY_URL, timeout=20000, wait_until='domcontentloaded')
                except: pass
            if err_count >= 5:
                await admin_alert(bot_ref, "⚠️ Errors — recovering...")
                err_count = 0
                await start_browser()
                await do_login()
                try: await page.goto(OTP_SUMMARY_URL, timeout=20000, wait_until='domcontentloaded')
                except: pass

        await asyncio.sleep(POLL_INTERVAL)

async def main():
    global bot_ref
    if not BOT_TOKEN:
        print("❌ BOT_TOKEN missing!", flush=True); return

    app = Application.builder().token(BOT_TOKEN).read_timeout(30).write_timeout(30).connect_timeout(30).build()
    bot_ref = app.bot

    await app.initialize()
    await app.start()
    
    print("✅ Bot is running in SEND-ONLY mode (Conflict error is impossible now!)", flush=True)

    asyncio.create_task(run_bot())
    await asyncio.Event().wait()

if __name__ == "__main__":
    try: asyncio.run(main())
    except KeyboardInterrupt: print("STOPPED", flush=True)
