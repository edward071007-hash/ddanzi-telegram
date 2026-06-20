import urllib.request
import urllib.parse
import json
import re
import os
import html

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")
CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")
LAST_ID_FILE = os.environ.get("LAST_ID_FILE", "ddanzi_last_ids.json")


def load_config():
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def fetch_page(url):
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    })
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read().decode("utf-8", errors="replace")


def get_latest_post_ids(author):
    search_url = "https://www.ddanzi.com/index.php?_filter=search&mid=free&search_target=nick_name&search_keyword=" + urllib.parse.quote(author)
    page_html = fetch_page(search_url)
    pattern = r'document_srl=(\d+)'
    matches = re.findall(pattern, page_html)
    seen = []
    for m in matches:
        if m not in seen:
            seen.append(m)
    seen.sort(key=lambda x: int(x), reverse=True)
    return seen


def is_by_author(page_html, author):
    match = re.search(r'class="member_\d+\s+author[^"]*"[^>]*>([^<]+)<', page_html)
    return match is not None and match.group(1).strip() == author


def get_post_content(document_srl, author):
    url = f"https://www.ddanzi.com/free/{document_srl}"
    page_html = fetch_page(url)

    if not is_by_author(page_html, author):
        return None, None, None

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


def load_last_ids():
    try:
        with open(LAST_ID_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_last_ids(data):
    with open(LAST_ID_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)


def main():
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID must be set")
        return

    config = load_config()
    authors = config.get("ddanzi", [])
    if not authors:
        print("No ddanzi authors in config")
        return

    last_ids = load_last_ids()

    for author in authors:
        print(f"\n--- Checking author: {author} ---")
        is_new = author not in last_ids
        last_id = last_ids.get(author, "0")
        print(f"Last sent post ID: {last_id}")

        post_ids = get_latest_post_ids(author)
        if not post_ids:
            print("No posts found")
            continue

        print(f"Found {len(post_ids)} posts, latest: {post_ids[0]}")

        if is_new:
            last_ids[author] = post_ids[0]
            print(f"New author registered, saving latest: {post_ids[0]}")
            continue

        new_posts = [pid for pid in post_ids if int(pid) > int(last_id)]
        new_posts.sort(key=lambda x: int(x))

        if not new_posts:
            print("No new posts")
            continue

        latest_sent = last_id
        for pid in new_posts:
            print(f"Processing post {pid}...")
            title, body, url = get_post_content(pid, author)

            if title is None:
                print(f"Skipped {pid} (not by {author})")
                continue

            message = f"📌 {title}\n\n{body}\n\n🔗 {url}"
            send_telegram(message)
            print(f"Sent: {title}")
            latest_sent = pid

        last_ids[author] = latest_sent

    save_last_ids(last_ids)
    print("\nDone.")


if __name__ == "__main__":
    main()
