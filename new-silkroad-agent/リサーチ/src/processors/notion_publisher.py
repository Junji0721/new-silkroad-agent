#!/usr/bin/env python3
"""
RSSで収集した記事をClaude APIで日本語化し、Notionデータベースに登録するスクリプト。

実行方法:
    python3 notion_publisher.py

前提:
    - リサーチ/src/collectors/rss_collector.py で記事を収集
    - リサーチ/config/.env に NOTION_API_KEY, NOTION_DATABASE_ID を設定
"""

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import requests
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parents[2]  # リサーチ/
CONFIG_DIR = BASE_DIR / "config"
DATA_DIR = BASE_DIR / "data"
RAW_DIR = DATA_DIR / "raw"

ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"
NOTION_API_URL = "https://api.notion.com/v1"
REQUEST_TIMEOUT_SECONDS = 30

NOTION_SOURCES_MAP = {
    "aljazeera": "Al Jazeera",
    "trtworld": "TRT World",
    "wion": "WION",
    "scmp": "SCMP",
    "xinhua": "Xinhua",
    "diplomat": "The Diplomat",
    "rt": "RT",
}


def log(message: str) -> None:
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    print(f"[{timestamp}] {message}", flush=True)


def translate_with_claude(article: dict, api_key: str) -> Optional[dict]:
    """Claude APIを使用して記事を日本語化・要約"""
    try:
        prompt = f"""以下は{article['source_name']}の記事です。日本の主要メディアが報じない地政学的視点を意識し、次のJSON形式のみで出力してください(前後に説明文を付けないこと):
{{"title_ja": "日本語訳タイトル", "summary_ja": "3〜4文の日本語要約"}}

タイトル: {article['title']}
概要: {article['summary']}"""

        headers = {
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }

        payload = {
            "model": "claude-sonnet-5",
            "max_tokens": 1024,
            "messages": [{"role": "user", "content": prompt}],
        }

        response = requests.post(
            ANTHROPIC_API_URL, json=payload, headers=headers, timeout=REQUEST_TIMEOUT_SECONDS
        )
        response.raise_for_status()

        result = response.json()
        if result.get("content") and result["content"][0].get("text"):
            text = result["content"][0]["text"]
            translated = json.loads(text)
            return translated
        else:
            log(f"[WARN] Claude API: 予期しないレスポンス形式")
            return None

    except json.JSONDecodeError:
        log(f"[WARN] Claude API: JSONパースエラー - {article['title'][:50]}")
        return None
    except requests.RequestException as exc:
        log(f"[WARN] Claude API呼び出し失敗 - {article['source_name']}: {exc}")
        return None


def add_to_notion(article: dict, translated: dict, database_id: str, api_key: str) -> bool:
    """Notionデータベースに記事を追加"""
    try:
        source_ja = NOTION_SOURCES_MAP.get(article["source_id"], article["source_name"])

        properties = {
            "タイトル（和訳）": {"title": [{"text": {"content": translated.get("title_ja", "")}}]},
            "タイトル（原文）": {"rich_text": [{"text": {"content": article.get("title", "")}}]},
            "媒体": {"select": {"name": source_ja}},
            "要約（和訳）": {"rich_text": [{"text": {"content": translated.get("summary_ja", "")}}]},
            "公開日時": {"rich_text": [{"text": {"content": article.get("published", "")}}]},
            "記事URL": {"url": article.get("link", "")},
            "収集日時": {"date": {"start": article.get("collected_at", "")}},
        }

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Notion-Version": "2023-06-01",
            "Content-Type": "application/json",
        }

        payload = {"parent": {"database_id": database_id}, "properties": properties}

        response = requests.post(
            f"{NOTION_API_URL}/pages", json=payload, headers=headers, timeout=REQUEST_TIMEOUT_SECONDS
        )
        response.raise_for_status()
        return True

    except requests.RequestException as exc:
        log(f"[WARN] Notion API呼び出し失敗 - {article['source_name']}: {exc}")
        return False


def load_articles_from_raw(days: int = 1) -> list:
    """ローカル保存されたRSS記事を読み込む"""
    articles = []
    RAW_DIR.mkdir(parents=True, exist_ok=True)

    # 直近N日間のファイルを確認
    for i in range(days):
        date = datetime.now(timezone.utc)
        if i > 0:
            from datetime import timedelta

            date = date - timedelta(days=i)

        date_str = date.strftime("%Y-%m-%d")
        file_path = RAW_DIR / f"{date_str}.jsonl"

        if not file_path.exists():
            continue

        with open(file_path, "r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    articles.append(json.loads(line))

    return articles


def main() -> int:
    # .env ファイルがあればロード（開発環境用）
    env_file = CONFIG_DIR / ".env"
    if env_file.exists():
        load_dotenv(env_file)

    notion_api_key = os.environ.get("NOTION_API_KEY", "").strip()
    notion_database_id = os.environ.get("NOTION_DATABASE_ID", "").strip()
    claude_api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()

    if not notion_api_key or not notion_database_id:
        log("❌ NOTION_API_KEY または NOTION_DATABASE_ID が未設定です")
        return 1

    if not claude_api_key:
        log("❌ Claude API キーが設定されていません")
        return 1

    log("📚 ローカルRSS記事を読み込み中...")
    articles = load_articles_from_raw(days=3)

    if not articles:
        log("新着記事がありません")
        return 0

    log(f"📝 {len(articles)} 件の記事を処理中...")

    success_count = 0
    for article in articles:
        log(f"処理中: {article['source_name']} - {article['title'][:50]}...")

        # Claude APIで日本語化
        translated = translate_with_claude(article, claude_api_key)
        if not translated:
            log(f"⏭️  スキップ: Claude API処理失敗")
            continue

        # Notionに登録
        if add_to_notion(article, translated, notion_database_id, notion_api_key):
            log(f"✅ Notion登録成功")
            success_count += 1
        else:
            log(f"❌ Notion登録失敗")

    log(f"✅ 完了: {success_count}/{len(articles)} 件をNotionに登録しました")
    return 0


if __name__ == "__main__":
    sys.exit(main())
