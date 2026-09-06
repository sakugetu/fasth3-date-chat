# FastH3 Date Chat

ローカルLLMが作る日本語の二択会話と、FastH3の短い動画を組み合わせた、実験的な会話ゲーム用スターターです。

プレイヤーは画面上の二択を選び、相手との会話を進めます。LM Studioを使うと返答と次の選択肢が毎回生成され、FastH3対応のComfyUIを接続すると、その返答を話す短い動画も生成されます。

このリポジトリは完成品ではなく、会話ゲームへ改造するための最小構成です。モデル本体、会話履歴、個別に作った設定、生成動画、生成ログは同梱していません。

## 最初に：利用モードごとの設定

`run_full.bat` を実行するだけで、LM StudioやFastH3自体が自動導入されるわけではありません。デモ以外を使う場合は、先に外部アプリとモデルを用意してください。

| 利用したい機能 | 事前に必要な設定 |
|---|---|
| UIと固定会話だけ試す | 追加設定なし。`run_demo.bat` または `run_demo.sh` を実行 |
| AIによる会話と二択 | LM Studioへチャットモデルをロードし、Local Serverを開始 |
| AI会話 + FastH3動画 | 上記のLM Studio設定に加え、FastH3対応ComfyUI、モデル4点、必要ノード、キャラクター参照画像を用意 |

初回は次の順で確認すると、問題の場所を切り分けやすくなります。

1. デモモードで画面が開くことを確認します。
2. LM Studioを起動し、開始画面の「接続を確認」で会話APIを確認します。
3. ComfyUIを起動し、開始画面で映像を「FastH3」にして接続先を確認します。
4. キャラクター参照画像を選び、通常は「Omni（人物を保つ）」を選びます。
5. 必要なモデル名が既定値と異なる場合は、後述の環境変数を設定してサーバーを起動し直します。

FastH3動画で既定値として探すモデルファイルは次の4点です。

```text
minimax_h3_fastvideo_vsa_datafree_1300step_4step_int8_convrot.safetensors
qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors
minimax_h3_video_vae_fp16.safetensors
minimax_h3_audio_vae_fp32.safetensors
```

ファイル名が異なる場合は、`FASTH3_MODEL`、`FASTH3_TEXT_ENCODER`、`FASTH3_VIDEO_VAE`、`FASTH3_AUDIO_VAE` で実際の名前を指定してください。標準構成では、人物参照に `MiniMaxH3ReferenceToVideo`、先頭フレーム参照に `MiniMaxH3ImageToVideo` を使います。そのほか `MiniMaxH3SigmaShift`、`VAEDecodeAudio` を使い、高速化が有効な場合は `SolAttnMiniMax` も使います。

開始画面で指定するLM StudioとComfyUIの接続先はブラウザに保存されます。モデルファイル名などの詳細値は、現在の版では画面設定ではなくサーバー起動時の環境変数で指定します。

## 主な機能

- 動画の上へ大きく表示される二択UI
- LM Studioによる日本語の返答と次の選択肢の生成
- FastH3対応ComfyUIによる短い音声付き動画の生成
- 一枚の参照画像を全ターンへ渡すOmniReference／First-frame構成
- デモ、LM Studioのみ、LM Studio + FastH3の3段階で起動可能
- 5種類の既定シチュエーションと、それぞれの会話ゴール
- 日本語の説明からキャラクターとシチュエーションを生成
- キャラクターの外見プロンプトとseedを会話中に固定
- スタート画面、途中リセット、ゴール結果画面
- 会話履歴や生成物をGit管理から除外

## 動作構成

```text
ブラウザ
  └─ FastH3 Date Chat（このリポジトリ）
       ├─ LM Studio：返答、二択、キャラクター、シチュエーション
       └─ ComfyUI + FastH3：音声付き短尺動画（任意）
```

UIだけならPython以外は不要です。AI会話にはLM Studio、動画生成にはFastH3を利用できるComfyUIが別途必要です。

## 必要環境

- Python 3.11以降
- 対応ブラウザ
- 任意：LM Studioと、OpenAI互換APIで利用できるチャットモデル
- 任意：FastH3対応のComfyUI、必要モデル、対応カスタムノード

Pythonの追加パッケージはありません。

## 1. UIをすぐ試す

Windowsでは `run_demo.bat` を実行します。macOS/Linuxでは次を実行します。

```sh
sh run_demo.sh
```

