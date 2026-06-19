import urllib.request
import urllib.parse
import json
import re
import os
import html

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")
TARGET_AUTHOR = "정대만mitsui"
SEARCH_URL = "https://www.ddanzi.com/index.php?_filter=search&mid=free&search_target=nick_name&search_keyword=" + urllib.parse.quote(TARGET_AUTHOR)
LAST_ID_FILE = os.environ.get("LAST_ID_FILE", "last_post_id.txt")


def fetch_page(url):
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    })
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read().decode("utf-8", errors="replace")


def get_latest_post_ids():
    page_html = fetch_page(SEARCH_URL)
    pattern = r'document_srl=(\d+)'
    matches = re.findall(pattern, page_html)
    seen = []
    for m in matches:
        if m not in seen:
            seen.append(m)
    # document_srl이 큰 게 최신글 → 내림차순 정렬
    seen.sort(key=lambda x: int(x), reverse=True)
    return seen


def is_by_target_author(page_html):
    return TARGET_AUTHOR in page_html


def get_post_content(document_srl):
    url = f"https://www.ddanzi.com/free/{document_srl}"
    page_html = fetch_page(url)

    if not is_by_target_author(page_html):
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


def load_last_id():
    try:
        with open(LAST_ID_FILE, "r", encoding="utf-8-sig") as f:
            return f.read().strip()
    except FileNotFoundError:
        return ""


def save_last_id(post_id):
    with open(LAST_ID_FILE, "w", encoding="utf-8") as f:
        f.write(post_id)


def main():
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID must be set")
        return

    last_id = load_last_id()
    print(f"Last sent post ID: {last_id or '(none)'}")

    post_ids = get_latest_post_ids()
    if not post_ids:
        print("No posts found")
        return

    print(f"Found {len(post_ids)} posts, latest: {post_ids[0]}")

    new_posts = []
    for pid in post_ids:
        if int(pid) <= int(last_id or "0"):
            continue
        new_posts.append(pid)

    new_posts.sort(key=lambda x: int(x))

    if not new_posts:
        print("No new posts")
        return

    sent_any = False
    latest_sent = last_id

    for pid in new_posts:
        print(f"Processing post {pid}...")
        title, body, url = get_post_content(pid)

        if title is None:
            print(f"Skipped {pid} (not by {TARGET_AUTHOR})")
            continue

        message = f"📌 {title}\n\n{body}\n\n🔗 {url}"
        send_telegram(message)
        print(f"Sent: {title}")
        sent_any = True
        latest_sent = pid

    if sent_any:
        save_last_id(latest_sent)
        print(f"Updated last ID to {latest_sent}")
    else:
        save_last_id(post_ids[0])
        print("No new posts by target author")


if __name__ == "__main__":
    main()
