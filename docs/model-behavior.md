# Проверки моделей и промптов

Release Full Acceptance проверяет приложение, а не способность tiny-модели следовать
промпту. Только внешний LLM HTTP endpoint заменён disposable fixture
`windows-app/sandbox/llm_fixture.py`: настоящие запросы через production adapters,
streaming chunks, markers/таймкоды, штатные worker/валидация/сохранение и UI.
Проверяются также неверный ответ и сохранность источника. Unit HTTP regression
проверяет обрыв потока и штатные повторы/ошибку. Whisper CPU в установленном
приложении остаётся настоящим. Mock не означает inference proof и не поставляется
как доступный пользователю backend. Отчёты явно указывают границу подмены.

## Реальные модели

Actions → **Model and prompt behavior** → Run workflow: выбрать ref, Ollama model,
при необходимости `few_shot`. Запускается только явно, независимо от релизов.
Модель скачивается из официальной Ollama в изолированный Windows runner;
ничего не устанавливается и не скачивается на рабочий компьютер. Workflow не
запускает установщик приложения и не публикует GitHub Release.

CLI для уже работающей модели:

```powershell
python scripts/evaluate_models.py --provider ollama --model qwen3.5:9b --base-url http://127.0.0.1:11434 --output runtime/model-evaluation/baseline
python scripts/evaluate_models.py --provider lmstudio --model MODEL_ID --base-url http://127.0.0.1:1234 --output runtime/model-evaluation/lmstudio
```

Используются production prompts `construction.PROMPTS['lecture']`, `ARTICLE_PROMPT` и
`prompts/translate_markers_ru.txt`. В `tests/model-behavior/cases.json` хранятся
синтетическая речь, допустимые факты/формулировки и запрещённые утверждения.
Начальные случаи: короткая запись, отрицание/неопределённость в конспекте и статье, разрыв предложения
между репликами перевода. Проверяются production timestamp/notes contract,
translation markers и заданные признаки фактов. Keyword checks ограничены:
они не доказывают полную семантическую корректность; ответы доступны для ревью.

Каждый случай выполняется один раз (transport retry адаптера сохраняется), без
повторов до удачного ответа. FAIL остаётся FAIL. Артефакт содержит модель/digest
(если доступен), хеши фактического промпта и case, длительность, ошибку и исходный
ответ. Ответы/промпты не пишутся в общий журнал приложения. В corpus и артефактах
разрешены только синтетические/обезличенные данные, без пользовательских записей.

## Добавление регрессии и few-shot

1. Сократить проблемный текст до синтетического случая и добавить уникальный `id`,
   `task`, `segments`, `required_any` и при необходимости `forbidden` в cases.json.
2. Запустить baseline для используемой модели и сохранить факт ошибки.
3. Добавить отдельный обучающий пример в `examples.json`, сохраняя case как проверку.
   Не подставлять готовый ответ проверяемого case вместо генерации.
4. Сравнить тот же ref/model/corpus с `few_shot=true` либо CLI `--examples tests/model-behavior/examples.json`.
5. Принять изменение production prompt отдельно после ревью всех случаев.

Примеры не добавляются к production prompt автоматически. Это позволяет сравнить
baseline и эксперимент, не менять поведение установленного приложения ради CI.
Новые модели проверяются отдельными ручными запусками; все используют общий corpus.
