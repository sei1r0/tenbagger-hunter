import os
import io
import re
import requests
import pandas as pd
from urllib.parse import urljoin

# JPXの東証上場銘柄一覧ページ（親ページ）
PAGE_URL = "https://www.jpx.co.jp/markets/statistics-equities/misc/01.html"
OUTPUT_CSV = os.path.join(os.path.dirname(__file__), "..", "data", "jpx_stocks.csv")

def update_jpx_stock_list():
    print("[INFO] JPX銘柄一覧ページからダウンロードURLを探索中...")
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }

    try:
        page_res = requests.get(PAGE_URL, headers=headers, timeout=20)
        page_res.raise_for_status()
    except Exception as e:
        print(f"[ERROR] JPX親ページの取得に失敗しました: {e}")
        return

    # data_j.xls へのリンクを抽出
    match = re.search(r'href="([^"]*data_j\.xls[^"]*)"', page_res.text)
    if not match:
        # 見つからない場合は旧仕様の別パターンを探索
        match = re.search(r'href="([^"]*data_j\.[a-z]+)"', page_res.text)

    if not match:
        print("[ERROR] ページ内から銘柄一覧ファイルのリンクを検出できませんでした。")
        return

    file_rel_url = match.group(1)
    file_url = urljoin(PAGE_URL, file_rel_url)
    print(f"[INFO] 最新のファイルURLを特定: {file_url}")

    print("[INFO] 銘柄一覧ファイルをダウンロード中...")
    file_res = requests.get(file_url, headers=headers, timeout=30)
    if file_res.status_code != 200:
        print(f"[ERROR] ファイルのダウンロードに失敗しました (Status: {file_res.status_code})")
        return

    # Excelパース
    try:
        df = pd.read_excel(io.BytesIO(file_res.content), dtype=str)
    except Exception as e:
        print(f"[ERROR] Excelの読み込みに失敗しました: {e}")
        return

    df.columns = [str(c).strip() for c in df.columns]

    target_cols = {
        "コード": "code",
        "銘柄名": "name",
        "市場・商品区分": "market",
        "33業種区分": "sector"
    }
    
    # 存在確認
    if not all(col in df.columns for col in target_cols.keys()):
        print(f"[ERROR] 必要な列名が見つかりません。現在の列: {list(df.columns)}")
        return

    df = df[list(target_cols.keys())].rename(columns=target_cols)

    # 内国株式全銘柄（プライム、スタンダード、グロース）のみ抽出
    valid_markets = [
        "プライム（内国株式）",
        "スタンダード（内国株式）",
        "グロース（内国株式）"
    ]
    df_filtered = df[df["market"].isin(valid_markets)].copy()
    df_filtered["market"] = df_filtered["market"].str.replace("（内国株式）", "", regex=False)
    df_filtered["code"] = df_filtered["code"].astype(str).str.strip()

    os.makedirs(os.path.dirname(OUTPUT_CSV), exist_ok=True)
    df_filtered.to_csv(OUTPUT_CSV, index=False, encoding="utf-8")
    
    print(f"[INFO] 東証全銘柄の母集団保存完了: {len(df_filtered)} 銘柄 -> {OUTPUT_CSV}")

if __name__ == "__main__":
    update_jpx_stock_list()