# Issue #194 製品サーバーの起動経路でEngineLifecycleのreadyをappへ反映

## 設計
- `lifecycle_readiness.LifecycleReadiness`: EngineLifecycleを真実源にし、スレッドで`prepare()`、失敗時は一定間隔で再試行、停止で取り消し。`status()`が(ready, 安全な理由)を返す。
- `startup.lifecycle_from_environment`: `SCREEN_TRANSLATION_MODEL_MANIFEST` / `SCREEN_TRANSLATION_MODEL_DIR` から構成。不備は`main()`が終了コード2。
- `create_app(readiness=...)`: lifespanで開始/停止。`is_ready`・`app.state.ready`は`readiness`未指定時の従来互換。
- `_ensure_pipeline`: 準備済みエンジンから`create_pipeline_from_engines`でpipelineを作り二重ロードしない。
- `_safe_failure_reason`: パス様・`[Errno`を含む理由を汎用文へ。
- `__main__.py`追加(`python -m screen_translation_server`)。

## テスト
- `server/tests/test_lifecycle_readiness.py`(Event/注入sleep/Queueで決定的)。mutation: lifespanのstart除去、main()のreadiness除去、状態参照をapp.state.readyへ戻す、準備済みエンジン不使用 を確認。
- 結合: `server/tests/integration/test_startup_ready.py`。
- 結合試験(#85)側のready補完の除去は#192マージ後に別コミットで実施。
