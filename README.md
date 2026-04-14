# 宅建業者リスト収集ツール (MVP)

首都圏(東京・神奈川・埼玉・千葉)の宅建業者情報を収集し、「同業者から仕入れ案件をもらう」ための営業リストを CSV で作成するツールです。

> **はじめに読むべき法務・マナー面の注意**
> - 本ツールは SUUMO / athome / HOME'S などの業者一覧を参照します。**各サービスの利用規約 / robots.txt を実行前に必ずご自身で確認**してください。規約で自動収集が制限されている場合は、`--source kokkosho`(予定)や都道府県の公開名簿に切替えてください。
> - アクセス間隔は 3 秒 + ジッターで自動制御しています。短縮は相手方のサーバに負担となるため行わないでください。
> - 収集データは **業者間 (B2B) の仕入れ提案** の用途に限定してください。消費者向けの大量メール送信は特定電子メール法の対象となります。
> - 取得データの第三者提供・再配布は禁止です。

## セットアップ

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## ディレクトリ構成

```
.
├── README.md
├── requirements.txt
├── config/areas.yaml          # 対象エリア (首都圏4都県)
├── src/                       # ライブラリ
│   ├── http_client.py         # レート制御付き HTTP クライアント
│   ├── robots.py              # robots.txt 許可チェック
│   ├── portal_suumo.py        # SUUMO アダプタ
│   ├── portal_athome.py       # athome アダプタ
│   ├── portal_homes.py        # HOME'S アダプタ
│   ├── extract_contacts.py    # HP から email / 問合せフォーム URL 抽出
│   └── storage.py             # CSV 読み書き(UPSERT)
├── scripts/
│   ├── run_collect.py         # 業者リスト収集(MVP のメイン)
│   └── run_send_mail.py       # 一斉メール送信(後日実装のスタブ)
├── templates/outreach_ja.txt  # 送信用の日本語文案
└── data/
    ├── brokers.csv            # 成果物 (実行後に生成)
    └── brokers_sample.csv     # サンプル 3 行
```

## 使い方

### 1. まず小さく動かす(推奨)

```bash
python scripts/run_collect.py --areas tokyo --source suumo --limit 5
```

- 5 社分だけ収集して `data/brokers.csv` に追記します
- 出力は UTF-8 (BOM 付き)。Excel で文字化けせず開けます

### 2. 本番収集(首都圏 4 都県 × 3 ソース)

```bash
python scripts/run_collect.py \
    --areas tokyo,kanagawa,saitama,chiba \
    --source suumo,athome,homes
```

### 3. 出力 CSV フォーマット (5 列)

| 列 | 値の例 |
|---|---|
| 会社名 | 株式会社〇〇不動産 |
| 担当者名 | 代表取締役 山田太郎 (取得できなければ空) |
| HPリンク | https://example.co.jp/ |
| メールアドレス | info@example.co.jp (複数なら `;` 区切り、無ければ空) |
| 問い合わせフォームリンク | https://example.co.jp/contact/ |

キーは「会社名 + HP リンク」。再実行時は重複行を UPSERT します。

## 将来対応: メール一斉送信

`scripts/run_send_mail.py` は現在スタブです。次回以降に以下を実装予定:

- 入力: `data/brokers.csv` + `templates/outreach_ja.txt` + `.env` の SMTP 情報
- 1 通ずつ **個別 To:** で送信(BCC 一斉送信は行わない)
- 送信間隔: 最短 5 秒/通 + ジッター
- `List-Unsubscribe` ヘッダを付与
- `--dry-run` で実送信せず確認可能
- 送信履歴は `data/send_log.csv` に別ファイルで記録

### 送信前の注意

- 送信先は **業者 (B2B)** に限定してください
- 自社の宅建免許番号・住所・連絡先を本文末に必ず明記
- 受信拒否の意思表示を受けた宛先は `data/brokers.csv` から除外する運用としてください

## 実行ログ

実行するたびに `logs/run_YYYYMMDD_HHMMSS.log` に取得件数・スキップ理由を記録します (`.gitignore` 対象)。

## 注意: 実サイトアクセスなしのスキーマ確認

`data/brokers_sample.csv` に 3 行のダミーデータがあります。ネットワーク不要で取り込み挙動 (Excel/スプレッドシート) を確認するのに使ってください。
