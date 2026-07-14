"""Ansible runner helpers for framework-managed playbooks."""

import datetime as dt
import gzip
import json
import logging
import os
import signal
import shutil
import threading
import time
from dataclasses import dataclass
from typing import Any

import ansible_runner
import yaml

from cpkit.time import STRFTIME

logger = logging.getLogger(__name__)

SSH_CREDENTIAL_PREPARE_PLAYBOOK = "SSH_CREDENTIAL_PREPARE"
SSH_CREDENTIAL_CLEANUP_PLAYBOOK = "SSH_CREDENTIAL_CLEANUP"
SSH_CREDENTIAL_DIR_ROOT = "/tmp/cpkit/jobs"


@dataclass(frozen=True)
class LoadedPlaybook:
    content: str
    version: str


@dataclass(frozen=True)
class RunnerResult:
    status: str
    data: dict[str, Any]
    task_id_counter: int
    playbook_name: str | None = None
    playbook_version: str | None = None


@dataclass(frozen=True)
class LiteRunnerResult:
    status: str
    data: dict[str, Any]
    playbook_name: str | None = None
    playbook_version: str | None = None


@dataclass(frozen=True)
class PlaybookRunOptions:
    """Runtime options used by cpkit playbook execution."""

    ssh_credential_hook_enabled: bool = False
    ssh_credential_prepare_playbook: str = SSH_CREDENTIAL_PREPARE_PLAYBOOK
    ssh_credential_cleanup_playbook: str = SSH_CREDENTIAL_CLEANUP_PLAYBOOK
    ssh_credential_dir_root: str = SSH_CREDENTIAL_DIR_ROOT
    ssh_credential_retain_artifacts_on_failure: bool = False


DEFAULT_PLAYBOOK_RUN_OPTIONS = PlaybookRunOptions()
_configured_playbook_run_options = DEFAULT_PLAYBOOK_RUN_OPTIONS


