# 手動データインポートガイド

ローカルログの自動収集ができない場合（ChatGPT Web版、Claude.ai Web版、Gemini等）のデータ取得方法。

---

## ChatGPT エクスポート

### エクスポート手順
1. ChatGPT にログイン
2. Settings > Data controls > Export data
3. 「Export」をクリック
4. メールに届く ZIP をダウンロード
5. ZIP を展開し、中の `conversations.json` を使う

### データ構造（conversations.json）
```json
[
  {
    "title": "会話タイトル",
    "create_time": 1700000000.0,
    "update_time": 1700001000.0,
    "mapping": {
      "uuid-1": {
        "message": {
          "id": "msg-uuid",
          "author": {"role": "user"},
          "content": {
            "content_type": "text",
            "parts": ["ユーザーのメッセージ"]
          },
          "create_time": 1700000000.0
        }
      },
      "uuid-2": {
        "message": {
          "id": "msg-uuid",
          "author": {"role": "assistant"},
          "content": {
            "content_type": "text",
            "parts": ["AIの回答"]
          },
          "create_time": 1700000100.0
        }
      }
    }
  }
]
```

### 抽出ルール
- `mapping` 内の各エントリを走査
- `message` が `null` のエントリはスキップ（システムノード）
- `message.author.role === "user"` のみ抽出
- `message.content.parts` を結合してテキスト化（`content_type` が `"text"` のもの）
- `create_time` は **Unix秒**（ミリ秒ではない）。ISO 8601 に変換してタイムスタンプとする
- `title` をプロジェクト名として使う

### 注意点
- `mapping` はツリー構造（`parent`/`children`フィールドあり）だが、分析用には全メッセージをフラットに展開してよい
- DALL-E等の画像生成メッセージは `content_type` が `"text"` 以外の場合がある。テキスト以外はスキップ
- `author.role === "system"` のメッセージもスキップ

---

## Claude.ai エクスポート

### エクスポート手順（公式機能あり）
1. Claude.ai にログイン
2. Settings > Privacy > Export data
3. 「Export data」をクリック
4. **メールに届くダウンロードリンク（24時間で失効）** からZIPをダウンロード
5. ZIP 内の `conversations.json` を使う

### データ構造（conversations.json）
```json
[
  {
    "uuid": "c3ce82e9-e7f8-4925-a54f-b436fc6809da",
    "name": "会話タイトル",
    "created_at": "2025-08-21T10:38:16.293907Z",
    "updated_at": "2025-08-21T10:38:29.287745Z",
    "chat_messages": [
      {
        "uuid": "3e957f9f-85f9-4590-a29a-905064d97664",
        "text": "ユーザーのメッセージ",
        "sender": "human",
        "created_at": "2025-08-21T10:38:18.136525Z",
        "content": [
          {
            "type": "text",
            "text": "ユーザーのメッセージ"
          }
        ],
        "attachments": [],
        "files": []
      },
      {
        "uuid": "another-uuid",
        "text": "Claudeの回答",
        "sender": "assistant",
        "created_at": "2025-08-21T10:39:00.000000Z",
        "content": [
          {
            "type": "text",
            "text": "Claudeの回答"
          }
        ],
        "attachments": [],
        "files": []
      }
    ]
  }
]
```

### 抽出ルール
- トップレベルは会話の配列
- 各会話の `chat_messages` 配列を走査
- `sender === "human"` のみ抽出
- `text` フィールドをメッセージ本文とする
- `created_at` はISO 8601形式
- `name` をプロジェクト名として使う

### 注意点
- ダウンロードリンクは**24時間で失効**する
- ZIP内には `conversations.json`、`users.json`、`projects.json` が含まれる
- `users.json` に個人情報（氏名・メールアドレス）が含まれるため、共有時は注意

---

## Gemini エクスポート

### エクスポート手順（Google Takeout）
1. https://takeout.google.com/ にアクセス
2. 「すべての選択を解除」で全データの選択を外す
3. **「マイ アクティビティ」** セクション内の **「Gemini Apps」** を選択する
4. 「次のステップ」→ エクスポートを作成
5. メールにダウンロードリンクが届く（処理に2時間〜数日かかる場合がある）
6. ZIP/TGZ内のJSONファイルを使う

> **重要**: 「Gemini」カテゴリ（Gemini Gems用）ではなく、**「マイ アクティビティ」内の「Gemini Apps」** を選ぶこと。間違えると空のHTMLが出力される。

