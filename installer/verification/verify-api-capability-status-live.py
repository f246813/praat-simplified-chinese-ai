"""Real Tk mainloop / background audio probe; fixture model raises the reported 400."""
import json
from pathlib import Path
import sys
import tempfile
import time
import tkinter as tk
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'ai'))
from pydantic_ai.exceptions import ModelHTTPError
from pydantic_ai.models.function import FunctionModel
from praat_ai import api_settings, ui_windows


def main():
    report={'checks':[], 'python':sys.version.split()[0], 'tk':tk.TkVersion}
    with tempfile.TemporaryDirectory(prefix='praat-api-status-') as directory:
        path=Path(directory)/'config.json'
        path.write_text(json.dumps({'api':{'enabled':True,'base_url':'https://dashscope.aliyuncs.com/compatible-mode/v1',
                                           'model':'qwen3.7-flash','api_key':'fixture-secret'}}),encoding='utf-8')
        root=ui_windows.create_root(); root.withdraw()
        dialog=api_settings.ApiSettingsDialog(root,config_path=path); dialog.window.withdraw()
        deadline=time.monotonic()+15
        def reject(messages,info):
            raise ModelHTTPError(400,'qwen3.7-flash',body={'message':'The provided URL does not appear to be valid. Ensure it is correctly formatted.'})
        def observe():
            text=dialog.audio_hint.get()
            if '未能验证' in text:
                report.update(ok=True, visible_label=text, footer=dialog.status.get(),
                              label_required_height=dialog.audio_hint_label.winfo_reqheight(),
                              window_required_height=dialog.window.winfo_reqheight(),
                              screen_height=dialog.window.winfo_screenheight())
                report['checks']=['real_Tk_mainloop','background_probe_SDK_400',
                                  'short_code_model_before_preset_and_test','readonly_redacted_details','fits_screen_height']
                assert text.startswith('status code: 400 · model: qwen3.7-flash')
                assert '不支持直接音频输入（官方文档）' in text and '资源 URL' in text
                assert report['window_required_height'] < report['screen_height']
                assert dialog.audio_hint_label.cget('text')==text
                dialog.show_diagnostic_details()
                detail=next(w for w in dialog.window.winfo_children() if w.winfo_class()=='Toplevel')
                detail.withdraw()
                def texts(widget):
                    return ([widget] if widget.winfo_class()=='Text' else [])+[t for w in widget.winfo_children() for t in texts(w)]
                body=texts(detail)[0]
                assert body.cget('state')=='disabled' and 'fixture-secret' not in body.get('1.0','end')
                detail.destroy(); root.quit()
            elif time.monotonic()>deadline:
                report.update(ok=False,error='Timed out: '+text); root.quit()
            else: root.after(30,observe)
        try:
            with patch('praat_ai.cloud_agent.create_model',return_value=FunctionModel(reject)):
                dialog.test_audio(); root.after(30,observe); root.mainloop()
            assert report.get('ok'),report
        finally:
            dialog.close(); root.update_idletasks(); root.destroy()
            (ROOT/'test-records/installer/api-capability-status-live.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False,indent=2))


if __name__=='__main__': main()