class AnsibleRunner:
    """Run a stored playbook and record job/task progress through a repository."""

    def __init__(
        self,
        *,
        repo: Any,
        job_id: int,
        counter: int = 0,
        running_status: Any = "RUNNING",
        completed_status: Any = "COMPLETED",
        failed_status: Any = "FAILED",
        job_dir_root: str = "/tmp",
        playbook_run_options: PlaybookRunOptions | None = None,
    ):
        self.data: dict[str, Any] = {}
        self.repo = repo
        self.job_id = job_id
        self.counter = counter
        self.running_status = running_status
        self.completed_status = completed_status
        self.failed_status = failed_status
        self.job_dir_root = job_dir_root
        self.playbook_run_options = playbook_run_options or get_playbook_run_options()

    def status_handler(self, status, runner_config):
        return

    def event_handler(self, event):
        task_type = ""
        task_data = ""

        if event["event"] in [
            "verbose",
            "playbook_on_start",
            "playbook_on_no_hosts_matched",
            "runner_on_skipped",
            "runner_item_on_skipped",
            "runner_item_on_ok",
            "runner_on_start",
            "runner_retry",
            "playbook_on_include",
        ]:
            return

        if event["event"] == "runner_on_ok":
            if event.get("event_data")["task"] == "Data":
                self.data = event["event_data"]["res"]["msg"]
            return

        if event["event"] == "warning":
            task_type = "WARNING"
            task_data = event["stdout"]
        elif event["event"] == "error":
            task_type = "ERROR"
            task_data = event["stdout"]
        elif event["event"] == "playbook_on_play_start":
            task_type = f"PLAY [{event['event_data']['play']}]"
        elif event["event"] == "playbook_on_task_start":
            task_type = f"{event['event_data']['task']}"
        elif event["event"] == "runner_on_failed":
            task_data = (
                f"fatal: [{event['event_data']['host']}]\n"
                f"{json.dumps(event['event_data']['res']['msg'])}"
            )
        elif event["event"] == "runner_item_on_failed":
            task_data = (
                f"fatal: [{event['event_data']['host']}]\n"
                f"{event['event_data']['res']['stderr']}"
            )
        elif event["event"] == "playbook_on_stats":
            task_type = "PLAY RECAP"
            task_data = (
                f"ok: {event['event_data']['ok']} \n"
                f"failures: {event['event_data']['failures']}"
            )
        else:
            task_type = event["event"]
            task_data = json.dumps(event)

        self.repo.create_task(
            self.job_id,
            self.counter,
            event["created"],
            task_type,
            task_data,
        )
        self.counter += 1

    def launch_runner(self, playbook_name: str, extra_vars: dict) -> RunnerResult:
        loaded_playbook: LoadedPlaybook | None = None
        credential_dir: str | None = None
        target_result: RunnerResult | None = None
        try:
            loaded_playbook = self._load_playbook(playbook_name)
            self.repo.set_job_playbook_version(self.job_id, loaded_playbook.version)

            effective_extra_vars = dict(extra_vars)
            if self.playbook_run_options.ssh_credential_hook_enabled:
                credential_dir = _create_job_credential_dir(
                    self.job_id,
                    self.playbook_run_options.ssh_credential_dir_root,
                )
                hook_vars = _build_ssh_credential_hook_vars(
                    job_id=self.job_id,
                    credential_dir=credential_dir,
                    target_playbook_name=playbook_name,
                    target_playbook_version=loaded_playbook.version,
                    extra_vars=extra_vars,
                )
                prepare_playbook = self._load_playbook(
                    self.playbook_run_options.ssh_credential_prepare_playbook
                )
                prepare_result = self._run_loaded_playbook(
                    self.playbook_run_options.ssh_credential_prepare_playbook,
                    prepare_playbook,
                    hook_vars,
                    job_dir_suffix="ssh-credential-prepare",
                    update_job_status=False,
                )
                self._record_internal_task(
                    "SSH_CREDENTIAL_PREPARE",
                    {
                        "enabled": True,
                        "playbook_name": (
                            self.playbook_run_options.ssh_credential_prepare_playbook
                        ),
                        "playbook_version": prepare_result.playbook_version,
                        "status": prepare_result.status,
                    },
                )
                if prepare_result.status != "successful":
                    self.repo.update_job(self.job_id, self.failed_status)
                    return RunnerResult(
                        "failed",
                        self.data,
                        self.counter,
                        playbook_name,
                        loaded_playbook.version,
                    )
                effective_extra_vars = _merge_ssh_credential_vars(
                    effective_extra_vars,
                    _build_ssh_vars_from_credential_dir(credential_dir),
                )
                self._record_internal_task(
                    "SSH_CREDENTIAL_ARTIFACTS",
                    _credential_artifacts(credential_dir),
                )

            target_result = self._run_loaded_playbook(
                playbook_name,
                loaded_playbook,
                effective_extra_vars,
                job_dir_suffix="target",
                update_job_status=True,
            )
            return target_result
        except Exception as err:
            self.repo.update_job(self.job_id, self.failed_status)
            self.repo.create_task(
                self.job_id,
                self.counter,
                dt.datetime.now(dt.timezone.utc),
                "FAILURE",
                str(err),
            )
            logger.exception(
                "Error preparing playbook '%s' for job %s",
                playbook_name,
                self.job_id,
            )
            return RunnerResult(
                "failed",
                self.data,
                self.counter + 1,
                playbook_name,
                loaded_playbook.version if loaded_playbook else None,
            )
        finally:
            if self.playbook_run_options.ssh_credential_hook_enabled and credential_dir:
                self._run_ssh_credential_cleanup(
                    credential_dir=credential_dir,
                    target_playbook_name=playbook_name,
                    target_playbook_version=(
                        loaded_playbook.version if loaded_playbook else ""
                    ),
                    extra_vars=extra_vars,
                )
                if not (
                    self.playbook_run_options.ssh_credential_retain_artifacts_on_failure
                    and target_result is not None
                    and target_result.status != "successful"
                ):
                    _remove_job_credential_dir(credential_dir)

    def _run_loaded_playbook(
        self,
        playbook_name: str,
        loaded_playbook: LoadedPlaybook,
        extra_vars: dict,
        *,
        job_dir_suffix: str,
        update_job_status: bool,
    ) -> RunnerResult:
        job_dir = os.path.join(
            self.job_dir_root,
            f"job-{self.job_id}-{job_dir_suffix}",
        )
        try:
            shutil.rmtree(job_dir, ignore_errors=True)
            os.makedirs(job_dir, exist_ok=True)
            if update_job_status:
                self.repo.update_job(self.job_id, self.running_status)
            thread, runner = _run_async_preserving_signals(
                quiet=False,
                verbosity=1,
                playbook=yaml.safe_load(loaded_playbook.content),
                private_data_dir=job_dir,
                extravars=extra_vars,
                event_handler=self.event_handler,
                status_handler=self.status_handler,
            )
        except Exception as err:
            if update_job_status:
                self.repo.update_job(self.job_id, self.failed_status)
            self.repo.create_task(
                self.job_id,
                self.counter,
                dt.datetime.now(dt.timezone.utc),
                "FAILURE",
                str(err),
            )
            logger.exception(
                "Error starting playbook '%s' for job %s",
                playbook_name,
                self.job_id,
            )
            shutil.rmtree(job_dir, ignore_errors=True)
            return RunnerResult(
                "failed",
                self.data,
                self.counter + 1,
                playbook_name,
                loaded_playbook.version if loaded_playbook else None,
            )

        heartbeat_ts = time.time() + 60
        try:
            while thread.is_alive():
                if update_job_status and time.time() > heartbeat_ts:
                    self.repo.update_job(self.job_id, self.running_status)
                    heartbeat_ts = time.time() + 60

                time.sleep(1)

            thread.join()
            if update_job_status:
                if runner.status == "successful":
                    self.repo.update_job(self.job_id, self.completed_status)
                else:
                    self.repo.update_job(self.job_id, self.failed_status)
        except Exception:
            if update_job_status:
                self.repo.update_job(self.job_id, self.failed_status)
            logger.exception(
                "Error while monitoring playbook '%s' for job %s",
                playbook_name,
                self.job_id,
            )
            return RunnerResult(
                "failed",
                self.data,
                self.counter,
                playbook_name,
                loaded_playbook.version,
            )
        finally:
            shutil.rmtree(job_dir, ignore_errors=True)

        return RunnerResult(
            runner.status,
            self.data,
            self.counter,
            playbook_name,
            loaded_playbook.version,
        )

    def _run_ssh_credential_cleanup(
        self,
        *,
        credential_dir: str,
        target_playbook_name: str,
        target_playbook_version: str,
        extra_vars: dict,
    ) -> None:
        try:
            cleanup_playbook = self._load_playbook(
                self.playbook_run_options.ssh_credential_cleanup_playbook
            )
        except Exception:
            logger.info(
                "Optional SSH credential cleanup playbook '%s' is not configured",
                self.playbook_run_options.ssh_credential_cleanup_playbook,
            )
            return

        cleanup_vars = _build_ssh_credential_hook_vars(
            job_id=self.job_id,
            credential_dir=credential_dir,
            target_playbook_name=target_playbook_name,
            target_playbook_version=target_playbook_version,
            extra_vars=extra_vars,
        )
        cleanup_result = self._run_loaded_playbook(
            self.playbook_run_options.ssh_credential_cleanup_playbook,
            cleanup_playbook,
            cleanup_vars,
            job_dir_suffix="ssh-credential-cleanup",
            update_job_status=False,
        )
        if cleanup_result.status != "successful":
            logger.warning(
                "SSH credential cleanup playbook '%s' finished with status %s",
                self.playbook_run_options.ssh_credential_cleanup_playbook,
                cleanup_result.status,
            )
        self._record_internal_task(
            "SSH_CREDENTIAL_CLEANUP",
            {
                "enabled": True,
                "playbook_name": (
                    self.playbook_run_options.ssh_credential_cleanup_playbook
                ),
                "playbook_version": cleanup_result.playbook_version,
                "status": cleanup_result.status,
            },
        )

    def _load_playbook(self, playbook_name: str) -> "LoadedPlaybook":
        playbook = self.repo.get_default_playbook(playbook_name)
        if playbook is None or playbook.content is None:
            raise RuntimeError(f"Default playbook '{playbook_name}' is not configured")
        return LoadedPlaybook(
            content=gzip.decompress(playbook.content).decode(),
            version=playbook.version.strftime(STRFTIME),
        )

    def _record_internal_task(self, task_name: str, task_desc: dict[str, Any]) -> None:
        self.repo.create_task(
            self.job_id,
            self.counter,
            dt.datetime.now(dt.timezone.utc),
            task_name,
            json.dumps(task_desc, sort_keys=True),
        )
        self.counter += 1


