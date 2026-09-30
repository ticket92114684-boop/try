import asyncio
import re
from playwright.async_api import async_playwright
from playwright_stealth import Stealth
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, ContextTypes, CallbackQueryHandler

# ========== CONFIG ==========
BOT_TOKEN       = "8639806583:AAHBP81e5g8Luf7jhJRwi1-t8hM7VKnn5AU"
OTP_CHANNEL_ID  = -1003250473765
OTP_GROUP_ID    = -1004427004477
ADMIN_ID        = 8473160748
PANEL_USER      = "xyz@gmail.com"
PANEL_PASS      = "Sanju@71"
LOGIN_URL       = "https://livestatspanel.com/index.php"
SMS_URL         = "https://livestatspanel.com/index.php?opt=shw_sms_tod&lang=EN"
POLL_INTERVAL   = 12

# 🔗 Inline button ke liye — apna channel username daal yahan
CHANNEL_URL     = "https://t.me/dolaotp"

seen_messages = set()
full_msg_store = {}  # callback button ke liye full message store

# ========== COUNTRY FLAG DETECT ==========
import phonenumbers
from phonenumbers.phonenumberutil import region_code_for_number

def get_country(phone):
    fallback = ('🌍', 'XX')
    digits = re.sub(r'\D', '', phone)
    if not digits:
        return fallback
        
    # Prepend '+' so phonenumbers can parse it as international format
    phone_with_plus = '+' + digits

    try:
        parsed = phonenumbers.parse(phone_with_plus)
        region = region_code_for_number(parsed)
        if region and len(region) == 2:
            # Generate flag emoji from ISO 2-letter region code
            flag = chr(ord(region[0]) + 127397) + chr(ord(region[1]) + 127397)
            return (flag, region)
    except Exception:
        pass
    
    return fallback

# ========== UTILS ==========
async def send_screenshot(page, app, caption="Screenshot"):
    try:
        screenshot = await page.screenshot(type="jpeg", quality=80, full_page=True)
        await app.bot.send_photo(chat_id=ADMIN_ID, photo=screenshot, caption=caption)
        return True
    except Exception as e:
        print(f"Screenshot failed: {e}", flush=True)
        return False

def extract_otp(text):
    m = re.search(r'\b(\d{4,6})\b', text)
    if m:
        return m.group(1)
    m = re.search(r'(?:OTP|code|pin|password|key|verification)[^\dA-Z]*([A-Z0-9]{4,8})', text, re.I)
    if m:
        return m.group(1)
    return None

def mask_phone(text):
    digits = re.sub(r'\D', '', text)
    if len(digits) <= 8:
        return digits
    return f"{digits[:4]}**{digits[-4:]}"

def clean_text(text):
    return re.sub(r'\s+', ' ', text).strip()

def is_valid_phone(text):
    digits = re.sub(r'\D', '', text)
    return len(digits) >= 10

def is_header_row(phone_text):
    header_keywords = ['NUMBER', 'Number', 'number', 'PHONE', 'Phone', 'phone']
    return any(keyword in phone_text for keyword in header_keywords)

def escape_markdown(text):
    escape_chars = ['_', '*', '[', ']', '(', ')', '~', '`', '>', '#', '+', '-', '=', '|', '{', '}', '.', '!']
    for char in escape_chars:
        text = text.replace(char, f'\\{char}')
    return text

