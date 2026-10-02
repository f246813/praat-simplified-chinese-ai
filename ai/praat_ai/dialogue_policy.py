"""Conservative local routing, without another model request."""
from __future__ import annotations
import re

# Operations and references win over greetings and explanatory prefixes.
_MATERIAL = re.compile(
    r'选中|选区|当前|这段|这个|这些|那个|该录音|录音|对象|刚才|上述|上一|继续|它|再做|'
    r'测量|计算|读取|打开|删除|创建|保存|截取|播放|分析|对比|比较|导出|标注|'
    r'复制|重命名|生成|重采样|翻转|拼接|合并|转换|裁剪|归一化|滤波|之前|此前|这里|那里|'
    r'\b(?:Sound|LongSound|Pitch|Formant|Spectrum|Intensity|TextGrid)\s+\d+\b|'
    r'\d+\s*号|#\s*\d+|\d+(?:\.\d+)?\s*(?:秒|\b(?:seconds?|Hz)\b)|'
    r'\d+(?:\.\d+)?\s*(?:到|至|[-–—~～])\s*\d+(?:\.\d+)?|'
    r'[A-Za-z]:[\\/]|\.(?:wav|mp3|flac|textgrid)\b|'
    r'\b(?:selected|current|recording|recordings|measure|measurement of|calculate|'
    r'open|delete|remove|create|save|extract|play|analy[sz]e|compare|export|annotate|'
    r'this|these|that|those|it|its|them|their|continue|previous|above|again|'
    r'rename|resample|copy|duplicate|generate|plot|invert|join|merge|concatenate|clips?|results?|values)\b', re.I)
_CONCEPT = re.compile(r'什么是|如何理解|原理|理论|科普|解释|练习方法|一般来说|'
                      r'\b(?:what (?:is|are)|explain|define|definition|theory|principle)\b', re.I)
_COMPOUND = re.compile(r'[，,；;\n。！？?!&]|顺便|然后|另外|同时|接着|再做|并|和|与|\b(?:and|then|also|after|next)\b', re.I)
_DOMAIN = re.compile(r'基频|共振峰|强度|时长|波形|音高|音素|声音|音频|'
                     r'\b(?:pitch|formant|intensity|duration|sound|audio|vot|cpp|jitter|shimmer)\b', re.I)
_GREETING = r'(?:hello|hi|hey|你好|您好|嗨|哈喽|早上好|晚上好|早安|午安|晚安|谢谢|多谢|thanks|thank you)'
_SEPARATOR = r'[\s,，。！!？?、:：]*'
_ORDINARY = re.compile(
    r'(?:'+_GREETING+_SEPARATOR+r')*'
    r'(?:'+_GREETING+r'|what can (?:you|u) do(?: for me)?|'
    r'what (?:are|is) (?:your|ur) (?:capabilities|abilities|functions|name)|'
    r'who are (?:you|u)|how are (?:you|u)|'
    r'你(?:能帮我做什么|能做什么|有哪些功能|有什么功能|是谁|叫什么|是什么模型)|'
    r'介绍(?:一下)?(?:你自己|你的功能)|讲(?:个|一个)(?:笑话|故事)|聊聊天|随便聊聊)'
    +_SEPARATOR, re.I)


def dialogue_kind(goal: str) -> str | None:
    """Unknown domain/operation requests keep the existing analysis safeguards."""
    if not goal.strip() or _MATERIAL.search(goal):
        return None
    if _ORDINARY.fullmatch(goal.strip()):
        return 'conversation'
    concept = goal.strip().rstrip('。！？?!')
    if _CONCEPT.match(concept) and not _COMPOUND.search(concept):
        return 'concept'
    if _DOMAIN.search(goal):
        return None
    return None


def effective_thinking_level(api, kind: str | None) -> str:
    level = api.thinking_level
    if kind == 'conversation' and level == 'high' and not api.force_deep_thinking:
        return 'off'
    return level


def force_high(api) -> bool:
    return api.thinking_level == 'high' and api.force_deep_thinking


def direct_measurement(goal: str):
    text = goal.strip().rstrip('。！？?!')
    chinese = r'(?:请|帮我)?(?:测量|查询|读取|告诉我)?(?:当前|选中)(?:声音|音频)(?:的)?(?:总)?(?:时长|长度)'
    english = r'(?:please\s+)?(?:what is|measure|query|get|tell me)\s+(?:the\s+)?(?:total\s+)?duration\s+(?:of\s+)?(?:the\s+)?(?:current|selected)\s+sound'
    if re.fullmatch(chinese+'|'+english, text, re.I):
        return {'tool':'duration', 'arguments':{}}
    return None
