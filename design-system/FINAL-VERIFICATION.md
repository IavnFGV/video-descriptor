# Финальная проверка production UI

19.10.2026. Полный backend test suite: **283 passed, 2 skipped**; Ruff, JS syntax,
CSS bundles и immutable DOM/API/handler guard PASS. Windows build ZIP/installer PASS.

Реальный host WebView2 с изолированной новой workspace (не prototype): MP4 input,
CPU Whisper из кэша, сохранённый результат и таймкоды; реальная правка реплики,
revision, dirty Escape; stage Back, query/AI round trip и session title recovery;
реальные скачивания SRT/VTT/TXT. Ollama qwen3.5:9b создала отдельный конспект через UI.
Скрипт воспроизведения: windows-app/verify_workspace_ui.py. Он требует явно заданный
loopback WebView2 и disposable запись; --edit-reply сохраняет тестовую правку.

[Скриншоты и метрики](evidence/final/workspace/workspace-ui.json): production WebView2
при 760×560, 1024×768, 1200×820, 1440×900, без горизонтального overflow и пропущенных
labels. DPR 1.25/1.5 — эмуляция, **не** Windows scaling; OS scaling не менялся.

Sandbox PR: https://github.com/IavnFGV/video-descriptor/pull/2
Merge: c2ba86b2ea4285ed957099b026dd6c5a9cd1b3b4.
Windows CI 39268899930: PASS на повторе (первый запуск: WiX closed pipe).
Container CI 39268900112: PASS. Optional Ollama CI там не запускался.

Окончательная установленная UI-приёмка и проверка итогового main дописываются
по фактическим результатам перед merge UI. Это не заявление готовности этих gates.
