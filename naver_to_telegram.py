import urllib.request
import json
import re
import os
import html
from xml.etree import ElementTree

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")
CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")
LAST_ID_FILE = os.environ.get("LAST_ID_FILE", "naver_last_ids.json")


def load_config():
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def fetch_rss(blog_id):
    url = f"https://rss.blog.naver.com/{blog_id}.xml"
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    })
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read().decode("utf-8", errors="replace")


def parse_rss(xml_text):
    root = ElementTree.fromstring(xml_text)
    items = []
    for item in root.iter("item"):
        title = item.findtext("title", "")
        link = item.findtext("link", "")
        guid = item.findtext("guid", "")
        desc_raw = item.findtext("description", "")

        # description에서 HTML 태그 제거
        desc = re.sub(r'<[^>]+>', '', desc_raw)
        desc = html.unescape(desc).strip()
        desc = re.sub(r'\n{3,}', '\n\n', desc)

        # guid에서 logNo 추출
        log_no_match = re.search(r'/(\d+)(?:\?|$)', guid or link)
        log_no = log_no_match.group(1) if log_no_match else ""

        # 링크에서 추적 파라미터 제거
        clean_link = re.sub(r'\?fromRss.*$', '', link)

        items.append({
            "title": title,
            "link": clean_link,
            "log_no": log_no,
            "description": desc,
        })
    return items


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
    blog_ids = config.get("naver", [])
    if not blog_ids:
        print("No naver blogs in config")
        return

    last_ids = load_last_ids()

    for blog_id in blog_ids:
        print(f"\n--- Checking blog: {blog_id} ---")
        is_new = blog_id not in last_ids
        last_log_no = last_ids.get(blog_id, "0")
        print(f"Last sent logNo: {last_log_no}")

        try:
            xml_text = fetch_rss(blog_id)
        except Exception as e:
            print(f"Failed to fetch RSS for {blog_id}: {e}")
            continue

        items = parse_rss(xml_text)
        if not items:
            print("No posts found")
            continue

        print(f"Found {len(items)} posts, latest: {items[0]['log_no']}")

        if is_new:
            last_ids[blog_id] = items[0]["log_no"]
            print(f"New blog registered, saving latest: {items[0]['log_no']}")
            continue

        new_items = [item for item in items if int(item["log_no"] or "0") > int(last_log_no)]
        new_items.sort(key=lambda x: int(x["log_no"] or "0"))

        if not new_items:
            print("No new posts")
            continue

        latest_sent = last_log_no
        for item in new_items:
            print(f"Processing: {item['title']}...")

            # RSS description은 요약본 → 전문이 필요하면 본문 크롤링 가능
            body = item["description"]
            if len(body) > 3000:
                body = body[:3000] + "\n\n... (전문은 링크에서 확인)"

            message = f"📝 {item['title']}\n\n{body}\n\n🔗 {item['link']}"
            send_telegram(message)
            print(f"Sent: {item['title']}")
            latest_sent = item["log_no"]

        last_ids[blog_id] = latest_sent

    save_last_ids(last_ids)
    print("\nDone.")


if __name__ == "__main__":
    main()
