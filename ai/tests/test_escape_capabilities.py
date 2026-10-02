import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from praat_ai.config import load_config
from praat_ai import model_capabilities as caps
from praat_ai.materials import TaskMaterials
from praat_ai import api_settings
from praat_ai import tools
from jsonschema import Draft202012Validator


class CapabilityTests(unittest.TestCase):
    def test_exact_presets_and_unknown(self):
        self.assertTrue(caps.audio_preset('https://dashscope.aliyuncs.com/compatible-mode/v1', 'qwen3.8-omni-flash').enabled)
        self.assertFalse(caps.audio_preset('https://dashscope.aliyuncs.com/compatible-mode/v1', 'qwen3.7-flash').enabled)
        self.assertEqual(caps.audio_preset('https://custom/v1', 'special-omni').support, 'unknown')

    def test_explicit_errors_only(self):
        self.assertTrue(caps.is_audio_unsupported(400, 'This model does not support audio input'))
        for code, text in [(400, 'Invalid input_audio format'), (401, 'audio not supported'), (429, 'audio not supported'), (500, 'audio not supported'), (400, 'Invalid audio size')]:
            self.assertFalse(caps.is_audio_unsupported(code, text))

    def test_manual_reopen_and_compare_update(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'config.json'
            api = {'base_url':'https://custom/v1', 'model':'x', 'audio_input_enabled':True, 'audio_input_source':'manual'}
            path.write_text(json.dumps({'api':api}), encoding='utf-8')
            cfg = load_config(path)
            self.assertTrue(cfg.api.audio_input_enabled)
            identity = caps.config_identity(cfg.api)
            self.assertTrue(caps.correct_audio_setting(path, identity, 'unsupported'))
            self.assertFalse(load_config(path).api.audio_input_enabled)
            api['model'] = 'new-model'
            path.write_text(json.dumps({'api':api}), encoding='utf-8')
            self.assertFalse(caps.correct_audio_setting(path, identity, 'unsupported'))
            self.assertTrue(load_config(path).api.audio_input_enabled)

    def test_material_cleanup_preserves_user_source(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / 'source.wav'
            source.write_bytes(b'user source')
            materials = TaskMaterials(root / 'tasks')
            temporary = materials.directory / 'segment.wav'
            temporary.write_bytes(b'temporary')
            materials.audio_path = temporary
            materials.source = str(source)
            materials.close()
            self.assertTrue(source.is_file())
            self.assertFalse(temporary.exists())

    def test_settings_preserve_audio_and_new_model_resets_preset(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'config.json'
            path.write_text(json.dumps({'api':{'base_url':'https://custom/v1', 'model':'x',
                           'audio_input_enabled':True, 'audio_input_source':'manual'}}), encoding='utf-8')
            api_settings.save_settings({'plan_max_tokens':900}, path)
            self.assertTrue(load_config(path).api.audio_input_enabled)
            api_settings.save_settings({'model':'unknown-new-model'}, path)
            self.assertFalse(load_config(path).api.audio_input_enabled)

    def test_unrelated_save_cannot_undo_concurrent_audio_correction(self):
        from praat_ai import control
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'config.json'
            path.write_text(json.dumps({'api':{'base_url':'https://custom/v1', 'model':'x',
                           'audio_input_enabled':True, 'audio_input_source':'manual'}}), encoding='utf-8')
            identity = caps.config_identity(load_config(path).api)
            writer = control.update_config
            def concurrent(values, config_path=None):
                self.assertTrue(caps.correct_audio_setting(path, identity, 'unsupported'))
                return writer(values, config_path)
            with patch.object(control, 'update_config', side_effect=concurrent):
                api_settings.save_settings({'plan_max_tokens':900}, path)
            self.assertFalse(load_config(path).api.audio_input_enabled)
            self.assertEqual(load_config(path).api.audio_input_source, 'corrected')

    def test_invalid_wav_is_classified_as_material_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'bad.wav'
            source.write_bytes(b'invalid user file')
            materials = TaskMaterials(Path(directory) / 'tasks')
            try:
                with self.assertRaises(ValueError):
                    materials.snapshot_wav(source)
                self.assertTrue(materials.snapshot_attempted)
                self.assertTrue(source.exists())
            finally:
                materials.close()

    def test_abandoned_owned_tasks_cleanup_keeps_active_and_user_files(self):
        import os
        from praat_ai.materials import cleanup_abandoned
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            old = TaskMaterials(root / 'tasks')
            active = TaskMaterials(root / 'tasks')
            owner = old.directory / '.owner.json'
            owner.write_text(json.dumps({'pid':99999999,'identity':{}}), encoding='utf-8')
            user = root / 'source.wav'
            user.write_bytes(b'keep')
            with patch('praat_ai.materials.process_alive', return_value=False), patch('praat_ai.materials.process_identity', return_value=None):
                removed = cleanup_abandoned(root / 'tasks')
            self.assertEqual(removed, 1)
            self.assertFalse(old.directory.exists())
            self.assertTrue(active.directory.exists())
            self.assertTrue(user.exists())
            active.close()

    def test_wav_range_snapshot_has_stable_fingerprint(self):
        import wave
        import hashlib
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'source.wav'
            with wave.open(str(source), 'wb') as writer:
                writer.setparams((1,2,16000,0,'NONE','not compressed'))
                writer.writeframes(b'\x00\x00' * 16000)
            materials = TaskMaterials(Path(directory) / 'tasks')
            try:
                clipped = materials.snapshot_wav(source, (0.2,0.5))
                with wave.open(str(clipped), 'rb') as reader:
                    self.assertEqual(reader.getnframes(), 4800)
                self.assertEqual(materials.provenance()['sha256'], hashlib.sha256(clipped.read_bytes()).hexdigest())
                self.assertEqual(materials.range, (0.2,0.5))
                self.assertTrue(source.is_file())
            finally:
                materials.close()

    def test_formant_schema_matches_multiple_numbers_and_default(self):
        for name in ('formant_frequency', 'formant_bandwidth', 'formant_statistics'):
            validator = Draft202012Validator(tools.TOOL_PARAMETERS[name])
            for arguments in ({}, {'formant':2}, {'formant':'1,2'}, {'formant':[1,2]}):
                self.assertEqual(list(validator.iter_errors(arguments)), [])
        self.assertIn('默认 2', tools.TOOL_MAP['formant_statistics'].signature)


if __name__ == '__main__':
    unittest.main()