class LiteAnsibleRunner:
    """Run a stored playbook and capture only the playbook's Data result."""

    def __init__(
        self,
        *,
        repo: Any,
        job_id: int,
        job_dir_root: str = "/tmp",
    ):
        self.data: dict[str, Any] = {}
        self.repo = repo
        self.job_id = job_id
        self.job_dir_root = job_dir_root

    def status_handler(self, status, runner_config):
        return

    def event_handler(self, event):
        if event["event"] == "runner_on_ok":
            if event.get("event_data")["task"] == "Data":
                self.data = event["event_data"]["res"]["msg"]

    def launch_runner(self, playbook_name: str, extra_vars: dict) -> LiteRunnerResult:
        job_dir = os.path.join(self.job_dir_root, f"job-{self.job_id}")
        loaded_playbook: LoadedPlaybook | None = None
        try:
            loaded_playbook = self._load_playbook(playbook_name)
            self.repo.set_job_playbook_version(self.job_id, loaded_playbook.version)

            shutil.rmtree(job_dir, ignore_errors=True)
            os.makedirs(job_dir, exist_ok=True)

            thread, runner = _run_async_preserving_signals(
                quiet=False,
                verbosity=1,
                playbook=loaded_playbook.content,
                private_data_dir=job_dir,
                extravars=extra_vars,
                event_handler=self.event_handler,
                status_handler=self.status_handler,
            )
        except Exception:
            logger.exception(
                "Error starting playbook '%s' for job %s",
                playbook_name,
                self.job_id,
            )
            shutil.rmtree(job_dir, ignore_errors=True)
            return LiteRunnerResult(
                "failed",
                self.data,
                playbook_name,
                loaded_playbook.version if loaded_playbook else None,
            )

        try:
            thread.join()
        finally:
            shutil.rmtree(job_dir, ignore_errors=True)

        return LiteRunnerResult(
            runner.status,
            self.data,
            playbook_name,
            loaded_playbook.version,
        )

    def _load_playbook(self, playbook_name: str) -> "LoadedPlaybook":
        playbook = self.repo.get_default_playbook(playbook_name)
        if playbook is None or playbook.content is None:
            raise RuntimeError(f"Default playbook '{playbook_name}' is not configured")
        return LoadedPlaybook(
            content=gzip.decompress(playbook.content).decode(),
            version=playbook.version.strftime(STRFTIME),
        )


