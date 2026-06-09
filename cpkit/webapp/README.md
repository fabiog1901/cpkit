# cpkit Template Webapp

This is the generic cpkit webapp shell. It keeps the framework-owned pages for
auth/session visibility, jobs, events, API keys, settings, and playbooks while
leaving application-specific business pages to the consuming app.

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
