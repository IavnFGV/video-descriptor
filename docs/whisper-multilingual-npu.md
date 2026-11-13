# Проверка многоязычного Whisper small на Windows NPU

Историческая методика эксперимента. Small впоследствии подключена к desktop:
[проверки Windows](verification-windows.md), [актуальная настройка](ai-setup-windows.md).
Это не обязательная подготовка пользователя установленного приложения.

Старый base.en и порт 8765 остаются самостоятельным английским сервисом.
Новый эксперимент: официальный OpenVINO/whisper-small-fp16-ov, NPU,
STATIC_PIPELINE=True, num_beams=1, task=transcribe, автоматическое определение
языка (language не задаётся). Русский/украинский/английский поддерживаются
многоязычной моделью; переключения языка внутри речи требуют проверки качества.
https://huggingface.co/OpenVINO/whisper-small-fp16-ov

Архив `output/frigg-preparation/whisper-multilingual-npu.zip` и исходный
`sample-frigg-900.wav` были локальными входами опыта и не входят в репозиторий.
Исходники находятся в `scripts/`: `test_whisper_multilingual_npu.ps1`,
`download_official_whisper_ir.py`, `benchmark_whisper.py`, `whisper_npu_server.py`.
Команда ниже ожидает эти файлы, WAV и готовую `.venv-npu` рядом в отдельном
benchmark-каталоге. Скрипт использует `$PSScriptRoot`; запуск из `scripts/`
не подключит внешнюю benchmark-среду автоматически. Не меняйте рабочую защищённую
среду для воспроизведения исторического опыта:

```powershell
powershell -ExecutionPolicy Bypass -File .\test_whisper_multilingual_npu.ps1
```

Загрузится только официальный small IR. Benchmark выполнит два прохода одного
15-минутного WAV; сохраняет таймкоды, тексты, версии, время загрузки, время проходов,
контрольные суммы и ошибки в whisper-small-npu-frigg.json. Проверяет непустой текст,
границы таймкодов и грубые повторы; это не самостоятельная оценка точности текста.
После успешного benchmark запускается отдельный worker на 8766. Проверить /health:
model=small, device=NPU, multilingual=true, pipeline=static, num_beams=1.
JSON результата нужно вернуть в рабочую папку для сравнения с Whisper CPU/Gemini.

У контейнера нет Windows command execution, поэтому запуск на хосте делает
пользователь или Windows Codex. В исходном эксперименте до проверки текста и
стабильности вариант ещё не предлагался в UI. Сервис выдаёт таймкоды реплик,
а не отдельных слов: для точного назначения голосов внутри реплики потребуется
выравнивание слов или дробление реплик; это отличие от текущего Gemini hybrid.
