# Диаризация на Intel Arc из devcontainer / WSL2

Проверено на хосте 2026-10-10: /dev/dxg присутствует и в Ubuntu, и в docker-desktop.
В старом контейнере устройства нет. Это подтверждает возможность проброса, но ещё
не подтверждает совместимость операций pyannote с XPU и ускорение.

Основной devcontainer теперь использует Ubuntu 24.04, Intel compute runtime из
ppa:kobuk-team/intel-graphics, --device=/dev/dxg и readonly mount /usr/lib/wsl.
Ubuntu выбрана вместо Debian Bookworm по проверенной Intel конфигурации Lunar Lake.
Старый CPU-профиль сохранён в .devcontainer/cpu/devcontainer.json.
Профиль требует Docker Desktop с WSL2 и Intel Windows GPU driver.

1. В VS Code: F1 → Dev Containers: Rebuild Container. Это завершит терминалы и
   веб-сервер контейнера; данные в рабочей папке сохраняются.
2. В новом терминале:

```bash
bash scripts/prepare_diarization_xpu.sh
```

Скрипт создаёт отдельную .venv-diarization-xpu и проверяет настоящий расчёт на GPU.
CPU-окружение не заменяется. При недоступном XPU тест завершается ошибкой,
автоматического перехода на CPU нет. Если pip сообщает несовместимые зависимости,
дальнейший тест не запускается.

3. Короткая проба на сохранённом аудио (лог и результат остаются для сравнения):

```bash
mkdir -p output/frigg-preparation/xpu
.venv-diarization-xpu/bin/python -u scripts/probe_diarization_xpu.py --audio output/frigg-preparation/sample-0000-0900.wav --seconds 60 --device xpu --output output/frigg-preparation/xpu/60s-xpu.json > output/frigg-preparation/xpu/60s-xpu.log 2>&1
```

Повторить с --device cpu и отдельными файлами 60s-cpu.json / 60s-cpu.log в том же
окружении. Сравнивать одинаковые pcm_sha256, длительность и разметку; загрузка
модели измеряется отдельно. После успешной короткой пробы можно поставить
--seconds 900. Ошибка неподдерживаемой операции сохраняется в логе: отсутствие
исключения и скорость сами по себе не доказывают качество разметки.

Рабочий обработчик приложения пока продолжает использовать CPU: эксперимент
не меняет существующие результаты и задания. Для возвращения прежнего контейнера
выбрать CPU-профиль при открытии в контейнере. Сервер после пересоздания запустить:
`python -m video_descriptor.serve --port 8000`.

Источники:
- https://www.intel.com/content/www/us/en/developer/articles/tool/pytorch-prerequisites-for-intel-gpu/2-14.html
- https://dgpu-docs.intel.com/installation-guides/installing-packages-from-the-intel-ppa.html
- https://docs.pytorch.org/docs/2.14/notes/get_start_xpu.html
