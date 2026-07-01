"""Ansible runner helpers for framework-managed playbooks."""

import datetime as dt
import gzip
import json
import logging
import os
import shutil
import time
from dataclasses import dataclass
from typing import Any

import ansible_runner
import yaml

from cpkit.audit import log_event
from cpkit.time import STRFTIME

logger = logging.getLogger(__name__)


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
        audit_actor: str | None = None,
    ):
        self.data: dict[str, Any] = {}
        self.repo = repo
        self.job_id = job_id
        self.counter = counter
        self.running_status = running_status
        self.completed_status = completed_status
        self.failed_status = failed_status
        self.job_dir_root = job_dir_root
        self.audit_actor = audit_actor

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
        job_dir = self._job_dir()
        loaded_playbook: LoadedPlaybook | None = None
        try:
            loaded_playbook = self._load_playbook(playbook_name)

            shutil.rmtree(job_dir, ignore_errors=True)
            os.makedirs(job_dir, exist_ok=True)
            self.repo.update_job(self.job_id, self.running_status)
            self.repo.create_task(
                self.job_id,
                self.counter,
                dt.datetime.now(dt.timezone.utc),
                "PLAYBOOK_STARTED",
                json.dumps(
                    {
                        "playbook_name": playbook_name,
                        "playbook_version": loaded_playbook.version,
                    },
                ),
            )
            self.counter += 1
            self._emit_playbook_run_event(playbook_name, loaded_playbook.version)

            thread, runner = ansible_runner.run_async(
                quiet=False,
                verbosity=1,
                playbook=yaml.safe_load(loaded_playbook.content),
                private_data_dir=job_dir,
                extravars=extra_vars,
                event_handler=self.event_handler,
                status_handler=self.status_handler,
            )
        except Exception as err:
            self._mark_failed()
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
                if time.time() > heartbeat_ts:
                    self.repo.update_job(self.job_id, self.running_status)
                    heartbeat_ts = time.time() + 60

                time.sleep(1)

            if runner.status == "successful":
                self.repo.update_job(self.job_id, self.completed_status)
            else:
                self._mark_failed()
        except Exception:
            self._mark_failed()
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
                loaded_playbook.version if loaded_playbook else None,
            )
        finally:
            shutil.rmtree(job_dir, ignore_errors=True)

        return RunnerResult(
            runner.status,
            self.data,
            self.counter,
            playbook_name,
            loaded_playbook.version if loaded_playbook else None,
        )

    def _job_dir(self) -> str:
        return os.path.join(self.job_dir_root, f"job-{self.job_id}")

    def _load_playbook(self, playbook_name: str) -> "LoadedPlaybook":
        playbook = self.repo.get_default_playbook(playbook_name)
        if playbook is None or playbook.content is None:
            raise RuntimeError(f"Default playbook '{playbook_name}' is not configured")
        return LoadedPlaybook(
            content=gzip.decompress(playbook.content).decode(),
            version=playbook.version.strftime(STRFTIME),
        )

    def _mark_failed(self) -> None:
        self.repo.update_job(self.job_id, self.failed_status)

    def _emit_playbook_run_event(
        self, playbook_name: str, playbook_version: str
    ) -> None:
        if not self.audit_actor:
            return
        try:
            log_event(
                self.repo,
                self.audit_actor,
                "PLAYBOOK_RUN_STARTED",
                {
                    "job_id": self.job_id,
                    "playbook_name": playbook_name,
                    "playbook_version": playbook_version,
                },
            )
        except Exception:
            logger.exception(
                "Failed to write playbook run audit event for job %s",
                self.job_id,
            )


class LiteAnsibleRunner:
    """Run a stored playbook and capture only the playbook's Data result."""

    def __init__(
        self,
        *,
        repo: Any,
        job_id: int,
        job_dir_root: str = "/tmp",
        audit_actor: str | None = None,
    ):
        self.data: dict[str, Any] = {}
        self.repo = repo
        self.job_id = job_id
        self.job_dir_root = job_dir_root
        self.audit_actor = audit_actor

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
            self._emit_playbook_run_event(playbook_name, loaded_playbook.version)

            shutil.rmtree(job_dir, ignore_errors=True)
            os.makedirs(job_dir, exist_ok=True)

            thread, runner = ansible_runner.run_async(
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
            loaded_playbook.version if loaded_playbook else None,
        )

    def _load_playbook(self, playbook_name: str) -> "LoadedPlaybook":
        playbook = self.repo.get_default_playbook(playbook_name)
        if playbook is None or playbook.content is None:
            raise RuntimeError(f"Default playbook '{playbook_name}' is not configured")
        return LoadedPlaybook(
            content=gzip.decompress(playbook.content).decode(),
            version=playbook.version.strftime(STRFTIME),
        )

    def _emit_playbook_run_event(
        self, playbook_name: str, playbook_version: str
    ) -> None:
        if not self.audit_actor:
            return
        try:
            log_event(
                self.repo,
                self.audit_actor,
                "PLAYBOOK_RUN_STARTED",
                {
                    "job_id": self.job_id,
                    "playbook_name": playbook_name,
                    "playbook_version": playbook_version,
                },
            )
        except Exception:
            logger.exception(
                "Failed to write playbook run audit event for job %s",
                self.job_id,
            )


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
    audit_actor: str | None = None,
) -> RunnerResult:
    """Run a stored playbook for a framework job."""
    return AnsibleRunner(
        repo=repo,
        job_id=job_id,
        counter=task_id_counter,
        running_status=running_status,
        completed_status=completed_status,
        failed_status=failed_status,
        job_dir_root=job_dir_root,
        audit_actor=audit_actor,
    ).launch_runner(playbook_name, extra_vars)


def run_playbook_lite(
    *,
    repo: Any,
    job_id: int,
    playbook_name: str,
    extra_vars: dict,
    job_dir_root: str = "/tmp",
    audit_actor: str | None = None,
) -> LiteRunnerResult:
    """Run a stored playbook and capture only its Data result."""
    return LiteAnsibleRunner(
        repo=repo,
        job_id=job_id,
        job_dir_root=job_dir_root,
        audit_actor=audit_actor,
    ).launch_runner(playbook_name, extra_vars)
