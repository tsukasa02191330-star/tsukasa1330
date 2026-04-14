"""メール一斉送信スクリプト (後日実装予定のスタブ)。

設計メモ (実装時に参照):
    - 入力: data/brokers.csv + templates/outreach_ja.txt + .env(SMTP_HOST/PORT/USER/PASS, FROM_EMAIL, FROM_NAME)
    - 動作:
        1. CSV の「メールアドレス」列が空でない行を抽出
        2. 1 通/5 秒 + ジッター で順次送信 (BCC 一斉送信はしない)
        3. 本文末に自社の宅建免許番号・住所・連絡先 を必ず付記
        4. List-Unsubscribe ヘッダを付与
        5. 送信履歴は data/send_log.csv に追記 (会社名, email, 送信日時, 成否, エラー)
    - フラグ:
        --dry-run       実送信せず宛先と本文だけ表示
        --limit N       N 件だけ送信
        --resume        既に送信済み(send_log.csv)の宛先をスキップ

法務・マナー(実装前に要確認):
    - 送信先は宅建業者 (B2B) に限定。消費者への大量メールは特定電子メール法の対象
    - 宛先の事前同意がないメールは、先方の判断で迷惑メール扱いになる可能性がある
    - 送信前に自社の宅建協会・顧問弁護士にルール確認を推奨
"""

from __future__ import annotations


def main() -> int:
    print(
        "[未実装] scripts/run_send_mail.py は後日実装予定です。\n"
        "        - 入力: data/brokers.csv + templates/outreach_ja.txt + .env (SMTP 情報)\n"
        "        - 挙動: メールアドレス列が埋まっている行に 1 通/5 秒 で個別送信 (BCC しない)\n"
        "        - --dry-run で実送信せず確認、--resume で送信済みスキップを予定\n"
        "        本ファイル先頭のドックストリングに設計メモがあります。"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
