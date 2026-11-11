# Домашняя сборка Windows — удалена

Профиль `--domestic` (встроенные Whisper small FP16, community-1, изолированный CPU
runtime pyannote и WebView2 CAB) и связанный cached/content-addressed полный
офлайн-пакет удалены 12.11.2026. Единственный распространяемый профиль — стандартный
установщик, собираемый `windows-app/build_release.py` с `PublicRelease` и распространяемый
Inno Setup.

Удалены: `windows-app/domestic_bundle.py`, `domestic_setup.py`, `domestic-wheels.json`,
`DOMESTIC-NOTICES.md`, `verify_domestic.py`, `build_cached.py`, `component_cache.py`,
`verify_cached.py` и их тесты. `scripts/local_build.py` и `scripts/Build-Local.ps1`
теперь собирают только стандартный профиль; флаги `--domestic`/`--cached`/`-Domestic`
отклоняются.

Стандартный ZIP/staging, pinned wheels (включая `requirements-pyannote-*.lock` для
обычной SDK-диаризации), общий download/кэш компонентов, общественный artifact gate и
стандартные workflow/lifecycle сохранены. Пользователь получает Whisper/community-1 с
официальных источников при первоначальной настройке с собственным согласием/доступом,
а готовая локальная модель переиспользуется.

Исторические proof и release notes сохранены как есть (например,
`docs/verification-domestic-0.8.26.json`, записи в `docs/development/history.md`);
это не текущая поставка.