def _run_async_preserving_signals(**kwargs):
    signal_handlers = _capture_signal_handlers()
    try:
        return ansible_runner.run_async(**kwargs)
    finally:
        _restore_signal_handlers(signal_handlers)


def _capture_signal_handlers():
    if not _can_manage_signal_handlers():
        return None
    return {
        signal.SIGINT: signal.getsignal(signal.SIGINT),
        signal.SIGTERM: signal.getsignal(signal.SIGTERM),
    }


def _restore_signal_handlers(signal_handlers) -> None:
    if signal_handlers is None:
        return
    for signal_number, handler in signal_handlers.items():
        signal.signal(signal_number, handler)


def _can_manage_signal_handlers() -> bool:
    return threading.current_thread() is threading.main_thread()


def configure_playbook_run_options(options: PlaybookRunOptions | None = None) -> None:
    """Configure default runtime options for subsequent playbook runs."""
    global _configured_playbook_run_options
    _configured_playbook_run_options = options or DEFAULT_PLAYBOOK_RUN_OPTIONS


def get_playbook_run_options() -> PlaybookRunOptions:
    """Return the currently configured playbook runtime options."""
    return _configured_playbook_run_options


def _create_job_credential_dir(job_id: int, credential_dir_root: str) -> str:
    credential_dir = os.path.join(credential_dir_root, str(job_id), "ssh")
    os.makedirs(credential_dir, mode=0o700, exist_ok=True)
    os.chmod(credential_dir, 0o700)
    return credential_dir


