# Компоненты и условия распространения

Прототип подключается к существующим моделям/сервисам. В Git нет моделей, FFmpeg
binary, Python venv или чужих исходников. Это перечень компонентов, не заключение
о лицензии готового будущего дистрибутива.

| Компонент | Источник/условия | Что учитывать |
|---|---|---|
| Наш исходный проект | Отдельная LICENSE пока не выбрана владельцем | До публичного распространения определить лицензию и notices. |
| OpenVINO / OpenVINO GenAI | [Apache-2.0](https://github.com/openvinotoolkit/openvino.genai/blob/master/LICENSE) | Проверять notices runtime/драйверов; драйвер имеет отдельные условия Intel. |
| Whisper small / OpenVINO IR | [Model card](https://huggingface.co/OpenVINO/whisper-small-fp16-ov), [Whisper MIT](https://github.com/openai/whisper/blob/main/LICENSE) | Зафиксированы HF revision/size и engine digest; веса не включены в Git. |
| faster-whisper / Silero VAD | [MIT](https://github.com/SYSTRAN/faster-whisper/blob/master/LICENSE) / [Silero MIT](https://github.com/snakers4/silero-vad/blob/master/LICENSE) | В этом режиме faster-whisper нужен для CPU VAD, CPU Whisper-модель не скачивается. |
| imageio-ffmpeg wrapper | [BSD-2-Clause](https://github.com/imageio/imageio-ffmpeg/blob/main/LICENSE) | Лицензия wrapper не равна лицензии бинарника. |
| Bundled FFmpeg 7.1 Windows | [FFmpeg legal](https://ffmpeg.org/legal.html) | `ffmpeg -L` у установленного binary сообщает GPL v3 or later. Перед bundling обеспечить соответствующие условия и доступ к исходникам сборки; сейчас binary ставится из PyPI. |
| PyAV / FFmpeg libraries | [PyAV license](https://github.com/PyAV-Org/PyAV/blob/main/LICENSE.txt) | Проверять фактическую сборку включённых библиотек отдельно от Python wrapper. |
| pyannote community-1 | [CC-BY-4.0 model card](https://huggingface.co/pyannote/speaker-diarization-community-1) | Отдельные условия доступа Hugging Face/атрибуции; модель в прототип не скачивается. |
| Ollama/Qwen | [Ollama MIT](https://github.com/ollama/ollama/blob/main/LICENSE), лицензия конкретной модели в её card | Не переносить лицензию Ollama на все доступные веса; проверять выбранный tag/revision перед распространением. |

Все фактически разрешённые версии Python-зависимостей — в `requirements-lock.txt`.
Проверенные размер/SHA256 FFmpeg binary и модельный digest — `component-manifest.json`.
Отдельные библиотеки могут иметь дополнительные notices и транзитивные зависимости:
полный SBOM и third-party bundle нужны перед публичным installer, а не подразумеваются готовыми.
