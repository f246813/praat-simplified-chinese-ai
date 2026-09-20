# AI 工具插件（plugin_praat_ai）：把 AI 声学测量和「启动 AI 对话窗口」加进
# Praat 自己的菜单。Praat 启动时会扫 preferences 目录下的 plugin_*/setup.praat
# （Windows：%APPDATA%\Praat\plugin_praat_ai\），所以**不用重新编译 Praat**。
#
# 安装：跑 ai/plugin/install.ps1，或者手工把这个文件夹复制成
#       %APPDATA%\Praat\plugin_praat_ai\。说明见 ai/plugin/README.zh-CN.md。
# 出处：chengafni/praat 的 plugin_*/setup.praat + Add menu command 那套做法。

# 对象列表：选中一个 Sound 时，右侧动态菜单底部出现「AI 声学测量...」
Add action command: "Sound", 1, "", 0, "", 0, "AI 声学测量...", "", 0, "praatAiMeasure.praat"

# 声音 / TextGrid 编辑器：Analyses 菜单里出现「AI 声学测量（圈选段）...」
Add menu command: "SoundEditor", "Analyses", "AI 声学测量（圈选段）...", "", 0, "praatAiMeasureEditor.praat"
Add menu command: "TextGridEditor", "Analyses", "AI 声学测量（圈选段）...", "", 0, "praatAiMeasureEditor.praat"

# 对象列表窗口的 Praat 菜单：启动本地 AI 对话窗口（Python 前端）
Add menu command: "Objects", "Praat", "启动 AI 对话窗口", "", 0, "praatAiChat.praat"