def _remove_job_credential_dir(credential_dir: str) -> None:
    job_dir = os.path.dirname(credential_dir)
    shutil.rmtree(job_dir, ignore_errors=True)


def _build_ssh_credential_hook_vars(
    *,
    job_id: int,
    credential_dir: str,
    target_playbook_name: str,
    target_playbook_version: str,
    extra_vars: dict,
) -> dict[str, Any]:
    hook_vars = dict(extra_vars)
    hook_vars.update(
        {
            "cpkit_job_id": job_id,
            "cpkit_target_playbook_name": target_playbook_name,
            "cpkit_target_playbook_version": target_playbook_version,
            "cpkit_credential_dir": credential_dir,
        }
    )
    target_hosts = _target_hosts_from_extra_vars(extra_vars)
    if target_hosts:
        hook_vars["cpkit_target_hosts"] = target_hosts
        first_host = target_hosts[0]
        if first_host.get("hostname") is not None:
            hook_vars.setdefault("target_hostname", first_host["hostname"])
        if first_host.get("ansible_host") is not None:
            hook_vars.setdefault("target_ansible_host", first_host["ansible_host"])
        if first_host.get("ansible_user") is not None:
            hook_vars.setdefault("target_ansible_user", first_host["ansible_user"])
    return hook_vars


def _target_hosts_from_extra_vars(extra_vars: dict) -> list[dict[str, Any]]:
    existing_hosts = extra_vars.get("cpkit_target_hosts")
    if isinstance(existing_hosts, list):
        return [host for host in existing_hosts if isinstance(host, dict)]

    host = {
        "hostname": extra_vars.get("target_hostname") or extra_vars.get("hostname"),
        "ansible_host": extra_vars.get("target_ansible_host")
        or extra_vars.get("ansible_host"),
        "ansible_user": extra_vars.get("target_ansible_user")
        or extra_vars.get("ansible_user"),
    }
    return [host] if any(value is not None for value in host.values()) else []


def _build_ssh_vars_from_credential_dir(credential_dir: str) -> dict[str, Any]:
    id_key = os.path.join(credential_dir, "id_key")
    id_key_cert = os.path.join(credential_dir, "id_key-cert.pub")
    known_hosts = os.path.join(credential_dir, "known_hosts")
    ssh_config = os.path.join(credential_dir, "ssh_config")

    ssh_vars: dict[str, Any] = {}
    common_args: list[str] = []
    if os.path.exists(id_key):
        os.chmod(id_key, 0o600)
        ssh_vars["ansible_ssh_private_key_file"] = id_key
        common_args.append("-o IdentitiesOnly=yes")
    if os.path.exists(id_key_cert):
        os.chmod(id_key_cert, 0o644)
        common_args.append(f"-o CertificateFile={id_key_cert}")
    if os.path.exists(known_hosts):
        os.chmod(known_hosts, 0o644)
        common_args.append(f"-o UserKnownHostsFile={known_hosts}")
    if os.path.exists(ssh_config):
        os.chmod(ssh_config, 0o644)
        common_args.append(f"-F {ssh_config}")
    if common_args:
        ssh_vars["ansible_ssh_common_args"] = " ".join(common_args)
    return ssh_vars


def _credential_artifacts(credential_dir: str) -> dict[str, bool]:
    return {
        "id_key": os.path.exists(os.path.join(credential_dir, "id_key")),
        "id_key_cert_pub": os.path.exists(
            os.path.join(credential_dir, "id_key-cert.pub")
        ),
        "known_hosts": os.path.exists(os.path.join(credential_dir, "known_hosts")),
        "ssh_config": os.path.exists(os.path.join(credential_dir, "ssh_config")),
    }


