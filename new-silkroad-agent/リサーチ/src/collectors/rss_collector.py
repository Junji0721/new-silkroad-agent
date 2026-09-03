"""
非日本語一次ソース(Al Jazeera, TRT World, WION, SCMP, Xinhua, The Diplomat, RT)を
定期的にポーリングし、新着記事のみを Make.com の Webhook へ送信する収集スクリプト。

実行方法:
    python3 rss_collector.py

前提:
    - リサーチ/config/rss_sources.json に監視対象RSSを定義
    - リサーチ/config/.env に MAKE_WEBHOOK_URL を設定(未設定時はWebhook送信をスキップ)
"""

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import feedparser
import requests
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parents[2]  # リサーチ/
CONFIG_DIR = BASE_DIR / "config"
DATA_DIR = BASE_DIR / "data"
SOURCES_FILE = CONFIG_DIR / "rss_sources.json"
SEEN_IDS_FILE = DATA_DIR / "processed" / "seen_ids.json"
RAW_DIR = DATA_DIR / "raw"

MAX_SEEN_IDS_PER_SOURCE = 1000
REQUEST_TIMEOUT_SECONDS = 15
HTTP_USER_AGENT = "Mozilla/5.0 (compatible; NewSilkroadIntelligenceAgent/1.0)"


def log(message: str) -> None:
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    print(f"[{timestamp}] {message}", flush=True)


def load_sources() -> list:
    with open(SOURCES_FILE, encoding="utf-8") as f:
        return json.load(f)


def load_seen_ids() -> dict:
    if not SEEN_IDS_FILE.exists():
        return {}
    with open(SEEN_IDS_FILE, encoding="utf-8") as f:
        return json.load(f)


def save_seen_ids(seen_ids: dict) -> None:
    SEEN_IDS_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(SEEN_IDS_FILE, "w", encoding="utf-8") as f:
        json.dump(seen_ids, f, ensure_ascii=False, indent=2)


def entry_id(entry) -> str:
    return entry.get("id") or entry.get("guid") or entry.get("link", "")


def fetch_new_entries(source: dict, known_ids: set) -> list:
    parsed = feedparser.parse(source["url"], request_headers={"User-Agent": HTTP_USER_AGENT})
    if parsed.bozo and not parsed.entries:
        log(f"[WARN] {source['name']}: フィード取得/解析に失敗しました ({parsed.bozo_exception})")
        return []

    new_entries = []
    for entry in parsed.entries:
        eid = entry_id(entry)
        if not eid or eid in known_ids:
            continue
        new_entries.append(
            {
                "_id": eid,
                "source_id": source["id"],
                "source_name": source["name"],
                "title": entry.get("title", ""),
                "link": entry.get("link", ""),
                "published": entry.get("published", ""),
                "summary": entry.get("summary", "")[:1000],
                "collected_at": datetime.now(timezone.utc).isoformat(),
            }
        )
    return new_entries


def public_fields(item: dict) -> dict:
    return {k: v for k, v in item.items() if k != "_id"}


def archive_raw(items: list) -> None:
    if not items:
        return
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    archive_file = RAW_DIR / f"{today}.jsonl"
    with open(archive_file, "a", encoding="utf-8") as f:
        for item in items:
            f.write(json.dumps(public_fields(item), ensure_ascii=False) + "\n")


def send_to_make(webhook_url: str, item: dict) -> bool:
    try:
        response = requests.post(webhook_url, json=public_fields(item), timeout=REQUEST_TIMEOUT_SECONDS)
        response.raise_for_status()
        return True
    except requests.RequestException as exc:
        log(f"[WARN] Webhook送信失敗: {item['source_name']} - {item['title'][:50]} ({exc})")
        return False


def main() -> int:
    # .env ファイルがあればロード（開発環境用）
    env_file = CONFIG_DIR / ".env"
    if env_file.exists():
        load_dotenv(env_file)

    webhook_url = os.environ.get("MAKE_WEBHOOK_URL", "").strip()
    if not webhook_url:
        log("[WARN] MAKE_WEBHOOK_URL が未設定のため、Webhook送信をスキップします(ローカル保存のみ実施)")

    sources = load_sources()
    seen_ids = load_seen_ids()

    total_new = 0
    total_sent = 0

    for source in sources:
        known_ids = set(seen_ids.get(source["id"], []))
        new_entries = fetch_new_entries(source, known_ids)

        if not new_entries:
            log(f"{source['name']}: 新着なし")
            continue

        archive_raw(new_entries)

        sent_count = 0
        for item in new_entries:
            if webhook_url:
                if send_to_make(webhook_url, item):
                    sent_count += 1
            known_ids.add(item["_id"])

        # 既知IDリストを更新(直近 MAX_SEEN_IDS_PER_SOURCE 件のみ保持)
        updated_ids = list(known_ids)[-MAX_SEEN_IDS_PER_SOURCE:]
        seen_ids[source["id"]] = updated_ids

        log(f"{source['name']}: 新着 {len(new_entries)} 件 / Webhook送信成功 {sent_count} 件")
        total_new += len(new_entries)
        total_sent += sent_count

    save_seen_ids(seen_ids)
    log(f"完了: 新着合計 {total_new} 件, Webhook送信成功合計 {total_sent} 件")
    return 0


if __name__ == "__main__":
    sys.exit(main())
