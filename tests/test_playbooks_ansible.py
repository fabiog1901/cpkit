import datetime as dt
import gzip
import os
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from cpkit.playbooks.ansible import (
    AnsibleRunner,
    PlaybookRunOptions,
    SSH_CREDENTIAL_CLEANUP_PLAYBOOK,
    SSH_CREDENTIAL_PREPARE_PLAYBOOK,
    configure_playbook_run_options,
    get_playbook_run_options,
    _build_ssh_vars_from_credential_dir,
    _effective_playbook_run_options,
    _merge_ssh_credential_vars,
    _run_async_preserving_signals,
)
from cpkit.playbooks.types import Playbook


class FakeThread:
    def is_alive(self):
        return False

    def join(self):
        return None


class FakeRunner:
    status = "successful"


class FakeRepo:
    def __init__(self):
        self.playbooks = {}
        self.job_updates = []
        self.tasks = []
        self.playbook_versions = []

    def add_playbook(self, name, content, version_second):
        version = dt.datetime(
            2026,
            7,
            13,
            12,
            0,
            version_second,
            tzinfo=dt.timezone.utc,
        )
        self.playbooks[name] = Playbook(
            name=name,
            version=version,
            default_version=version,
            created_at=version,
            created_by="test",
            updated_by=None,
            content=gzip.compress(content.encode("utf-8")),
        )

    def get_default_playbook(self, name):
        return self.playbooks.get(name)

    def set_job_playbook_version(self, job_id, playbook_version):
        self.playbook_versions.append((job_id, playbook_version))

    def update_job(self, job_id, status):
        self.job_updates.append((job_id, status))

    def create_task(self, *args):
        self.tasks.append(args)


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


