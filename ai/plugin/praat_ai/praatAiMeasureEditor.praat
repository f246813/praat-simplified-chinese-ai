# 从声音 / TextGrid 编辑器调用：把编辑器里圈选的那一段交给 praatAiMeasure.praat。
#
# 为什么单独一个文件：Add menu command 只能指定脚本文件、不能带参数，而圈选范围
# 只有在编辑器上下文里才读得到（editor ... endeditor）。批量模式（--run）里没有
# 编辑器（Praat 报 “Cannot edit a Sound from batch”），所以这一段只能在真机上
# 手点验证；下面 runScript 那行的参数传递方式在 verify_plugin.py 里有自动化验证。

editor
    aiStart = Get start of selection
    aiEnd = Get end of selection
endeditor

if aiEnd <= aiStart
    # 只点了光标、没有拖选：交给主脚本按「整个对象」处理。
    aiStart = 0
    aiEnd = 0
endif

runScript: "praatAiMeasure.praat", "all", aiStart, aiEnd, 0
