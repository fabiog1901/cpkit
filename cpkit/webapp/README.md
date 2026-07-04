# cpkit Template Webapp

This is the generic cpkit webapp shell. It keeps the framework-owned pages for
auth/session visibility, jobs, events, API keys, settings, and playbooks while
leaving application-specific business pages to the consuming app.

The webapp is intentionally static: `index.html`, `style.css`, and `script.js`
are served as files, and the browser talks to cpkit's JSON APIs. Apps extend the
shell by mounting their own static directory at `/app`.

Use it from an app with:

```python
from cpkit import create_cpkit_app, template_webapp_directory

app = create_cpkit_app(
    title="my-app",
    version="0.1.0",
    repo_class=Repo,
    db_url=CPKIT_DB_URL,
    capabilities=(cpkit_capabilities,),
    routers=(my_router,),
    static_directory=template_webapp_directory(),
    app_static_directory="webapp",
)
```

If `app_static_directory` is set, cpkit mounts it at `/app` and the template
loads optional `/app/extension.html`, `/app/extension.css`, and
`/app/extension.js` assets. Applications can use those files to add navigation
items, views, Alpine state, and methods without copying the cpkit webapp.

## Files

- `index.html`: The shared shell markup and built-in pages.
- `script.js`: Alpine state, API helpers, routing, table behavior, dashboard
  card handling, and extension loading.
- `style.css`: Shared visual system for the shell and built-in pages.
- `__init__.py`: Exports `template_webapp_directory()` so apps can mount the
  template without hard-coding a path.

## Built-In Pages

- Dashboard
- Jobs and job details
- Events
- Admin landing page
- Admin settings
- Admin API keys
- Admin playbooks
- Login/session UI

## Extension Contract

Apps can define `window.cpkitWebappExtension` from `/app/extension.js`.
Common extension fields include:

- `navItems`: App-owned main navigation entries.
- `adminItems`: App-owned admin entries.
- `routes`: Hash routes handled by the app extension.
- `state`: Extra Alpine state merged into the shell.
- `methods`: Extra Alpine methods merged into the shell.
- Dashboard cards rendered through the extension dashboard template/card APIs.

For the full extension guide, see
`resources/webapp_extension_guide.md`.
