# tenki — 松山周辺の降水区分（静的アプリ）

HTML/CSS とブラウザー標準 JavaScript のみで動きます。**本番の Python API・Node サーバーは不要**です。ブラウザーから気象庁の公開 JSON/PNG を匿名 CORS GET で取得し、canvas で表示区分を読み取ります。外部ライブラリー、APIキー、位置情報権限は使いません。

## ビルド・ローカル確認

Node.js 22以上（テスト／ファイルコピー用。本番ランタイムではありません）：

```sh
npm ci
npm test
npm run build
# dist/ の4ファイルが静的公開用成果物
python3 -m http.server 8000 --bind 127.0.0.1 --directory dist
# http://127.0.0.1:8000
```

この標準静的サーバーはローカル確認専用です。アプリ独自のHTTPサーバーや `/api/rain` はありません。`file://` ではなく HTTP(S) で開いてください。すべてのアセットとモジュール参照は相対パスなので、カスタムドメインのルートでも `/tenki/` のようなサブパスでも配信できます。`dist/` を GitHub Pages 等へ配置できますが、公開 workflow・DNS・Pages設定の変更はこの PR に含めません。

ブラウザーテスト（JMA応答はすべてオフラインのモック）：

```sh
python3 -m venv .venv
.venv/bin/pip install -r requirements-lock.txt
.venv/bin/python -m playwright install chromium
npm run build
.venv/bin/python -m pytest -q
# インストール済み Chromium を使う場合：
# TENKI_CHROMIUM=/usr/bin/chromium .venv/bin/python -m pytest -q
```

Node の共有ロジックテストは時刻・座標・境界・パレット・5分キャッシュ・取得失敗・HTTP検証・容量制限・timeout・直列化を確認します。Playwright はビルド済みの静的ファイルだけを配信して、モバイル、サブパス、匿名クロスオリジン取得、更新失敗、CORS拒否と canvas `SecurityError` を確認します。Python/Pillow/Playwright はテスト専用で、推移依存も固定済みです。CIも静的ビルドと同じオフラインテストを実行し、成功時に `tenki-static` artifact（7日保持）を添付します。公開処理は行いません。

## データと表示

初期地点は松山の代表点 33.84 N, 132.77 E。対象は緯度 33.65–34.05、経度 132.55–133.0 の矩形で、市境ではありません。利用者が入力した座標のみをローカル計算に使い、気象庁には選択タイル番号だけを送信します。背景地図なしの z10 単一タイルと選択ピクセルを表示します。選択タイルには矩形外の画素も含まれます。

- 解析 index: https://www.jma.go.jp/bosai/jmatile/data/nowc/targetTimes_N1.json
- 予測 index: https://www.jma.go.jp/bosai/jmatile/data/nowc/targetTimes_N2.json
- PNG: `https://www.jma.go.jp/bosai/jmatile/data/nowc/{basetime}/none/{validtime}/surf/hrpns/10/{x}/{y}.png`

`static/core.js` の `snapshot()` が検証済みの時刻、区分と上下限、出典 URL、取得時刻、タイル・ピクセル情報を返します。対象時刻は index に実在するエントリーだけから選び、予測は0–60分・5分刻みの指定が存在しなければエラーです。UTC14桁の basetime/validtime と ISO UTC取得時刻をメモリー内に保持し、UIはJST表示します。永続保存はありません。基準時刻が15分超なら古いと表示し、表示中も30秒ごとに鮮度だけをローカル再計算します。このタイマーは通信しません。予測の基準時刻は将来の実測時刻ではありません。

代表点は tile 889/409, pixel 168/154。元プロダクトは陸上の現在〜30分が250m、35〜60分は1kmの情報です。Web Mercator PNG の画素はネイティブ250m格子そのものではありません（松山 z10 は約127m/画素）。画像の表示区分を抽出し、元 GRIB の精密値は復元しません。取得上限z10、UIのz11〜14は引き伸ばしです。

PNG RGB と区分（下限を含み上限を含まない、mm/h）：

| RGB | 区分 |
| --- | --- |
| 242,242,255 | [0,1) |
| 160,210,255 | [1,5) |
| 33,140,255 | [5,10) |
| 0,65,255 | [10,20) |
| 250,245,0 | [20,30) |
| 255,153,0 | [30,50) |
| 255,40,0 | [50,80) |
| 180,0,104 | [80,∞) |

黄色は SVG 凡例の255,245,0ではありません。これは表示凡例に基づく区分であり元データの丸め精度を保証しません。透明は `transparent_unclassified`、未知色・半透明は `unknown_color`、欠けた index エントリーや HTTP/JSON/PNG/CORS/canvas の異常はエラーです。いずれもゼロ降水に変換しません。`hrpns_nd` 別GeoJSONの範囲・分類と市町村マスクは未検証・未実装です。

## 更新・通信・検証限界

初期表示では通信せず、手動更新のみです。取得は共有1スロット・各10秒・最大2MB、リダイレクト禁止、自動リトライなし。URLは固定 JMA origin と検証済み時刻・限定範囲のタイル番号から構築します。PNG署名・事前寸法・デコード後寸法・HTTP状態・content typeも検証します。メモリーキャッシュは最大32パスで、成功と通信失敗を各5分保持します。古い成功で新しい失敗を隠さず、更新失敗時は前回結果を非表示にします。ページ再読込ではキャッシュが消えます。複数タブ・複数利用者を横断するレート制御はありません。全国取得・常駐ジョブ・Actions collector・スケジュールはありません。

fetch は `mode: cors`, `credentials: omit`、独自ヘッダーなしの単純 GET です。PNGをCORS fetchしてBlobからcanvasへ描画し、SecurityErrorもエラーとして扱います。CORS回避プロキシはありません。

独立したクラウド環境で、`Origin: https://tenki.moukaeritai.work` を付けた公開 N1 JSON と hrpns PNG の匿名 GET がHTTP200、`Access-Control-Allow-Origin: *` を返すことが確認されました（2026-10-26、基準20261026081500、PNG714bytes・256×256）。観測された Cache-Control は index max-age=60、時刻付きPNG max-age=86400。これはヘッダーの証拠であり、実際の公開ドメインでのブラウザー動作確認ではありません。提供元のCORS設定変更、ネットワーク制限時は取得できません。公開環境のライブ確認は保留です。

以前の Library 証拠ZIP転送は対応手順と1回の再試行でも失敗し、この実装環境のJMA直接HTTPもプロキシ403でした。再試行や迂回は行っていません。テストPNGは合成画像で、実PNGパレットの再検証を完了したとは主張しません。

出典：[気象庁](https://www.jma.go.jp/bosai/nowc/)／本アプリが加工。[利用規約](https://www.jma.go.jp/jma/kishou/info/coment.html)。防災判断には気象庁の最新情報をご確認ください。

[tenki.jp](https://tenki.jp/radar/map/) と [Yahoo!天気](https://weather.yahoo.co.jp/weather/zoomradar/?pref=38) は通常の外部リンクのみ。タイル転載・自動収集・iframe・Yahoo API連携はありません。リンク先で地域や時間を確認してください。
