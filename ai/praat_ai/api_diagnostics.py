"""Separate documented audio capability, test observations and user settings."""
from __future__ import annotations
import hashlib
import json
import re
from datetime import datetime, timezone

from . import model_capabilities as caps


def request_identity(base_url, model, api_key):
    values = [str(base_url or '').strip().rstrip('/'), str(model or '').strip(), str(api_key or '').strip(), caps.ADAPTER_VERSION]
    return hashlib.sha256(json.dumps(values, ensure_ascii=False).encode('utf-8')).hexdigest()


def status_code(detail, explicit=None):
    if isinstance(explicit, int) and not isinstance(explicit, bool) and 100 <= explicit <= 599:
        return explicit
    match = re.search(r'(?i)(?:status[_ ]code\s*[:=]\s*|HTTP\s+)(\d{3})\b', detail)
    return int(match[1]) if match and 100 <= int(match[1]) <= 599 else None


def test_record(base_url, model, api_key, result):
    reason = caps.safe_error(RuntimeError(str(result.get('reason', ''))), api_key)
    return {
        'identity': request_identity(base_url, model, api_key),
        'status': result.get('status', 'unverified'),
        'reason': reason,
        'status_code': status_code(reason, result.get('status_code')),
        'tested_at': datetime.now(timezone.utc).isoformat(),
    }


def matching_record(record, base_url, model, api_key):
    if not isinstance(record, dict) or record.get('status') not in {'verified','unsupported','unverified','cancelled'}:
        return {}
    if record.get('identity') != request_identity(base_url, model, api_key):
        return {}
    clean = test_record(base_url, model, api_key, record)
    clean['tested_at'] = str(record.get('tested_at', ''))
    return clean


def observation_time(value):
    try:
        moment = datetime.fromisoformat(str(value).replace('Z','+00:00'))
        return moment.replace(tzinfo=timezone.utc) if moment.tzinfo is None else moment.astimezone(timezone.utc)
    except (ValueError, TypeError):
        return datetime.min.replace(tzinfo=timezone.utc)


def failure_summary(result):
    detail = str(result.get('reason', '')).casefold()
    code = result.get('status_code')
    if 'timeout' in detail or 'timed out' in detail or '超时' in detail:
        return '请求超时'
    if code in {401, 403}:
        return '鉴权或权限错误'
    if code == 429:
        return '请求频率受限'
    if code is not None and code >= 500:
        return '服务端错误'
    if 'url' in detail:
        return '资源 URL 或请求参数错误'
    if '特征校验未通过' in detail:
        return '基础音频特征校验未通过'
    if code in {400, 404, 422}:
        return '接口拒绝请求；详见错误详情'
    if any(word in detail for word in ('connection', 'connect', '连接')):
        return '网络连接失败'
    return '请求或结果校验失败；详见错误详情'


def audio_hint(base_url, model, enabled, result=None, diagnostic=None):
    preset = caps.audio_preset(base_url, model)
    support = {'supported':'支持直接音频输入', 'unsupported':'不支持直接音频输入', 'unknown':'直接音频输入能力未知'}[preset.support]
    if not preset.source:
        basis = '未收录'
    elif preset.documented:
        basis = '官方文档'
    else:
        support = '按名称推定' + support
        basis = '网关未验证'
    lines = []
    if diagnostic and diagnostic.get('status') in {'unsupported','unverified'}:
        code = diagnostic.get('status_code')
        name = ' '.join(model.split())[:100] or '未填写'
        lines.append(f"status code: {code if code is not None else '未返回'} · model: {name}")
    lines.append(f'模型预设：{support}（{basis}）')
    status = (result or {}).get('status')
    if status == 'verified':
        text = '基础音频验证通过；不代表精确测量或细微发音判断准确'
    elif status == 'unsupported':
        text = '接口明确不支持音频输入'
    elif status == 'unverified':
        text = '未能验证——' + failure_summary(result)
    elif status == 'cancelled':
        text = '已取消'
    elif status == 'running':
        text = '正在验证（仅使用随机合成短音频）'
    else:
        text = '尚未验证'
    lines.extend(['音频实测：' + text, '当前设置：直接音频输入' + ('已启用' if enabled else '已关闭')])
    return '\n'.join(lines)