def _merge_ssh_credential_vars(
    extra_vars: dict[str, Any],
    ssh_vars: dict[str, Any],
) -> dict[str, Any]:
    merged = dict(extra_vars)
    ssh_vars = dict(ssh_vars)
    ssh_common_args = ssh_vars.pop("ansible_ssh_common_args", None)
    merged.update(ssh_vars)
    if ssh_common_args:
        existing_common_args = str(merged.get("ansible_ssh_common_args") or "").strip()
        merged["ansible_ssh_common_args"] = " ".join(
            value for value in (existing_common_args, ssh_common_args) if value
        )
    return merged


def run_playbook(
    *,
    repo: Any,
    job_id: int,
    playbook_name: str,
    extra_vars: dict,
    task_id_counter: int = 0,
    running_status: Any = "RUNNING",
    completed_status: Any = "COMPLETED",
    failed_status: Any = "FAILED",
    job_dir_root: str = "/tmp",
    playbook_run_options: PlaybookRunOptions | None = None,
    ssh_credential_hook_enabled: bool | None = None,
    ssh_credential_prepare_playbook: str | None = None,
    ssh_credential_cleanup_playbook: str | None = None,
    ssh_credential_dir_root: str | None = None,
    ssh_credential_retain_artifacts_on_failure: bool | None = None,
) -> RunnerResult:
    """Run a stored playbook for a framework job."""
    effective_options = _effective_playbook_run_options(
        playbook_run_options=playbook_run_options,
        ssh_credential_hook_enabled=ssh_credential_hook_enabled,
        ssh_credential_prepare_playbook=ssh_credential_prepare_playbook,
        ssh_credential_cleanup_playbook=ssh_credential_cleanup_playbook,
        ssh_credential_dir_root=ssh_credential_dir_root,
        ssh_credential_retain_artifacts_on_failure=(
            ssh_credential_retain_artifacts_on_failure
        ),
    )
    return AnsibleRunner(
        repo=repo,
        job_id=job_id,
        counter=task_id_counter,
        running_status=running_status,
        completed_status=completed_status,
        failed_status=failed_status,
        job_dir_root=job_dir_root,
        playbook_run_options=effective_options,
    ).launch_runner(playbook_name, extra_vars)


def _effective_playbook_run_options(
    *,
    playbook_run_options: PlaybookRunOptions | None,
    ssh_credential_hook_enabled: bool | None,
    ssh_credential_prepare_playbook: str | None,
    ssh_credential_cleanup_playbook: str | None,
    ssh_credential_dir_root: str | None,
    ssh_credential_retain_artifacts_on_failure: bool | None,
) -> PlaybookRunOptions:
    base = playbook_run_options or get_playbook_run_options()
    return PlaybookRunOptions(
        ssh_credential_hook_enabled=(
            base.ssh_credential_hook_enabled
            if ssh_credential_hook_enabled is None
            else ssh_credential_hook_enabled
        ),
        ssh_credential_prepare_playbook=(
            ssh_credential_prepare_playbook or base.ssh_credential_prepare_playbook
        ),
        ssh_credential_cleanup_playbook=(
            ssh_credential_cleanup_playbook or base.ssh_credential_cleanup_playbook
        ),
        ssh_credential_dir_root=ssh_credential_dir_root or base.ssh_credential_dir_root,
        ssh_credential_retain_artifacts_on_failure=(
            base.ssh_credential_retain_artifacts_on_failure
            if ssh_credential_retain_artifacts_on_failure is None
            else ssh_credential_retain_artifacts_on_failure
        ),
    )


def run_playbook_lite(
    *,
    repo: Any,
    job_id: int,
    playbook_name: str,
    extra_vars: dict,
    job_dir_root: str = "/tmp",
) -> LiteRunnerResult:
    """Run a stored playbook and capture only its Data result."""
    return LiteAnsibleRunner(
        repo=repo,
        job_id=job_id,
        job_dir_root=job_dir_root,
    ).launch_runner(playbook_name, extra_vars)
