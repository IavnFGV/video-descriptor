"""Export the current original and translated subtitle tracks."""

import html


def plain_transcript(result):
    names = result.get('speaker_names', {})
    lines = []
    for row in result['segments']:
        seconds = int(row['start'])
        time = f"{seconds // 3600:02}:{seconds // 60 % 60:02}:{seconds % 60:02}"
        speaker = row.get('speaker', '')
        name = names.get(speaker) or speaker
        label = f" {name}:" if name and name != 'unknown' else ''
        lines.append(f"[{time}]{label} {row['text']}")
    return '\n'.join(lines)


def webvtt(result, language="original"):
    def stamp(seconds):
        ms = round(seconds * 1000)
        return f"{ms // 3600000:02}:{ms // 60000 % 60:02}:{ms // 1000 % 60:02}.{ms % 1000:03}"

    cues = ["WEBVTT", ""]
    segments = result["segments"]
    translations = result.get("translations", {})
    for index, row in enumerate(segments, 1):
        id = row.get("id", f"s{index}")
        text = row["text"] if language == "original" else translations.get(id, "")
        end = row["end"]
        if language == "ru":
            for next_index, following in enumerate(segments[index:], index + 1):
                next_id = following.get("id", f"s{next_index}")
                if next_id not in translations or translations[next_id].strip():
                    break
                end = max(end, following["end"])
        if text.strip() and end > row["start"]:
            cues.extend([id, f"{stamp(row['start'])} --> {stamp(end)}",
                         html.escape(text).replace("\n\n", "\n"), ""])
    return "\n".join(cues)


def subrip(result, language='original'):
    """Share cue selection/translated grouping with VTT; preserve stable IDs in JSON."""
    lines = webvtt(result, language).splitlines()[2:]
    cues, current = [], []
    for line in [*lines, '']:
        if line:
            current.append(line)
        elif current:
            cues.append(current)
            current = []
    return '\n\n'.join('\n'.join([str(index), cue[1].replace('.', ','), *cue[2:]])
                         for index, cue in enumerate(cues, 1)) + ('\n' if cues else '')
