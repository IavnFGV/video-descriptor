# Компоненты и условия распространения

Сборка 0.7 после приёмки 19.10.2026 включает app-local Microsoft Visual C++ Runtime
14.44.35211.0 (12 x64 DLL рядом с python.exe). Источник — официальный подписанный
Microsoft `VC_redist.x64.exe`, точный URL/SHA256 и хеши DLL в release-inputs.json;
лицензия из bundle включается как python/Microsoft-Visual-Cpp-LICENSE.rtf.
DLL не берутся из System32 хоста, redistributable не устанавливается в систему.
Условия Microsoft распространяются на эти файлы отдельно от лицензий Python/OpenVINO:
[Redistributing Visual C++ files](https://learn.microsoft.com/en-us/cpp/windows/redistributing-visual-cpp-files).
WiX 6.0.2 используется только для извлечения build input, в приложение не входит.

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

Desktop 0.7 включает Microsoft.Web.WebView2 SDK 1.0.2903.40 (NuGet), три runtime/managed
DLL; LICENSE.txt из проверенного nupkg включается рядом в desktop-sdk. URL/SHA256
закреплены в release-inputs.json. При отсутствии рабочего WebView2 Runtime установщик
скачивает официальный Fixed Version CAB 155.0.4283.62 x64 с закреплёнными URL/SHA256
в WebView2Runtime.iss, проверяет подпись Microsoft и размещает полный пакет в папке
приложения. Применяются отдельные условия Microsoft WebView2, включая notices из пакета;
в Git и основной ZIP веса/Runtime CAB не включаются. Fixed Runtime обслуживается
обновлениями приложения. .NET Framework используется системный.

Все фактически разрешённые версии Python-зависимостей — в `requirements-lock.txt`.
Проверенные размер/SHA256 FFmpeg binary и модельный digest — `component-manifest.json`.
Отдельные библиотеки могут иметь дополнительные notices и транзитивные зависимости:
полный SBOM и third-party bundle нужны перед публичным installer, а не подразумеваются готовыми.
