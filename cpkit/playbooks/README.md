# Playbooks

The playbooks package owns versioned playbook storage and Ansible execution.
It lets apps store playbook versions in the database, choose a default version,
edit playbooks from the admin webapp, and run the selected playbook as part of a
job.

## Files

- `types.py`: Playbook records, list/version responses, and save requests.
- `repository.py`: Repository mixin for playbook version storage and defaults.
- `service.py`: Version listing, loading, saving, deleting, and default-setting
  rules.
- `router.py`: Admin playbook API routes.
- `ansible.py`: Ansible runner wrappers that load stored playbooks, update jobs,
  and record task output.

## Runtime Flow

1. Admin APIs manage compressed playbook content and default versions.
2. A job handler calls `run_playbook()` or `run_playbook_lite()`.
3. The runner loads the default playbook version from the database.
4. The runner records the selected version on the job and writes task output as
   Ansible events arrive.

## Optional SSH Credential Hooks

`run_playbook()` can optionally run app-provided, versioned Ansible hook
playbooks before and after the target playbook:

- `SSH_CREDENTIAL_PREPARE`: required when hooks are enabled.
- `SSH_CREDENTIAL_CLEANUP`: optional and best-effort.

This is disabled by default and normally configured through CPKit settings under
`playbooks.ssh_credential_hook.*`. On startup, `create_cpkit_app()` loads those
settings into `PlaybookRunOptions`; settings updates and resets refresh the
in-memory options for subsequent playbook runs.

The settings are:

- `playbooks.ssh_credential_hook.enabled`
- `playbooks.ssh_credential_hook.prepare_playbook`
- `playbooks.ssh_credential_hook.cleanup_playbook`
- `playbooks.ssh_credential_hook.dir_root`
- `playbooks.ssh_credential_hook.retain_artifacts_on_failure`

Direct `run_playbook()` keyword arguments can still override the effective
settings-backed default for that one call.

The prepare hook receives job, target playbook, and target host context plus
`cpkit_credential_dir`, a job-scoped directory created with `0700` permissions.

If the prepare hook writes conventional files such as `id_key`,
`id_key-cert.pub`, `known_hosts`, or `ssh_config`, cpkit applies them to the
target playbook through Ansible SSH extra vars while preserving existing
`ansible_ssh_common_args`. The credential directory is removed after execution
unless artifact retention on failure is explicitly enabled.

The hook mechanism is intentionally provider-neutral. cpkit does not implement
Teleport, Vault, Smallstep, or any other SSH CA integration; apps own those
hook playbooks.
