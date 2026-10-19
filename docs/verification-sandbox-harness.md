# Sandbox harness: фактическая проверка 19.10.2026

Реализованы `Run-Acceptance.ps1`, официальный WSB LogonCommand, guest bootstrap,
стадийный DAG, проверенный read-only cache, host reports/checkpoint, статус,
повтор неуспешных стадий и очистка временных input. Поставка WebView2 используется
из существующего installer; повторная реализация не добавлялась.

| Реальный прогон | Результат | Доказательство |
|---|---|---|
| Security, `20261019-120136-110-security` | PASS: preflight, блокировка unsigned installer, cleanup | [Отчёт](verification-sandbox-harness-evidence/security/report.json), [событие 3033](verification-sandbox-harness-evidence/security/security-block-events.xml), [сообщение Windows](verification-sandbox-harness-evidence/security/security-launch-error.txt) |
| Functional, `20261019-120602-241-functional` | BLOCKED на preflight; зависимые стадии BLOCKED, cleanup PASS | [Отчёт](verification-sandbox-harness-evidence/functional/report.json), [CiTool](verification-sandbox-harness-evidence/functional/initial-citool.json) |
| Следующий чистый гость, `20261019-120709-353-security` | PASS выбранного preflight после автоматического закрытия завершённого Functional-гостя | [Отчёт](verification-sandbox-harness-evidence/fresh-successor/report.json), [предыдущий ID](verification-sandbox-harness-evidence/fresh-successor/wsb-list-before.json), [новый ID](verification-sandbox-harness-evidence/fresh-successor/wsb-list-after.json) |

Гости: Windows 11 Enterprise build 26100, 8192 МиБ конфигурации (8191 МиБ по CIM).
До и после тестов registry SAC state=1; защитная политика не изменялась.
CiTool возвращает `OperationResult=-2147009597` / `0x80073BC3`; отдельная диагностика
под System ранее дала тот же результат. Для Security использованы наблюдаемая
блокировка конкретного EXE и связанное событие, а не предположение по exit code.
Источники отчётов фиксируют Git SHA `a211473` и dirty=true: harness тестировался
как незакоммиченные исходники, с отдельными fingerprint и per-file hashes input.
Поздние уточнения метаданных/описаний не объявляются повторно проверенной приёмкой.

Установленная версия native Sandbox launcher повторно открывает существующего
гостя. Это воспроизведено: новая конфигурация оставалась PREPARED, а явный CLI
start вернул `CO_E_APPSINGLEUSE`. Harness теперь сохраняет sandbox ID вне writable
guest reports и закрывает только собственный завершённый экземпляр перед новым
запуском. Active/untracked/foreign Sandbox не уничтожается. Переход Functional →
новый Security preflight проверен реальным запуском с разными guest ID.

В PowerShell 5.1 исправлены и проверены чтение root JSON array, инициализация
путей параметров и ожидание host report при sharing conflict. Для `wsb` ожидается
только его процесс, а не всё дерево с долгоживущим Sandbox broker. Host deadline
сохраняет отдельный маркер; позднее завершение не должно превращаться в своевременный
PASS. Целевые тесты проверяют зависимости, отсутствие Whisper в Ollama-плане,
стабильность fingerprints, integrity/выход за cache root, отказ bootstrap на хосте,
безопасную очистку, loopback-only CDP и WebSocket framing.

Автоматические проверки на хосте: **272 passed, 2 skipped**, включая **13 новых**
тестов harness; Ruff всего проекта PASS; парсер PowerShell PASS. Запуск pytest
без UTF-8 показал ошибки чтения русскоязычных отчётов в старых тестах, поэтому
окончательный прогон выполнен с `-X utf8`, как в Windows CI. Это host unit/API
результаты, не подтверждение функциональной приёмки.

Полный критерий «новая Sandbox → подготовка Ollama → реальная генерация →
перевод → конспект» **не достигнут**. В данном госте не подтверждён разрешённый
поддерживаемый Evaluation/Audit. Текущие документированные Microsoft процедуры
форсирования режима требуют recovery, ACL/ownership или EFI-изменений, исключённых
исходным заданием. Реальные Functional UI, Ollama и их кэш/жизненный цикл не
проверены этим harness; исторические SAC-Off результаты не перенесены в PASS.
Автоматизация этих стадий написана, но блокируется до запуска приложения.
Для продолжения требуется допустимое окружение, в котором CiTool подтверждает
работающий поддерживаемый Evaluation/Audit; обходы защищённых файлов
и изменение основной Windows не выполнялись. Reboot recovery также не заявляется
проверенным: сценарий не дошёл до разрешённой настройки, требующей reboot.

[Машиночитаемый итог](verification-sandbox-harness.json),
[SHA256 сохранённых доказательств](verification-sandbox-harness-evidence/SHA256SUMS.json),
[команды и ограничения](../windows-app/sandbox/README.md).
Большие модели и медиа в Git не добавлялись. Push, merge и публичный Release
не выполнялись.
