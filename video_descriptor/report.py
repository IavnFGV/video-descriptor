import hashlib
import html
import json
import os
from importlib.resources import files
from pathlib import Path
from urllib.parse import quote

from .library import lecture_info
from .models import Chapter, Note, Source


def clock(seconds: float) -> str:
    value = int(seconds)
    return f"{value // 3600:02d}:{value // 60 % 60:02d}:{value % 60:02d}"


def source_details(evidence: list[Source]) -> str:
    details = []
    for source in evidence:
        picture = (
            f'<img loading="lazy" src="{html.escape(source.image, quote=True)}">'
            if source.image else ""
        )
        details.append(
            f'<p><button data-time="{source.start}">{clock(source.start)} '
            f'{html.escape(source.id)}</button></p>{picture}'
            f"<pre>{html.escape(source.text)}</pre>"
        )
    return '<details><summary>Источники</summary>' + "".join(details) + "</details>"


def render(folder: Path, video: Path, sources: list[Source], notes: list[Note],
           chapters: list[Chapter] | None = None,
           translations: dict[str, str] | None = None,
           write_markdown: bool = True) -> None:
    translations = translations or {}
    speech_folder = folder if (folder / "manifest.json").is_file() else folder.parent
    edits_file = speech_folder / "transcript-edits.json"
    if edits_file.is_file():
        edits = json.loads(edits_file.read_text(encoding="utf-8"))
        sources = [source for source in sources if source.image] + [
            Source(id=row.get("id", f"s{index}"), start=row["start"], end=row["end"], text=row["text"])
            for index, row in enumerate(edits["segments"], 1)]
        translations = {**translations, **edits.get("translations", {})}
    assets = folder / "assets"
    assets.mkdir(exist_ok=True)
    for asset in files("video_descriptor").joinpath("assets").iterdir():
        (assets / asset.name).write_bytes(asset.read_bytes())
    speech_edit_version = hashlib.sha256((assets / 'speech-edit.js').read_bytes()).hexdigest()[:12]
    subtitle_report_version = hashlib.sha256((assets / 'subtitle-report.js').read_bytes()).hexdigest()[:12]
    speech = sorted((source for source in sources if not source.image and source.text.strip()),
                    key=lambda source: (source.start, source.end))
    speech_file = speech_folder / "speech.json"
    recognition = json.loads(speech_file.read_text(encoding="utf-8")) if speech_file.is_file() else {}
    if edits_file.is_file():
        recognition["segments"] = edits["segments"]
    speaker_names = recognition.get("speaker_names", {})
    speakers = {(row["start"], row["end"]): row.get("speaker")
                for row in recognition.get("segments", [])}
    def vtt_time(seconds):
        milliseconds = round(seconds * 1000)
        return f"{clock(milliseconds // 1000)}.{milliseconds % 1000:03d}"
    for name, texts in [("original.vtt", {source.id: source.text for source in speech}),
                        ("ru.vtt", translations)]:
        cues = ["WEBVTT", ""]
        for index, source in enumerate(speech):
            if source.id in texts and texts[source.id].strip() and source.end > source.start:
                # Escape VTT markup while preserving the recognized words.
                text = html.escape(texts[source.id]).replace("\n\n", "\n")
                end = source.end
                if name == "ru.vtt":
                    for following in speech[index + 1:]:
                        if following.id not in texts or texts[following.id].strip():
                            break
                        end = max(end, following.end)
                cues.extend([source.id,
                             f"{vtt_time(source.start)} --> {vtt_time(end)}", text, ""])
        (folder / name).write_text("\n".join(cues), encoding="utf-8")
    by_id = {source.id: source for source in sources}
    video_url = quote(Path(os.path.relpath(video, folder)).as_posix(), safe="/")
    markdown = [f"# {video.stem}", ""]
    sections = []
    navigation = []
    chapter_cards = []
    if chapters:
        markdown.extend(["## Разделы видео", "", "Границы разделов приблизительные.", ""])
        for chapter in chapters:
            label = html.escape(chapter.kind)
            display_title = chapter.quiz.question if chapter.quiz else chapter.title
            time_range = f"{clock(chapter.start)}–{clock(chapter.end)}"
            navigation.append(
                f'<li data-start="{chapter.start}" data-end="{chapter.end}">'
                f'<button data-time="{chapter.start}">{time_range}</button> '
                f'<span class="kind">{label}</span> {html.escape(display_title)}</li>'
            )
            markdown.extend([f"### [{time_range}] {display_title} ({chapter.kind})", "",
                             *[f"- {item}" for item in chapter.items], ""])
            body = ""
            if chapter.visual_evidence:
                body += f"<p>{html.escape(chapter.visual_evidence)}</p>"
                markdown.extend([chapter.visual_evidence, ""])
            if chapter.items:
                body += "<ol>" + "".join(
                    f"<li>{html.escape(item)}</li>" for item in chapter.items
                ) + "</ol>"
            if chapter.quiz:
                quiz = chapter.quiz
                answer = quiz.correct_option or "Не определён по источникам"
                markdown.extend([f"**Вопрос:** {quiz.question}", "", *[
                    f"- {option.label}: {option.text}" for option in quiz.options
                ], "", f"**Правильный ответ:** {answer}", "", quiz.explanation, ""])
                body += f"<p><strong>Вопрос:</strong> {html.escape(quiz.question)}</p><ul>"
                for option in quiz.options:
                    css = ' class="correct"' if option.label == quiz.correct_option else ""
                    body += f"<li{css}>{html.escape(option.label)}: {html.escape(option.text)}</li>"
                body += f"</ul><p><strong>Правильный ответ:</strong> {html.escape(answer)}</p>"
                if quiz.explanation:
                    body += f"<p>{html.escape(quiz.explanation)}</p>"
            chapter_cards.append(
                f'<section><h3><button data-time="{chapter.start}">{clock(chapter.start)}</button> '
                f'{html.escape(display_title)}</h3>{body}'
                + source_details([by_id[key] for key in chapter.source_ids]) + "</section>"
            )
    markdown.extend(["## Конспект", ""])
    for note in notes:
        evidence = [by_id[key] for key in note.source_ids]
        timestamp = min(source.start for source in evidence)
        markdown.extend([f"## [{clock(timestamp)}] {note.title}", "", note.explanation, ""])
        body = f"<p>{html.escape(note.explanation)}</p>"
        for title, items in [("Шаги", note.steps), ("Ограничения", note.limitations)]:
            if items:
                markdown.extend([f"### {title}", "", *[f"- {item}" for item in items], ""])
                body += f"<h3>{title}</h3><ul>" + "".join(
                    f"<li>{html.escape(item)}</li>" for item in items
                ) + "</ul>"
        for source in evidence:
            markdown.append(f"- Источник {source.id}: {clock(source.start)}")
        markdown.append("")
        sections.append(
            f'<section class="lecture-note" data-note-time="{timestamp}"><h2><button data-time="{timestamp}">{clock(timestamp)}</button> '
            f'{html.escape(note.title)}</h2>{body}' + source_details(evidence) + "</section>"
        )
    if not notes:
        sections.append("<p>Содержательные пункты не выделены. См. исходные источники.</p>")
    editor_seed = "\n".join(line for line in markdown if not line.startswith("- Источник "))
    if (speech_folder / 'construction-result.md').is_file():
        editor_seed = (speech_folder / 'construction-result.md').read_text(encoding='utf-8')
    (folder / "editor-default.md").write_text(editor_seed, encoding="utf-8")
    page = """<!doctype html><html lang="ru"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<link rel="stylesheet" href="assets/easymde.min.css">
<title>Video Descriptor</title>"""
    page += '<link rel="stylesheet" href="assets/editor.css">'
    try:
        display_title = lecture_info(folder)["display"]
    except (OSError, ValueError, KeyError):
        display_title = video.name
    page += '<nav class="vd-global-nav" aria-label="Основная навигация"><a href="/output/" aria-current="page">Записи</a><a href="/#settings">Настройки AI</a><a href="/#diagnostics">Диагностика</a></nav>'
    page += f'<h1 id="lecture-title">{html.escape(display_title)}</h1>'
    page += '<button id="rename-lecture">Изменить название</button>'
    page += '<form id="title-form" hidden><label>Название записи '
    page += '<input id="title-input" maxlength="200" placeholder="Например: Лекция AWS"></label> '
    page += '<button type="submit">Сохранить название</button> '
    page += '<button type="button" id="cancel-title">Отмена</button></form>'
    page += '<p id="title-status" role="status" hidden></p>'
    page += '<p>Конспект создан моделью. Проверяйте существенные детали по источникам.</p>'
    error_path = folder / "analysis-errors.json"
    errors = json.loads(error_path.read_text()) if error_path.exists() else []
    if errors:
        page += '<section role="alert">'
        page += '<strong>Конспект неполный: есть необработанные фрагменты.</strong><ul>'
        for error in errors:
            page += (f'<li>Блок {error["block"]}/{error["total_blocks"]}: '
                     f'<button data-time="{error["start"]}">{clock(error["start"])}</button>'
                     f'–{clock(error["end"])} — {html.escape(error["error"])}</li>')
        page += '</ul><p>Подробности и запросы сохранены в папке результата.</p></section>'
    page += '<div class="workspace"><aside class="watch-pane">'
    page += f'<div class="player"><video id="video" controls preload="metadata" src="{video_url}">'
    if speech:
        page += '<track kind="subtitles" src="original.vtt" srclang="en" label="Оригинал">'
        if translations:
            page += '<track kind="subtitles" src="ru.vtt" srclang="ru" label="Русский">'
    page += '</video><div id="caption" aria-live="off"></div>'
    page += '<p id="playback-status" role="status" hidden></p></div>'
    if speech:
        page += f'<section data-subtitle-folder="{html.escape(speech_folder.name, quote=True)}"><h2>Речь и перевод</h2><div class="subtitle-tools">'
        page += ('<label' + (' hidden' if not translations else '')
                 + '>Показать <select id="subtitle-mode"><option value="original">Оригинал</option>')
        if translations:
            page += '<option value="ru">Русский</option><option value="both" selected>Оба</option>'
        page += '</select></label><label><input id="follow" type="checkbox" checked>Следить за видео</label>'
        page += '<a href="original.vtt" download>Субтитры</a>'
        if translations:
            page += '<a href="ru.vtt" download>Перевод</a>'
        page += '</div><p>Нажмите на время реплики, чтобы перейти к ней.</p>'
        if not translations:
            page += '<p>Перевод пока не подготовлен.</p>'
        page += '<div class="transcript" id="transcript">'
        for source in speech:
            page += (f'<div class="utterance" data-start="{source.start}" data-end="{source.end}">'
                     f'<button data-time="{source.start}">{clock(source.start)}</button>')
            page += f'<button class="edit-reply" data-edit-subtitle="{html.escape(source.id, quote=True)}" title="Редактировать реплику" aria-label="Редактировать реплику {clock(source.start)}">✎</button>'
            speaker = speakers.get((source.start, source.end))
            if speaker:
                page += f'<strong> · {html.escape(speaker_names.get(speaker) or speaker)}</strong>'
            page += f'<p class="subtitle-original">{html.escape(source.text)}</p>'
            if source.id in translations:
                page += f'<p class="subtitle-ru">{html.escape(translations[source.id])}</p>'
            page += '</div>'
        page += '</div></section>'
    page += '</aside><main class="read-pane"><section id="personal-notes" data-editing="false">'
    page += '<div class="notes-toolbar"><button data-notes-view="read">Конспект</button>'
    page += '<button data-notes-view="edit">Редактировать</button>'
    page += '<button data-notes-view="model">Материал модели</button></div>'
    page += '<div class="notes-actions"><button id="save-notes" disabled>Сохранить</button>'
    page += '<button id="add-section">+ Раздел в этом месте</button>'
    page += '<span>Экспорт:</span><button id="download-notes">Markdown</button><button id="download-html">HTML</button>'
    page += '<button id="download-draft" hidden>Скачать старый черновик</button></div>'
    page += '<p id="editor-status" role="status">Открываем конспект…</p>'
    page += '<details id="outline-group" class="notes-fold"><summary>Оглавление</summary>'
    page += '<div id="personal-outline" aria-label="Оглавление конспекта"></div></details>'
    page += '<div id="personal-preview"></div><div id="editor-pane" hidden>'
    page += '<p>Заголовки с временем, например <code>## [00:05:30] Тема</code>, связываются с видео.</p>'
    page += '<textarea id="notes-editor" aria-label="Редактор конспекта"></textarea></div>'
    page += f'<textarea id="editor-seed" hidden>{html.escape(editor_seed)}</textarea></section>'
    page += '<div id="model-material" hidden>'
    if navigation:
        page += '<details class="notes-fold"><summary>Разделы видео</summary>'
        page += '<nav aria-label="Разделы видео"><h2>Разделы видео</h2>'
        page += '<p>Нажмите на время, чтобы перейти к разделу. Границы приблизительные.</p>'
        page += "<ul>" + "".join(navigation) + "</ul></nav>"
        page += "".join(chapter_cards)
        page += '</details>'
    page += "<h2>Конспект</h2>"
    page += "".join(sections)
    page += '</div></main></div>'
    page += """<script>
const video=document.getElementById('video');
const rows=Array.from(document.querySelectorAll('.utterance'));
const caption=document.getElementById('caption');
const transcript=document.getElementById('transcript');
const mode=document.getElementById('subtitle-mode');
let active=null;
function sync(){
  const time=video.currentTime;
  let low=0,high=rows.length-1,index=-1;
  while(low<=high){const mid=(low+high)>>1;
    if(Number(rows[mid].dataset.start)<=time){index=mid;low=mid+1;}else high=mid-1;
  }
  const next=index>=0&&time<Number(rows[index].dataset.end)?rows[index]:null;
  if(next!==active){
    if(active)active.classList.remove('active');
    active=next;caption.replaceChildren();
    if(active){
      active.classList.add('active');
      active.querySelectorAll('p').forEach(line=>caption.append(line.cloneNode(true)));
      if(document.getElementById('follow').checked){
        transcript.scrollTop=active.offsetTop-transcript.offsetTop-transcript.clientHeight/2;
      }
    }
  }
  document.querySelectorAll('nav li[data-start]').forEach(row=>{
    row.classList.toggle('active',time>=Number(row.dataset.start)&&time<Number(row.dataset.end));
  });
}
if(mode){document.body.dataset.subtitles=mode.value;
mode.addEventListener('change',()=>{document.body.dataset.subtitles=mode.value;});}
function followNotes(){
  const preview=document.getElementById('personal-preview');
  const material=document.getElementById('model-material');
  const container=preview&&!preview.hidden?preview:material&&!material.hidden?material:null;
  if(!container)return;
  const notes=Array.from(container.querySelectorAll('[data-note-time]'));
  if(!notes.length)return;
  const time=video.currentTime;
  let target=null;
  for(const note of notes){
    const start=Number(note.dataset.noteTime);
    if(start<=time&&(!target||start>Number(target.dataset.noteTime)))target=note;
  }
  if(!target)target=notes.reduce((first,note)=>Number(note.dataset.noteTime)<Number(first.dataset.noteTime)?note:first);
  notes.forEach(note=>note.classList.toggle('current-note',note===target));
  for(let parent=target.parentElement;parent&&parent!==container;parent=parent.parentElement){
    if(parent.tagName==='DETAILS')parent.open=true;
  }
  target.scrollIntoView({behavior:'smooth',block:'start'});
}
video.addEventListener('timeupdate',sync);
video.addEventListener('seeked',()=>{sync();followNotes();});
const status=document.getElementById('playback-status');
let pendingTime=null;
function seekTo(time){
  pendingTime=time;
  if(video.readyState===0){
    status.hidden=false;status.textContent='Загружаем видео для перехода…';
    video.preload='auto';video.load();return;
  }
  pendingTime=null;
  video.currentTime=Math.min(time,Number.isFinite(video.duration)?video.duration:time);
  status.hidden=true;
  sync();
  video.play().catch(()=>{
    status.hidden=false;status.textContent='Нажмите ▶ в плеере, чтобы начать воспроизведение.';
  });
}
video.addEventListener('loadedmetadata',()=>{if(pendingTime!==null)seekTo(pendingTime);});
video.addEventListener('error',()=>{
  status.hidden=false;status.textContent='Не удалось загрузить видео. Откройте отчёт через локальный сервер.';
});
document.addEventListener('click',event=>{
  const button=event.target.closest('[data-time]');
  if(button){const time=Number(button.dataset.time);if(Number.isFinite(time)&&time>=0)seekTo(time);}
});</script>
<script src="assets/easymde.min.js"></script>
<script src="assets/purify.min.js"></script>
<script src="assets/editor.js"></script>
<script src="assets/speech-edit.js?v=__SPEECH_EDIT_VERSION__"></script>
<script src="assets/subtitle-report.js?v=__SUBTITLE_REPORT_VERSION__"></script></html>"""
    page = page.replace('__SPEECH_EDIT_VERSION__', speech_edit_version).replace('__SUBTITLE_REPORT_VERSION__', subtitle_report_version)
    (folder / "report.html").write_text(page, encoding="utf-8")
    if write_markdown:
        (folder / "notes.md").write_text("\n".join(markdown), encoding="utf-8")
