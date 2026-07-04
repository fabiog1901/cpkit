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