または、リポジトリのルートで直接起動します。

```powershell
python -m app.server --provider demo --video-mode none
```

ブラウザで <http://127.0.0.1:8767/> を開き、「ゲームをはじめる」を押してください。

デモモードでは、同梱の導入動画を一度だけ再生したあと、固定の日本語会話で画面遷移を確認できます。外部LLMやGPUは使いません。

## 2. LM Studioで会話する

1. LM Studioでチャットモデルをロードします。
2. LM StudioのLocal Serverを開始します。
3. `run_lmstudio.bat`（macOS/Linuxでは `sh run_lmstudio.sh`）を実行します。
4. <http://127.0.0.1:8767/> を開きます。
5. 開始画面で「LM Studio」を選び、接続確認を行います。

直接起動する場合は次のとおりです。

```powershell
python -m app.server --provider lmstudio --video-mode none
```

標準の接続先は `http://127.0.0.1:1234/v1` です。複数のモデルをロードしている場合はモデルIDを指定できます。

```powershell
$env:LM_STUDIO_MODEL = "loaded-model-id"
python -m app.server --provider lmstudio --video-mode none
```

会話用システムプロンプトは、台詞と選択肢を必ず日本語で返すよう指定しています。`response_format` に対応しないOpenAI互換モデルでは、通常のJSON応答へ自動的に切り替わります。

## 3. FastH3動画を使う

FastH3対応のComfyUIを別途用意し、必要なモデルを各自のComfyUIモデルフォルダへ配置してください。モデルやカスタムノードはこのリポジトリに含まれません。

Windowsでは `run_full.bat`、macOS/Linuxでは `sh run_full.sh` を実行します。直接起動する場合は次のとおりです。

```powershell
python -m app.server --provider lmstudio --video-mode fasth3
```

開始画面で映像を「FastH3」にすると、ComfyUI接続先、キャラクター参照画像、参照方法が表示されます。標準値は `http://127.0.0.1:8002` です。

参照画像には、会話中に出したい人物の顔、髪型、服装がよく分かるPNG、JPEG、WebP（12MB以下）を選びます。画像はこのアプリの `data/reference_images/` にローカル保存され、Git管理には入りません。ゲーム開始時はその画像を静止画として表示し、最初の選択後から各動画へ同じ画像を渡します。

初期状態では、同梱の過去のスタート動画から切り出した320×320の `media/default-character-reference.png` を使います。設定画面の「既定画像」でいつでも戻せます。元の `media/opening.mp4` は変更していません。

参照方法は次の二つです。

| 参照方法 | 用途 |
|---|---|
| Omni（既定） | 参照画像を人物の同一性として使い、会話場面の構図や小さな動作をプロンプトで作る |
| FL | 参照画像そのものを動画の先頭フレームとして動かす |

別の接続先を使う場合は、画面で入力するか環境変数を指定します。

```powershell
$env:FASTH3_BASE_URL = "http://your-comfyui-host:8002"
python -m app.server --provider lmstudio --video-mode fasth3
```

既定の短時間プロファイルは次のとおりです。

| 項目 | 値 |
|---|---:|
| 解像度 | 320 × 320 |
| フレーム数 | 72 |
| FPS | 24 |
| 長さ | 約3秒 |
| steps | 4 |
| Attention | `SolAttnMiniMax` |

`SolAttnMiniMax` がない環境では、起動前に `FASTH3_USE_SOL_ATTN=0` を設定すると、追加のAttentionノードを使わないグラフになります。

## キャラクターとシチュエーション

開始画面には「澪」が既定キャラクターとして入っています。LM Studioを選ぶと、日本語の説明から別のキャラクター案を生成し、確認・編集して保存できます。

キャラクターには次の情報が含まれます。

- 名前、関係、性格、話し方
- 初回の台詞と最初の二択
- FastH3へ毎回渡す固定外見プロンプト
- 動画生成で共有するseed

既定シチュエーションは「夜の雑談」「デートの約束」「明日の背中押し」「古い絵葉書の謎」「週末の小旅行」の5種類です。各シチュエーションには会話上のゴールがあります。こちらも日本語の説明から別案を生成し、ゴールや達成条件を編集して保存できます。

保存した設定は `data/characters/` と `data/scenarios/` に置かれ、Git管理には入りません。ゲーム開始時に設定のスナップショットを作るため、途中で保存内容を変えても進行中の人物やゴールは変わりません。

