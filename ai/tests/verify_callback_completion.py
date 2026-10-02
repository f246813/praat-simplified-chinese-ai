"""隔离用户目录/对象/消息文件验证新版 Praat 的回调完成确认，不调用模型。"""
import os
import subprocess
import tempfile
import time
from pathlib import Path
from unittest.mock import patch

from praat_ai import chat, sendpraat, tools


def main():
    # 2026-09-30 起新版已经覆盖成仓库根目录的 Praat.exe，这里跟着改名；仍然允许用
    # PRAAT_AI_PRAAT_EXECUTABLE 指定别的构建来做对照。
    executable = Path(
        os.getenv("PRAAT_AI_PRAAT_EXECUTABLE", "").strip()
        or (Path(__file__).resolve().parents[2] / "Praat.exe")
    )
    with tempfile.TemporaryDirectory(prefix='praat-callback-') as directory:
        base = Path(directory)
        project = base / 'ai'
        runtime = project / 'runtime'
        runtime.mkdir(parents=True)
        roaming = base / 'user' / 'AppData' / 'Roaming'
        (roaming / 'Praat').mkdir(parents=True)
        env = dict(os.environ, USERPROFILE=str(base / 'user'), APPDATA=str(roaming), PRAAT_AI_PROJECT_DIR=str(project))
        startup = subprocess.STARTUPINFO()
        startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startup.wShowWindow = 0
        init = base / 'init.praat'
        init.write_text('a = 1\n', encoding='utf-8')
        process_log = (base / 'process.log').open('wb')
        process = subprocess.Popen([str(executable), '--new-send', '--FULL-TRUST', '--no-pref-files', '--no-plugins', '--hide-picture', str(init)],
                                   env=env, startupinfo=startup, stdout=process_log, stderr=process_log)
        try:
            deadline = time.monotonic() + 15
            while time.monotonic() < deadline:
                if sendpraat.choose_window(sendpraat.praat_windows(), process.pid):
                    break
                if process.poll() is not None:
                    process_log.flush()
                    detail = chat._decode_console((base / 'process.log').read_bytes())
                    raise RuntimeError(f'isolated Praat exited: {process.returncode}: {detail}')
                time.sleep(0.05)
            else:
                raise RuntimeError('isolated Praat did not open its message window')
            with patch.dict(os.environ, {'APPDATA': str(roaming)}), patch.object(chat, 'runtime_dir', return_value=runtime), patch.object(chat, 'ai_directory', return_value=project):
                def send(script):
                    ok, note = chat._send_script(str(executable), script, process_id=process.pid)
                    if not ok:
                        raise RuntimeError(note)
                    return chat._read_failure()

                assert not send('Create Sound from formula: "tone", 1, 0, 1, 44100, ~ 0.5*sin(2*pi*220*x)\nTo Harmonicity (cc): 0.01, 75, 0.1, 1\n' + chat.context_ping_script())
                assert '# praat-protocol=2' in chat.object_context()
                # 故意提前写旧 done，最终选择/改名必须在确认返回前完成。
                assert not send(chat.context_ping_script() + 'selectObject: 1\nRename: "renamed"\n')
                rows = tools.parse_object_context(chat.object_context())
                assert rows[0].selected and 'renamed' in rows[0].name
                print('PASS: early done waits for final object context')
                failure = send('selectObject: 2\nTo Pitch: 0, 75, 600\n')
                assert 'To Pitch:' in failure
                print('PASS: callback failure is visible before completion')
                for tool in ('pitch_statistics', 'intensity_statistics', 'formant_statistics'):
                    context = tools.ToolContext(tools.parse_object_context(chat.object_context()), chat.result_path(), chat.state_path())
                    assert not send(tools.render(tool, {'object': 1}, context))
                    assert chat._read_results()
                    print(f'PASS: {tool} on Sound after failed Harmonicity conversion')
        finally:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
            process_log.close()


if __name__ == '__main__':
    main()
