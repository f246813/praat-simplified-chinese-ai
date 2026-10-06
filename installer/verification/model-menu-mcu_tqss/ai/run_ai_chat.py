
import json, threading, time
from pathlib import Path
from praat_ai import modern_host
root = Path(__file__).resolve().parent / 'runtime'
original = modern_host.create_window
def create_window(*args, **kwargs):
    window, server = original(*args, **kwargs)
    def probe():
        previous = ''
        while True:
            try:
                action = root / 'probe-action.json'
                if action.exists():
                    raw = json.loads(action.read_text(encoding='utf8'))
                    if raw['id'] != previous:
                        window.evaluate_js(raw['script'])
                        previous = raw['id']
                result = window.evaluate_js("""(()=>({
                    heading:document.querySelector('.settings-main h1')?.textContent,
                    category:document.querySelector('.settings-nav [aria-current=page]')?.textContent,
                    api:Array.from(document.querySelectorAll('.segmented button')).find(b=>b.textContent==='云端 API')?.getAttribute('aria-pressed'),
                    model:document.querySelector('input[aria-label=模型名]')?.value,
                    chat:!document.querySelector('.settings-dashboard')&&!!document.querySelector('.app'),
                    action:""" + json.dumps(previous) + """
                }))()""")
                from praat_ai.desktop_launch import write_record
                write_record(root / 'probe.json', result)
            except Exception:
                pass
            time.sleep(.15)
    window.events.loaded += lambda: threading.Thread(target=probe, daemon=True).start()
    return window, server
modern_host.create_window = create_window
raise SystemExit(modern_host.main())
