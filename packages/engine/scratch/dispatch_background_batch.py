import sys
import json
import time
import base64
from pathlib import Path
import urllib.request

sys.path.append(r"C:\Users\artlu\OracliomNew\Oracliom\emiliano-cowork-plaatoos")
from crm import OutreachCRM

ARTIFACT_DIR = Path(r"C:\Users\artlu\.gemini\antigravity-cli\brain\8fbaa064-7416-4540-8a08-956d9cba103b")

def send_browser_command(action: str, params: dict = None) -> dict:
    payload = {"action": action, "params": params or {}}
    req = urllib.request.Request(
        "http://127.0.0.1:8765/api/browser/command",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode())

def cdp_eval(expression: str):
    res = send_browser_command("cdp_command", {
        "targetUrlMatch": "instagram.com",
        "method": "Runtime.evaluate",
        "params": {
            "expression": expression,
            "returnByValue": True
        }
    })
    return res.get("result", {}).get("result", {}).get("value")

def cdp_cmd(method: str, params: dict = None):
    return send_browser_command("cdp_command", {
        "targetUrlMatch": "instagram.com",
        "method": method,
        "params": params or {}
    })

def close_mini_chat_if_open():
    """Closes any docked mini-chat or floating dialog to ensure clean surface."""
    close_js = """
    (() => {
        const svgs = Array.from(document.querySelectorAll('svg[aria-label="Close"], svg[aria-label="Zamknij"]'));
        for (const svg of svgs) {
            const btn = svg.closest('div[role="button"], button') || svg;
            const r = btn.getBoundingClientRect();
            if (r.width > 0 && r.height > 0) {
                btn.click();
                return true;
            }
        }
        return false;
    })()
    """
    closed = cdp_eval(close_js)
    if closed:
        time.sleep(0.5)
    return closed

