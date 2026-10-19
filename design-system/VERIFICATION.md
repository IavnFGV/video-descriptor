# Проверки первого этапа

19.10.2026 · baseline `9ffa842` · отдельный worktree `E:\LocalAI\video-descriptor-ui-audit`, ветка `design/ui-ux-audit`.

## Выполнено

| Проверка | Результат / доказательство |
|---|---|
| `python scripts/check-ui-audit.py` | PASS: 82 production файла совпадают с baseline (CRLF → LF only); 75 уникальных desktop ids; все 73 прямых `$()` targets существуют. В baseline также инвентарь общих HTML/JS и API literals. |
| `node --check design-system/prototype/prototype.js` | PASS, синтаксис JavaScript |
| Ruff для добавленного Python guard | PASS через существующий `E:/LocalAI/video desriptor/.venv-windows/Scripts/python.exe -m ruff check scripts/check-ui-audit.py`; системный Python не имеет Ruff, новые пакеты не устанавливались |
| `git diff --check` | PASS |
| Пустая форма | Показывает inline error; file input получает фокус, aria-invalid=true; dropzone focus-within solid |
| Демонстрационный файл → submit | Пример queued; progress без value; явное сообщение, что файл не отправлялся |
| Running | Текст этапа и progress value=42; это заданный пример, не настоящий ход обработки |
| Error → retry | Причина + recovery; «Продолжить из кэша» переключает пример на queued |
| Done → export dialog | Открывается именованный native dialog; initial focus «Закрыть»; Escape закрывает и возвращает фокус на demo-export |
| No speech | Отдельное пустое состояние с пояснением VAD, без выдуманного текста |
| Components dialog | Primary/secondary/quiet/danger/disabled/busy, статусы, поле, ссылка. Escape возвращает фокус на demo-components |
| Keyboard | Tab из названия переходит к языку; focus-visible и solid outline; первый неверный file получает фокус. Это выборочные проверки, не полная сертификация доступности |
| Навигация | Записи → Настройки AI → Диагностика → Записи; hash/aria-current и видимая область согласованы; фокус main после перехода |
| Длинное название | Ввод длинного RU текста, без горизонтального переполнения |
| Responsive | 375×812, 768×1024, 760×560, 1024×768, 1440×900 и 1200×820; scrollWidth=clientWidth в проверенных состояниях; readiness доступна на узкой странице ниже формы. Метрики: `evidence/responsive.json`, изображения `evidence/main-*.jpg` |
| Контраст | Текст/surface 14.15:1, muted/surface 6.14:1, muted/canvas 5.65:1, primary label 7.08:1; текст статусов 5.7–6.47:1, control border 3.18:1, focus 6.48:1. Расчёт sRGB: `evidence/contrast.json`; disabled отдельно от нормы текста active |
| Browser console | При проверке прототипа warnings/errors не зафиксированы |
| Изоляция | Исходный checkout остаётся на feat/sandbox-acceptance-harness; существующая untracked `.codex/` не тронута. Merge, push, запуск/остановка AI, операции Sandbox не выполнялись |

## Ограничения доказательств

Это **эвристический аудит исходников + браузерная проверка reference-прототипа**. Не запускались установленное приложение WebView2, рабочие backend/jobs, GPU/NPU inference, Ollama, Gemini, Sandbox и backend regression suite. Не выполнялись настоящее скачивание модели, реальный экспорт/редактирование production данных, OS picker, drag/drop реального медиа, Windows high contrast/Narrator/scaling 125–200%. Последние проверки обязательны при внедрении, перечислены в PLAN/CONTRACTS. Сохранность production обеспечена отсутствием изменений исходников, а не подменяется успешным mock сценарием.

Прототип не импортирует production scripts, не содержит fetch/XMLHttpRequest и не обращается к `/api/`. Статический preview server слушает только 127.0.0.1:8947 и обслуживает только каталог design-system. UI работает также при открытии `prototype/index.html` как локального файла.

Браузерный fullPage-capture при viewport overrides дал некорректную компоновку; снимки заменены обычными viewport-capture после проверки состояния. Формат полученных снимков JPEG, расширения приведены к `.jpg`. Для полного просмотра длинных узких страниц использовать сам прототип.
