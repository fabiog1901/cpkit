# cpkit Webapp Extension Guide

This guide describes how an application should use cpkit's template webapp
without copying or forking the framework-owned shell.

Use this document as the instruction source when asking Codex to port an app
webapp, such as Kloigos, to cpkit.

## Goal

The application uses cpkit's webapp as the main shell. cpkit owns the shared
pages and browser plumbing for:

- Authentication/session visibility
- Dashboard
- Jobs
- Events
- Settings
- API keys
- Playbooks

The application contributes only business-specific views, styles, and browser
logic through extension assets.

## Expected App Structure

The app should provide a small static webapp directory:

```text
webapp/
  extension.html
  extension.css
  extension.js
```

The app bootstrap should pass that directory to cpkit:

```python
from cpkit import create_cpkit_app, template_webapp_directory

app = create_cpkit_app(
    title="my-app",
    version="0.1.0",
    repo_class=Repo,
    db_url=CPKIT_DB_URL,
    capabilities=(app_capabilities,),
    routers=(app_router,),
    static_directory=template_webapp_directory(),
    app_static_directory="webapp",
)
```

cpkit mounts the app webapp directory at `/app`.

## Extension JavaScript Contract

`extension.js` registers the application extension on `window`:

```javascript
window.cpkitWebappExtension = {
  htmlPath: "/app/extension.html",
  navItems: [{ view: "app_view", label: "App" }],
  routes: {
    app_view: {
      path: "/app-view",
      label: "App",
      subtitle: "Application view",
      ensure: "ensureAppView",
    },
  },
  state: {
    rows: [],
    loading: { list: false },
  },
  methods: {
    async ensureAppView() {
      await this.refreshAppRows();
    },
    async refreshAppRows() {
      this.loading.list = true;
      try {
        this.rows = await this.apiFetch("/app/resources", { method: "GET" });
      } finally {
        this.loading.list = false;
      }
    },
  },
};
```

Route `path` values are hash routes in the cpkit shell. API calls should be
relative to cpkit's `/api` prefix by using the shell-provided `apiFetch()`
helper.

## Extension HTML Contract

`extension.html` contains app-specific Alpine markup. It can also declare app
branding:

```html
<template
  id="cpkit-extension-brand"
  data-logo-text="kg"
  data-app-name="Kloigos"
  data-login-subtitle="Authenticate to manage Kloigos"
></template>

<main class="layout" x-show="view === 'app_view'">
  <aside class="sidebar">
    <section>
      <h2>Actions</h2>
      <div class="metric button-stack">
        <button class="btn primary" @click="refreshAppRows()">Refresh</button>
      </div>
    </section>
  </aside>

  <section class="main">
    <div class="section-head">
      <div>
        <h2>App</h2>
        <p>Application-specific data.</p>
      </div>
    </div>
  </section>
</main>
```

Use cpkit's existing shell classes where possible, such as `layout`, `sidebar`,
`main`, `section-head`, `table-wrap`, `btn`, `input`, `notice`, and `modal`.

## Extension CSS Contract

`extension.css` should only style app-specific content. Prefer additive class
names that belong to the app view:

```css
.app-title-cell {
  min-width: 16rem;
}

.app-actions {
  display: flex;
  gap: 0.5rem;
  justify-content: flex-end;
}
```

Avoid restyling the cpkit shell globally unless the app intentionally owns a
broader visual theme.

## Porting Checklist

1. Map the existing app webapp.
   - Identify old shell code.
   - Identify pages already provided by cpkit.
   - Identify true app-specific pages.
   - List API endpoints each app page calls.

2. Update the app bootstrap.
   - Use `template_webapp_directory()` for cpkit's static shell.
   - Pass `app_static_directory="webapp"` or the app's equivalent path.
   - Keep app API routers mounted through cpkit.

3. Create extension assets.
   - Move app-specific markup into `webapp/extension.html`.
   - Move app-specific state, route registration, and methods into
     `webapp/extension.js`.
   - Move app-specific styles into `webapp/extension.css`.

4. Remove duplicate shell code.
   - Do not copy cpkit's topbar, auth/login panel, admin pages, jobs page,
     events page, settings page, API keys page, or playbooks page.
   - Do not reimplement session/auth UI in the app extension.

5. Preserve API behavior.
   - Keep existing app-specific endpoints unless the migration explicitly
     changes them.
   - Use `this.apiFetch()` from extension methods for authenticated API calls.

6. Handle database IDs carefully.
   - Database-generated `INT8` IDs can exceed JavaScript's safe integer range.
   - Serialize large IDs as strings in JSON responses.
   - Treat IDs as strings in JavaScript and path construction.

7. Verify the port.
   - Run `node --check webapp/extension.js`.
   - Run Python compile/import checks for the app.
   - Start the app and confirm the `/app` static mount is present.
   - Confirm each app route renders once and only once.
   - Confirm app actions call the expected `/api/...` endpoints.

## Recommended Codex Prompt

```text
Read resources/webapp_extension_guide.md and port this app's webapp to cpkit's
template extension model.

Preserve app-specific behavior, remove duplicate shell code, do not fork
cpkit's webapp, and work in small verifiable steps. Keep large database IDs as
strings in JavaScript-facing JSON.
```

Before starting a larger port, add a short app-specific map to the prompt:

```text
Current webapp map:
- webapp/index.html: old app shell and page markup
- webapp/script.js: old app state/actions
- webapp/style.css: reusable app styles
- /api/example: endpoint used by Example page
```
