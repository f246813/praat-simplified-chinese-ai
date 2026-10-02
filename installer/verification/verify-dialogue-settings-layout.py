"""Realized advanced settings layout, using an invisible private test window."""
import json
from pathlib import Path
import sys
import tempfile
import tkinter as tk

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'ai'))
from praat_ai import api_settings, ui_windows


def main():
    with tempfile.TemporaryDirectory(prefix='praat-dialogue-layout-') as directory:
        path=Path(directory)/'config.json'; path.write_text('{}')
        root=ui_windows.create_root(); root.withdraw()
        dialog=api_settings.ApiSettingsDialog(root,config_path=path)
        dialog.window.attributes('-alpha',0.0)
        dialog.window.deiconify()
        try:
            dialog.show_advanced.set(True); dialog._toggle_advanced()
            for _ in range(3):root.update()
            dialog.canvas.yview_moveto(1.0); root.update()
            button=next(w for w in dialog.test_button.master.winfo_children() if getattr(w,'_text','')=='保存')
            top=button.winfo_rooty()-dialog.canvas.winfo_rooty()
            assert dialog.window.winfo_height() < dialog.window.winfo_screenheight()
            assert top>=0 and top+button.winfo_height()<=dialog.canvas.winfo_height()
            report={'python':sys.version.split()[0],'tk':tk.TkVersion,'ok':True,
                    'window_height':dialog.window.winfo_height(),'screen_height':dialog.window.winfo_screenheight(),
                    'viewport_height':dialog.canvas.winfo_height(),'save_top_in_viewport':top,
                    'save_bottom_in_viewport':top+button.winfo_height(),'scroll_position':dialog.canvas.yview()}
        finally:
            dialog.close(); root.update_idletasks()
            for callback in root.tk.splitlist(root.tk.call('after','info')):root.after_cancel(callback)
            root.destroy()
    print(json.dumps(report,indent=2))


if __name__=='__main__':main()
