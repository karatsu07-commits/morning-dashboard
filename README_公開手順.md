# 朝のダッシュボード — セットアップ手順

毎朝 中国時間 8:00 に自動更新され、URLで見られるダッシュボード。
GitHubの作業は **自宅または携帯回線** から行えばOK（会社Wi-Fiは不要）。

---

## このフォルダのファイル

| ファイル | 役割 |
|---|---|
| `template.html` | デザイン（見た目）のひな形。ここを直すと見た目が変わる |
| `build.py` | 為替・ニュースを取得して `index.html` を生成する処理 |
| `requirements.txt` | build.py が使うライブラリの一覧 |
| `index.html` | 実際に表示されるページ（build.py が自動生成） |
| `.github/workflows/update.yml` | 毎朝8:00に自動実行する予約設定 |
| `data/history.json` | 為替の履歴（自動で貯まる。将来のグラフ用） |

---

## ステップ1：ファイルをGitHubに載せる

### A. ソースファイルをアップロード
1. github.com で自分の `morning-dashboard` リポジトリを開く
2. **Add file → Upload files**
3. 次の4つをドラッグして追加：
   - `build.py` / `template.html` / `requirements.txt` / `index.html`
4. 下の「**Commit changes**」をクリック

### B. 自動更新の設定ファイルを追加（フォルダ付きなので別作業）
1. **Add file → Create new file**
2. ファイル名の欄に **そのまま** こう入力（スラッシュでフォルダが自動作成される）：
   ```
   .github/workflows/update.yml
   ```
3. 本文に、ローカルの `.github/workflows/update.yml` の中身をコピペ
4. 「**Commit changes**」

---

## ステップ2：自動更新をオンにして動作確認
1. リポジトリ上部の **Actions** タブを開く（初回は「I understand…」で有効化）
2. 左の **Update dashboard** をクリック → 右の **Run workflow** → 緑のボタンで今すぐ実行
3. 1〜2分待つと処理が完了し、`index.html` が最新データで更新される
4. 公開URL（`https://<ユーザー名>.github.io/morning-dashboard/`）を開いて、実データが出ていればOK

これ以降は **毎朝 中国時間 8:00 に自動実行**されます。
（※GitHubの混雑時は数分〜十数分ずれることがあります＝仕様）

---

## うまく動かないとき
- **Actionsが赤×（push失敗）**：Settings → Actions → General →
  「Workflow permissions」を **Read and write permissions** にして保存 → もう一度 Run workflow
- **ページが古いまま**：Pagesの反映に1〜2分かかる。ブラウザの更新（再読み込み）を試す
- **ニュースが「取得できませんでした」**：一時的な失敗。翌朝の自動実行で回復（ページは壊れない）

---

## キーワードを変えたいとき
`build.py` の上のほうにある `FEEDS` を編集すると、ニュースの検索語を変えられます。
例：半導体メーカー名を足す、特定の規制ワードを足す など。

---

## 次のステップ（第2弾）
- 金属（ニッケル・アルミ・モリブデン）・原油・SOX を実データ化
- WeChat配信（毎朝、手元に要約を届ける）
- 春節以外のカレンダー・展示会の自動表示
- メモの「書いて保存」機能
