# Makeシナリオ構築手順書

`rss_collector.py` が送信するWebhookペイロードを受け取り、Claude APIで日本語訳・要約し、Notionデータベースへ登録するMakeシナリオの構築手順です。Makeのシナリオ自体はWeb UI上でモジュールを組み立てる必要があるため、コードではなくこの手順書として提供します。

## 全体構成

```
[1] Custom Webhook (トリガー)
        ↓
[2] HTTP - Anthropic Messages API を呼び出し(翻訳・要約)
        ↓
[3] JSON - レスポンスをパース
        ↓
[4] Notion - データベースへ新規ページを作成
```

## モジュール1: Custom Webhook

1. Make で新規シナリオを作成し、最初のモジュールに **Webhooks > Custom webhook** を選択。
2. 「Add」で新規Webhookを作成し、生成されたURLをコピー。
3. `リサーチ/config/.env` の `MAKE_WEBHOOK_URL` にこのURLを設定する。
4. `rss_collector.py` を一度実行し、Webhookにテストデータを送信して「Redetermine data structure」でペイロード構造を確定させる。

**受信ペイロード構造:**

| フィールド | 内容 |
|---|---|
| `source_id` | 媒体ID(例: `aljazeera`) |
| `source_name` | 媒体名(例: `Al Jazeera`) |
| `title` | 記事タイトル(原文) |
| `link` | 記事URL |
| `published` | 公開日時(原文表記) |
| `summary` | 記事概要(原文、先頭1000文字) |
| `collected_at` | 収集日時(ISO8601, UTC) |

## モジュール2: HTTP - Anthropic Messages API 呼び出し

1. **HTTP > Make a request** モジュールを追加。
2. 設定:
   - URL: `https://api.anthropic.com/v1/messages`
   - Method: `POST`
   - Headers:
     - `x-api-key`: Claude APIキー(Makeの「Add」でキーチェーンに保存し、シナリオに直接書き込まない)
     - `anthropic-version`: `2023-06-01`
     - `content-type`: `application/json`
   - Body type: `Raw` / `JSON`
   - Body例:
     ```json
     {
       "model": "claude-sonnet-5",
       "max_tokens": 1024,
       "messages": [
         {
           "role": "user",
           "content": "以下は{{1.source_name}}の記事です。日本の主要メディアが報じない地政学的視点を意識し、次のJSON形式のみで出力してください(前後に説明文を付けないこと): {\"title_ja\": \"日本語訳タイトル\", \"summary_ja\": \"3〜4文の日本語要約\"}\n\nタイトル: {{1.title}}\n概要: {{1.summary}}"
         }
       ]
     }
     ```
3. Claude APIキーはMakeの接続(Connection)機能で管理し、シナリオ内にハードコーディングしない。

## モジュール3: JSON - レスポンスをパース

1. **JSON > Parse JSON** モジュールを追加。
2. パース対象: モジュール2のレスポンスの `content[0].text`(Claudeが出力したJSON文字列)。
3. これにより `title_ja` / `summary_ja` を後続モジュールで変数として利用可能にする。

## モジュール4: Notion - データベースへ登録

1. 事前にNotion側で以下の列を持つデータベースを作成し、MakeとNotionの連携(Integration)を許可しておく。

   | 列名 | 型 |
   |---|---|
   | タイトル(和訳) | タイトル(Title) |
   | タイトル(原文) | テキスト |
   | 媒体 | セレクト(Al Jazeera / TRT World / WION / SCMP / Xinhua / The Diplomat / RT) |
   | 要約(和訳) | テキスト |
   | 公開日時 | テキスト |
   | 記事URL | URL |
   | 収集日時 | 日付 |

2. **Notion > Create a Database Item** モジュールを追加し、上記列に各モジュールの出力値をマッピングする。

## 動作確認

1. `リサーチ/src/collectors/rss_collector.py` を手動実行し、Notionデータベースに日本語訳された記事が登録されることを確認する。
2. 問題なければ [crontab設定](#crontab設定) に従い自動実行を有効化する。

## crontab設定

`crontab -e` で以下を追加(2時間おきに実行する例。パスは環境に合わせて調整):

```
0 */2 * * * cd /Users/saitoujunji/Desktop/my-claude-project/new-silkroad-agent/リサーチ && ./.venv/bin/python src/collectors/rss_collector.py >> data/processed/collector.log 2>&1
```
