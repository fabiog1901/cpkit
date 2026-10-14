# Composing API-key operations

Applications can pass `api_keys_router` to `create_cpkit_bundle` to replace only
the standard API-key routes under the existing administrator guard. Authentication,
settings, playbooks, events, jobs and workers retain their normal registration.

`ApiKeysService.create_api_key` and `delete_api_key` accept a caller-owned CPKit
`DatabaseTransaction` as keyword `tx`. Framework SQL and crypto remain canonical;
credential writes and deletion's locked read use the bound helpers. The caller
owns the complete transaction, retry and post-commit audit. Composed operations
suppress success hooks because the outer transaction has not yet committed.
Return generated secrets only after complete commit and never include secrets
in audit metadata. Standalone calls retain their existing behavior.

The actual consumer is Kloigos #289: credential creation/deletion and the single
organization binding/history must commit together. Independently committed
credential writes followed by an audit hook cannot provide that guarantee.
