# Проверка Windows Sandbox

19.10.2026: для новых стадийных прогонов используйте
[Run-Acceptance.ps1](../windows-app/sandbox/README.md). Новый harness разделяет
Security и Functional, сохраняет checkpoint/результаты и поддерживает verified
cache. Документ ниже сохраняет историю прежнего release smoke. Новый Security
прогон подтвердил блокировку unsigned preview; новый Functional остановлен как
BLOCKED из-за недоступного поддерживаемого SAC Evaluation/Audit.

Пользователь согласовал включение Sandbox 17.10.2026 после объяснения назначения.
Рабочая система Windows 11 Pro, 32 ГБ RAM. Компонент изначально не был доступен.
Автоматическая перезагрузка не разрешена и не выполняется.

## Подготовка

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File windows-app/Prepare-Sandbox.ps1 -Enable
```

Команда копирует проверенные ZIP/EXE из `dist/SHA256SUMS.json` в отдельную папку
`windows-app/runtime/sandbox/<run-id>/input`, добавляет проверочные скрипты и создаёт
`Video Descriptor.wsb`. Доступ гостя к input только для чтения. Для reports выделена
отдельная доступная для записи папка; к checkout/видео/моделям/ключам доступа нет.
Гость получает 4096 MiB; сеть, vGPU, microphone/camera, clipboard и printers отключены.

`-Enable` вызывает Windows UAC и отдельный admin helper, который включает только
`Containers-DisposableClientVM` с обязательными зависимостями и флагом `-NoRestart`.
Статус — `feature-status.json` в папке run: enabling/enabled/error и restart_needed.
Если UAC отклонён, компонент не включается. Если restart_needed=true, сохранить работу
и самостоятельно перезагрузить Windows; рабочие NPU/Ollama сервисы helper не останавливает.

## Запуск после готовности компонента

Откройте уже подготовленный `Video Descriptor.wsb` двойным щелчком. Либо новая подготовка:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File windows-app/Prepare-Sandbox.ps1 -Launch
```

В госте откроется PowerShell с автоматическим прогоном: hash ZIP/EXE, распаковка,
запуск без системного Python/моделей, UI/doctor, install/reinstall, отказ обновления
работающей копии, uninstall с сохранением тестовых данных. Сборка fixture installer
0.4.1 в госте не выполняется: compiler туда не передаётся. Этот upgrade fixture уже
проверен на основном хосте и предусмотрен в CI.

Отчёты сохраняются сразу наружу:

- `reports/status.json`: preparing/running/passed/failed, время и сообщение ошибки.
- `reports/stdout.log`, `stderr.log`: вывод verifier.
- `reports/verification-release.json`: точные artifact hashes и результаты.

Закрытие Sandbox удаляет гостевые файлы; отчёты в mapped reports остаются на хосте.
Дождитесь passed/failed перед закрытием. Не считать отсутствие файла успешным прогоном.
Отчёт явно помечает execution_environment=Windows Sandbox, сохраняя clean_vm=false:
Sandbox не тождественен минимальной независимой Windows VM и не проверяет NPU/GPU.

Официальные сведения: [установка](https://learn.microsoft.com/en-us/windows/security/application-security/application-isolation/windows-sandbox/windows-sandbox-install),
[WSB configuration](https://learn.microsoft.com/en-us/windows/security/application-security/application-isolation/windows-sandbox/windows-sandbox-configure-using-wsb-file).

## Первый фактический запуск 17 октября 2026

После ручной перезагрузки WindowsSandbox.exe стал доступен. Первый запуск дополнительно
обновил приложение Windows Sandbox на хосте. Гость: Windows 11 Enterprise build 26100,
4096 MiB назначенной памяти, системный Python отсутствует, сетевых адаптеров нет.

Гостевой verifier проверил 4387 файлов ZIP, loopback UI/doctor, отсутствие модели,
штатную остановку, install/reinstall, отказ обновления работающей копии и uninstall
с сохранением sentinel/config. ZIP/EXE hashes совпали с исходными артефактами 0.4.0.
Это реальная гостевая проверка; аппаратное ASR и upgrade fixture 0.4.1 здесь не запускались.

Первая распаковка выполнялась без раннего status-файла и создала впечатление, что
автозапуск не сработал. Повторный bootstrap столкнулся с уже существующей папкой;
этот отдельный retry не считается ошибкой ZIP/installer. Добавлены ранний preparing,
уникальная bootstrap-папка и mutex/проверка активного verifier. Конкурентный запуск
проверен внутри гостя: он завершается без изменения текущего status/report.
В Windows PowerShell 5.1 последовательность WaitForExit/Refresh дала пустой ExitCode
при успешном verifier. Заменена на Start-Process -Wait -PassThru; отдельная гостевая
проба подтверждает exit 0 и exit 7. Каждая попытка пишет собственный JSON, чтобы
старый успешный отчёт не мог подменить результат новой попытки.

Интерфейс из ZIP открыт в Edge внутри гостя через локальный ярлык. Приложение
корректно показывает отсутствие моделей; аппаратное распознавание не включалось.
[Снимок гостевого интерфейса](windows-sandbox-preview.png).

После установки обновления доступен официальный [wsb CLI](https://learn.microsoft.com/en-us/windows/security/application-security/application-isolation/windows-sandbox/windows-sandbox-cli).
Для диагностики можно использовать `wsb list` и `wsb exec --id <id> --run-as ExistingLogin
--command <command>`. Вывод гостя CLI не передаёт: диагностика сохраняется в reports.
Отключённый clipboard мешает UI-paste; включать его ради диагностики не требуется.
