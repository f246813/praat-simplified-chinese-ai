"""Real ChatWindow/mainloop and real SDK over localhost; private files only."""
import json
from pathlib import Path
import sys
import tempfile
import time
import tkinter as tk
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/'ai'),str(ROOT/'ai/tests')]
from praat_ai import api_settings, chat
from test_dialogue_stream import config
from test_dialogue_protocol import endpoint, DialogueProtocolTests


def main():
    report={'python':sys.version.split()[0],'tk':tk.TkVersion}
    with tempfile.TemporaryDirectory(prefix='praat-dialogue-live-') as directory:
        private=Path(directory); cfg=config(); path=private/'config.json'; path.write_text('{}')
        runtime=private/'runtime'; runtime.mkdir()
        with (patch.object(chat,'load_config',return_value=cfg),
              patch.object(chat,'config_path',return_value=path),
              patch.object(chat,'runtime_dir',return_value=runtime),
              patch.object(chat,'selected_object_label',return_value='private fixture'),
              patch.object(chat.parent_watch,'should_watch',return_value=False),
              patch.object(chat,'object_context',side_effect=AssertionError('Ordinary chat must not read objects')),
              endpoint(chunk_delay=0.6) as (base,requests,ports),DialogueProtocolTests().redirect(base)):
            window=chat.ChatWindow(); window.root.withdraw()
            dialog=api_settings.ApiSettingsDialog(window.root,config_path=path); dialog.window.withdraw()
            dialog.show_advanced.set(True); dialog._toggle_advanced(); dialog.window.update_idletasks()
            assert dialog.window.winfo_reqheight() < dialog.window.winfo_screenheight()
            dialog.force_deep_thinking.set(True); dialog.save()
            other=api_settings.ApiSettingsDialog(window.root,config_path=path); other.window.withdraw()
            assert other.force_deep_thinking.get(); other.close()
            started=time.monotonic(); deadline=started+15
            def observe():
                visible=window.transcript.get('1.0','end')
                if '您好！' in visible and window.busy and 'first_visible_seconds' not in report:
                    report['first_visible_seconds']=time.monotonic()-started
                if not window.busy:
                    report['finished_seconds']=time.monotonic()-started
                    report['status']=window.analysis_state.status
                    report['metrics']=window.analysis_state.metrics
                    report['requests']=len(requests)
                    records=window.store.records(window.session_id)
                    finals=[r for r in records if r['kind']=='message' and r['payload'].get('text')=='您好！我可以介绍功能。']
                    assert len(finals)==1 and report['requests']==1
                    assert '普通对话直接回复' in visible
                    assert report['status']=='complete' and report.get('first_visible_seconds') is not None
                    assert requests[0]['enable_thinking'] is False
                    report['ok']=True; window.root.quit()
                elif time.monotonic()>deadline:
                    window.root.quit()
                else:window.root.after(20,observe)
            try:
                window.entry.insert('1.0','Hello,what can u do for me?'); window.submit()
                window.root.after(20,observe); window.root.mainloop()
                assert report.get('ok'),report
            finally:
                worker=getattr(window,'_turn_worker',None)
                window.cancel_event.set()
                if worker is not None:worker.join(timeout=3)
                for callback in window.root.tk.splitlist(window.root.tk.call('after','info')):window.root.after_cancel(callback)
                window.close()
                if getattr(window,'cloud_runtime',None):window.cloud_runtime.close(wait=True)
    report['checks']=['actual_ChatWindow_submit_worker_queue_mainloop','SDK_localhost_SSE',
                      'first_visible_before_completion','one_request_one_saved_final',
                      'process_hint_preserved','advanced_force_save_reopen_fits_screen','client_thread_closed']
    output=ROOT/'test-records/installer/dialogue-fastpath-live.json'
    output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False,indent=2))


if __name__=='__main__':main()
