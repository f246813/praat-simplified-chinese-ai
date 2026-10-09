# 强制对齐模块与检查

`ai/praat_ai/forced_alignment.py` 组织配置的 MFA／wav2vec2 后端、音素映射、融合来源与置信度。配置项见 `AlignmentConfig`；模型和工具安装应以所用后端要求为准，文档不假定机器已安装某个固定环境。

逐音素比较同时需要可靠的标准侧和学习者侧边界，当前路径见 [专业模块](DESIGN.zh-CN.md)。后端分歧及低置信度需要保留来源和复核提示，不能把成功生成区间当作边界正确的证明。

MFA 与 wav2vec2 的音素集合需要语言映射；中文声调及复合音素不能仅凭无调 tokenizer 推断已被覆盖。合成语音也不能代表真实人声准确率。

可复现检查入口为 `ai/tests/test_alignment.py` 与 `test_pronunciation.py`。真实后端检查需要准备相应模型、音频与已知边界，并分别记录边界误差、映射遗漏和后端来源。