### データ構造
```json
{
  "id": "conversation-id",
  "createdTime": "2025-01-01T00:00:00Z",
  "lastModifiedTime": "2025-01-01T01:00:00Z",
  "messages": [
    {
      "role": "user",
      "parts": [
        {"text": "ユーザーのメッセージ"}
      ]
    },
    {
      "role": "model",
      "parts": [
        {"text": "Geminiの回答"}
      ]
    }
  ]
}
```

### 抽出ルール
- `messages` 配列を走査
- `role === "user"` のみ抽出
- `parts` 配列内の `text` フィールドを結合してテキスト化
- `createdTime` をタイムスタンプとする（ISO 8601形式）

### 注意点
- エクスポート処理に時間がかかることがある（大量データで数日）
- `isThought: true` のメッセージはモデル内部の思考プロセスなのでスキップ

---

## Markdown形式の対話ファイル

ChatGPTやClaude.aiの対話をMarkdownにエクスポートするツール（Obsidian連携等）で出力されたファイルにも対応する。

### 形式1: ヘッダー付きMarkdown（ChatGPT / Claude.ai エクスポーター）

```markdown
# 会話タイトル

- **作成日時**: 2025-06-24 02:18:15
- **ソース**: ChatGPT / Claude

## 対話内容

### **User** (2025-06-24 02:18:16)

ユーザーのメッセージ

---

### **Assistant** (2025-06-24 02:19:27)

AIの回答

---
```

### 抽出ルール
- `### **User**` で始まるセクションのみ抽出
- 括弧内のタイムスタンプ `(YYYY-MM-DD HH:MM:SS)` を取得
- `---` で区切られた次のセクションまでがメッセージ本文
- `### **Claude**` / `### **Assistant**` / `### **ChatGPT**` はAI側なのでスキップ

### 形式2: プレフィックス付きテキスト

以下のプレフィックスで話者を判定:
- ユーザー: `Human:`, `User:`, `私:`, `Q:`, `質問:`, `> ` (引用符)
- AI: `Assistant:`, `AI:`, `Claude:`, `ChatGPT:`, `A:`, `回答:`

### フォールバック
プレフィックスがない場合は、交互の発話として解釈（奇数行=ユーザー、偶数行=AI）。

---

## ディレクトリ入力

ファイルパスの代わりにディレクトリパスが渡された場合:

1. ディレクトリ内の全ファイルを走査（`.json`, `.md`, `.txt`）
2. 各ファイルのフォーマットを自動判定
3. すべてのファイルからユーザーメッセージを抽出・結合

これにより、Obsidian Vault のような対話アーカイブディレクトリを一括分析できる。

---

## 正規化

どのソースから読み取っても、最終的に以下のJSON構造に正規化する:

```json
{
  "summary": {
    "total_messages": 100,
    "detected_tools": ["ChatGPT（手動インポート）"],
    "filter_days": null,
    "filter_project": null,
    "collected_at": "2026-03-13 12:00 UTC",
    "import_method": "manual"
  },
  "sources": [
    {
      "tool": "ChatGPT（手動インポート）",
      "status": "インポート済み",
      "messages": [
        {
          "text": "メッセージ本文",
          "timestamp": "2025-01-01 00:00",
          "project": "会話タイトル"
        }
      ],
      "period": "2025-01-01 〜 2025-03-01"
    }
  ],
  "project_stats": {},
  "secret_warnings": []
}
```

この構造により、自動収集と手動入力で同じ分析パイプラインを使える。

---

## ユーザーへの案内テンプレート

collect.py が見つからず、ファイルパスも指定されていない場合の案内:

```
AI対話履歴のデータが必要です。以下のいずれかの方法でデータを用意してください:

1. **ChatGPT**: Settings > Data controls > Export data でエクスポートし、
   ZIP 内の `conversations.json` のパスを教えてください。

2. **Claude.ai**: Settings > Privacy > Export data でエクスポートし、
   ZIP 内の `conversations.json` のパスを教えてください。
   （ダウンロードリンクは24時間で失効します）

3. **Gemini**: Google Takeout (https://takeout.google.com/) で
   「マイ アクティビティ」>「Gemini Apps」をエクスポートしてください。
   ※「Gemini」カテゴリではなく「Gemini Apps」を選ぶこと

4. **Markdown/テキスト**: 対話をMarkdownやテキストファイルに保存し、
   そのパス（ファイルまたはディレクトリ）を教えてください。
   Obsidian Vault等のディレクトリも一括で読み込めます。

例:
  /ai-collab-review ~/Downloads/conversations.json
  /ai-collab-review ~/Obsidian/vault/ai_conversations/
```
