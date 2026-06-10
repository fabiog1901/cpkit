window.app = function () {
  const extension = window.cpkitWebappExtension || {};
  return {
    view: "dashboard",
    apiBase: "/api",
    extensionNavItems: Array.isArray(extension.navItems) ? extension.navItems : [],
    extensionAdminItems: Array.isArray(extension.adminItems) ? extension.adminItems : [],
    brand: {
      logoText: "ck",
      appName: "cpkit",
      loginSubtitle: "Authenticate to access the dashboard",
    },
    authChecked: false,
    isAuthenticated: false,
    authClaims: null,
    authLoginPath: "/api/auth/login",
    authDisplayNameClaim: "preferred_username",
    authSessionCookieName: "cp_session",
    authError: "",
    viewNotice: "",
    viewNoticeJobId: "",

    jobs: [],
    jobStats: { total: 0, running: 0, queued: 0, failed: 0 },
    jobsVisibleRows: [],
    jobsFilterQuery: "",
    jobsLastUpdatedUtc: null,
    jobsSortIndex: 0,
    jobsSortDir: "desc",
    jobsLoading: { list: false },
    jobsAutoRefreshEnabled: true,
    _jobsAutoTimer: null,
    selectedJobId: "",
    selectedJobDetails: null,
    jobLoading: { details: false, reschedule: false },
    jobDetailsAutoRefreshEnabled: true,

    events: [],
    eventsVisibleRows: [],
    eventsFilterQuery: "",
    eventsLastUpdatedUtc: null,
    eventsSortIndex: 0,
    eventsSortDir: "desc",
    eventsLoading: { list: false },
    eventsAutoRefreshEnabled: true,
    _eventsAutoTimer: null,

    apiKeys: [],
    apiKeysVisibleRows: [],
    apiKeysFilterQuery: "",
    apiKeysLastUpdatedUtc: null,
    apiKeysSortIndex: 2,
    apiKeysSortDir: "desc",
    apiKeysLoading: { list: false, create: false, delete: false },
    apiKeysAutoRefreshEnabled: true,
    _apiKeysAutoTimer: null,

    settings: [],
    settingsVisibleRows: [],
    settingsFilterQuery: "",
    settingsCategoryTab: "all",
    settingsLastUpdatedUtc: null,
    settingsDrafts: {},
    settingsSortIndex: 0,
    settingsSortDir: "asc",
    settingsLoading: { list: false, update: false, reset: false },
    settingsAutoRefreshEnabled: true,
    settingsToast: { message: "", ok: true },
    _settingsAutoTimer: null,
    _settingsToastTimer: null,

    selectedPlaybook: "",
    pbLoading: { load: false, save: false, setDefault: false, delete: false },
    pbToast: { message: "", ok: true },
    pbLastUpdatedUtc: null,
    pbDefaultVersion: "",
    pbSelectedVersion: "",
    pbVersions: [],
    _ace: null,
    _aceReady: false,

    modal: {
      userInfo: { open: false },
      apiKeyCreate: {
        open: false,
        valid_until: "",
        rolesText: "CP_ADMIN",
        created: null,
      },
    },
    modalError: {},

    async init() {
      await this.loadExtensionHtml();
      this.applyExtensionHooks();
      this.applyExtensionBrand();
      this.restoreLocalState();
      await this.checkAuth();
      if (!this.isAuthenticated) return;
      this.applyRouteFromHash();
      window.addEventListener("hashchange", () => this.applyRouteFromHash());
      await this.ensureViewData();
      this.setManagedInterval("_jobsAutoTimer", () => {
        if (this.jobsAutoRefreshEnabled && this.view === "jobs") this.refreshJobs();
      });
      this.setManagedInterval("_jobDetailsAutoTimer", () => {
        if (this.jobDetailsAutoRefreshEnabled && this.view === "job") this.refreshSelectedJobDetails();
      });
      this.setManagedInterval("_eventsAutoTimer", () => {
        if (this.eventsAutoRefreshEnabled && this.view === "events") this.refreshEvents();
      });
      this.setManagedInterval("_apiKeysAutoTimer", () => {
        if (this.apiKeysAutoRefreshEnabled && this.view === "api_keys") this.refreshApiKeys();
      }, 20000);
      this.setManagedInterval("_settingsAutoTimer", () => {
        if (this.settingsAutoRefreshEnabled && this.view === "settings") this.refreshSettings();
      }, 20000);
      this.refreshDashboardOverview({ onlyIfEmpty: true });
      if (typeof extension.init === "function") {
        await extension.init.call(this);
      }
    },

    async loadExtensionHtml() {
      const target = document.getElementById("cpkit-extension-root");
      if (!target || target.dataset.extensionLoaded) return;

      const htmlPath = extension.htmlPath || "/app/extension.html";
      try {
        target.dataset.extensionLoaded = "loading";
        const res = await fetch(htmlPath, { method: "GET" });
        if (!res.ok) {
          delete target.dataset.extensionLoaded;
          return;
        }
        const html = await res.text();
        if (!html.trim()) {
          delete target.dataset.extensionLoaded;
          return;
        }
        target.innerHTML = html;
        target.dataset.extensionLoaded = "true";
      } catch {
        delete target.dataset.extensionLoaded;
        return;
      }
    },

    applyExtensionHooks() {
      for (const [key, value] of Object.entries(extension.state || {})) {
        if (this.isPlainObject(this[key]) && this.isPlainObject(value)) {
          this[key] = { ...this[key], ...value };
        } else {
          this[key] = value;
        }
      }
      for (const [name, method] of Object.entries(extension.methods || {})) {
        if (typeof method === "function") this[name] = method;
      }
    },

    applyExtensionBrand() {
      const brandMarker = document.getElementById("cpkit-extension-brand");
      const htmlBrand = brandMarker
        ? {
            logoText: brandMarker.dataset.logoText,
            appName: brandMarker.dataset.appName,
            loginSubtitle: brandMarker.dataset.loginSubtitle,
          }
        : {};
      this.brand = {
        ...this.brand,
        ...(extension.brand || {}),
        ...Object.fromEntries(Object.entries(htmlBrand).filter(([, value]) => value)),
      };
      document.title = this.brand.appName || "cpkit";
    },

    isPlainObject(value) {
      return Boolean(value && typeof value === "object" && !Array.isArray(value));
    },

    restoreLocalState() {
      this.jobsFilterQuery = localStorage.getItem("cpkit_jobs_filter") || "";
      this.eventsFilterQuery = localStorage.getItem("cpkit_events_filter") || "";
      this.apiKeysFilterQuery = localStorage.getItem("cpkit_api_keys_filter") || "";
      this.settingsFilterQuery = localStorage.getItem("cpkit_settings_filter") || "";
      this.settingsCategoryTab = localStorage.getItem("cpkit_settings_category") || "all";
    },

    setManagedInterval(key, fn, ms = 15000) {
      if (this[key]) clearInterval(this[key]);
      this[key] = setInterval(fn, ms);
    },

    async checkAuth() {
      try {
        const res = await fetch("/api/auth/me", { method: "GET" });
        const data = await this.safeJson(res);
        if (res.status === 401) {
          this.setAuthRequired(
            res.headers.get("x-auth-login-url") || data?.auth_login_url || "/api/auth/login",
            data?.detail || "Not authenticated.",
          );
          return;
        }
        if (!res.ok) throw new Error(data?.detail || `HTTP ${res.status}`);
        this.authClaims = data && typeof data === "object" ? data : null;
        this.applyAuthMetadata();
        this.isAuthenticated = true;
        this.authChecked = true;
      } catch (e) {
        this.authError = this.errorMessage(e, "Unable to verify session.");
        this.authChecked = true;
      }
    },

    setAuthRequired(loginPath, errorMessage) {
      this.isAuthenticated = false;
      this.authClaims = null;
      this.authLoginPath = loginPath || "/api/auth/login";
      this.authError = errorMessage || "Not authenticated.";
      this.authChecked = true;
    },

    applyAuthMetadata() {
      const meta = this.authClaims?._cp || {};
      this.authDisplayNameClaim = meta.display_name_claim || "preferred_username";
      this.authSessionCookieName = meta.session_cookie_name || "cp_session";
    },

    async refreshAuthMeSnapshot() {
      try {
        const data = await this.apiFetch("/auth/me", { method: "GET" });
        this.authClaims = data;
        this.applyAuthMetadata();
      } catch {
        return;
      }
    },

    loginWithSSO() {
      window.location.assign(this.authLoginPath || "/api/auth/login");
    },

    async logout() {
      try {
        await fetch("/api/auth/logout", { method: "POST" });
      } finally {
        this.setAuthRequired(this.authLoginPath, "");
        window.location.assign(this.authLoginPath || "/api/auth/login");
      }
    },

    applyRouteFromHash() {
      const hash = window.location.hash.replace(/^#/, "");
      const parts = hash.split("/").filter(Boolean);
      let next = "dashboard";
      if (parts[0] === "jobs" && parts[1]) {
        next = "job";
        this.selectedJobId = decodeURIComponent(parts[1]);
      } else if (parts[0] === "jobs") next = "jobs";
      else if (parts[0] === "events") next = "events";
      else if (parts[0] === "admin" && parts[1] === "api-keys") next = "api_keys";
      else if (parts[0] === "admin" && parts[1] === "settings") next = "settings";
      else if (parts[0] === "admin" && parts[1] === "playbooks") next = "playbooks";
      else {
        const hashPath = `/${parts.join("/")}`;
        const matched = this.extensionRouteForPath(hashPath);
        if (matched) next = matched[0];
        else if (parts[0] === "admin") next = "admin";
      }
      if (!this.canAccessView(next)) {
        this.handleForbiddenView(next);
        return;
      }
      this.view = next;
      this.ensureViewData();
    },

    routeForView(view) {
      const routes = {
        dashboard: "/",
        jobs: "/jobs",
        job: `/jobs/${encodeURIComponent(this.selectedJobId || "")}`,
        events: "/events",
        admin: "/admin",
        api_keys: "/admin/api-keys",
        settings: "/admin/settings",
        playbooks: "/admin/playbooks",
      };
      if (extension.routes?.[view]?.path) return extension.routes[view].path;
      return routes[view] || "/";
    },

    setView(next) {
      if (!this.canAccessView(next)) {
        this.handleForbiddenView(next);
        return;
      }
      this.view = next;
      window.location.hash = this.routeForView(next);
      this.ensureViewData();
    },

    canAccessView(viewName) {
      if (this.isExtensionAdminView(viewName) || extension.routes?.[viewName]?.adminOnly) return this.canViewAdmin();
      if (!["admin", "api_keys", "settings", "playbooks"].includes(viewName)) return true;
      return this.canViewAdmin();
    },

    handleForbiddenView(viewName) {
      this.viewNotice = `${this.viewLabel(viewName)} requires CP_ADMIN.`;
      this.view = "dashboard";
      window.location.hash = "/";
    },

    viewLabel(viewName) {
      return {
        api_keys: "API Keys",
        settings: "Settings",
        playbooks: "Playbooks",
        admin: "Admin",
      }[viewName] || extension.routes?.[viewName]?.label || viewName;
    },

    async ensureViewData() {
      if (!this.isAuthenticated) return;
      const extensionEnsure = extension.routes?.[this.view]?.ensure;
      if (extensionEnsure && typeof this[extensionEnsure] === "function") {
        await this[extensionEnsure]();
        return;
      }
      if (this.view === "jobs") await this.refreshJobs();
      else if (this.view === "job") await this.refreshSelectedJobDetails();
      else if (this.view === "events") await this.refreshEvents();
      else if (this.view === "api_keys") await this.refreshApiKeys();
      else if (this.view === "settings") await this.refreshSettings();
      else if (this.view === "playbooks") this.ensureAce();
      else if (this.view === "dashboard") await this.refreshDashboardOverview({ onlyIfEmpty: true });
    },

    viewSubtitle() {
      return {
        dashboard: "Framework overview",
        jobs: "Queued and completed orchestration work",
        job: "Job details",
        events: "Audit activity stream",
        admin: "Framework administration",
        api_keys: "Programmatic access credentials",
        settings: "Dynamic configuration",
        playbooks: "Versioned automation content",
      }[this.view] || extension.routes?.[this.view]?.subtitle || "";
    },

    isAdminSectionView() {
      return ["admin", "api_keys", "settings", "playbooks"].includes(this.view) || this.isExtensionAdminView(this.view);
    },

    extensionRouteForPath(path) {
      return Object.entries(extension.routes || {}).find(([, route]) => route.path === path);
    },

    builtInAdminItems() {
      return [
        {
          view: "api_keys",
          label: "API Keys",
          kicker: "Access",
          description: "Role-scoped access keys and one-time secret issuance.",
          icon: "key",
          countKey: "apiKeys",
        },
        {
          view: "settings",
          label: "Settings",
          kicker: "Configuration",
          description: "Dynamic framework settings and effective values.",
          icon: "settings",
          countKey: "settings",
        },
        {
          view: "playbooks",
          label: "Playbooks",
          kicker: "Automation",
          description: "Versioned playbook content used by cpkit jobs.",
          icon: "book",
          countKey: "pbVersions",
        },
      ];
    },

    normalizedExtensionAdminItems() {
      return this.extensionAdminItems
        .filter((item) => item && item.view && extension.routes?.[item.view])
        .map((item) => {
          const route = extension.routes[item.view] || {};
          return {
            ...item,
            label: item.label || route.label || item.view,
            kicker: item.kicker || route.kicker || "Application",
            description: item.description || route.subtitle || "",
            icon: item.icon || route.icon || "app",
            countKey: item.countKey || route.countKey || "",
          };
        });
    },

    adminItems() {
      return [...this.builtInAdminItems(), ...this.normalizedExtensionAdminItems()];
    },

    adminItemCount(item) {
      if (!item?.countKey) return "";
      const value = this[item.countKey];
      if (Array.isArray(value)) return value.length;
      if (value && typeof value === "object") return Object.keys(value).length;
      if (typeof value === "number") return value;
      return "";
    },

    isExtensionAdminView(viewName) {
      return this.extensionAdminItems.some((item) => item?.view === viewName);
    },

    async refreshDashboardOverview({ onlyIfEmpty = false } = {}) {
      if (!onlyIfEmpty || this.jobStats.total === 0) await this.refreshJobStats();
      if (!onlyIfEmpty || this.events.length === 0) await this.refreshEvents({ limit: 20 });
    },

    async refreshJobs() {
      this.jobsLoading.list = true;
      try {
        this.jobs = await this.apiFetch("/jobs/", { method: "GET" });
        if (!Array.isArray(this.jobs)) this.jobs = [];
        this.jobsLastUpdatedUtc = this.utcNowString();
        this.applyJobsFilterSort();
        this.refreshJobStats();
      } catch (e) {
        this.viewNotice = this.errorMessage(e, "Failed to load jobs.");
      } finally {
        this.jobsLoading.list = false;
      }
    },

    async refreshJobStats() {
      try {
        const data = await this.apiFetch("/jobs/stats", { method: "GET" });
        this.jobStats = { ...this.jobStats, ...(data || {}) };
      } catch {
        return;
      }
    },

    openJob(jobId) {
      this.selectedJobId = String(jobId || "");
      this.view = "job";
      window.location.hash = this.routeForView("job");
      this.refreshSelectedJobDetails();
    },

    async refreshSelectedJobDetails() {
      if (!this.selectedJobId) return;
      this.jobLoading.details = true;
      try {
        this.selectedJobDetails = await this.apiFetch(
          `/jobs/${encodeURIComponent(this.selectedJobId)}/details`,
          { method: "GET" },
        );
      } catch (e) {
        this.viewNotice = this.errorMessage(e, "Failed to load job details.");
      } finally {
        this.jobLoading.details = false;
      }
    },

    async rescheduleSelectedJob() {
      if (!this.selectedJobId) return;
      this.jobLoading.reschedule = true;
      try {
        const data = await this.apiFetch(
          `/jobs/${encodeURIComponent(this.selectedJobId)}/reschedule`,
          { method: "POST" },
        );
        this.viewNotice = `Created replacement job ${data.job_id}.`;
        this.viewNoticeJobId = String(data.job_id || "");
      } catch (e) {
        this.viewNotice = this.errorMessage(e, "Failed to reschedule job.");
      } finally {
        this.jobLoading.reschedule = false;
      }
    },

    jobsCellText(job, index) {
      return [
        job?.job_id,
        job?.job_type,
        job?.status,
        job?.created_by,
        job?.created_at,
        job?.updated_at,
      ][index] ?? "";
    },

    jobsRowText(job) {
      return [
        ...[0, 1, 2, 3, 4, 5].map((idx) => String(this.jobsCellText(job, idx))),
        this.jobsDescriptionText(job),
      ].join(" ").toLowerCase();
    },

    sortJobs(index) {
      if (this.jobsSortIndex === index) this.jobsSortDir = this.jobsSortDir === "asc" ? "desc" : "asc";
      else {
        this.jobsSortIndex = index;
        this.jobsSortDir = index === 0 || index >= 4 ? "desc" : "asc";
      }
      this.applyJobsFilterSort();
    },

    jobsSortClass(index) {
      if (this.jobsSortIndex !== index) return "";
      return this.jobsSortDir === "asc" ? "sort-asc" : "sort-desc";
    },

    applyJobsFilterSort() {
      localStorage.setItem("cpkit_jobs_filter", this.jobsFilterQuery || "");
      const q = String(this.jobsFilterQuery || "").toLowerCase().trim();
      let rows = this.jobs.slice();
      if (q) rows = rows.filter((job) => this.jobsRowText(job).includes(q));
      rows.sort((a, b) => this.compareValues(this.jobsCellText(a, this.jobsSortIndex), this.jobsCellText(b, this.jobsSortIndex)));
      if (this.jobsSortDir === "desc") rows.reverse();
      this.jobsVisibleRows = rows;
    },

    jobsTitle() {
      return "Jobs";
    },

    jobsSubtitle() {
      return "List of visible jobs from the jobs API.";
    },

    jobsDescriptionText(job) {
      return this.toYaml(job?.description ?? null);
    },

    jobTaskDescriptionText(task) {
      if (typeof task?.task_desc === "string") return task.task_desc;
      return this.toYaml(task?.task_desc ?? null);
    },

    onJobsFilterInput() {
      this.applyJobsFilterSort();
    },

    jobStatusClass(status) {
      const s = String(status || "").toLowerCase();
      if (!s || s === "unknown") return "status-muted";
      if (["completed", "succeeded", "success"].includes(s)) return "status-online";
      if (s === "running") return "status-warning";
      if (["queued", "pending"].includes(s)) return "status-pending status-pulse";
      if (["failed", "error", "cancelled"].includes(s)) return "status-offline";
      return "status-default";
    },

    async refreshEvents({ limit = 200, offset = 0 } = {}) {
      this.eventsLoading.list = true;
      try {
        const data = await this.apiFetch(`/events/?limit=${limit}&offset=${offset}`, { method: "GET" });
        this.events = Array.isArray(data) ? data : [];
        this.eventsLastUpdatedUtc = this.utcNowString();
        this.applyEventsFilterSort();
      } catch (e) {
        this.viewNotice = this.errorMessage(e, "Failed to load events.");
      } finally {
        this.eventsLoading.list = false;
      }
    },

    eventsCellText(event, index) {
      return [
        event?.ts,
        event?.user_id,
        event?.action,
        this.eventsDetailsText(event),
        event?.request_id,
      ][index] ?? "";
    },

    eventsRowText(event) {
      return [0, 1, 2, 3, 4].map((idx) => String(this.eventsCellText(event, idx))).join(" ").toLowerCase();
    },

    sortEvents(index) {
      if (this.eventsSortIndex === index) this.eventsSortDir = this.eventsSortDir === "asc" ? "desc" : "asc";
      else {
        this.eventsSortIndex = index;
        this.eventsSortDir = index === 0 ? "desc" : "asc";
      }
      this.applyEventsFilterSort();
    },

    eventsSortClass(index) {
      if (this.eventsSortIndex !== index) return "";
      return this.eventsSortDir === "asc" ? "sort-asc" : "sort-desc";
    },

    applyEventsFilterSort() {
      localStorage.setItem("cpkit_events_filter", this.eventsFilterQuery || "");
      const q = String(this.eventsFilterQuery || "").toLowerCase().trim();
      let rows = this.events.slice();
      if (q) rows = rows.filter((event) => this.eventsRowText(event).includes(q));
      rows.sort((a, b) => this.compareValues(this.eventsCellText(a, this.eventsSortIndex), this.eventsCellText(b, this.eventsSortIndex)));
      if (this.eventsSortDir === "desc") rows.reverse();
      this.eventsVisibleRows = rows;
    },

    eventsDetailsText(event) {
      return this.toYaml(event?.details ?? null);
    },

    onEventsFilterInput() {
      this.applyEventsFilterSort();
    },

    recentEvents(limit) {
      return this.events.slice(0, limit);
    },

    async refreshApiKeys() {
      this.apiKeysLoading.list = true;
      try {
        const data = await this.apiFetch("/admin/api_keys/", { method: "GET" });
        this.apiKeys = Array.isArray(data) ? data : [];
        this.apiKeysLastUpdatedUtc = this.utcNowString();
        this.applyApiKeysFilterSort();
      } catch (e) {
        this.viewNotice = this.errorMessage(e, "Failed to load API keys.");
      } finally {
        this.apiKeysLoading.list = false;
      }
    },

    applyApiKeysFilterSort() {
      localStorage.setItem("cpkit_api_keys_filter", this.apiKeysFilterQuery || "");
      const q = String(this.apiKeysFilterQuery || "").toLowerCase().trim();
      let rows = this.apiKeys.slice();
      if (q) rows = rows.filter((row) => this.apiKeysRowText(row).includes(q));
      rows.sort((a, b) => this.compareValues(this.apiKeysCellText(a, this.apiKeysSortIndex), this.apiKeysCellText(b, this.apiKeysSortIndex)));
      if (this.apiKeysSortDir === "desc") rows.reverse();
      this.apiKeysVisibleRows = rows;
    },

    apiKeysCellText(row, index) {
      return [
        row?.access_key,
        row?.owner,
        row?.valid_until,
        this.rolesText(row?.roles),
      ][index] ?? "";
    },

    apiKeysRowText(row) {
      return [0, 1, 2, 3].map((idx) => String(this.apiKeysCellText(row, idx))).join(" ").toLowerCase();
    },

    sortApiKeys(index) {
      if (this.apiKeysSortIndex === index) this.apiKeysSortDir = this.apiKeysSortDir === "asc" ? "desc" : "asc";
      else {
        this.apiKeysSortIndex = index;
        this.apiKeysSortDir = index === 2 ? "desc" : "asc";
      }
      this.applyApiKeysFilterSort();
    },

    apiKeysSortClass(index) {
      if (this.apiKeysSortIndex !== index) return "";
      return this.apiKeysSortDir === "asc" ? "sort-asc" : "sort-desc";
    },

    openApiKeyCreateModal() {
      this.modal.apiKeyCreate.open = true;
      this.modal.apiKeyCreate.valid_until = this.defaultApiKeyValidUntilLocal();
      this.modal.apiKeyCreate.rolesText = "CP_ADMIN";
      this.modal.apiKeyCreate.created = null;
      this.modalError.apiKeyCreate = "";
    },

    closeApiKeyCreateModal() {
      this.modal.apiKeyCreate.open = false;
    },

    async createApiKey() {
      this.apiKeysLoading.create = true;
      this.modalError.apiKeyCreate = "";
      try {
        const roles = this.modal.apiKeyCreate.rolesText.split(",").map((role) => role.trim()).filter(Boolean);
        const validUntil = new Date(this.modal.apiKeyCreate.valid_until).toISOString();
        const created = await this.apiFetch("/admin/api_keys/", {
          method: "POST",
          body: { valid_until: validUntil, roles },
        });
        this.modal.apiKeyCreate.created = created;
        await this.refreshApiKeys();
      } catch (e) {
        this.modalError.apiKeyCreate = this.errorMessage(e, "Failed to create API key.");
      } finally {
        this.apiKeysLoading.create = false;
      }
    },

    async deleteApiKey(accessKey) {
      if (!window.confirm(`Delete API key ${accessKey}?`)) return;
      this.apiKeysLoading.delete = true;
      try {
        await this.apiFetch(`/admin/api_keys/${encodeURIComponent(accessKey)}`, { method: "DELETE" });
        await this.refreshApiKeys();
      } catch (e) {
        this.viewNotice = this.errorMessage(e, "Failed to delete API key.");
      } finally {
        this.apiKeysLoading.delete = false;
      }
    },

    async refreshSettings() {
      this.settingsLoading.list = true;
      try {
        const data = await this.apiFetch("/admin/settings/", { method: "GET" });
        this.settings = Array.isArray(data) ? data : [];
        this.settingsDrafts = Object.fromEntries(
          this.settings.map((row) => [row.key, row.effective_value ?? row.default_value ?? ""]),
        );
        this.settingsLastUpdatedUtc = this.utcNowString();
        this.applySettingsFilterSort();
      } catch (e) {
        this.settingsToast = { ok: false, message: this.errorMessage(e, "Failed to load settings.") };
      } finally {
        this.settingsLoading.list = false;
      }
    },

    settingsCategories() {
      return [...new Set(this.settings.map((row) => String(row.category || "").trim()).filter(Boolean))].sort();
    },

    settingsCategoryCount(category) {
      if (category === "all") return this.settings.length;
      return this.settings.filter((row) => String(row.category || "").trim() === category).length;
    },

    setSettingsCategory(category) {
      this.settingsCategoryTab = category || "all";
      localStorage.setItem("cpkit_settings_category", this.settingsCategoryTab);
      this.applySettingsFilterSort();
    },

    settingDraftValue(row) {
      return this.settingsDrafts[row.key] ?? row.effective_value ?? row.default_value ?? "";
    },

    setSettingDraft(key, value) {
      this.settingsDrafts = { ...this.settingsDrafts, [key]: value };
    },

    isSettingDirty(row) {
      return String(this.settingDraftValue(row)) !== String(row.effective_value ?? row.default_value ?? "");
    },

    isSettingOverridden(row) {
      return String(row?.effective_value ?? "") !== String(row?.default_value ?? "");
    },

    settingValuePreview(row, value) {
      if (row?.is_secret) return "secret";
      return value === null || value === undefined || value === "" ? "-" : String(value);
    },

    applySettingsFilterSort() {
      localStorage.setItem("cpkit_settings_filter", this.settingsFilterQuery || "");
      const q = String(this.settingsFilterQuery || "").toLowerCase().trim();
      let rows = this.settings.slice();
      if (this.settingsCategoryTab !== "all") {
        rows = rows.filter((row) => String(row.category || "") === this.settingsCategoryTab);
      }
      if (q) rows = rows.filter((row) => this.settingsRowText(row).includes(q));
      rows.sort((a, b) => this.compareValues(this.settingsCellText(a, this.settingsSortIndex), this.settingsCellText(b, this.settingsSortIndex)));
      if (this.settingsSortDir === "desc") rows.reverse();
      this.settingsVisibleRows = rows;
    },

    settingsCellText(row, index) {
      return [
        row?.key,
        row?.value_type,
        this.settingDraftValue(row),
        row?.default_value,
        row?.updated_at,
      ][index] ?? "";
    },

    settingsRowText(row) {
      return [
        row?.key,
        row?.category,
        row?.value_type,
        this.settingDraftValue(row),
        row?.default_value,
        row?.description,
        row?.updated_at,
      ].map((value) => String(value ?? "")).join(" ").toLowerCase();
    },

    sortSettings(index) {
      if (this.settingsSortIndex === index) this.settingsSortDir = this.settingsSortDir === "asc" ? "desc" : "asc";
      else {
        this.settingsSortIndex = index;
        this.settingsSortDir = index === 4 ? "desc" : "asc";
      }
      this.applySettingsFilterSort();
    },

    settingsSortClass(index) {
      if (this.settingsSortIndex !== index) return "";
      return this.settingsSortDir === "asc" ? "sort-asc" : "sort-desc";
    },

    async saveSetting(key) {
      this.settingsLoading.update = true;
      try {
        await this.apiFetch(`/admin/settings/${encodeURIComponent(key)}`, {
          method: "PATCH",
          body: { value: this.settingsDrafts[key] ?? "" },
        });
        this.showSettingsToast(`Saved ${key}.`, true);
        await this.refreshSettings();
      } catch (e) {
        this.showSettingsToast(this.errorMessage(e, "Failed to save setting."), false);
      } finally {
        this.settingsLoading.update = false;
      }
    },

    async resetSetting(key) {
      this.settingsLoading.reset = true;
      try {
        await this.apiFetch(`/admin/settings/${encodeURIComponent(key)}/reset`, { method: "PUT" });
        this.showSettingsToast(`Reset ${key}.`, true);
        await this.refreshSettings();
      } catch (e) {
        this.showSettingsToast(this.errorMessage(e, "Failed to reset setting."), false);
      } finally {
        this.settingsLoading.reset = false;
      }
    },

    showSettingsToast(message, ok) {
      if (this._settingsToastTimer) clearTimeout(this._settingsToastTimer);
      this.settingsToast = { message, ok };
      this._settingsToastTimer = setTimeout(() => {
        this.settingsToast = { message: "", ok: true };
      }, 4000);
    },

    ensureAce() {
      if (this._aceReady) return;
      if (!window.ace || !this.$refs.aceContainer) {
        this.pbToast = { ok: false, message: "Editor is not available." };
        return;
      }
      this._ace = window.ace.edit(this.$refs.aceContainer);
      this._ace.setTheme("ace/theme/cobalt");
      this._ace.session.setMode("ace/mode/yaml");
      this._ace.setOptions({ showPrintMargin: false, useSoftTabs: true, tabSize: 2, wrap: true });
      this._aceReady = true;
      this.pbToast = { ok: true, message: "Editor ready." };
    },

    applyPlaybookPayload(payload) {
      const content = payload?.modified_content ?? payload?.original_content ?? "";
      this.pbVersions = Array.isArray(payload?.available_versions) ? payload.available_versions.map(String) : [];
      this.pbDefaultVersion = payload?.default_version ? String(payload.default_version) : "";
      this.pbSelectedVersion = payload?.playbook_version ? String(payload.playbook_version) : this.pbDefaultVersion;
      if (this._ace) this._ace.setValue(String(content ?? ""), -1);
      this.pbLastUpdatedUtc = this.utcNowString();
    },

    async loadPlaybookSelection(name) {
      const playbookName = String(name || "").trim();
      if (!playbookName) {
        this.pbToast = { ok: false, message: "Enter a playbook name." };
        return;
      }
      this.ensureAce();
      this.pbLoading.load = true;
      try {
        const payload = await this.apiFetch(`/admin/playbooks/${encodeURIComponent(playbookName)}`, { method: "GET" });
        this.selectedPlaybook = playbookName;
        this.applyPlaybookPayload(payload);
        this.pbToast = { ok: true, message: `Loaded ${playbookName}.` };
      } catch (e) {
        this.pbToast = { ok: false, message: this.errorMessage(e, "Failed to load playbook.") };
      } finally {
        this.pbLoading.load = false;
      }
    },

    async onSelectPlaybookVersion() {
      const name = String(this.selectedPlaybook || "").trim();
      const version = String(this.pbSelectedVersion || "").trim();
      if (!name || !version) return;
      this.pbLoading.load = true;
      try {
        const payload = await this.apiFetch(
          `/admin/playbooks/${encodeURIComponent(name)}/${encodeURIComponent(version)}`,
          { method: "GET" },
        );
        this.applyPlaybookPayload(payload);
      } catch (e) {
        this.pbToast = { ok: false, message: this.errorMessage(e, "Failed to load version.") };
      } finally {
        this.pbLoading.load = false;
      }
    },

    async savePlaybook() {
      const name = String(this.selectedPlaybook || "").trim();
      if (!name) {
        this.pbToast = { ok: false, message: "Enter a playbook name." };
        return;
      }
      this.ensureAce();
      this.pbLoading.save = true;
      try {
        const payload = await this.apiFetch(`/admin/playbooks/${encodeURIComponent(name)}`, {
          method: "POST",
          body: { content: this._ace.getValue() },
        });
        this.applyPlaybookPayload(payload);
        this.pbToast = { ok: true, message: `Saved ${name}.` };
      } catch (e) {
        this.pbToast = { ok: false, message: this.errorMessage(e, "Failed to save playbook.") };
      } finally {
        this.pbLoading.save = false;
      }
    },

    async setDefaultPlaybookVersion() {
      const name = String(this.selectedPlaybook || "").trim();
      const version = String(this.pbSelectedVersion || "").trim();
      if (!name || !version) return;
      this.pbLoading.setDefault = true;
      try {
        await this.apiFetch(`/admin/playbooks/${encodeURIComponent(name)}/${encodeURIComponent(version)}`, {
          method: "PUT",
        });
        this.pbDefaultVersion = version;
        this.pbToast = { ok: true, message: `Set ${version} as default.` };
      } catch (e) {
        this.pbToast = { ok: false, message: this.errorMessage(e, "Failed to set default version.") };
      } finally {
        this.pbLoading.setDefault = false;
      }
    },

    async deletePlaybookVersion() {
      const name = String(this.selectedPlaybook || "").trim();
      const version = String(this.pbSelectedVersion || "").trim();
      if (!name || !version) return;
      if (!window.confirm(`Delete ${name} version ${version}?`)) return;
      this.pbLoading.delete = true;
      try {
        const payload = await this.apiFetch(`/admin/playbooks/${encodeURIComponent(name)}/${encodeURIComponent(version)}`, {
          method: "DELETE",
        });
        this.applyPlaybookPayload(payload);
        this.pbToast = { ok: true, message: `Deleted ${version}.` };
      } catch (e) {
        this.pbToast = { ok: false, message: this.errorMessage(e, "Failed to delete version.") };
      } finally {
        this.pbLoading.delete = false;
      }
    },

    async apiFetch(path, options = {}) {
      const headers = { Accept: "application/json", ...(options.headers || {}) };
      const fetchOptions = { method: options.method || "GET", headers };
      if (options.body !== undefined) {
        headers["Content-Type"] = "application/json";
        fetchOptions.body = JSON.stringify(options.body);
      }
      const res = await fetch(`${this.apiBase}${path}`, fetchOptions);
      const data = await this.safeJson(res);
      if (res.status === 401) {
        this.setAuthRequired(res.headers.get("x-auth-login-url"), data?.detail || "Not authenticated.");
        throw new Error("Not authenticated.");
      }
      if (!res.ok) throw new Error(data?.detail || data?.message || `HTTP ${res.status}`);
      return data;
    },

    async safeJson(res) {
      const text = await res.text();
      if (!text) return null;
      try {
        return JSON.parse(text);
      } catch {
        return text;
      }
    },

    errorMessage(error, fallback) {
      return error && error.message ? error.message : fallback;
    },

    compareValues(a, b) {
      const av = this.parseSortValue(a);
      const bv = this.parseSortValue(b);
      if (av < bv) return -1;
      if (av > bv) return 1;
      return 0;
    },

    parseSortValue(value) {
      if (value === null || value === undefined) return "";
      const date = Date.parse(value);
      if (!Number.isNaN(date) && String(value).match(/\d{4}-\d{2}-\d{2}/)) return date;
      const num = Number(value);
      if (!Number.isNaN(num) && String(value).trim() !== "") return num;
      return String(value).toLowerCase();
    },

    toUtcStringMaybe(value) {
      if (!value) return "-";
      const date = new Date(value);
      if (Number.isNaN(date.getTime())) return String(value);
      return date.toISOString().replace(".000Z", "Z");
    },

    utcNowString() {
      return new Date().toISOString().replace(".000Z", "Z");
    },

    relativeTimeFromNow(value) {
      if (!value) return "-";
      const diff = Date.now() - new Date(value).getTime();
      if (Number.isNaN(diff)) return "-";
      const mins = Math.floor(diff / 60000);
      if (mins < 1) return "now";
      if (mins < 60) return `${mins}m`;
      const hours = Math.floor(mins / 60);
      if (hours < 24) return `${hours}h`;
      return `${Math.floor(hours / 24)}d`;
    },

    detailsText(details) {
      if (details === null || details === undefined) return "-";
      if (typeof details === "string") return details;
      return JSON.stringify(details);
    },

    formatJson(value) {
      return JSON.stringify(value ?? {}, null, 2);
    },

    toYaml(value) {
      const isObj = (v) => v && typeof v === "object" && !Array.isArray(v);
      const needsQuotes = (s) =>
        s === "" ||
        /[:\-?[\]{},#&*!|>'"%@`]/.test(s) ||
        /^\s|\s$/.test(s) ||
        /^(true|false|null|~|-?\d+(\.\d+)?)$/i.test(s);
      const quote = (s) => `"${String(s).replace(/\\/g, "\\\\").replace(/"/g, '\\"')}"`;
      const scalar = (v) => {
        if (v === null || v === undefined) return "null";
        if (v === true) return "true";
        if (v === false) return "false";
        if (typeof v === "number") return Number.isFinite(v) ? String(v) : quote(String(v));
        if (typeof v === "string") return needsQuotes(v) ? quote(v) : v;
        return quote(String(v));
      };
      const indent = (n) => "  ".repeat(n);
      const render = (v, depth) => {
        if (Array.isArray(v)) {
          if (v.length === 0) return "[]";
          return v
            .map((item) => {
              if (isObj(item) || Array.isArray(item)) {
                return `${indent(depth)}- ${render(item, depth + 1).trimStart()}`;
              }
              return `${indent(depth)}- ${scalar(item)}`;
            })
            .join("\n");
        }
        if (isObj(v)) {
          const keys = Object.keys(v);
          if (keys.length === 0) return "{}";
          return keys
            .map((key) => {
              const val = v[key];
              const keyStr = needsQuotes(key) ? quote(key) : key;
              if (isObj(val) || Array.isArray(val)) {
                return `${indent(depth)}${keyStr}:\n${render(val, depth + 1)}`;
              }
              return `${indent(depth)}${keyStr}: ${scalar(val)}`;
            })
            .join("\n");
        }
        return scalar(v);
      };
      return render(value, 0);
    },

    statusClass(status) {
      const s = String(status || "").toLowerCase();
      if (["failed", "error", "cancelled"].includes(s)) return "danger";
      if (["running", "queued", "pending"].includes(s)) return "pending";
      if (["completed", "succeeded", "success"].includes(s)) return "success";
      return "neutral";
    },

    rolesText(roles) {
      return Array.isArray(roles) ? roles.join(", ") : String(roles || "-");
    },

    defaultApiKeyValidUntilLocal() {
      const date = new Date(Date.now() + 90 * 24 * 60 * 60 * 1000);
      date.setSeconds(0, 0);
      return date.toISOString().slice(0, 16);
    },

    openUserInfoModal() {
      this.modal.userInfo.open = true;
    },

    closeUserInfoModal() {
      this.modal.userInfo.open = false;
    },

    authClaimsWithoutCookies() {
      const claims = { ...(this.authClaims || {}) };
      delete claims.cookie;
      return claims;
    },

    authGroupsClaimName() {
      return this.authClaims?._groups_claim_name || this.authClaims?._cp?.groups_claim_name || "groups";
    },

    authGroups() {
      return this.normalizeClaimValues(this.authClaims?.[this.authGroupsClaimName()]);
    },

    authRoleGroups() {
      return this.authClaims?._role_groups || {};
    },

    authRoles() {
      if (this.authIsUnauthenticatedMode()) return ["CP_ADMIN"];
      const userGroups = new Set(this.authGroups());
      return Object.entries(this.authRoleGroups())
        .filter(([, groups]) => this.normalizeClaimValues(groups).some((group) => userGroups.has(group)))
        .map(([role]) => role);
    },

    hasRole(role) {
      if (this.authIsUnauthenticatedMode()) return true;
      return this.authRoles().includes(role);
    },

    canViewAdmin() {
      return this.hasRole("CP_ADMIN");
    },

    authIsUnauthenticatedMode() {
      return Boolean(this.authClaims && this.authClaims.auth_disabled);
    },

    normalizeClaimValues(value) {
      if (Array.isArray(value)) return value.map(String).filter(Boolean);
      if (typeof value === "string") return value.split(",").map((item) => item.trim()).filter(Boolean);
      return [];
    },

    userDisplayName() {
      if (this.authIsUnauthenticatedMode()) return "Unauthenticated";
      const claim = this.authDisplayNameClaim || "preferred_username";
      return this.authClaims?.[claim] || this.authClaims?.email || this.authClaims?.sub || "User";
    },

    userIconTitle() {
      return this.authIsUnauthenticatedMode() ? "Running in unauthenticated mode" : "Open user details";
    },
  };
};
