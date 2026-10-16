# Проверка Windows Sandbox

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

- `reports/status.json`: running/passed/failed, время и сообщение ошибки.
- `reports/stdout.log`, `stderr.log`: вывод verifier.
- `reports/verification-release.json`: точные artifact hashes и результаты.

Закрытие Sandbox удаляет гостевые файлы; отчёты в mapped reports остаются на хосте.
Дождитесь passed/failed перед закрытием. Не считать отсутствие файла успешным прогоном.
Отчёт явно помечает execution_environment=Windows Sandbox, сохраняя clean_vm=false:
Sandbox не тождественен минимальной независимой Windows VM и не проверяет NPU/GPU.

Официальные сведения: [установка](https://learn.microsoft.com/en-us/windows/security/application-security/application-isolation/windows-sandbox/windows-sandbox-install),
[WSB configuration](https://learn.microsoft.com/en-us/windows/security/application-security/application-isolation/windows-sandbox/windows-sandbox-configure-using-wsb-file).