# ========== LOGIN ==========
async def login_panel(app):
    pw = browser = ctx = page = None
    try:
        print("Starting browser...", flush=True)
        pw = await async_playwright().start()
        browser = await pw.chromium.launch(
            headless=True,
            args=['--no-sandbox', '--disable-setuid-sandbox', '--disable-dev-shm-usage']
        )
        ctx = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/129.0.0.0"
        )
        page = await ctx.new_page()

        # Stealth lagao taaki Cloudflare block na kare
        await Stealth().apply_stealth_async(page)

        print("Opening login page...", flush=True)
        await page.goto(LOGIN_URL, timeout=60000, wait_until="domcontentloaded")
        await asyncio.sleep(2)

        email_filled = False
        for sel in ['input[name="user"]', 'input[name="email"]', 'input[type="text"]']:
            try:
                loc = page.locator(sel)
                if await loc.count() > 0:
                    await loc.click(timeout=3000)
                    await loc.fill(PANEL_USER, timeout=3000)
                    print(f"Username filled: {sel}", flush=True)
                    email_filled = True
                    break
            except Exception:
                continue

        if not email_filled:
            await send_screenshot(page, app, "Username field not found!")
            await cleanup_resources_direct(pw, browser, ctx, page)
            return False, None

        await asyncio.sleep(0.5)

        try:
            pass_input = page.locator('input[type="password"]')
            await pass_input.click(timeout=5000)
            await pass_input.fill(PANEL_PASS, timeout=5000)
            print("Password filled", flush=True)
        except Exception as e:
            await send_screenshot(page, app, f"Password field error: {e}")
            await cleanup_resources_direct(pw, browser, ctx, page)
            return False, None

        await asyncio.sleep(0.5)

        submitted = False
        btn_selectors = [
            'button[type="submit"]', 'input[type="submit"]',
            'input[value*="Login"]', 'button:has-text("Login")',
            'form button'
        ]
        for sel in btn_selectors:
            try:
                loc = page.locator(sel)
                if await loc.count() > 0:
                    await loc.click(timeout=5000)
                    submitted = True
                    break
            except Exception:
                continue

        if not submitted:
            print("Using form.submit()", flush=True)
            await page.evaluate("document.querySelector('form')?.submit()")

        await asyncio.sleep(3)

        page_content = await page.content()
        if "Please enter your login details" not in page_content:
            print("LOGIN SUCCESSFUL!", flush=True)
            return True, page
        else:
            await send_screenshot(page, app, "LOGIN FAILED - Still on login page")
            print("Login failed - check credentials", flush=True)
            await cleanup_resources_direct(pw, browser, ctx, page)
            return False, None

    except Exception as e:
        print(f"Login error: {e}", flush=True)
        await cleanup_resources_direct(pw, browser, ctx, page)
        return False, None

async def cleanup_resources_direct(pw, browser, ctx, page):
    try:
        if page: await page.close()
        if ctx: await ctx.close()
        if browser: await browser.close()
        if pw: await pw.stop()
    except Exception as e:
        print(f"Cleanup note: {e}", flush=True)

async def cleanup_resources(page):
    try:
        if page:
            ctx = page.context
            browser = ctx.browser
            await page.close()
            await ctx.close()
            await browser.close()
    except Exception as e:
        print(f"Cleanup note: {e}", flush=True)

# ========== SMS DETAILS EXTRACT ==========
async def get_sms_details(page):
    try:
        await asyncio.sleep(1.5)

        tables = page.locator('table')
        table_count = await tables.count()

        if table_count < 2:
            print("Details table nahi mila", flush=True)
            return None, None

        details_table = tables.first
        all_rows = details_table.locator('tr')
        all_row_count = await all_rows.count()

        if all_row_count < 2:
            print("Details table mein data nahi hai", flush=True)
            return None, None

        data_row = all_rows.nth(1)
        cells = data_row.locator('td')
        cell_count = await cells.count()

        if cell_count < 5:
            print(f"Details row mein kam cells: {cell_count}", flush=True)
            return None, None

        dt = clean_text(await cells.nth(0).inner_text())
        msg_body = clean_text(await cells.nth(4).inner_text())

        print(f"Date: {dt}", flush=True)
        print(f"Message: {msg_body[:120]}...", flush=True)

        return dt, msg_body

    except Exception as e:
        print(f"SMS details error: {e}", flush=True)
        return None, None

# ========== CLICKABLE ELEMENT FIND ==========
async def find_and_click_select(details_cell):
    try:
        cell_html = await details_cell.inner_html()
        print(f"  Cell HTML: {cell_html[:200]}", flush=True)

        # Check if there's a form inside
        form = details_cell.locator('form')
        if await form.count() > 0:
            print("  Found form, submitting it...", flush=True)
            try:
                # Use expect_navigation to wait properly for the page to load
                async with details_cell.page.expect_navigation(timeout=15000):
                    await form.evaluate("f => f.submit()")
                return True
            except Exception as e:
                print(f"  Form submit note: {e}", flush=True)
                return True

        element_selectors = ['a', 'button', 'span', 'u', 'div', 'p', '[onclick]', '[href]', '*']

        for sel in element_selectors:
            try:
                el = details_cell.locator(sel).first
                if await el.count() > 0 and await el.is_visible():
                    el_text = await el.inner_text()
                    el_tag = await el.evaluate("e => e.tagName")
                    print(f"  Trying {el_tag}: '{el_text.strip()}'", flush=True)
                    # Use a longer timeout for click since navigation is slow
                    await el.click(timeout=15000)
                    print(f"  Clicked successfully!", flush=True)
                    return True
            except Exception as e:
                print(f"  {sel} failed: {str(e)[:80]}", flush=True)
                continue

        print(f"  Last resort: clicking cell directly", flush=True)
        await details_cell.click(timeout=15000)
        return True

    except Exception as e:
        print(f"  Find/click error: {e}", flush=True)
        return False

