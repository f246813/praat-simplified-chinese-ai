"""Launch from the real Sound editor menu with an isolated Praat profile."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

from verify_path_settings_live import children, command, menu, press, text, user32, wait, windows


def main():
    project = Path(__file__).resolve().parents[2]
    executable = Path(sys.argv[1]).resolve()
    report = {'checks': [], 'executable': str(executable)}
    with tempfile.TemporaryDirectory(prefix='praat-dictionary-menu-') as directory:
        root = Path(directory)
        profile = root / 'profile'; profile.mkdir()
        ai = project / 'ai'
        (profile / 'Preferences.txt').write_text('Python.executablePath: ' + sys.executable +
            '\nAI.projectDirectory: ' + str(ai) + '\n', encoding='utf-8')
        config = root / 'config.json'; config.write_text('{}', encoding='utf-8')
        script = root / 'editor.praat'
        script.write_text('Create Sound from formula: "dictionary-menu-test", 1, 0, 0.2, 44100, ~sin(2*pi*220*x)\nView & Edit\n', encoding='utf-8')
        environment = dict(os.environ, PRAAT_AI_PROJECT_DIR=str(ai), PRAAT_AI_CONFIG_PATH=str(config),
                           PRAAT_PYTHON_EXECUTABLE=sys.executable)
        before = {w[0] for w in windows()}
        process = subprocess.Popen([str(executable), '--new-send', '--no-plugins',
                                   '--pref-dir=' + str(profile), str(script)], env=environment)
        try:
            editor = wait(lambda: next((w for w in windows() if w[1] == process.pid and 'dictionary-menu-test' in w[2]), None), 'isolated Sound editor')
            number = command(editor[0], ('管理语音词典与模型',))
            labels = next(items for items in menu(editor[0]) if any(n == number for _, n in items))
            assert any(label == 'MFA' for label, _ in labels)
            assert any(label == 'wav2vec2' for label, _ in labels)
            report['checks'].append('Chinese_dictionary_command_in_alignment_menu')
            press(editor[0], number)
            dictionary_window = wait(lambda: next((w for w in windows() if w[0] not in before and w[2] == '管理语音词典与模型'), None), 'dictionary window', 30)
            assert process.poll() is None
            report['checks'].append('native_menu_opens_detached_assistant_window')
            # Close only the isolated test parent; its bound child should close itself.
            process.terminate(); process.wait(timeout=5)
            wait(lambda: not any(w[0] == dictionary_window[0] for w in windows()), 'parent-bound dictionary window closure')
            report['checks'].append('dictionary_window_closes_with_bound_Praat_parent')
            assert config.read_text(encoding='utf-8') == '{}'
            report['checks'].append('menu_opening_does_not_modify_configuration')
        except Exception as error:
            report['error'] = str(error)
            report['windows'] = [(w, [text(child) for child in children(w[0])]) for w in windows() if w[0] not in before]
            raise
        finally:
            if process.poll() is None: process.terminate(); process.wait(timeout=5)
            (project / 'test-records' / 'installer' / 'speech-dictionaries-menu.json').write_text(
                json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
