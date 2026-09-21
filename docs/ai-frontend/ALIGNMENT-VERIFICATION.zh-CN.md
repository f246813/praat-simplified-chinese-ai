# 强制对齐安装与验证记录

日期：2026-09-20

## 环境

- Miniforge：`%USERPROFILE%\miniforge3`
- MFA 环境：`aligner`
- MFA 版本：3.4.2
- Python 属性环境：`<venv>`
- wav2vec2：`facebook/wav2vec2-lv-60-espeak-cv-ft`

已安装 MFA、Kalpy、Kaldi、OpenFST、NGram、Baum-Welch、Pynini，以及中文
分词扩展 `spacy-pkuseg`、`dragonmapper`、`hanziconv`。

## 英语验证

- 音频：Windows TTS，`hello world`
- MFA 模型：`english_us_arpa`
- 音素序列：`HH AH L OW W ER L D`
- 结果：成功得到 8 个音素边界。
- wav2vec2 映射：`h ə l oʊ w ɜ l d`
- 双对齐：MFA 与 wav2vec2 边界接近，融合结果正常生成。
- 融合来源：`dual:mfa+wav2vec2:...`
- 融合置信度：约 `0.229`
- 结论：合成英语测试音的两个后端边界接近，但因部分音素边界差超过
  40 ms，系统按设计降低置信度并给出复核警告。

示例 MFA 边界：

```text
HH 0.090-0.170
AH 0.170-0.280
L  0.280-0.370
OW 0.370-0.460
W  0.460-0.620
ER 0.620-0.820
L  0.820-0.940
D  0.940-1.040
```

## 中文验证

- 音频：Windows Huihui TTS，`你好世界`
- MFA 模型：`mandarin_mfa`
- 映射后的无调音素序列：
  `n i x aw ʂ ʐ tɕ j e`
- 双对齐：成功生成 9 个融合区间。
- 融合来源：`dual:mfa+wav2vec2:...`
- 融合置信度：约 `0.259`
- 结果置信度偏低，按设计生成“建议复核该区间”警告。

中文低置信度主要来自两个原因：

1. MFA 词典包含声调和复合音素，而当前多语言 wav2vec2 tokenizer 不含全部对应 token。
2. 当前测试音为合成语音，声学分布与真实人声不完全一致。

这说明双对齐器工作正常，也验证了“低一致性必须降低置信度”的设计。

## 当前限制

- MFA 与 wav2vec2 的音素集需要语言级映射表。
- 中文声调尚未进入 wav2vec2 音素对齐，需要单独的声调轮廓分析。
- 下一阶段应建立 `language_profiles`，保存 ARPA/IPA/wav2vec2 token 之间的映射。
