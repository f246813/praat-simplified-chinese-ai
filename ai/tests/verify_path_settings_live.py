"""Exercise real editor menu, path dialog, save/cancel, and Python preference IPC.

Runs an isolated Praat with temporary preferences and synthetic AI configuration.
Usage: python ai/tests/verify_path_settings_live.py path/to/Praat.exe
"""
from __future__ import annotations
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

user32=ctypes.windll.user32
callback=ctypes.WINFUNCTYPE(wintypes.BOOL,wintypes.HWND,wintypes.LPARAM)
user32.GetWindowThreadProcessId.argtypes=[wintypes.HWND,ctypes.POINTER(wintypes.DWORD)]
user32.GetMenu.argtypes=[wintypes.HWND];user32.GetMenu.restype=wintypes.HMENU
user32.GetSubMenu.argtypes=[wintypes.HMENU,ctypes.c_int];user32.GetSubMenu.restype=wintypes.HMENU
user32.GetMenuItemCount.argtypes=[wintypes.HMENU]
user32.GetMenuItemID.argtypes=[wintypes.HMENU,ctypes.c_int]
user32.GetMenuStringW.argtypes=[wintypes.HMENU,ctypes.c_uint,wintypes.LPWSTR,ctypes.c_int,ctypes.c_uint]
user32.SendMessageW.argtypes=[wintypes.HWND,ctypes.c_uint,wintypes.WPARAM,wintypes.LPARAM]
user32.SendMessageW.restype=wintypes.LPARAM
user32.PostMessageW.argtypes=[wintypes.HWND,ctypes.c_uint,wintypes.WPARAM,wintypes.LPARAM]
user32.IsWindowEnabled.argtypes=[wintypes.HWND]
user32.GetWindowRect.argtypes=[wintypes.HWND,ctypes.POINTER(wintypes.RECT)]

def text(hwnd):
    buffer=ctypes.create_unicode_buffer(2048)
    user32.SendMessageW(hwnd,0xD,len(buffer),ctypes.cast(buffer,ctypes.c_void_p).value)
    return buffer.value

def class_name(hwnd):
    buffer=ctypes.create_unicode_buffer(256);user32.GetClassNameW(hwnd,buffer,len(buffer));return buffer.value

def windows():
    result=[]
    @callback
    def collect(hwnd,_):
        pid=wintypes.DWORD();user32.GetWindowThreadProcessId(hwnd,ctypes.byref(pid))
        if user32.IsWindowVisible(hwnd):result.append((int(hwnd),pid.value,text(hwnd)))
        return True
    user32.EnumWindows(collect,0);return result

def children(hwnd):
    result=[]
    @callback
    def collect(child,_):
        result.append(int(child));return True
    user32.EnumChildWindows(hwnd,collect,0);return result

def wait(predicate,label,timeout=15):
    deadline=time.monotonic()+timeout
    while time.monotonic()<deadline:
        value=predicate()
        if value:return value
        time.sleep(.05)
    raise AssertionError("Timeout: "+label)

def menu(hwnd):
    result=[];bar=user32.GetMenu(hwnd)
    for i in range(user32.GetMenuItemCount(bar)):
        sub=user32.GetSubMenu(bar,i)
        if not sub:continue
        labels=[]
        for j in range(user32.GetMenuItemCount(sub)):
            buffer=ctypes.create_unicode_buffer(256);user32.GetMenuStringW(sub,j,buffer,256,0x400)
            labels.append((buffer.value,user32.GetMenuItemID(sub,j)))
        result.append(labels)
    return result

def command(hwnd,wanted):
    for labels in menu(hwnd):
        for label,number in labels:
            if any(word in label for word in wanted):return number
    raise AssertionError("Menu command missing: "+str(wanted))

def press(hwnd,number):
    assert user32.PostMessageW(hwnd,0x111,number,0)

def button(hwnd,label):
    return next(child for child in children(hwnd) if text(child)==label)

def edits(hwnd):
    result=[child for child in children(hwnd) if "EDIT" in class_name(child).upper()]
    def top(child):
        rect=wintypes.RECT();user32.GetWindowRect(child,ctypes.byref(rect));return rect.top
    return sorted(result,key=top)

def set_text(hwnd,value):
    buffer=ctypes.create_unicode_buffer(value);user32.SendMessageW(hwnd,0xC,0,ctypes.cast(buffer,ctypes.c_void_p).value)

def click(hwnd):
    user32.PostMessageW(hwnd,0xF5,0,0)