## FastH3の人物・声の一貫性

選択した一枚の画像を全ターンへ渡し、固定外見プロンプトと固定seedも併用します。通常はOmniを選ぶと、画像を人物の基準にしながら、そのターンの表情や小さな動作を作れます。FLは元画像の構図から直接動かしたい場合に向きます。

生成モデルの性質上、参照画像を使っても顔、衣装、画風が完全に一致する保証はありません。また、この構成では声質を固定する専用話者参照は使っていません。より強い一貫性が必要な場合は、用途に応じて次の構成も検討してください。

- キャラクター専用LoRA
- 外部TTSとリップシンク
- 生成済み動画を使う固定分岐シナリオ

## 環境変数

| 環境変数 | 標準値 | 用途 |
|---|---|---|
| `APP_HOST` | `127.0.0.1` | Webサーバーの待受アドレス |
| `APP_PORT` | `8767` | Webサーバーのポート |
| `CHAT_PROVIDER` | `demo` | `demo` または `lmstudio` |
| `VIDEO_MODE` | `none` | `none` または `fasth3` |
| `CHARACTER_CONFIG` | `config/character.example.json` | 既定キャラクター設定 |
| `LM_STUDIO_BASE_URL` | `http://127.0.0.1:1234/v1` | OpenAI互換API |
| `LM_STUDIO_MODEL` | 自動選択 | ロード済みモデルID |
| `LM_STUDIO_TIMEOUT` | `60` | LLM応答の待機秒数 |
| `FASTH3_BASE_URL` | `http://127.0.0.1:8002` | ComfyUI API |
| `FASTH3_MODEL` | ソース内の既定値 | UNETファイル名 |
| `FASTH3_TEXT_ENCODER` | ソース内の既定値 | テキストエンコーダー名 |
| `FASTH3_VIDEO_VAE` | ソース内の既定値 | Video VAE名 |
| `FASTH3_AUDIO_VAE` | ソース内の既定値 | Audio VAE名 |
| `FASTH3_REFERENCE_MODE` | `omni` | 既定の参照方法（`omni` または `first_frame`） |
| `FASTH3_REF_IMAGE_SIZE` | `match` | Omniの参照画像サイズ方針（`match` または `max`） |
| `FASTH3_USE_SOL_ATTN` | `1` | 高速Attentionノードの使用 |
| `DATE_CHAT_DATA_ROOT` | `data` | 会話履歴と保存設定の格納先 |
| `DATE_CHAT_WORK_ROOT` | `work` | 動画生成の一時作業先 |

既定キャラクターをファイルで差し替える場合は、`config/character.example.json` を `config/character.json` にコピーして編集します。`config/character.json` はGit管理から除外されます。

## 改造の入口

| ファイル | 主な役割 |
|---|---|
| `app/static/index.html` | 開始画面とゲーム画面 |
| `app/static/style.css` | レイアウトと見た目 |
| `app/static/app.js` | UI遷移、動画再生、API呼び出し |
| `app/date_chat.py` | 会話状態、LLMプロンプト、ゴール判定 |
| `app/profiles.py` | キャラクターとシチュエーションの定義・生成 |
| `app/video_generation.py` | ComfyUIへ送るFastH3ワークフロー |
| `app/server.py` | ローカルHTTPサーバーとAPI |

## テスト

```powershell
python -m unittest discover -s tests -v
python tools/release_audit.py .
node --check app/static/app.js
```

`release_audit.py` は、Git管理対象にしてはいけない実行時データ、秘密情報らしい文字列、個別環境の絶対パスなどを検査します。公開前には、必要に応じて固有名も追加できます。

```powershell
python tools/release_audit.py . --forbid "internal-name"
```

## セキュリティ

このサーバーには認証、TLS、利用者ごとのデータ分離、生成要求の制限がありません。標準の `127.0.0.1` のままローカルで使用してください。インターネットへ直接公開しないでください。詳しくは [SECURITY.md](SECURITY.md) を参照してください。

## 外部コンポーネント

このリポジトリはLM Studio、ComfyUI、FastH3のモデルやカスタムノードを再配布しません。外部コンポーネントについては [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) を参照してください。

## ライセンス

現時点ではコードのライセンスを指定していません。第三者へ利用・改変・再配布を許可する公開へ移る前に、目的に合うライセンスを選び、`LICENSE` を追加してください。外部モデルとソフトウェアには、それぞれ別の利用条件があります。
