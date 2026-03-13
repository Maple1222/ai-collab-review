# ai-collab-review

AI との対話履歴から **AI協働力** を分析し、日本語レポートを生成する Claude Code プラグイン。

**文脈を渡す力、探索を広げる力、対話を操舵する力、検証して採る力、AI環境を自分で進化させる力**——エンジニアに限らず、あらゆるAIユーザーの協働スタイルを診断する。

## 着想元: prompt-review

本プラグインは [tokoroten/prompt-review](https://github.com/tokoroten/prompt-review) から着想を得ています。

prompt-review は「**成果物ではなくプロンプトを見ることで、裏側にある意図や認識を指導できる**」という考え方に基づいたツールです。従来は成果物を見れば意図や認識がわかっていたのに、生成AIの普及でそれが難しくなった——だからプロンプトを見よう、という発想。AIとの対話からプロンプティングパターン・技術理解度・AI依存度を分析し、開発者の技術力を可視化するツールとして設計されています。

この「プロンプトに意図が埋まっている」という考え方が面白いと感じ、**エンジニア以外の一般ユーザーにも届くように** 評価軸を再設計したのが ai-collab-review です。

prompt-review がエンジニアの技術的な深さ（技術理解度、コード品質への意識、AI依存度等）を見るのに対して、ai-collab-review は職種を問わず「AIとどう協働しているか」の全体像を見ます。目的が異なるので、エンジニアの方は両方使ってみると違う角度の気づきが得られると思います。

データ収集スクリプト（`scripts/collect.py`）は、prompt-review の collect.py が持つ6ツール対応のデータ収集ロジックをお借りし、手動インポート対応等を追加しています。

## 評価フレームワーク

### 主プロフィール6軸

| 軸 | 見ていること |
|---|---|
| **目的設計力** | 何を作るのか、誰向けか、何をもって成功とするかを定める力 |
| **文脈供給力** | 背景・制約・素材・例を、必要なタイミングで渡す力 |
| **探索展開力** | 視点を広げる、複数案を出させる、別解を引き出す力 |
| **対話操舵力**（中核指標） | AIの返答を受けて、広げる・狭める・修正する・ピボットする力 |
| **検証・採択力** | 比べる、確かめる、捨てる、採る、統合する力 |
| **学習資産化力** | うまくいった進め方を再利用可能な資産に変える力 |

### 統制レイヤー（条件付き評価）

高リスク・不可逆・外部影響のある場面でのみ評価。クレデンシャル管理、デプロイ前確認、委任範囲の設計を見る。

### スコアリング

| スコア | ラベル |
|--------|--------|
| 0 | 未観測 |
| 1 | 芽がある |
| 2 | 時々できている |
| 3 | 安定している |
| 4 | 他者の参考になる |

## 対応データソース

### 自動収集（ローカルログ）

| ツール | ログ形式 |
|--------|---------|
| Claude Code（CLI / VS Code拡張） | JSONL（history.jsonl + プロジェクト別セッション） |
| GitHub Copilot Chat | SQLite（state.vscdb） |
| Cline | JSON（api_conversation_history.json） |
| Roo Code | JSON（Clineと同一構造） |
| Windsurf (Cascade) | テキスト（自動要約メモリ） |
| Google Antigravity | テキスト（ログファイル） |

### 手動インポート

| ソース | 取得方法 | ファイル形式 |
|--------|---------|------------|
| ChatGPT | Settings > Data controls > Export data | `conversations.json`（ZIP内） |
| Claude.ai | Settings > Privacy > Export data | `conversations.json`（ZIP内、リンク24h失効） |
| Gemini | Google Takeout > **マイ アクティビティ > Gemini Apps** | JSON（ZIP/TGZ内） |
| Markdown | Obsidian Vault 等の対話アーカイブ | `### **User** (timestamp)` 形式等 |
| その他 | テキストファイルにコピー&ペースト | `Human:` / `User:` プレフィックス |

> **Gemini注意**: Takeoutで「Gemini」カテゴリではなく「**マイ アクティビティ > Gemini Apps**」を選ぶこと。間違えると空のHTMLが出力される。

ディレクトリパスを渡せば、中のファイルを一括で読み込める:
```bash
/ai-collab-review ~/Obsidian/vault/ai_conversations/
```

## インストール

```bash
claude plugin add github:Maple1222/ai-collab-review
```

## 使い方

```bash
/ai-collab-review              # 全プロジェクト、過去30日（デフォルト）
/ai-collab-review 7            # 過去7日分
/ai-collab-review 0            # 全期間
/ai-collab-review yonshogen    # 特定プロジェクトのみ
/ai-collab-review yonshogen 30 # 特定プロジェクト × 過去30日分
```

手動インポートの場合:
```bash
/ai-collab-review ~/Downloads/conversations.json
```

レポートは `reports/ai-collab-review-YYYY-MM-DD.md` に出力されます。

### 大規模データの自動処理

2,000件を超えるメッセージがある場合、時間チャンクに分割してサブエージェント（`chunk-analyzer`）で並列分析し、結果を統合します。並列実行前にはユーザーに確認を取ります。

### データ収集の制約

collect.py はパフォーマンスとプライバシーのため、以下のサンプリング制限を適用します。全データの網羅的な分析ではなく、サンプリングされたデータに基づく評価です。

| 制限 | 値 |
|------|---|
| メッセージテキスト | 先頭500文字 |
| Claude Codeセッションファイル | 最新50件 |
| Claude Codeメッセージ/セッション | 100件 |
| Cline/Rooタスク | 最新20件 |
| Windsurfファイル | 最新20件 |
| Antigravityログ | 最新10件 |

また、自動収集ではユーザーメッセージのみを収集します（AIの応答は含まれません）。手動インポート（ChatGPT/Claude.ai/Gemini エクスポート）ではユーザー・AI双方のメッセージを含むため、より精度の高い分析が可能です。

## レポートの構成（12セクション）

1. **タイトルと要約** — 協働スタイルの全体像（単一スコアは出さない）
2. **データソースサマリー** — 検出ツール・メッセージ数・期間
3. **シークレット/リスク警告** — クレデンシャル検出時のみ
4. **仕事タイプの傾向** — 生成/分析/変換/対話/作業の5分類
5. **エピソードサマリー** — 代表的な作業セッション
6. **AI協働プロフィール** — 6軸のスコア・confidence・エビデンス引用
7. **統制レイヤー所見** — 条件付き評価
8. **強い協働パターン** — 再利用可能な行動パターン
9. **詰まりやすいパターン** — 改善機会（責める口調にしない）
10. **成長の軌跡** — 時系列変化
11. **次の2週間で試す小さな習慣** — 具体的な小さな行動
12. **総合所見** — 強みと次の一歩

## ファイル構成

```
ai-collab-review/
├── .claude-plugin/
│   └── plugin.json                # プラグインメタデータ
├── commands/
│   └── ai-collab-review.md       # /ai-collab-review コマンド
├── skills/
│   └── ai-collab-review/
│       ├── SKILL.md               # スキル定義（実行手順）
│       └── references/
│           ├── evaluation-framework.md  # 6軸+統制レイヤー評価基準
│           ├── report-template.md       # 12セクションレポートテンプレート
│           └── manual-import-guide.md   # 手動インポート詳細ガイド
├── agents/
│   └── chunk-analyzer.md         # 大規模データ並列分析エージェント
├── scripts/
│   └── collect.py                # データ収集スクリプト（自己完結型）
├── README.md
├── LICENSE
└── .gitignore
```

## 要件

- Claude Code（CLI または VS Code拡張）
- Python 3.10+
- SQLite3（GitHub Copilot Chat の解析に必要。他ツールのみなら不要）

## 謝辞

- [tokoroten/prompt-review](https://github.com/tokoroten/prompt-review) — 本プラグインの着想元。データ収集ロジックとレポート生成の設計思想を参考にしています。「成果物ではなくプロンプトを見る」という考え方を提唱し、本プラグインの出発点となりました。

## ライセンス

MIT
