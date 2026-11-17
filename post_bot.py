"""NEELEGAL Telegram auto-poster.
Every run (GitHub starts it every 30 minutes) it:
  1. posts every item in schedule.json whose time has come and has not been posted yet (quiz poll, PDF, text, photo);
  2. checks your YouTube channel's public video feed and posts a "new video" message for any new upload.
Secrets: TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID.  Variable (not secret): YOUTUBE_CHANNEL_ID.
Test without posting:  python3 post_bot.py --dry-run --now "2026-11-17 13:05"
All times in schedule.json are India time (IST), written as "YYYY-MM-DD HH:MM".
"""
import json, os, sys, uuid, urllib.request, urllib.parse, urllib.error, datetime, xml.etree.ElementTree as ET
HERE = os.path.dirname(os.path.abspath(__file__))
MAX_LATE_HOURS = 3   # an item more than 3 hours late is skipped (so old items never flood the channel)
def arg(n, d=None):
    a = sys.argv[1:]; return a[a.index(n) + 1] if n in a else d
DRY = "--dry-run" in sys.argv
def now_ist():
    if arg("--now"): return datetime.datetime.strptime(arg("--now"), "%Y-%m-%d %H:%M")
    return datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None) + datetime.timedelta(hours=5, minutes=30)
def load(name, default):
    p = os.path.join(HERE, name)
    return json.load(open(p, encoding="utf-8")) if os.path.exists(p) else default
def save(name, data): json.dump(data, open(os.path.join(HERE, name), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
def call(method, fields, files=None):
    url = f"https://api.telegram.org/bot{os.environ['TELEGRAM_BOT_TOKEN']}/{method}"
    fields = dict(fields, chat_id=os.environ["TELEGRAM_CHAT_ID"])
    if files:
        b = uuid.uuid4().hex; body = b""
        for k, v in fields.items():
            body += f'--{b}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode()
        for k, path in files.items():
            body += (f'--{b}\r\nContent-Disposition: form-data; name="{k}"; filename="{os.path.basename(path)}"\r\n'
                     f'Content-Type: application/octet-stream\r\n\r\n').encode() + open(path, "rb").read() + b"\r\n"
        body += f"--{b}--\r\n".encode()
        req = urllib.request.Request(url, data=body, headers={"Content-Type": f"multipart/form-data; boundary={b}"})
    else:
        req = urllib.request.Request(url, data=urllib.parse.urlencode(fields).encode())
    try:
        with urllib.request.urlopen(req, timeout=60) as r: return json.load(r).get("ok", False)
    except urllib.error.HTTPError as e:
        print("Telegram refused:", e.read().decode()); return False
def post(item):
    t = item["type"]
    if DRY:
        print("DRY RUN would post:", item["id"], "|", t); return True
    if t == "quiz":
        return call("sendPoll", {
            "question": item["question"],
            "options": json.dumps([{"text": o} for o in item["options"]], ensure_ascii=False),
            "type": "quiz", "is_anonymous": "true",
            "correct_option_ids": json.dumps([item["correct_index"]]),
            "explanation": item["explanation"],
            "members_only": "true", "allows_revoting": "false", "allows_multiple_answers": "false",
            "shuffle_options": "true" if item.get("shuffle") else "false", "hide_results_until_closes": "false"})
    if t == "document":
        return call("sendDocument", {"caption": item.get("caption", "")}, {"document": os.path.join(HERE, item["file"])})
    if t == "photo":
        return call("sendPhoto", {"caption": item.get("caption", "")}, {"photo": os.path.join(HERE, item["file"])})
    if t == "text":
        return call("sendMessage", {"text": item["text"], "disable_web_page_preview": "false"})
    print("Unknown type", t); return False
def run_schedule(state, now):
    done = set(state.get("posted", [])); n = 0
    for it in load("schedule.json", []):
        when = datetime.datetime.strptime(it["when"], "%Y-%m-%d %H:%M")
        if it["id"] in done or when > now: continue
        if (now - when) > datetime.timedelta(hours=MAX_LATE_HOURS):
            print("Skipped (too late):", it["id"]); done.add(it["id"]); continue
        if post(it): done.add(it["id"]); n += 1
    state["posted"] = sorted(done); print("Schedule items posted:", n)
def feed_videos(cid, xml_text=None):
    if xml_text is None:
        with urllib.request.urlopen(f"https://www.youtube.com/feeds/videos.xml?channel_id={cid}", timeout=30) as r: xml_text = r.read().decode()
    ns = {"a": "http://www.w3.org/2005/Atom", "yt": "http://www.youtube.com/xml/schemas/2015"}
    out = []
    for e in ET.fromstring(xml_text).findall("a:entry", ns):
        out.append({"id": e.find("yt:videoId", ns).text, "title": e.find("a:title", ns).text,
                    "link": e.find("a:link", ns).attrib["href"]})
    return out
def run_youtube(state, xml_text=None):
    cid = os.environ.get("YOUTUBE_CHANNEL_ID") or arg("--channel")
    if not cid and xml_text is None: print("YOUTUBE_CHANNEL_ID not set: skipping YouTube check."); return
    vids = feed_videos(cid, xml_text); seen = state.get("seen_videos")
    if seen is None:
        state["seen_videos"] = [v["id"] for v in vids]; print("First YouTube check: remembered", len(vids), "existing videos, posted none."); return
    rules = load("video_rules.json", [])
    for v in reversed(vids):
        if v["id"] in seen: continue
        extra = next((r["extra"] for r in rules if r["match"].lower() in v["title"].lower()), "")
        text = f"Naya video aa gaya: {v['title']}\nDekhiye: {v['link']}\n{extra}\nRoz ki free practice yahin Telegram par."
        if post({"id": "yt-" + v["id"], "type": "text", "text": text.replace("\n\n", "\n")}): seen.append(v["id"])
    state["seen_videos"] = seen
def main():
    state = load("state.json", {}); now = now_ist(); print("India time now:", now)
    run_schedule(state, now)
    try:
        run_youtube(state, open(arg("--feed-file")).read() if arg("--feed-file") else None)
    except Exception as e: print("YouTube check failed (will retry next run):", e)
    if not DRY: save("state.json", state)
    return 0
if __name__ == "__main__": sys.exit(main())
