"""Both API settings entrances must apply the same local-service policy."""

from __future__ import annotations

import json
import queue
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from praat_ai import api_settings, control
from praat_ai.chat import ChatWindow
from praat_ai.config import AppConfig
from praat_ai.server import QwenServerError


def write_config(directory: Path, *, enabled: bool, stop_local: bool = True) -> Path:
    config = AppConfig()
    config.server.host = "127.0.0.1"
    config.server.port = 18008
    config.api.enabled = enabled
    config.api.base_url = "https://example.test/v1"
    config.api.model = "remote-model"
    config.api.api_key = "test-key"
    config.api.stop_local_service = stop_local
    path = directory / "ai_config.json"
    path.write_text(json.dumps(config.to_dict()), encoding="utf-8")
    return path


class ApiTransitionTests(unittest.TestCase):
    def test_settings_callback_failure_is_visible_after_save(self) -> None:
        dialog = object.__new__(api_settings.ApiSettingsDialog)
        dialog.collect = lambda: {"enabled": False}
        dialog.config_path = Path("unused.json")
        dialog.verified = False
        dialog.window = object()
        dialog._messagebox = SimpleNamespace(showerror=Mock(), showwarning=Mock())
        dialog.on_saved = lambda _values: (_ for _ in ()).throw(RuntimeError("queue failed"))
        dialog.close = Mock()
        with patch.object(api_settings, "save_settings"):
            dialog.save()
        dialog._messagebox.showerror.assert_called_once()
        self.assertIn("queue failed", dialog._messagebox.showerror.call_args.args[1])
        dialog.close.assert_not_called()

    def test_concurrent_saves_converge_on_the_latest_api_mode(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            path = write_config(directory, enabled=False)
            starting = threading.Event()
            release_start = threading.Event()
            stopped = threading.Event()
            state = {"running": False}
            errors: list[BaseException] = []

            def slow_start(*_args, **_kwargs):
                starting.set()
                if not release_start.wait(3):
                    raise TimeoutError("test did not release local startup")
                state["running"] = True
                return {"api_enabled": False}

            def stop(*_args, **_kwargs):
                state["running"] = False
                stopped.set()
                return {"api_enabled": True}

            def apply() -> None:
                try:
                    control.reconcile_api_transition(path)
                except BaseException as error:  # keep worker failures visible to this test
                    errors.append(error)

            with (
                patch.object(control, "runtime_dir", return_value=directory),
                patch.object(control, "ensure_local_service", side_effect=slow_start),
                patch.object(control, "stop_frontend", side_effect=stop),
            ):
                first = threading.Thread(target=apply)
                first.start()
                self.assertTrue(starting.wait(2))
                write_config(directory, enabled=True)
                second = threading.Thread(target=apply)
                second.start()
                stopped.wait(0.2)
                release_start.set()
                first.join(3)
                second.join(3)

        self.assertFalse(first.is_alive() or second.is_alive())
        self.assertEqual(errors, [])
        self.assertFalse(state["running"], "old local startup must not win the race")

    def test_api_switch_reports_when_an_unowned_service_still_occupies_port(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            path = write_config(Path(raw), enabled=True)
            with (
                patch.object(control, "_stop_running_service", return_value=False),
                patch.object(control, "endpoint_available", return_value=True),
                patch.object(control, "_wait_for_endpoint_gone"),
                patch.object(control, "collect_status", return_value={"success": True}),
            ):
                with self.assertRaises(QwenServerError):
                    control.reconcile_api_transition(path)

    def test_waiting_for_stopped_endpoint_raises_on_timeout(self) -> None:
        with patch.object(control, "endpoint_available", return_value=True):
            with self.assertRaises(QwenServerError):
                control._wait_for_endpoint_gone("http://127.0.0.1:18008/v1", timeout=0)

    def test_enabling_api_stops_only_the_configured_local_service(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            path = write_config(Path(raw), enabled=True)
            with (
                patch.object(control, "_stop_running_service", return_value=True) as stop,
                patch.object(control, "_wait_for_endpoint_gone") as wait,
                patch.object(control, "collect_status", return_value={"success": True}),
            ):
                control.reconcile_api_transition(path)
        self.assertEqual(stop.call_count, 1)
        wait.assert_called_once_with("http://127.0.0.1:18008/v1")

    def test_enabling_api_with_keep_local_option_does_not_stop_service(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            path = write_config(Path(raw), enabled=True, stop_local=False)
            with (
                patch.object(control, "_stop_running_service") as stop,
                patch.object(control, "collect_status", return_value={"success": True}),
            ):
                control.reconcile_api_transition(path)
        stop.assert_not_called()

    def test_disabling_api_starts_local_service_when_port_is_empty(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            path = write_config(Path(raw), enabled=False)
            with (
                patch.object(control, "endpoint_available", return_value=False),
                patch.object(control, "_launch_server", return_value={"success": True}) as launch,
            ):
                control.reconcile_api_transition(path)
        self.assertEqual(launch.call_count, 1)

    def test_standalone_dialog_reconciles_after_save(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            path = write_config(Path(raw), enabled=True)

            class FakeWindow:
                def __init__(self, on_saved):
                    self.on_saved = on_saved

                def mainloop(self) -> None:
                    if self.on_saved is not None:
                        self.on_saved({"enabled": True})

                def destroy(self) -> None:
                    return None

            class FakeDialog:
                def __init__(self, *_args, on_saved=None, **_kwargs):
                    self.window = FakeWindow(on_saved)

            with (
                patch.object(api_settings, "ApiSettingsDialog", FakeDialog),
                patch("praat_ai.parent_watch.should_watch", return_value=False),
                patch.object(control, "reconcile_api_transition") as reconcile,
            ):
                self.assertEqual(api_settings.run_standalone(path), 0)
        reconcile.assert_called_once_with(path)

    def test_chat_dialog_queues_same_transition_for_api_and_local_modes(self) -> None:
        for enabled in (True, False):
            with self.subTest(enabled=enabled):
                config = AppConfig()
                config.api.enabled = enabled
                config.api.base_url = "https://example.test/v1"
                config.api.model = "remote-model"
                config.api.api_key = "test-key"
                messages: queue.Queue[tuple[str, str]] = queue.Queue()
                window = SimpleNamespace(
                    config=config,
                    messages=messages,
                    reload_config=lambda: None,
                    append_hint=lambda _message: None,
                )
                ChatWindow.on_api_settings_saved(window, {})
                self.assertEqual(messages.get_nowait(), ("reconcile-service", ""))


if __name__ == "__main__":
    unittest.main()
