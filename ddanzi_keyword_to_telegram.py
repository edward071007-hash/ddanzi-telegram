import urllib.request
import urllib.parse
import json
import re
import os
import html

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")
CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")
LAST_ID_FILE = os.environ.get("LAST_ID_FILE", "ddanzi_keyword_last_ids.json")


def load_config():
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def fetch_page(url):
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    })
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read().decode("utf-8", errors="replace")


def search_posts(keyword):
    search_url = "https://www.ddanzi.com/index.php?_filter=search&mid=free&search_target=title_content&search_keyword=" + urllib.parse.quote(keyword)
    page_html = fetch_page(search_url)
    matches = re.findall(r'document_srl=(\d+)', page_html)
    seen = []
    for m in matches:
        if m not in seen:
            seen.append(m)
    seen.sort(key=lambda x: int(x), reverse=True)
    return seen


def get_post_content(document_srl):
    url = f"https://www.ddanzi.com/free/{document_srl}"
    page_html = fetch_page(url)

    title_match = re.search(r'<meta\s+property="og:title"\s+content="([^"]*)"', page_html)
    title = html.unescape(title_match.group(1)) if title_match else ""
    title = re.sub(r'^자유게시판\s*-\s*', '', title)

    desc_match = re.search(r'<meta\s+property="og:description"\s+content="([^"]*)"', page_html)
    description = html.unescape(desc_match.group(1)) if desc_match else ""

    content_match = re.search(
        r'<div[^>]*class="[^"]*xe_content[^"]*"[^>]*>(.*?)</div>',
        page_html, re.DOTALL
    )
    if not content_match:
        content_match = re.search(
            r'<article[^>]*>(.*?)</article>',
            page_html, re.DOTALL
        )

    if content_match:
        raw = content_match.group(1)
        raw = re.sub(r'<br\s*/?>', '\n', raw)
        raw = re.sub(r'<p[^>]*>', '\n', raw)
        raw = re.sub(r'</p>', '', raw)
        raw = re.sub(r'<[^>]+>', '', raw)
        raw = html.unescape(raw)
        lines = [line.rstrip() for line in raw.split('\n')]
        body = '\n'.join(lines).strip()
        body = re.sub(r'\n{3,}', '\n\n', body)
    else:
        body = description

    return title, body, f"https://www.ddanzi.com/free/{document_srl}"


def send_telegram(text):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    max_len = 4000
    chunks = []
    while len(text) > max_len:
        split_pos = text.rfind('\n', 0, max_len)
        if split_pos == -1:
            split_pos = max_len
        chunks.append(text[:split_pos])
        text = text[split_pos:].lstrip('\n')
    chunks.append(text)

    for chunk in chunks:
        payload = json.dumps({
            "chat_id": TELEGRAM_CHAT_ID,
            "text": chunk,
            "disable_web_page_preview": True
        }).encode("utf-8")
        req = urllib.request.Request(url, data=payload, headers={
            "Content-Type": "application/json; charset=utf-8"
        })
        with urllib.request.urlopen(req, timeout=30) as resp:
            result = json.loads(resp.read().decode())
            if not result.get("ok"):
                print(f"Telegram send failed: {result}")


def load_last_id():
    try:
        with open(LAST_ID_FILE, "r", encoding="utf-8") as f:
            return json.load(f).get("last_id", "0")
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def save_last_id(last_id):
    with open(LAST_ID_FILE, "w", encoding="utf-8") as f:
        json.dump({"last_id": last_id}, ensure_ascii=False, fp=f)


def main():
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID must be set")
        return

    config = load_config()
    keywords = config.get("ddanzi_keywords", [])
    if not keywords:
        print("No ddanzi_keywords in config")
        return

    print(f"Keywords: {keywords}")
    last_id = load_last_id()
    is_new = last_id is None
    if is_new:
        last_id = "0"
    print(f"Last sent post ID: {last_id}")

    all_post_ids = set()
    for kw in keywords:
        post_ids = search_posts(kw)
        print(f"  '{kw}': {len(post_ids)} posts")
        all_post_ids.update(post_ids)

    if not all_post_ids:
        print("No posts found")
        return

    max_id = max(all_post_ids, key=lambda x: int(x))
    print(f"Total unique posts: {len(all_post_ids)}, latest: {max_id}")

    if is_new:
        save_last_id(max_id)
        print(f"First run, saving latest: {max_id}")
        return

    new_posts = sorted(
        [pid for pid in all_post_ids if int(pid) > int(last_id)],
        key=lambda x: int(x)
    )

    if not new_posts:
        print("No new posts")
        save_last_id(last_id)
        return

    latest_sent = last_id
    for pid in new_posts:
        print(f"Processing post {pid}...")
        title, body, url = get_post_content(pid)

        if title is None:
            print(f"Skipped {pid} (fetch failed)")
            continue

        message = f"🔍 {title}\n\n{body}\n\n🔗 {url}"
        send_telegram(message)
        print(f"Sent: {title}")
        latest_sent = pid

    save_last_id(latest_sent)
    print("\nDone.")


if __name__ == "__main__":
    main()
