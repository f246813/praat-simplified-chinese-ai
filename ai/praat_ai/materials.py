"""Window-scoped audio snapshots. Persistent records contain provenance only."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import uuid
import wave
from pathlib import Path
from .process import process_alive, process_identity, identities_match


class TaskMaterials:
    def __init__(self, root: Path):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.directory = self.root / ('task-' + uuid.uuid4().hex)
        self.directory.mkdir()
        (self.directory / '.aipraat-task').write_text(self.directory.name, encoding='utf-8')
        (self.directory / '.owner.json').write_text(json.dumps({'pid':os.getpid(), 'identity':process_identity(os.getpid())}), encoding='utf-8')
        self.audio_path: Path | None = None
        self.fingerprint = ''
        self.source = ''
        self.source_kind = 'unknown'
        self.range: tuple[float, float] | None = None
        self.closed = False
        self.snapshot_attempted = False
        self.snapshot_error = ''

    def provenance(self) -> dict:
        return {'sha256':self.fingerprint, 'source':self.source, 'source_kind':self.source_kind, 'range':self.range, 'snapshot':'window-only',
                'audio_available':bool(self.audio_path and self.audio_path.is_file() and not self.closed)}

    def snapshot_wav(self, source: Path, selection: tuple[float, float] | None = None) -> Path:
        try:
            return self._snapshot_wav(source, selection)
        except (wave.Error, EOFError) as error:
            raise ValueError("原目标不是当前适配器可读取的 PCM WAV：" + str(error)) from error

    def _snapshot_wav(self, source: Path, selection: tuple[float, float] | None = None) -> Path:
        if self.closed:
            raise OSError('窗口已关闭，临时材料不能再创建')
        source = Path(source).resolve()
        self.source, self.source_kind, self.snapshot_attempted = str(source), 'file', True
        target = self.directory / 'segment.wav'
        with wave.open(str(source), 'rb') as reader:
            rate = reader.getframerate()
            start, end = selection or (0.0, reader.getnframes() / rate)
            if start < 0 or end <= start or end * rate > reader.getnframes() + 1:
                raise ValueError('原目标片段超出音频文件范围')
            if end - start > 120:
                raise ValueError('首版直接音频分析每片段最多 120 秒，请缩小目标片段')
            reader.setpos(int(start * rate))
            data = reader.readframes(int((end - start) * rate))
            if len(data) > 20 * 1024 * 1024:
                raise ValueError('目标片段超过 20 MiB')
            with wave.open(str(target), 'wb') as writer:
                writer.setparams(reader.getparams())
                writer.writeframes(data)
        self.source, self.range, self.audio_path = str(source), (start, end), target
        self.source_kind = 'file'
        self.fingerprint = hashlib.sha256(target.read_bytes()).hexdigest()
        return target

    def bytes(self) -> bytes:
        try:
            return self._bytes()
        except (wave.Error, EOFError) as error:
            raise ValueError("目标音频 WAV 格式不可用：" + str(error)) from error

    def _bytes(self) -> bytes:
        if self.closed or self.audio_path is None or not self.audio_path.is_file():
            raise OSError('原目标音频快照不可用')
        if self.audio_path.stat().st_size > 20 * 1024 * 1024:
            raise ValueError('目标音频超过 20 MiB')
        with wave.open(str(self.audio_path), 'rb') as reader:
            if reader.getnframes() / reader.getframerate() > 120:
                raise ValueError('目标音频超过 120 秒')
        data = self.audio_path.read_bytes()
        self.fingerprint = hashlib.sha256(data).hexdigest()
        return data

    def close(self) -> None:
        self.closed = True
        root, target = self.root.resolve(), self.directory.resolve()
        marker = target / '.aipraat-task'
        # Never traverse junctions/symlinks or clean source/user paths.
        if (target.parent != root or not target.name.startswith('task-')
                or self.directory.is_symlink() or not marker.is_file()
                or marker.read_text(encoding='utf-8') != target.name):
            raise OSError('临时目录身份核查失败，未清理')
        for item in target.rglob('*'):
            if item.is_symlink() or (hasattr(item, 'is_junction') and item.is_junction()):
                raise OSError('临时目录含链接，未递归清理')
        shutil.rmtree(target)


def cleanup_abandoned(root: Path) -> int:
    """Remove only verified owned task directories whose creating process ended."""
    root = Path(root).resolve()
    if not root.is_dir():
        return 0
    removed = 0
    for directory in root.glob('task-*'):
        if directory.is_symlink() or (hasattr(directory, 'is_junction') and directory.is_junction()):
            continue
        try:
            owner = json.loads((directory / '.owner.json').read_text(encoding='utf-8'))
            pid = int(owner['pid'])
            if pid <= 0 or pid == os.getpid():
                continue
            observed = process_identity(pid)
            if observed is None and process_alive(pid):
                continue  # Unverifiable running process: leave its files alone.
            expected = owner.get('identity')
            if observed is not None and (not expected or identities_match(expected, observed)):
                continue
            material = TaskMaterials.__new__(TaskMaterials)
            material.root, material.directory, material.closed = root, directory, False
            material.close()  # Rechecks marker, containment, symlinks and junctions.
            removed += 1
        except (OSError, ValueError, KeyError, TypeError):
            continue
    return removed