def process_lead(lead) -> str:
    print("\n=======================================================", flush=True)
    print(f"Target Lead: {lead.id} - {lead.name} (@{lead.ig}) [{lead.business_type}]", flush=True)
    print("=======================================================", flush=True)

    # Ensure previous mini-chats are closed
    close_mini_chat_if_open()

    profile_url = f"https://www.instagram.com/{lead.ig}/"
    print(f"[Extension] Navigating silently in background to {profile_url}...", flush=True)
    send_browser_command("navigate", {
        "targetUrlMatch": "instagram.com",
        "url": profile_url,
        "background": True
    })

    # Dynamic polling for profile header render
    check_btn_js = """
    (() => {
        const notFound = document.querySelector('h2');
        if (notFound && (notFound.innerText.includes("Sorry, this page isn't available") || notFound.innerText.includes("Niestety, ta strona jest niedostÄ™pna"))) {
            return { notFound: true };
        }

        const buttons = Array.from(document.querySelectorAll('button, div[role="button"], a[role="button"], header section button, header section div[role="button"]'));
        const found = buttons.find(b => {
            const t = (b.innerText || b.textContent || '').trim().toLowerCase();
            const r = b.getBoundingClientRect();
            return (t === 'message' || t === 'wyĹ›lij wiadomoĹ›Ä‡') && r.x > 200 && r.y < 450;
        });
        if (found) {
            const r = found.getBoundingClientRect();
            return { exists: true, text: found.innerText.trim(), x: Math.round(r.x), y: Math.round(r.y) };
        }

        // Check if header is at least rendered
        const header = document.querySelector('header');
        return { exists: false, headerReady: !!header };
    })()
    """

    btn_info = None
    for _ in range(16): # Up to 8 seconds
        time.sleep(0.5)
        btn_info = cdp_eval(check_btn_js)
        if btn_info and (btn_info.get("exists") or btn_info.get("notFound")):
            break

    if not btn_info or btn_info.get("notFound"):
        print(f"[Skip] Profile {lead.id} (@{lead.ig}) not found or unavailable.", flush=True)
        return "not_found"

    if not btn_info.get("exists"):
        print(f"[Skip] No Message button on profile for {lead.id} (@{lead.ig}) - restricted DMs.", flush=True)
        return "skipped"

    print(f"[Extension] Found Message button at ({btn_info['x']}, {btn_info['y']}). Clicking via DOM...", flush=True)
    click_js = """
    (() => {
        const buttons = Array.from(document.querySelectorAll('button, div[role="button"], a[role="button"], header section button, header section div[role="button"]'));
        const found = buttons.find(b => {
            const t = (b.innerText || b.textContent || '').trim().toLowerCase();
            const r = b.getBoundingClientRect();
            return (t === 'message' || t === 'wyĹ›lij wiadomoĹ›Ä‡') && r.x > 200 && r.y < 450;
        });
        if (found) {
            found.click();
            return true;
        }
        return false;
    })()
    """
    cdp_eval(click_js)

    # 2. Dynamic polling for composer textbox
    focus_js = """
    (() => {
        const el = document.querySelector('div[contenteditable="true"], [role="textbox"]');
        if (!el) return false;
        el.focus();
        return true;
    })()
    """
    composer_focused = False
    for _ in range(18): # Up to 9 seconds
        time.sleep(0.5)
        if cdp_eval(focus_js):
            composer_focused = True
            break

    if not composer_focused:
        print(f"[Error] Composer textbox not found for {lead.id}!", flush=True)
        return "error"

    # 3. Dispatch pitch across clean message bubbles (No literal \n or /n!)
    bubbles = lead.bubbles
    print(f"[Extension] Dispatching pitch across {len(bubbles)} clean message bubbles (zero literal \\n or /n)...", flush=True)

    for b_idx, bubble in enumerate(bubbles, 1):
        cdp_eval(focus_js)
        time.sleep(0.3)
        print(f"  -> Bubble {b_idx}/{len(bubbles)}: '{bubble[:55]}...'", flush=True)
        cdp_cmd("Input.insertText", {"text": bubble})
        time.sleep(0.6)

        # Dispatch Enter key
        cdp_cmd("Input.dispatchKeyEvent", {
            "type": "rawKeyDown",
            "windowsVirtualKeyCode": 13,
            "nativeVirtualKeyCode": 13,
            "macCharCode": 13,
            "unmodifiedText": "\r",
            "text": "\r",
            "key": "Enter",
            "code": "Enter"
        })
        cdp_cmd("Input.dispatchKeyEvent", {
            "type": "keyUp",
            "windowsVirtualKeyCode": 13,
            "nativeVirtualKeyCode": 13,
            "macCharCode": 13,
            "unmodifiedText": "\r",
            "text": "\r",
            "key": "Enter",
            "code": "Enter"
        })

        if b_idx < len(bubbles):
            time.sleep(1.5)

    # 4. Dynamic polling to verify sent bubble in DOM
    verify_js = """
    (() => {
        const elements = Array.from(document.querySelectorAll('div[dir="auto"], [role="row"], [role="listitem"], span'));
        const sent = elements.find(el => {
            const t = (el.innerText || el.textContent || '').trim();
            return (t.includes('Plaatoos') || t.includes('rezerwacji') || t.includes('stworzyÄ‡') || t.includes('zarzÄ…dzaÄ‡')) && !el.closest('[role="textbox"]');
        });
        if (sent) {
            const r = sent.getBoundingClientRect();
            return {
                verified: true,
                text: (sent.innerText || sent.textContent).trim().slice(0, 60),
                x: Math.round(r.x),
                y: Math.round(r.y)
            };
        }
        return { verified: false };
    })()
    """
    verify_info = None
    for _ in range(12): # Up to 6 seconds
        time.sleep(0.5)
        verify_info = cdp_eval(verify_js)
        if verify_info and verify_info.get("verified"):
            break

    # 5. Capture receipt screenshot via CDP
    receipt_file = ARTIFACT_DIR / f"receipt_{lead.id}_{lead.ig}.png"
    shot_res = cdp_cmd("Page.captureScreenshot", {"format": "png", "fromSurface": True})
    data = shot_res.get("result", {}).get("data")
    if data:
        with open(receipt_file, "wb") as f:
            f.write(base64.b64decode(data))
        print(f"[Receipt] Screenshot saved to {receipt_file}", flush=True)

    # Close mini-chat after receipt is taken to prepare for next lead
    close_mini_chat_if_open()

    if verify_info and verify_info.get("verified"):
        print(f"[SUCCESS] Delivery verified for {lead.id}: '{verify_info.get('text')}' at ({verify_info.get('x')}, {verify_info.get('y')})", flush=True)
        return "sent"
    else:
        print(f"[Warning] Delivery bubble not explicitly confirmed for {lead.id}.", flush=True)
        return "unverified"

def run_batch(count: int = 5):
    crm = OutreachCRM()
    leads = crm.load_leads()

    # Process next leads marked 'new' with IG
    pending = [lead for lead in leads if lead.prior == "new" and lead.ig]
    print(f"Loaded {len(pending)} pending leads. Starting batch of {count}...", flush=True)

    processed = 0
    for lead in pending:
        if processed >= count:
            break

        status = process_lead(lead)
        if status == "sent":
            crm.mark_dm_sent(lead.id, notes="Verified delivered via background Chrome Extension bridge (clean bubbles, no /n)")
            processed += 1
            print(f"[CRM] Committed {lead.id} as SENT. Progress: {processed}/{count}", flush=True)
            time.sleep(3.0)
        elif status in ("skipped", "not_found"):
            reason = "Restricted DMs (no message button)" if status == "skipped" else "Profile not found"
            crm.mark_lead_skipped(lead.id, reason=reason)
            print(f"[CRM] Marked {lead.id} as SKIPPED ({reason}).", flush=True)
            time.sleep(1.5)
        else:
            print(f"[CRM] {lead.id} resulted in {status}. Leaving for inspection.", flush=True)
            time.sleep(2.0)

if __name__ == "__main__":
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 5
    run_batch(n)
