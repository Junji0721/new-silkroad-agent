#!/usr/bin/env python3
"""
Notionデータベースの自動セットアップスクリプト
必要なプロパティ(列)を追加する
"""
import os
import re
import requests
import json
from dotenv import load_dotenv

# 環境変数を読み込む
load_dotenv(os.path.join(os.path.dirname(__file__), '../../config/.env'))

NOTION_API_KEY = os.getenv('NOTION_API_KEY')
BASE_URL = 'https://api.notion.com/v1'

# ヘッダー設定
HEADERS = {
    'Authorization': f'Bearer {NOTION_API_KEY}',
    'Notion-Version': '2026-03-11',
    'Content-Type': 'application/json'
}

def extract_page_id_from_url(url):
    """NotionのURLからページIDを抽出"""
    match = re.search(r'/p/([a-f0-9]{32})', url)
    if match:
        return match.group(1).replace('-', '')
    return None

def get_database_id_from_page(page_id):
    """ページの子ブロックからデータベースIDを取得"""
    url = f'{BASE_URL}/blocks/{page_id}/children'
    response = requests.get(url, headers=HEADERS)

    if response.status_code != 200:
        print(f"エラー: ページ情報の取得に失敗しました ({response.status_code})")
        print(response.text)
        return None

    blocks = response.json().get('results', [])
    for block in blocks:
        if block.get('type') == 'child_database':
            return block['id'].replace('-', '')

    # テーブルブロック（database）を探す
    for block in blocks:
        if block.get('type') == 'table_of_contents':
            continue
        print(f"見つかったブロック: {block.get('type')}")

    return None

def add_property_to_database(database_id, property_name, property_config):
    """データベースにプロパティを追加"""
    url = f'{BASE_URL}/databases/{database_id}'

    # 既存のプロパティを取得
    response = requests.get(url, headers=HEADERS)
    if response.status_code != 200:
        print(f"エラー: データベース情報取得失敗 ({response.status_code})")
        return False

    db_info = response.json()
    existing_properties = db_info.get('properties', {})

    # 既に存在するか確認
    if property_name in existing_properties:
        print(f"✓ '{property_name}' は既に存在します")
        return True

    # プロパティを追加
    properties = existing_properties.copy()
    properties[property_name] = property_config

    payload = {'properties': properties}
    response = requests.patch(url, json=payload, headers=HEADERS)

    if response.status_code == 200:
        print(f"✓ '{property_name}' を追加しました")
        return True
    else:
        print(f"✗ '{property_name}' の追加に失敗しました ({response.status_code})")
        print(response.text)
        return False

def setup_notion_database(database_id):
    """必要なプロパティを全て追加"""
    print(f"\n📋 Notionデータベースをセットアップ中... (ID: {database_id[:8]}...)")

    properties_to_add = {
        'タイトル（原文）': {'type': 'rich_text'},
        '媒体': {
            'type': 'select',
            'select': {
                'options': [
                    {'name': 'Al Jazeera', 'color': 'blue'},
                    {'name': 'TRT World', 'color': 'purple'},
                    {'name': 'WION', 'color': 'green'},
                    {'name': 'SCMP', 'color': 'red'},
                    {'name': 'Xinhua', 'color': 'yellow'},
                    {'name': 'The Diplomat', 'color': 'orange'},
                    {'name': 'RT', 'color': 'gray'},
                ]
            }
        },
        '要約（和訳）': {'type': 'rich_text'},
        '公開日時': {'type': 'rich_text'},
        '記事URL': {'type': 'url'},
        '収集日時': {'type': 'date'},
    }

    success_count = 0
    for prop_name, prop_config in properties_to_add.items():
        if add_property_to_database(database_id, prop_name, prop_config):
            success_count += 1

    print(f"\n✅ セットアップ完了: {success_count}/{len(properties_to_add)} のプロパティを追加しました")
    return success_count == len(properties_to_add)

def main():
    print("🚀 Notionデータベースセットアップツール\n")

    # 入力取得
    notion_url = input("Notion データベースのURLを入力してください: ").strip()

    if not notion_url:
        print("❌ URLが入力されていません")
        return

    # IDを抽出
    page_id = extract_page_id_from_url(notion_url)
    if not page_id:
        print("❌ URLから有効なIDを抽出できません")
        return

    print(f"📌 抽出したID: {page_id[:8]}...")

    # データベースを直接取得（ページIDがそのままデータベースIDの場合）
    url = f'{BASE_URL}/databases/{page_id}'
    response = requests.get(url, headers=HEADERS)

    if response.status_code == 200:
        print(f"✅ データベースが見つかりました")
        database_id = page_id
    else:
        # 子ブロックからデータベースを検索
        database_id = get_database_id_from_page(page_id)
        if not database_id:
            print("❌ このページからデータベースが見つかりません")
            print("確認: Notionでテーブル型データベースを作成し、右上のメニューから「Copy link to database」を選択してください")
            return

    print(f"✅ データベースID: {database_id[:8]}...")

    # セットアップ実行
    if setup_notion_database(database_id):
        # .env に保存
        env_file = os.path.join(os.path.dirname(__file__), '../../config/.env')
        with open(env_file, 'r') as f:
            env_content = f.read()

        if 'NOTION_DATABASE_ID=' not in env_content:
            with open(env_file, 'a') as f:
                f.write(f'NOTION_DATABASE_ID={database_id}\n')
            print(f"\n💾 NOTION_DATABASE_ID を .env に保存しました")

        print("\n🎉 セットアップが完了しました！")
    else:
        print("\n⚠️ セットアップ中にエラーが発生しました")

if __name__ == '__main__':
    main()
