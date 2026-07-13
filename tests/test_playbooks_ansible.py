import threading
import unittest
from unittest.mock import patch

from cpkit.playbooks.ansible import _run_async_preserving_signals


class AnsibleSignalTests(unittest.TestCase):
    def test_preserves_signal_handlers_on_main_thread(self):
        with (
            patch("cpkit.playbooks.ansible.ansible_runner.run_async") as run_async,
            patch("cpkit.playbooks.ansible.signal.getsignal") as getsignal,
            patch("cpkit.playbooks.ansible.signal.signal") as signal,
        ):
            run_async.return_value = ("thread", "runner")
            getsignal.side_effect = ["sigint-handler", "sigterm-handler"]

            result = _run_async_preserving_signals(playbook="demo")

        self.assertEqual(result, ("thread", "runner"))
        run_async.assert_called_once_with(playbook="demo")
        self.assertEqual(getsignal.call_count, 2)
        self.assertEqual(signal.call_count, 2)

    def test_does_not_restore_signal_handlers_from_worker_thread(self):
        errors = []

        def target():
            try:
                with (
                    patch(
                        "cpkit.playbooks.ansible.ansible_runner.run_async",
                        return_value=("thread", "runner"),
                    ) as run_async,
                    patch("cpkit.playbooks.ansible.signal.getsignal") as getsignal,
                    patch("cpkit.playbooks.ansible.signal.signal") as signal,
                ):
                    result = _run_async_preserving_signals(playbook="demo")
                    self.assertEqual(result, ("thread", "runner"))
                    run_async.assert_called_once_with(playbook="demo")
                    getsignal.assert_not_called()
                    signal.assert_not_called()
            except Exception as err:
                errors.append(err)

        thread = threading.Thread(target=target)
        thread.start()
        thread.join()

        self.assertEqual(errors, [])


if __name__ == "__main__":
    unittest.main()