class SSHCredentialHookTests(unittest.TestCase):
    def tearDown(self):
        configure_playbook_run_options()

    def test_configured_playbook_run_options_are_used_by_default(self):
        configure_playbook_run_options(
            PlaybookRunOptions(
                ssh_credential_hook_enabled=True,
                ssh_credential_dir_root="/tmp/custom",
            )
        )

        options = _effective_playbook_run_options(
            playbook_run_options=None,
            ssh_credential_hook_enabled=None,
            ssh_credential_prepare_playbook=None,
            ssh_credential_cleanup_playbook=None,
            ssh_credential_dir_root=None,
            ssh_credential_retain_artifacts_on_failure=None,
        )

        self.assertTrue(options.ssh_credential_hook_enabled)
        self.assertEqual(options.ssh_credential_dir_root, "/tmp/custom")

    def test_run_playbook_overrides_configured_options(self):
        configure_playbook_run_options(
            PlaybookRunOptions(ssh_credential_hook_enabled=True)
        )

        options = _effective_playbook_run_options(
            playbook_run_options=None,
            ssh_credential_hook_enabled=False,
            ssh_credential_prepare_playbook=None,
            ssh_credential_cleanup_playbook=None,
            ssh_credential_dir_root=None,
            ssh_credential_retain_artifacts_on_failure=None,
        )

        self.assertFalse(options.ssh_credential_hook_enabled)

    def test_build_ssh_vars_from_credential_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            credential_dir = Path(tmp)
            (credential_dir / "id_key").write_text("private", encoding="utf-8")
            (credential_dir / "id_key-cert.pub").write_text("cert", encoding="utf-8")
            (credential_dir / "known_hosts").write_text("host", encoding="utf-8")
            (credential_dir / "ssh_config").write_text("config", encoding="utf-8")

            ssh_vars = _build_ssh_vars_from_credential_dir(str(credential_dir))

            self.assertEqual(
                ssh_vars["ansible_ssh_private_key_file"],
                str(credential_dir / "id_key"),
            )
            self.assertIn("CertificateFile=", ssh_vars["ansible_ssh_common_args"])
            self.assertIn("IdentitiesOnly=yes", ssh_vars["ansible_ssh_common_args"])
            self.assertIn("UserKnownHostsFile=", ssh_vars["ansible_ssh_common_args"])
            self.assertIn("-F ", ssh_vars["ansible_ssh_common_args"])
            self.assertEqual(
                oct(os.stat(credential_dir / "id_key").st_mode & 0o777), "0o600"
            )

    def test_merge_ssh_vars_preserves_existing_common_args(self):
        merged = _merge_ssh_credential_vars(
            {"ansible_ssh_common_args": "-o StrictHostKeyChecking=no"},
            {
                "ansible_ssh_private_key_file": "/tmp/key",
                "ansible_ssh_common_args": "-o CertificateFile=/tmp/key-cert.pub",
            },
        )

        self.assertEqual(merged["ansible_ssh_private_key_file"], "/tmp/key")
        self.assertEqual(
            merged["ansible_ssh_common_args"],
            "-o StrictHostKeyChecking=no -o CertificateFile=/tmp/key-cert.pub",
        )

    def test_prepare_target_and_cleanup_hooks_run_with_generated_ssh_vars(self):
        repo = FakeRepo()
        repo.add_playbook(
            "SERVER_INIT",
            "- name: Target\n  hosts: all\n  tasks: []\n",
            1,
        )
        repo.add_playbook(
            SSH_CREDENTIAL_PREPARE_PLAYBOOK,
            "- name: Prepare\n  hosts: localhost\n  tasks: []\n",
            2,
        )
        repo.add_playbook(
            SSH_CREDENTIAL_CLEANUP_PLAYBOOK,
            "- name: Cleanup\n  hosts: localhost\n  tasks: []\n",
            3,
        )
        calls = []

        def fake_run_async(**kwargs):
            calls.append(kwargs)
            extra_vars = kwargs["extravars"]
            if "cpkit_credential_dir" in extra_vars and len(calls) == 1:
                credential_dir = Path(extra_vars["cpkit_credential_dir"])
                (credential_dir / "id_key").write_text("private", encoding="utf-8")
                (credential_dir / "id_key-cert.pub").write_text(
                    "cert", encoding="utf-8"
                )
            return FakeThread(), FakeRunner()

        with tempfile.TemporaryDirectory() as credential_root:
            runner = AnsibleRunner(
                repo=repo,
                job_id=99,
                playbook_run_options=PlaybookRunOptions(
                    ssh_credential_hook_enabled=True,
                    ssh_credential_dir_root=credential_root,
                ),
            )
            with patch(
                "cpkit.playbooks.ansible._run_async_preserving_signals", fake_run_async
            ):
                result = runner.launch_runner(
                    "SERVER_INIT",
                    {
                        "ansible_ssh_common_args": "-o StrictHostKeyChecking=no",
                        "target_ansible_host": "192.0.2.10",
                        "target_ansible_user": "ubuntu",
                    },
                )

        self.assertEqual(result.status, "successful")
        self.assertEqual(len(calls), 3)
        target_vars = calls[1]["extravars"]
        self.assertEqual(
            target_vars["ansible_ssh_private_key_file"],
            os.path.join(credential_root, "99", "ssh", "id_key"),
        )
        self.assertIn(
            "-o StrictHostKeyChecking=no",
            target_vars["ansible_ssh_common_args"],
        )
        self.assertIn("IdentitiesOnly=yes", target_vars["ansible_ssh_common_args"])
        self.assertIn("CertificateFile=", target_vars["ansible_ssh_common_args"])
        self.assertFalse(os.path.exists(os.path.join(credential_root, "99")))
        task_names = [task[3] for task in repo.tasks]
        self.assertIn("SSH_CREDENTIAL_PREPARE", task_names)
        self.assertIn("SSH_CREDENTIAL_ARTIFACTS", task_names)
        self.assertIn("SSH_CREDENTIAL_CLEANUP", task_names)


if __name__ == "__main__":
    unittest.main()
