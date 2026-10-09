"""Check the production empty layout in WebView2 with isolated host data."""
import json
from pathlib import Path
import sys
import tempfile
import time
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import webview
from praat_ai.modern_app import ModernApplication
from praat_ai.modern_host import create_window
from praat_ai import modern_budget


class NoExecution:
    def capture_target(self, text):
        raise AssertionError('Unexpected Praat capture')

    def run(self, **kwargs):
        raise AssertionError('Unexpected executor call')


output = Path(__file__).resolve().parents[2] / 'test-records/installer'
result = dict(realWebView2=True, productionAssets=True, samples=[])
with tempfile.TemporaryDirectory() as temporary:
    root = Path(temporary)
    config = root / 'config.json'
    config.write_text('{}', encoding='utf8')
    app = ModernApplication(root / 'modern', config, executor=NoExecution())
    window, assets = create_window(app)

    def check():
        def js(code):
            return window.evaluate_js(code)

        def wait(code):
            deadline = time.monotonic() + 15
            while time.monotonic() < deadline:
                if js(code):
                    return
                time.sleep(.1)
            raise AssertionError('Timed out: ' + code)

        try:
            wait('document.querySelector(".welcome") && document.querySelector(".tiptap")')
            for expanded in [False, True]:
                if expanded:
                    js('document.querySelector("[aria-label=展开会话侧栏]").click()')
                for width, height in [(900, 640), (800, 600), (1280, 850), (1600, 1000)]:
                    window.resize(width, height)
                    time.sleep(.25)
                    sample = js('''(()=>{const el=document.querySelector('.transcript'), composer=document.querySelector('.composer').getBoundingClientRect(), welcome=document.querySelector('.welcome').getBoundingClientRect();el.scrollTop=10000;return {width:innerWidth,height:innerHeight,client:el.clientHeight,scroll:el.scrollHeight,top:el.scrollTop,composerBottom:composer.bottom,welcomeTop:welcome.top,welcomeBottom:welcome.bottom};})()''')
                    sample['expanded'] = expanded
                    result['samples'].append(sample)
                    print(json.dumps(sample), flush=True)
                    assert sample['client'] == sample['scroll'] and sample['top'] == 0, sample
                    assert sample['composerBottom'] <= sample['height'], sample
                    assert sample['welcomeBottom'] <= sample['composerBottom'], sample
            js('Array.from(document.querySelectorAll(".welcome-cards button")).find(el=>el.textContent==="计算VOT").click()')
            wait('document.querySelector(".tiptap").textContent === "计算VOT"')
            assert not app.tasks
            result.update(passed=True, userAgent=js('navigator.userAgent'))
        except Exception as error:
            result.update(passed=False, error=repr(error))
        finally:
            window.destroy()

    with patch.object(modern_budget, 'text_request', side_effect=AssertionError('Unexpected model request')) as request:
        try:
            webview.start(check, gui='edgechromium', private_mode=True, storage_path=str(root / 'profile'))
            assert request.call_count == 0
        finally:
            app.close()
            assets.close()

(output / 'chat-empty-layout-webview.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf8')
print(json.dumps(result, ensure_ascii=False, indent=2))
raise SystemExit(0 if result.get('passed') else 1)