# ========== SEND COMPACT CARD MESSAGE (IMAGE 1 STYLE) ==========
async def send_card(chat_id, app, ph, sender, dt, otp, full_msg, msg_key):
    """Image 1 jaisa compact card with inline buttons bhejo"""
    try:
        flag, ccode = get_country(ph)
        masked = mask_phone(ph)

        # ---- Image 2 Layout ----
        # Line 1: 🇵🇰 PA | 🟢 +92AT581 #EN
        clean_masked = escape_markdown(masked)
        line1 = f"{flag} {ccode} \\| 🟢 {clean_masked} \\#EN"
        
        # Line 2: Sender - OTP (tap to copy)
        clean_sender = escape_markdown(sender)
        if otp:
            clean_otp = escape_markdown(otp)
            line2 = f"{clean_sender} \\- `{clean_otp}`"
        else:
            line2 = f"{clean_sender} \\- SMS Received"

        message_text = f"{line1}\n{line2}"

        # ---- Store full message for callback button ----
        store_id = str(abs(hash(msg_key)) % 1000000)
        full_msg_store[store_id] = full_msg
        if len(full_msg_store) > 200:
            oldest = next(iter(full_msg_store))
            del full_msg_store[oldest]

        # ---- Inline Buttons ----
        CHANNEL_URL = "https://t.me/dolaotp" # User's actual channel link
        
        if otp:
            otp_btn = InlineKeyboardButton(f"🛡️ {otp}", api_kwargs={'copy_text': {'text': str(otp)}})
        else:
            otp_btn = InlineKeyboardButton("🛡️ SMS", callback_data="ignore")

        keyboard = [
            [
                InlineKeyboardButton("🔔 Channel", url=CHANNEL_URL),
                otp_btn
            ],
            [
                InlineKeyboardButton("📞 Get Number", url=CHANNEL_URL)
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await app.bot.send_message(
            chat_id=chat_id,
            text=message_text,
            parse_mode="MarkdownV2",
            reply_markup=reply_markup
        )
        return True

    except Exception as e:
        print(f"Card send fail to {chat_id}: {e}", flush=True)
        # Fallback: simple text
        try:
            await app.bot.send_message(chat_id=chat_id, text=f"New SMS: {full_msg[:200]}")
            return True
        except Exception as e2:
            print(f"Fallback bhi fail: {e2}", flush=True)
            return False

# ========== BUTTON CALLBACK HANDLER ==========
async def button_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()  # loading spinner hatao
    data = query.data

    if data.startswith("full_"):
        store_id = data[5:]
        full_msg = full_msg_store.get(store_id, "Message expired (purana ho gaya)")
        # Popup alert mein full message dikhao
        await query.answer(text=full_msg[:190], show_alert=True)

    elif data.startswith("copy_"):
        store_id = data[5:]
        full_msg = full_msg_store.get(store_id, "")
        otp = extract_otp(full_msg)
        if otp:
            await query.answer(text=f"OTP: {otp} (long press to copy)", show_alert=False)
        else:
            await query.answer(text="OTP nahi mila is message mein", show_alert=True)

# ========== CHECK SMS ==========
async def check_sms(app, page):
    global seen_messages
    try:
        await page.goto(SMS_URL, timeout=30000, wait_until="domcontentloaded")
        await asyncio.sleep(2)

        page_content = await page.content()
        if "Please enter your login details" in page_content:
            print("Session expired - Need re-login", flush=True)
            return False

        # Wait for at least one table to load
        try:
            await page.wait_for_selector('table', timeout=15000)
        except Exception:
            print("Timeout waiting for any table to load on SMS page.", flush=True)

        tables = page.locator('table')
        table_count = await tables.count()
        
        if table_count == 0:
            print("Koi table nahi mila", flush=True)
            if not getattr(app, "debug_no_table_sent", False):
                await send_screenshot(page, app, "DEBUG: 'Koi table nahi mila' - Check if login failed or page is empty")
                app.debug_no_table_sent = True
            return True

        main_table = None
        for i in range(table_count):
            tbl = tables.nth(i)
            try:
                tbl_text = await tbl.inner_text()
                if "Today's SMS Statistics" in tbl_text:
                    main_table = tbl
                    print(f"Main table found at index {i}", flush=True)
                    break
            except Exception:
                continue

        if not main_table:
            main_table = tables.first
            print("Using first table as main table", flush=True)
            # Send screenshot to see what is going wrong
            if not getattr(app, "debug_screenshot_sent", False):
                await send_screenshot(page, app, "DEBUG: Could not find 'Today's SMS Statistics'. Here is what the page looks like.")
                app.debug_screenshot_sent = True

        all_rows = main_table.locator('tr')
        total_rows = await all_rows.count()

        print(f"Total rows in main table: {total_rows}", flush=True)

        new_messages_found = 0

        for i in range(total_rows):
            try:
                # 🔁 Har iteration pe page fresh re-navigate karo (bug fix)
                if i > 0:
                    await page.goto(SMS_URL, timeout=30000, wait_until="domcontentloaded")
                    await asyncio.sleep(2)
                    tables = page.locator('table')
                    main_table = None
                    for ti in range(await tables.count()):
                        tbl = tables.nth(ti)
                        try:
                            if "Today's SMS Statistics" in await tbl.inner_text():
                                main_table = tbl
                                break
                        except Exception:
                            continue
                    if not main_table:
                        main_table = tables.first
                    all_rows = main_table.locator('tr')

                row = all_rows.nth(i)
                cells = row.locator('td')
                cell_count = await cells.count()

                if cell_count < 7:
                    continue

                ph = clean_text(await cells.nth(0).inner_text())
                sender = clean_text(await cells.nth(2).inner_text())
                msg_count = clean_text(await cells.nth(5).inner_text())
                details_cell = cells.nth(6)

                if is_header_row(ph):
                    continue

                if not is_valid_phone(ph):
                    continue

                print(f"\nRow {i}: Phone={ph}, Sender={sender}", flush=True)

                msg_key = f"v3_{ph}_{sender}_{msg_count}"

                if msg_key in seen_messages:
                    print(f"  Skip: Already seen", flush=True)
                    continue

                clicked = await find_and_click_select(details_cell)

                if not clicked:
                    print(f"  Click nahi ho paya, skip", flush=True)
                    continue

                dt, full_msg = await get_sms_details(page)

                if not full_msg:
                    print(f"  Message nahi mila, skip", flush=True)
                    continue

                seen_messages.add(msg_key)
                new_messages_found += 1

                otp = extract_otp(full_msg)
                if otp:
                    print(f"  OTP found: {otp}", flush=True)

                # 🎯 NEW: Compact card format mein bhejo (image 1 style)
                await send_card(OTP_CHANNEL_ID, app, ph, sender, dt, otp, full_msg, msg_key)
                await send_card(OTP_GROUP_ID, app, ph, sender, dt, otp, full_msg, msg_key)
                print(f"  ✅ Card sent to Telegram!", flush=True)

            except Exception as row_err:
                print(f"Row {i} error: {row_err}", flush=True)
                continue

        print(f"\n📊 This cycle: {new_messages_found} new messages found", flush=True)
        print(f"📊 Total seen: {len(seen_messages)}", flush=True)

        if len(seen_messages) > 500:
            seen_messages = set(list(seen_messages)[-250:])
            print(f"🧹 Cleaned seen_messages, now: {len(seen_messages)}", flush=True)

        return True

    except Exception as e:
        print(f"Check SMS error: {e}", flush=True)
        return False

# ========== MAIN ==========
async def main():
    print("🤖 Bot Starting (v2 - Card Format)...", flush=True)

    app = Application.builder().token(BOT_TOKEN).build()

    async def start_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text("✅ Bot is Active! Login process in progress...")

    async def status_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if update.effective_user.id == ADMIN_ID:
            await update.message.reply_text(
                f"✅ Bot Running\n⏱️ Check every {POLL_INTERVAL}s\n📊 Processed: {len(seen_messages)}"
            )

    async def reset_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        global seen_messages
        if update.effective_user.id == ADMIN_ID:
            old_count = len(seen_messages)
            seen_messages = set()
            await update.message.reply_text(f"🔄 Seen cache reset! Old: {old_count}, New: 0")

    app.add_handler(CommandHandler("start", start_cmd))
    app.add_handler(CommandHandler("status", status_cmd))
    app.add_handler(CommandHandler("reset", reset_cmd))
    app.add_handler(CallbackQueryHandler(button_callback))  # 🆕 inline buttons ke liye

    await app.initialize()
    await app.start()

    print("🔒 Cleaning webhook & pending updates...", flush=True)
    await app.bot.delete_webhook(drop_pending_updates=True)
    await asyncio.sleep(2)

    await app.updater.start_polling(drop_pending_updates=True, allowed_updates=[])
    print("✅ Telegram Connected & Polling Started!", flush=True)

    while True:
        login_ok, page = await login_panel(app)
        if not login_ok or not page:
            print("🔄 Retry login in 8s...", flush=True)
            await asyncio.sleep(8)
            continue

        print("🚀 Monitoring Started!", flush=True)

        while True:
            check_ok = await check_sms(app, page)
            if not check_ok:
                print("🔄 Session lost - Re-logging in...", flush=True)
                await cleanup_resources(page)
                break
            await asyncio.sleep(POLL_INTERVAL)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n🛑 Bot Stopped by User", flush=True)
