"""Execute the native smoke's actual JS predicate; not WebView2 acceptance."""
import json
import re
import subprocess
from pathlib import Path

import pytest


@pytest.mark.parametrize('mutation,expected', [
    ('', []),  # Settings navigation has no inline onclick in the shared shell.
    ("delete elements['download-consent']", ['download-consent']),
    ("elements['probe-model'].onclick = null", ['probe-model.onclick']),
    ("elements['gemini-form'].onsubmit = null", ['gemini-form.onsubmit']),
    ("elements['setup-finish'].onclick = null", ['setup-finish.onclick']),
    ("elements['setup-open'].href = '/#records'", ['setup-open route']),
    ("elements['setup-open'].href = 'https://example.invalid/#settings'", ['setup-open route']),
    ("elements['setup-open'].href = '/?job=stale#settings'", ['setup-open route']),
    ("delete elements['setup-open']", ['setup-open route']),
    ("delete elements['setup-open'].dataset.desktopCommand", ['setup-open route']),
])
def test_native_smoke_checks_shell_route_and_actual_setup_handlers(mutation, expected):
    source = (Path(__file__).resolve().parents[1] / 'windows-app/DesktopHost.cs').read_text(encoding='utf-8')
    predicate = re.search(r'const string SetupSmokeCheck = @"(.*?)";', source, re.DOTALL).group(1)
    script = """
        const elements = Object.fromEntries(['setup-wizard','download-consent','probe-model',
            'gemini-form','setup-finish','setup-open'].map(id => [id, {}]));
        for (const id of ['probe-model','setup-finish']) elements[id].onclick = () => {};
        elements['gemini-form'].onsubmit = () => {};
        elements['setup-open'] = {dataset:{desktopCommand:'settings'}, href:'/#settings',
            getAttribute(name){return this[name]}};
        const document = {getElementById(id){return elements[id] || null}};
        const location = {href:'http://127.0.0.1:1234/', origin:'http://127.0.0.1:1234'};
    """ + mutation + ';\nconsole.log(JSON.stringify(' + predicate + '));'
    result = subprocess.run(['node', '-e', script], check=True, capture_output=True, text=True)
    assert json.loads(result.stdout) == expected
