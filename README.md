# tenki — 松山周辺の降水区分

Python 3.12 の標準 HTTP サーバー + Pillow、静的 HTML/CSS/JavaScript の小さなローカルアプリです。JMA への HTTP はサーバー側で行い、ブラウザー CORS に依存しません。実行時のブラウザー自動操作・API キー・位置情報権限は不要です。

```sh
python3 -m venv .venv
.venv/bin/pip install -r requirements-lock.txt
.venv/bin/python app.py
# http://127.0.0.1:8000
```

テスト（すべてオフライン。Playwright はテスト専用）：

```sh
.venv/bin/python -m playwright install chromium
.venv/bin/python -m pytest -q
```

CI は固定バージョンの依存と Chromium を導入し、オフライン単体・モバイル UI テストを実行します。`requirements-lock.txt` は推移依存も固定しています。サーバーは localhost のみで待受けます。デプロイ用サーバーではありません。

## 表示・API

初期地点は松山の代表点 33.84 N, 132.77 E。対象は緯度 33.65–34.05、経度 132.55–133.0 の矩形で、市境ではありません。利用者が入力した座標のみを使います。背景地図なしの z10 単一タイルと選択ピクセルを表示します。矩形で検証した選択地点を含むタイルは矩形外の画素も含みます。

`GET /api/rain?lat=33.84&lon=132.77&mode=analysis&lead=0`

`mode=forecast&lead=5` など 0–60 分・5分刻みも選べます。指定時間が index に存在しない場合はエラーです。UTC 14桁の basetime/validtime、観測基準時刻、取得時刻、鮮度、区分上下限（下限含む・上限含まない、mm/h）、タイル・ピクセル、出典 URL、表示 PNG を JSON で返します。時刻の保存・伝送は UTC、UI は JST。解析基準が15分超なら古いと表示します。予測の「観測時刻」は解析基準であり将来の実測ではありません。

JMA index:
- https://www.jma.go.jp/bosai/jmatile/data/nowc/targetTimes_N1.json （解析）
- https://www.jma.go.jp/bosai/jmatile/data/nowc/targetTimes_N2.json （予測）

PNG: `https://www.jma.go.jp/bosai/jmatile/data/nowc/{basetime}/none/{validtime}/surf/hrpns/10/{x}/{y}.png`。時刻は index の実在エントリーから選択します。代表点は tile 889/409, pixel 168/154。URL は固定 JMA origin と検証済みパラメーターで構築し、任意 URL プロキシは提供しません。

元プロダクトは陸上の現在〜30分が250m、35〜60分は1kmの情報です。Web Mercator PNG の画素はネイティブ250m格子そのものではありません（松山 z10 は約127m/画素）。このアプリは画像上の表示区分を抽出し、元 GRIB の精密値は復元しません。z10 が取得上限で、UI の z11〜14 は単なる拡大です。

PNG RGB と区分：242,242,255 → [0,1)、160,210,255 → [1,5)、33,140,255 → [5,10)、0,65,255 → [10,20)、250,245,0 → [20,30)、255,153,0 → [30,50)、255,40,0 → [50,80)、180,0,104 → [80,∞) mm/h。黄色は SVG 凡例の255,245,0ではありません。これらは表示凡例に基づく区分で、元の丸め精度を保証しません。

透明は `transparent_unclassified`、未知の色・半透明は `unknown_color`。欠測や HTTP/JSON/PNG の異常は error。どれもゼロ降水に変換しません。`hrpns_nd` の別 GeoJSON の範囲・分類は未検証で未実装、市町村マスクも保留です。透明から「雨なし」「欠測域」を断定できません。

## 更新・利用条件・検証限界

手動更新のみ。JMA の5分更新に合わせ、成功・失敗ともパス単位に5分キャッシュします。失敗を古い成功で隠さず、UI の前回結果を非表示にします。全国取得・定期ジョブはありません。時刻・座標・PNG署名/寸法・content type・HTTP状態・最大2MB・10秒timeoutを検証します。キャッシュはメモリーのみ・再起動で消去されます。

出典：[気象庁](https://www.jma.go.jp/bosai/nowc/)、[利用規約](https://www.jma.go.jp/jma/kishou/info/coment.html)。本アプリが加工して表示します。防災用途の正確性・可用性は保証しません。

[tenki.jp](https://tenki.jp/radar/map/) と [Yahoo!天気](https://weather.yahoo.co.jp/weather/zoomradar/?pref=38) は通常の外部リンクのみ。タイルの転載・自動収集・iframe・Yahoo API連携はしません。リンク先で地域や時間を確認してください。

提供された Library 証拠 ZIP は対応手順と1回の再試行でも転送失敗しました。この環境の JMA 直接 HTTP もネットワークプロキシの403で遮断され、ライブ smoke と実 PNG fixture 検証は未完了です。テストの PNG は明示的な合成パレット画像で、実データ取得の成功を証明しません。運用前にネットワークが許可された環境で上記 index と1タイルを確認してください。標準 CI はライブ取得に依存しません。
