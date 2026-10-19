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

## Установленная сборка и автоматизация

Локально проверенный UI-установщик (до финального исправления skip-link): ZIP SHA256
`8e632c3d657af6181516ffb96bf307f974911abfaa48156bb302261f6b05c614`.
Локальная установленная сборка реально выполнила API CPU/Ollama/перевод/конспект,
а через WebView2 — выбор MP4, upload, CPU inference, перевод и новый конспект.
Первый новый автоматический editor-check обнаружил разницу float 8.279999732 и
прежнего сохранения редактора 8.280: проверка теперь учитывает существующую
точность до миллисекунды (≤0.0005 s), а не требует побитового совпадения float.
Это исправление теста, не изменение экспортных таймкодов или backend.

Полный автоматический результат окончательной сборки, включая правку, dirty guard,
навигацию, независимые prompt drafts, экспорты и viewport PNG, сохраняется в
`dist/installed-acceptance/report.json` и `webview2-ui/workspace-ui.json` в артефакте
[Windows workflow](https://github.com/IavnFGV/video-descriptor/actions/workflows/windows-release.yml).
Локальный полный AI-прогон сохраняется отдельно в `dist/final-installed-ui/retry/`.
Финальный merge выполняется только после успешных Windows и Container проверок.

`verify_installed.py --ui` запускает сам установленный EXE и ввод через WebView2,
без mock API. `--with-ollama` добавляет реальные UI перевод, конспект, Markdown/HTML.
PR/main всегда проверяют CPU/UI. Событие опубликованного release автоматически
собирает его tag и включает полный Ollama/UI-прогон на кэшируемой qwen3.5:0.8b.
Ручной workflow_dispatch также позволяет включить AI-проверки. Это не создаёт
публичный release и не выдаёт rebuild за проверку произвольного загруженного asset.

## Ограничение Sandbox

UI run 20261019-174427-177-functional: свежая установка PASS, SAC Off и один
same-guest restart подтверждены; UI-драйвер не подключился к loopback DevTools
9222 за 150 s. Desktop stage FAIL, зависимые UI stages BLOCKED; это **не PASS**.
[Report](evidence/final/sandbox/report.json),
[transport failure](evidence/final/sandbox/desktop.json).
Обычные пользовательские сценарии отдельно выполняются установленным Windows
runner/host через автоматический драйвер, как предусмотрено заданием.

[Guest diagnostics](evidence/final/sandbox/guest-diagnostics.json): Windows PnP
показывает Intel AI Boost и Arc 140V, OpenVINO перечисляет только CPU. NPU/GPU
inference в этой Sandbox недоступен и не заявляется. Diagnostic labels теперь
различают список Windows и доступность в OpenVINO. На основном Windows runtime
обнаруживает CPU/GPU/NPU, но этот UI release gate использует явный CPU.
OS scaling 125/150% не менялся; DPR emulation обозначен отдельно. Narrator и
аппаратный NPU/GPU полный прогон не входят в полученную здесь приёмку.
