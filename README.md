# 一都三県 営業リスト自動化ツール

一都三県 (東京・神奈川・埼玉・千葉) の営業リストを収集し、
Slack 承認フローを介してメール/問い合わせフォームに自動送信する一気通貫ツール。

広範な仕様のため、**段階的に実装**している。本 README は現在の実装状況を反映する。

> 法務・マナー面の注意
> - 収集データは **業者間 (B2B) の営業提案** 用途に限定してください。
> - 各 API / サイトの利用規約・robots.txt を必ず確認してください。
> - Serper (Google Maps) などのサードパーティ API の利用規約も遵守してください。

---

## 進捗 (STEP ロードマップ)

| STEP | 内容 | 状態 |
|------|------|------|
| 1 | 宅建業者タブ・東京都 (Playwright で Google Maps 収集) を Excel に出力 | **実装済** |
| 2 | 宅建業者タブを神奈川・埼玉・千葉に拡張 | 未着手 |
| 3 | 士業タブを追加 (司法書士/税理士/弁護士/行政書士) | 未着手 |
| 4 | 相続専門業者タブを追加 | 未着手 |
| 5 | 賃貸管理会社・保険代理店タブを追加 | 未着手 |
| 6 | 国交省・協会サイトの補完ソースを追加 | 未着手 |
| 7 | Slack Bot (Socket Mode) による承認 UI | 未着手 |
| 8 | メール送信 (SMTP / SendGrid 切替) | 未着手 |
| 9 | Playwright によるフォーム自動送信 | 未着手 |
| 10 | Excel ステータス列の自動更新 | 未着手 |

---

## セットアップ

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Playwright 用の Chromium を初回のみインストール:

```bash
playwright install chromium
```

> STEP 1 時点では `.env` に必須の値はありません (API キー不要)。

---

## ディレクトリ構成

```
.
├── README.md
├── requirements.txt
├── .env.example
├── config/
│   ├── areas.yaml           # 都県マッピング
│   └── limits.yaml          # タブ × 都県ごとの件数上限
├── src/
│   ├── http_client.py       # レート制御付き HTTP クライアント
│   ├── robots.py            # robots.txt 許可チェック
│   ├── extract_contacts.py  # HP から email / フォーム URL / 担当者名を抽出
│   ├── excel_io.py          # Excel (.xlsx) 多タブ UPSERT
│   ├── gmaps_playwright.py  # Playwright Chromium で Google Maps を操作
│   └── collectors/
│       ├── base.py          # Record / エリアマップ
│       └── takken_gmaps.py  # 宅建業者 × Google Maps (Playwright)
├── scripts/
│   └── run_collect.py       # 収集オーケストレーター
├── templates/outreach_ja.txt  # 送信用の日本語文案 (STEP 8 で使用)
└── data/
    └── sales_list.xlsx      # 成果物 (実行後に生成)
```

---

## STEP 1: 宅建業者タブ × 東京都 (Playwright で Google Maps 収集)

Google Maps を Playwright Chromium で操作して業者名・HP を取得し、
そのあと各 HP から email / 問い合わせフォーム URL / 担当者名を抽出する。
API キー不要。

### 使い方

```bash
# まず小さく動作確認 (5 件)
python scripts/run_collect.py --tab takken --areas tokyo --limit 5

# 本番 (100 件、limits.yaml の値を使用)
python scripts/run_collect.py --tab takken --areas tokyo

# トラブルシュート: ブラウザを可視化して目視確認
python scripts/run_collect.py --tab takken --areas tokyo --limit 5 --headful
```

### 出力

- `data/sales_list.xlsx` の「宅建業者」タブに 1 件 1 行で UPSERT
- UPSERT キー: `(都道府県, 業者名・事務所名)`
- 再実行しても重複行は追加されず、空→値の上書きのみ行う

### Excel スキーマ (全タブ共通・11 列)

| # | 列名 | 備考 |
|---|------|------|
| 1 | 都道府県 | 東京都 / 神奈川県 / 埼玉県 / 千葉県 |
| 2 | 業者名・事務所名 | Serper Places の title |
| 3 | 担当者名 | HP から抽出できた場合のみ |
| 4 | メールアドレス | 複数は `;` 区切り |
| 5 | 問い合わせフォームURL | 取得できた場合のみ |
| 6 | HP | Serper Places の website |
| 7 | 出典 | 例: `GoogleMaps:不動産` |
| 8 | ステータス | STEP 10 で更新 |
| 9 | 送信日時 | STEP 10 で更新 |
| 10 | 送信方式 | mail / form (STEP 10) |
| 11 | エラー | STEP 10 で更新 |

### CLI オプション

```
--tab takken               対象タブ (STEP 1 では takken のみ)
--areas tokyo              収集エリア (カンマ区切り)
--limit N                  各エリアの件数上限を上書き (0 で無制限)
--skip-contacts            HP からの連絡先抽出をスキップ (Serper のみ)
--output PATH              出力 xlsx (default: data/sales_list.xlsx)
--log-dir DIR              ログ出力先 (default: logs)
```

### 件数制御 (config/limits.yaml)

```yaml
takken:
  tokyo: 100
  kanagawa: 0     # STEP 2 で 100 に引き上げる
  saitama: 0
  chiba: 0
```

`0` のエリアは `--limit` 指定が無ければスキップされる。

### 実行ログ

`logs/run_YYYYMMDD_HHMMSS.log` に収集状況を記録する (.gitignore 対象)。

---

## 注意

- `data/sales_list.xlsx` は `.gitignore` で除外 (個人情報を含むため)
- Serper の Places API はプランに応じた月間クエリ上限があります
- HP からの連絡先抽出は robots.txt を尊重し、取得できないサイトはスキップ
