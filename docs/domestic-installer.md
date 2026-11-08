# Домашняя сборка Windows

Профиль `--domestic` добавляет готовые компоненты на уровне упаковки, без изменений
приложения/UI. Цель: локальные распознавание и разделение по участникам без аккаунта
Hugging Face, pip и скачивания моделей на целевом компьютере.

Включены основной embedded Python и OpenVINO (как в стандартной сборке), FFmpeg из
imageio-ffmpeg и PyAV для чтения медиа, Whisper small FP16 (~493 МБ), community-1
(32 821 421 байт), отдельный embedded Python с закреплёнными CPU wheels pyannote
(~253 МБ wheel inputs) и официальный подписанный Fixed WebView2 CAB.
Это не итоговый размер установщика: распакованные библиотеки и WebView2 больше.
Системный Python, Docker, Hugging Face и Ollama для этих двух задач не нужны.
Перевод, конспекты и XPU-диаризация остаются дополнительной подготовкой.
Драйверы оборудования в установщик не входят. Распознавание сохраняет Auto;
диаризация на новой установке явно выбирает CPU, доступный без GPU-драйвера.

## Подготовка на компьютере сборки

Модели получают один раз обычным разрешённым способом; builder ничего не скачивает
с Hugging Face. Локальный JSON вне Git задаёт только четыре пути:

```json
{
  "whisper_model": "E:/models/whisper-small",
  "diarization_model": "E:/models/community-1",
  "wheelhouse": "E:/build-cache/domestic-wheels",
  "webview_cab": "E:/build-cache/webview2-fixed-x64.cab"
}
```

Wheelhouse наполняется на Windows CPython 3.12, без установки пакетов:

```powershell
python -m pip download --only-binary=:all: --no-deps --dest E:/build-cache/domestic-wheels -r windows-app/requirements-pyannote-cpu.lock
```

Имена/SHA256 должны совпадать с `windows-app/domestic-wheels.json`; другой набор
или повреждённые файлы останавливают сборку. Модели проверяются по размеру и SHA256
или Git blob из component-manifest.json. Копируются только перечисленные файлы,
никаких venv, кэшей аккаунтов, .env, токенов, очереди и личных записей.
Лицензии wheels и атрибуция моделей сохраняются в комплекте.

```powershell
python windows-app/build_release.py --domestic --domestic-inputs E:/build-cache/domestic-inputs.json --cache E:/build-cache --output dist/domestic --iscc E:/tools/ISCC.exe
```

Без `--domestic` стандартный builder работает по-прежнему. При `--domestic`
недостающий компонент является ошибкой; незаметного перехода к онлайн-установке нет.

## Локальный hook и результаты

К существующему `local_build.py configure` добавьте `--domestic-inputs <JSON>`.
`python scripts/local_build.py install-hook` обновляет только наш локальный hook.
После merge/pull в локальный main он вызывает `Build-Local.ps1 -Background -Domestic`.
До merge текущей ветки в main этот профиль там недоступен.
Ручной запуск: `scripts/Build-Local.ps1 -Domestic`.
Результаты: `dist/local/domestic/<версия>/`; стандартные — `dist/local/<версия>/`.
Очередь и reuse различают профили одного SHA. Ничего не публикуется автоматически.

## Установка и ZIP

Домашний Inno Setup использует встроенный CAB, проверяет SHA256 и подпись Microsoft,
не скачивает WebView2. После копирования файлов запускает `domestic_setup.py`:
проверка хешей → пути установленного комплекта → CPU inference на тестовой записи
для Whisper/pyannote → сохранение реального proof → завершение начальной подготовки.
Ошибка проверки завершает установку с ошибкой; диагностику можно повторить через
`Prepare Domestic.cmd`. Настройки и маркер готовности пишутся только локально.
Существующие внешние модели, устройства, хранилище и настройки не заменяются.

Для ZIP сначала запустить `Prepare Domestic.cmd`, затем desktop EXE; корневой
`Open Video Descriptor.cmd` выполняет оба шага. ZIP распаковывать сразу в постоянную
папку: перенос уже настроенного экземпляра требует повторной настройки путей.
Обычный portable smoke по-прежнему проверяет приложение без модели; он не считается
проверкой готовности domestic. Нужен отдельный запуск подготовки и реального inference.
Проверка на текущем компьютере не доказывает установку на чистой Windows или работу NPU/GPU.