def main():
    executable=Path(sys.argv[1]).resolve() if len(sys.argv)>1 else Path(__file__).resolve().parents[2]/"Praat.exe"
    project=Path(__file__).resolve().parents[2]
    fixture=Path(tempfile.mkdtemp(prefix="AIPraat-live-paths-"));(fixture/"ai").mkdir()
    profile=fixture/"home"/"AppData"/"Roaming"/"Praat";profile.mkdir(parents=True)
    configuration={"api":{"enabled":False,"api_key":"fixture-only"},"server":{"model_path":"D:/fixture-model.gguf","llama_server":"","mmproj_path":"","auto_start":False,"presets":[],"active_preset":""},"qwen":{"vision_when_requested":False}}
    config=fixture/"ai"/"ai_config.json";config.write_text(json.dumps(configuration),encoding="utf-8")
    preferences=profile/"Preferences.txt";preferences.write_text("Python.executablePath: missing-python\nAI.projectDirectory: "+str(fixture/"ai")+"\n",encoding="utf-8")
    (fixture/"install-settings.json").write_text('{"python_path":"missing-python","fixture":true}',encoding="utf-8")
    script=fixture/"open-editor.praat";script.write_text('Create Sound from formula: "path-test", 1, 0, 0.2, 44100, ~sin(2*pi*220*x)\nView & Edit\n',encoding="utf-8")
    environment=dict(os.environ);environment["PRAAT_AI_PROJECT_DIR"]=str(fixture/"ai");environment["PRAAT_AI_CONFIG_PATH"]=str(config);environment["PRAAT_PYTHON_EXECUTABLE"]="missing-python"
    environment["USERPROFILE"]=str(fixture/"home")
    process=subprocess.Popen([str(executable),"--new-send","--no-plugins",f"--pref-dir={profile}",str(script)],env=environment)
    report={"executable":str(executable),"fixture":str(fixture),"checks":[]}
    checks=report["checks"]
    def passed(name):checks.append(name);print("PASS "+name,flush=True)
    def path_window():return next((w for w in windows() if w[2]=="AIPraat 路径配置"),None)
    try:
        editor=wait(lambda:next((w for w in windows() if w[1]==process.pid and "path-test" in w[2]),None),"sound editor")
        objects=wait(lambda:next((w for w in windows() if w[1]==process.pid and ("Objects" in w[2] or "对象" in w[2])),None),"objects window")
        path_command=command(editor[0],("路径配置","Path configuration"))
        for labels in menu(editor[0]):
            for i,(label,number) in enumerate(labels):
                if number==path_command:
                    assert i>0 and any(x in labels[i-1][0] for x in ("添加模型路径","Add model path")),labels
        passed("path_menu_immediately_below_add_model")
        press(editor[0],path_command);dialog=wait(path_window,"path dialog with invalid Python")
        inputs=edits(dialog[0]);assert len(inputs)==7,len(inputs)
        assert text(inputs[0])=="missing-python" and not user32.IsWindowEnabled(button(dialog[0],"保存")),[text(x) for x in inputs]
        assert process.poll() is None
        passed("dialog_opens_without_usable_python_with_seven_path_fields")
        before=config.read_bytes();click(button(dialog[0],"取消"));wait(lambda:not path_window(),"cancel")
        assert config.read_bytes()==before;passed("cancel_leaves_configuration_unchanged")
        press(editor[0],path_command);dialog=wait(path_window,"reopened path dialog");inputs=edits(dialog[0])
        set_text(inputs[0],sys.executable)
        wait(lambda:user32.IsWindowEnabled(button(dialog[0],"保存")),"Python capability probe",30)
        passed("valid_python_enables_save")
        click(button(dialog[0],"保存"));wait(lambda:not path_window(),"save closes dialog",30)
        saved=json.loads(config.read_text(encoding="utf-8"));assert saved["server"]["model_path"]==configuration["server"]["model_path"] and saved["api"]==configuration["api"] and not saved["server"]["auto_start"]
        assert json.loads((fixture/"install-settings.json").read_text())["python_path"]==sys.executable
        passed("save_keeps_model_api_flags_and_updates_installation")
        # This independent Praat settings form reads the current in-memory Python getter.
        # It does not invoke the path menu or refresh AI status, so it catches broken polling.
        time.sleep(.7)
        press(objects[0],command(objects[0],("Python 设置","Python settings")))
        native=wait(lambda:next((w for w in windows() if w[1]==process.pid and ("Python settings" in w[2] or "Python 设置" in w[2])),None),"native Python settings")
        values=[text(child) for child in edits(native[0])]
        assert sys.executable in values,"Current Praat still uses old Python: "+repr(values)
        passed("saved_python_applied_to_current_praat_within_one_second")
        user32.PostMessageW(native[0],0x10,0,0)
        press(editor[0],path_command);dialog=wait(path_window,"saved paths refill")
        assert text(edits(dialog[0])[0])==sys.executable;passed("saved_python_refills_on_reopen")
        # Closing only this test Praat also closes its standalone path dialog.
        user32.PostMessageW(objects[0],0x10,0,0)
        confirmation=wait(lambda:next((w for w in windows() if w[1]==process.pid and ("Confirm Quit" in w[2] or "确认退出" in w[2])),None),"quit confirmation")
        quit_button=next(child for child in children(confirmation[0]) if any(word in text(child) for word in ("Quit","退出")) and "BUTTON" in class_name(child).upper())
        click(quit_button);wait(lambda:process.poll() is not None,"Praat quit")
        wait(lambda:not path_window(),"child dialog exits with parent")
        assert sys.executable in preferences.read_text(encoding="utf-16" if preferences.read_bytes()[:2] in (b'\xff\xfe',b'\xfe\xff') else "utf-8")
        passed("new_python_survives_praat_exit_and_dialog_follows_parent")
        report["ok"]=True
    finally:
        for hwnd,pid,title in windows():
            if pid==process.pid or title=="AIPraat 路径配置":user32.PostMessageW(hwnd,0x10,0,0)
        if process.poll() is None:
            try:process.wait(timeout=3)
            except subprocess.TimeoutExpired:process.terminate();process.wait(timeout=3)
        target=project/"installer"/"verification"/"path-config-live.json";target.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
        print("Artifacts: "+str(fixture),flush=True)
    return 0

if __name__=="__main__":raise SystemExit(main())
