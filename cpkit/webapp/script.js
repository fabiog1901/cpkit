window.app = function () {
  const extension = window.cpkitWebappExtension || {};
  return {
    view: "dashboard",
    apiBase: "/api",
    extensionNavItems: Array.isArray(extension.navItems) ? extension.navItems : [],
    extensionAdminItems: Array.isArray(extension.adminItems) ? extension.adminItems : [],
    extensionDashboardItems: Array.isArray(extension.dashboardItems) ? extension.dashboardItems : [],
    extensionDashboardTemplateLoaded: false,
    extensionDashboardTemplateCards: [],
    dashboardCardOrder: [],
    dashboardDragKey: "",
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

    playbooks: [],
    selectedPlaybook: "",
    pbLoading: { list: false, load: false, save: false, setDefault: false, delete: false },
    pbToast: { message: "", ok: true },
    pbLastUpdatedUtc: null,
    pbDefaultVersion: "",
    pbSelectedVersion: "",
    pbVersions: [],
    pbEditorText: "",
    _ace: null,
    _aceReady: false,
    _pbToastTimer: null,

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
      this.applyExtensionDashboardTemplate();
      this.restoreLocalState();
      await this.checkAuth();
      if (!this.isAuthenticated) return;
      await this.applyRouteFromHash();
      window.addEventListener("hashchange", () => {
        Promise.resolve(this.applyRouteFromHash()).catch((e) => {
          this.viewNotice = this.errorMessage(e, "Failed to apply route.");
        });
      });
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
      });
      this.setManagedInterval("_settingsAutoTimer", () => {
        if (this.settingsAutoRefreshEnabled && this.view === "settings") this.refreshSettings();
      });
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

    applyExtensionDashboardTemplate() {
      const template = document.getElementById("cpkit-extension-dashboard");
      const sourceCards = this.extensionDashboardTemplateSourceCards(template);
      const seenKeys = new Map();
      this.extensionDashboardTemplateCards = sourceCards.map((element, index) => {
        const baseKey = element.dataset.dashboardKey || element.id || `template-${index}`;
        const seenCount = seenKeys.get(baseKey) || 0;
        seenKeys.set(baseKey, seenCount + 1);
        const key = seenCount > 0 ? `${baseKey}-${seenCount + 1}` : baseKey;
        return {
          key: `app:template:${key}`,
          kind: "template",
          domId: `cpkit-dashboard-extension-slot-${this.domIdPart(key, index)}`,
          templateKey: key,
          templateIndex: index,
        };
      });
      this.extensionDashboardTemplateLoaded = this.extensionDashboardTemplateCards.length > 0;
      if (!template) return;
      this.renderExtensionDashboardTemplateCards();
      setTimeout(() => this.renderExtensionDashboardTemplateCards(), 0);
    },

    extensionDashboardTemplateSourceCards(template) {
      if (!template) return [];
      const children = Array.from(template.content.children);
      if (children.length === 1 && children[0].matches(".dashboard-grid, .dashboard-card-grid")) {
        return Array.from(children[0].children);
      }
      return children;
    },

    domIdPart(value, index) {
      const text = String(value || `template-${index}`).toLowerCase();
      return text.replace(/[^a-z0-9_-]+/g, "-").replace(/^-+|-+$/g, "") || `template-${index}`;
    },

    renderExtensionDashboardTemplateCards() {
      const template = document.getElementById("cpkit-extension-dashboard");
      const sourceCards = this.extensionDashboardTemplateSourceCards(template);
      if (!sourceCards.length) return;
      for (const card of this.extensionDashboardTemplateCards) {
        const slot = document.getElementById(card.domId);
        const source = sourceCards[card.templateIndex];
        if (!slot || !source) continue;
        slot.innerHTML = "";
        slot.appendChild(source.cloneNode(true));
        if (window.Alpine && typeof window.Alpine.initTree === "function") {
          window.Alpine.initTree(slot);
        }
      }
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
      this.dashboardCardOrder = this.loadDashboardCardOrder();
    },

    setManagedInterval(key, fn, ms = 5000) {
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
      } catch (e) {
        console.error(e);
      } finally {
        this.setAuthRequired(this.authLoginPath, "");
        this.authChecked = true;
        window.location.assign("/");
      }
    },

    async applyRouteFromHash() {
      const route = this.parseHashRoute();
      const parts = route.parts;
      let next = "dashboard";
      if (parts[0] === "jobs" && parts[1]) {
        next = "job";
        this.selectedJobId = parts[1];
      } else if (parts[0] === "jobs") {
        next = "jobs";
        this.jobsFilterQuery = String(route.query.filter || "");
      }
      else if (parts[0] === "events") next = "events";
      else if (parts[0] === "admin" && parts[1] === "api-keys") next = "api_keys";
      else if (parts[0] === "admin" && parts[1] === "settings") next = "settings";
      else if (parts[0] === "admin" && parts[1] === "playbooks") next = "playbooks";
      else {
        const matched = this.extensionRouteForPath(route.path);
        if (matched) next = matched[0];
        else if (parts[0] === "admin") next = "admin";
      }
      if (!this.canAccessView(next)) {
        this.handleForbiddenView(next);
        return;
      }
      this.view = next;
      await this.ensureViewData();
    },

    parseHashRoute() {
      const rawHash = String(window.location.hash || "").trim();
      const fragment = rawHash.startsWith("#") ? rawHash.slice(1) : rawHash;
      const normalized = fragment.startsWith("/") ? fragment : `/${fragment}`;
      const [pathPart, queryString = ""] = normalized.split("?");
      const path = pathPart || "/";
      const parts = path
        .split("/")
        .filter(Boolean)
        .map((segment) => {
          try {
            return decodeURIComponent(segment);
          } catch {
            return segment;
          }
        });
      const query = {};
      const params = new URLSearchParams(queryString);
      params.forEach((value, key) => {
        query[key] = value;
      });
      return { path, parts, query };
    },

    routeForView(view) {
      const routes = {
        dashboard: "/",
        jobs: this.jobsRoute(),
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

    jobsRoute() {
      const filter = String(this.jobsFilterQuery || "").trim();
      if (!filter) return "/jobs";
      return `/jobs?filter=${encodeURIComponent(filter)}`;
    },

    async setView(next) {
      if (next === this.view) {
        await this.ensureViewData();
        return;
      }
      if (!this.canAccessView(next)) {
        this.handleForbiddenView(next);
        return;
      }
      this.view = next;
      window.location.hash = this.routeForView(next);
      await this.ensureViewData();
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
      else if (this.view === "playbooks") await this.ensurePlaybooksView();
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
      return Object.entries(extension.routes || {}).find(([, route]) => {
        if (typeof route.match === "function" && route.match(path)) return true;
        if (route.path === path) return true;
        return false;
      });
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

    normalizedExtensionDashboardItems() {
      return this.extensionDashboardItems
        .filter((item) => item && (item.label || item.valueKey || item.countKey || item.value !== undefined))
        .map((item, index) => ({
          ...item,
          key: item.key || item.id || item.view || `item-${index}`,
          label: item.label || item.valueKey || item.countKey || "Metric",
          kicker: item.kicker || "Application",
          description: item.description || "",
          valueKey: item.valueKey || "",
          countKey: item.countKey || "",
          view: item.view || "",
        }));
    },

    hasExtensionDashboardContent() {
      return this.normalizedExtensionDashboardItems().length > 0 || this.extensionDashboardTemplateLoaded;
    },

    dashboardItemValue(item) {
      if (item?.value !== undefined) return item.value;
      const key = item?.valueKey || item?.countKey || "";
      if (!key) return "";
      const value = this[key];
      if (Array.isArray(value)) return value.length;
      if (value && typeof value === "object") return Object.keys(value).length;
      if (value === null || value === undefined) return "";
      return value;
    },

    openDashboardItem(item) {
      if (item?.view) this.setView(item.view);
    },

    dashboardCards() {
      const extensionCards = this.normalizedExtensionDashboardItems().map((item) => ({
        key: `app:${item.key}`,
        kind: "extension",
        item,
      }));
      const builtinCards = [
        { key: "builtin:jobs", kind: "jobs" },
        { key: "builtin:events", kind: "events" },
      ];
      const appCards = [...this.extensionDashboardTemplateCards, ...extensionCards];
      const cardsByKey = new Map([...appCards, ...builtinCards].map((card) => [card.key, card]));
      const ordered = this.dashboardCardOrder
        .map((key) => cardsByKey.get(key))
        .filter(Boolean);
      const orderedKeys = new Set(ordered.map((card) => card.key));
      const firstBuiltinIndex = ordered.findIndex((card) => card.key.startsWith("builtin:"));
      const missingAppCards = appCards.filter((card) => !orderedKeys.has(card.key));
      const missingBuiltinCards = builtinCards.filter((card) => !orderedKeys.has(card.key));
      if (firstBuiltinIndex >= 0) {
        return [
          ...ordered.slice(0, firstBuiltinIndex),
          ...missingAppCards,
          ...ordered.slice(firstBuiltinIndex),
          ...missingBuiltinCards,
        ];
      }
      return [
        ...ordered,
        ...missingAppCards,
        ...missingBuiltinCards,
      ];
    },

    loadDashboardCardOrder() {
      try {
        const parsed = JSON.parse(localStorage.getItem("cpkit_dashboard_card_order") || "[]");
        return Array.isArray(parsed) ? parsed.map(String) : [];
      } catch {
        return [];
      }
    },

    persistDashboardCardOrder() {
      localStorage.setItem("cpkit_dashboard_card_order", JSON.stringify(this.dashboardCardOrder));
    },

    dashboardCardDragStart(event, key) {
      this.dashboardDragKey = key;
      if (event?.dataTransfer) {
        event.dataTransfer.effectAllowed = "move";
        event.dataTransfer.setData("text/plain", key);
      }
    },

    dashboardCardDragEnd() {
      this.dashboardDragKey = "";
    },

    dashboardCardDrop(event, targetKey) {
      const sourceKey = event?.dataTransfer?.getData("text/plain") || this.dashboardDragKey;
      if (!sourceKey || sourceKey === targetKey) return;
      const keys = this.dashboardCards().map((card) => card.key);
      const from = keys.indexOf(sourceKey);
      const to = keys.indexOf(targetKey);
      if (from < 0 || to < 0) return;
      const [movedKey] = keys.splice(from, 1);
      keys.splice(keys.indexOf(targetKey), 0, movedKey);
      this.dashboardCardOrder = keys;
      this.persistDashboardCardOrder();
      this.dashboardDragKey = "";
      setTimeout(() => this.renderExtensionDashboardTemplateCards(), 0);
    },

    async refreshDashboardOverview({ onlyIfEmpty = false } = {}) {
      if (!onlyIfEmpty || this.jobs.length === 0) await this.refreshJobs();
      else if (this.jobStats.total === 0) await this.refreshJobStats();
      if (!onlyIfEmpty || this.events.length === 0) await this.refreshEvents({ limit: 10 });
      const dashboardEnsure = extension.dashboardEnsure;
      if (dashboardEnsure && typeof this[dashboardEnsure] === "function") {
        await this[dashboardEnsure]({ onlyIfEmpty });
      }
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
      this.selectedJobDetails = null;
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
        job?.playbook_version,
        job?.created_by,
        job?.created_at,
        job?.updated_at,
      ][index] ?? "";
    },

    jobsRowText(job) {
      return this.tableRowText(job, [0, 1, 2, 3, 4, 5, 6], this.jobsCellText, [this.jobsDescriptionText(job)]);
    },

    sortJobs(index) {
      this.toggleTableSort(index, {
        sortIndexKey: "jobsSortIndex",
        sortDirKey: "jobsSortDir",
        defaultDirForIndex: (idx) => (idx === 0 || idx >= 5 ? "desc" : "asc"),
        apply: () => this.applyJobsFilterSort(),
      });
    },

    jobsSortClass(index) {
      return this.tableSortClass(index, "jobsSortIndex", "jobsSortDir");
    },

    applyJobsFilterSort() {
      this.applyTableFilterSort({
        sourceKey: "jobs",
        visibleKey: "jobsVisibleRows",
        filterKey: "jobsFilterQuery",
        storageKey: "cpkit_jobs_filter",
        sortIndexKey: "jobsSortIndex",
        sortDirKey: "jobsSortDir",
        cellText: this.jobsCellText,
        rowText: this.jobsRowText,
      });
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
      if (this.view === "jobs" && typeof window !== "undefined") {
        window.location.hash = this.jobsRoute();
      }
    },

    recentJobs(limit) {
      return this.jobs
        .slice()
        .sort((a, b) => this.compareValues(b?.updated_at || b?.created_at, a?.updated_at || a?.created_at))
        .slice(0, limit);
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
      return this.tableRowText(event, [0, 1, 2, 3, 4], this.eventsCellText);
    },

    sortEvents(index) {
      this.toggleTableSort(index, {
        sortIndexKey: "eventsSortIndex",
        sortDirKey: "eventsSortDir",
        defaultDirForIndex: (idx) => (idx === 0 ? "desc" : "asc"),
        apply: () => this.applyEventsFilterSort(),
      });
    },

    eventsSortClass(index) {
      return this.tableSortClass(index, "eventsSortIndex", "eventsSortDir");
    },

    applyEventsFilterSort() {
      this.applyTableFilterSort({
        sourceKey: "events",
        visibleKey: "eventsVisibleRows",
        filterKey: "eventsFilterQuery",
        storageKey: "cpkit_events_filter",
        sortIndexKey: "eventsSortIndex",
        sortDirKey: "eventsSortDir",
        cellText: this.eventsCellText,
        rowText: this.eventsRowText,
      });
    },

    eventsDetailsText(event) {
      return this.toYaml(event?.details ?? null);
    },

    actionPillStyle(action) {
      const name = String(action || "").trim().toUpperCase();
      const palette = [
        { background: "rgba(30, 64, 175, 0.92)", borderColor: "rgba(147, 197, 253, 0.55)", color: "#eff6ff" },
        { background: "rgba(154, 52, 18, 0.92)", borderColor: "rgba(253, 186, 116, 0.55)", color: "#fff7ed" },
        { background: "rgba(6, 95, 70, 0.92)", borderColor: "rgba(110, 231, 183, 0.5)", color: "#ecfdf5" },
        { background: "rgba(91, 33, 182, 0.92)", borderColor: "rgba(196, 181, 253, 0.5)", color: "#f5f3ff" },
        { background: "rgba(190, 24, 93, 0.92)", borderColor: "rgba(251, 182, 206, 0.5)", color: "#fff1f2" },
        { background: "rgba(15, 23, 42, 0.96)", borderColor: "rgba(148, 163, 184, 0.45)", color: "#e5e7eb" },
        { background: "rgba(20, 83, 45, 0.92)", borderColor: "rgba(134, 239, 172, 0.45)", color: "#f0fdf4" },
        { background: "rgba(127, 29, 29, 0.92)", borderColor: "rgba(252, 165, 165, 0.45)", color: "#fef2f2" },
      ];
      const preferred = [
        { match: ["LOGIN", "_LOGIN"], style: palette[0] },
        { match: ["LOGOUT", "_LOGOUT"], style: palette[5] },
        { match: ["ALLOCATE", "ALLOCATION"], style: palette[1] },
        { match: ["DEALLOCATE", "DEALLOCATION"], style: palette[3] },
        { match: ["INIT", "CREATE"], style: palette[2] },
        { match: ["DECOMM", "DELETE", "REMOVE"], style: palette[7] },
        { match: ["UPDATE", "PATCH"], style: palette[4] },
      ];
      for (const entry of preferred) {
        if (entry.match.some((token) => name.includes(token))) return entry.style;
      }
      let hash = 0;
      for (let i = 0; i < name.length; i += 1) {
        hash = (hash * 31 + name.charCodeAt(i)) >>> 0;
      }
      return palette[hash % palette.length];
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
      this.applyTableFilterSort({
        sourceKey: "apiKeys",
        visibleKey: "apiKeysVisibleRows",
        filterKey: "apiKeysFilterQuery",
        storageKey: "cpkit_api_keys_filter",
        sortIndexKey: "apiKeysSortIndex",
        sortDirKey: "apiKeysSortDir",
        cellText: this.apiKeysCellText,
        rowText: this.apiKeysRowText,
      });
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
      return this.tableRowText(row, [0, 1, 2, 3], this.apiKeysCellText);
    },

    sortApiKeys(index) {
      this.toggleTableSort(index, {
        sortIndexKey: "apiKeysSortIndex",
        sortDirKey: "apiKeysSortDir",
        defaultDirForIndex: (idx) => (idx === 2 ? "desc" : "asc"),
        apply: () => this.applyApiKeysFilterSort(),
      });
    },

    apiKeysSortClass(index) {
      return this.tableSortClass(index, "apiKeysSortIndex", "apiKeysSortDir");
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
          this.settings.map((row) => [row.key, this.settingCurrentValue(row)]),
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

    settingCurrentValue(row) {
      return row?.value ?? row?.default_value ?? "";
    },

    settingDraftValue(row) {
      return this.settingsDrafts[row.key] ?? this.settingCurrentValue(row);
    },

    setSettingDraft(key, value) {
      this.settingsDrafts = { ...this.settingsDrafts, [key]: value };
    },

    isSettingDirty(row) {
      return String(this.settingDraftValue(row)) !== String(this.settingCurrentValue(row));
    },

    isSettingOverridden(row) {
      return String(this.settingCurrentValue(row)) !== String(row?.default_value ?? "");
    },

    settingValuePreview(row, value) {
      if (row?.is_secret) return "secret";
      return value === null || value === undefined || value === "" ? "-" : String(value);
    },

    applySettingsFilterSort() {
      this.applyTableFilterSort({
        sourceKey: "settings",
        visibleKey: "settingsVisibleRows",
        filterKey: "settingsFilterQuery",
        storageKey: "cpkit_settings_filter",
        sortIndexKey: "settingsSortIndex",
        sortDirKey: "settingsSortDir",
        cellText: this.settingsCellText,
        rowText: this.settingsRowText,
        prefilter: (row) => this.settingsCategoryTab === "all" || String(row.category || "") === this.settingsCategoryTab,
      });
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
      this.toggleTableSort(index, {
        sortIndexKey: "settingsSortIndex",
        sortDirKey: "settingsSortDir",
        defaultDirForIndex: (idx) => (idx === 4 ? "desc" : "asc"),
        apply: () => this.applySettingsFilterSort(),
      });
    },

    settingsSortClass(index) {
      return this.tableSortClass(index, "settingsSortIndex", "settingsSortDir");
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

    clearPlaybookToast() {
      this.pbToast = { message: "", ok: true };
      this._pbToastTimer = null;
    },

    showPlaybookToast(message, ok, { autoDismiss = ok } = {}) {
      if (this._pbToastTimer) window.clearTimeout(this._pbToastTimer);
      const toastMessage = String(message || "");
      this.pbToast = { message: toastMessage, ok };
      if (!autoDismiss) return;
      this._pbToastTimer = window.setTimeout(() => {
        if (this.pbToast.message === toastMessage) this.clearPlaybookToast();
      }, 4000);
    },

    isAceAvailable() {
      return Boolean(typeof window !== "undefined" && window.ace);
    },

    createAceEditor(elementOrRef, {
      mode = "text",
      theme = "cobalt",
      value = "",
      readOnly = false,
      wrap = true,
      minLines = null,
      maxLines = null,
      onChange = null,
    } = {}) {
      const element = typeof elementOrRef === "string" ? this.$refs[elementOrRef] : elementOrRef;
      if (!this.isAceAvailable() || !element) return null;

      const editor = window.ace.edit(element);
      editor.setTheme(String(theme).startsWith("ace/theme/") ? theme : `ace/theme/${theme}`);
      editor.session.setMode(String(mode).startsWith("ace/mode/") ? mode : `ace/mode/${mode}`);
      editor.session.setUseWorker(false);
      editor.setReadOnly(Boolean(readOnly));
      editor.setOptions({
        showPrintMargin: false,
        useSoftTabs: true,
        tabSize: 2,
        wrap: Boolean(wrap),
        ...(minLines !== null ? { minLines } : {}),
        ...(maxLines !== null ? { maxLines } : {}),
      });
      this.setAceValue(editor, value);
      if (typeof onChange === "function") {
        editor.session.on("change", () => onChange(editor.getValue(), editor));
      }
      if (typeof editor.resize === "function") editor.resize();
      return editor;
    },

    setAceValue(editor, value) {
      if (!editor || typeof editor.setValue !== "function") return;
      const next = String(value ?? "");
      if (typeof editor.getValue === "function" && editor.getValue() === next) return;
      editor.setValue(next, -1);
      if (typeof editor.resize === "function") editor.resize();
    },

    destroyAceEditor(editor) {
      if (!editor) return;
      if (typeof editor.destroy === "function") editor.destroy();
      if (editor.container && typeof editor.container.removeAttribute === "function") {
        editor.container.removeAttribute("ace_editor");
      }
    },

    ensureAce() {
      if (this._aceReady) return;
      this._ace = this.createAceEditor(this.$refs.aceContainer, {
        mode: "yaml",
        theme: "cobalt",
        value: this.pbEditorText,
        wrap: true,
        onChange: (value) => {
          this.pbEditorText = value;
        },
      });
      if (!this._ace) {
        this.showPlaybookToast("Ace editor is not available; using plain text editor.", false);
        return;
      }
      this._aceReady = true;
      const resize = () => {
        if (this._ace && typeof this._ace.resize === "function") this._ace.resize();
      };
      if (typeof this.$nextTick === "function") this.$nextTick(resize);
      else resize();
    },

    async ensurePlaybooksView() {
      this.ensureAce();
      if (!this.pbLoading.list) await this.reloadPlaybooks();
    },

    async reloadPlaybooks() {
      this.pbLoading.list = true;
      try {
        const payload = await this.apiFetch("/admin/playbooks/", { method: "GET" });
        this.playbooks = Array.isArray(payload?.playbooks) ? payload.playbooks.map(String) : [];
        if (!this.selectedPlaybook && this.playbooks.length > 0) {
          this.selectedPlaybook = this.playbooks[0];
          await this.loadPlaybookSelection(this.selectedPlaybook);
        } else if (this.selectedPlaybook && !this.playbooks.includes(this.selectedPlaybook)) {
          this.selectedPlaybook = "";
          this.pbVersions = [];
          this.pbDefaultVersion = "";
          this.pbSelectedVersion = "";
          this.pbEditorText = "";
          this.setAceValue(this._ace, "");
        }
      } catch (e) {
        this.showPlaybookToast(this.errorMessage(e, "Failed to list playbooks."), false);
      } finally {
        this.pbLoading.list = false;
      }
    },

    applyPlaybookPayload(payload, { preserveVersions = true } = {}) {
      const content = payload?.modified_content ?? payload?.original_content ?? "";
      const selectedVersion = payload?.playbook_version ? String(payload.playbook_version) : this.pbDefaultVersion;
      const versions = Array.isArray(payload?.available_versions)
        ? payload.available_versions.map(String)
        : preserveVersions
          ? this.pbVersions.slice()
          : [];
      if (selectedVersion && !versions.includes(selectedVersion)) versions.push(selectedVersion);
      this.pbVersions = versions;
      if (payload?.default_version !== null && payload?.default_version !== undefined) {
        this.pbDefaultVersion = String(payload.default_version);
      }
      this.pbSelectedVersion = selectedVersion || this.pbDefaultVersion;
      this.pbEditorText = String(content ?? "");
      this.setAceValue(this._ace, this.pbEditorText);
      this.pbLastUpdatedUtc = this.utcNowString();
    },

    async onSelectPlaybookName() {
      await this.loadPlaybookSelection(this.selectedPlaybook);
    },

    async loadPlaybookSelection(name) {
      const playbookName = String(name || "").trim();
      if (!playbookName) {
        this.showPlaybookToast("Enter a playbook name.", false);
        return;
      }
      this.ensureAce();
      this.pbLoading.load = true;
      this.pbVersions = [];
      this.pbDefaultVersion = "";
      this.pbSelectedVersion = "";
      try {
        const payload = await this.apiFetch(`/admin/playbooks/${encodeURIComponent(playbookName)}`, { method: "GET" });
        this.selectedPlaybook = playbookName;
        this.applyPlaybookPayload(payload, { preserveVersions: false });
      } catch (e) {
        this.showPlaybookToast(this.errorMessage(e, "Failed to load playbook."), false);
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
        this.showPlaybookToast(this.errorMessage(e, "Failed to load version."), false);
      } finally {
        this.pbLoading.load = false;
      }
    },

    async savePlaybook() {
      const name = String(this.selectedPlaybook || "").trim();
      if (!name) {
        this.showPlaybookToast("Enter a playbook name.", false);
        return;
      }
      this.ensureAce();
      this.pbLoading.save = true;
      try {
        const payload = await this.apiFetch(`/admin/playbooks/${encodeURIComponent(name)}`, {
          method: "POST",
          body: { content: this._aceReady && this._ace ? this._ace.getValue() : this.pbEditorText },
        });
        this.applyPlaybookPayload(payload);
        this.showPlaybookToast(`Saved ${name}.`, true);
      } catch (e) {
        this.showPlaybookToast(this.errorMessage(e, "Failed to save playbook."), false);
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
        this.showPlaybookToast(`Set ${version} as default.`, true);
      } catch (e) {
        this.showPlaybookToast(this.errorMessage(e, "Failed to set default version."), false);
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
        this.showPlaybookToast(`Deleted ${version}.`, true);
      } catch (e) {
        this.showPlaybookToast(this.errorMessage(e, "Failed to delete version."), false);
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

    tableRowText(row, indexes, cellText, extraValues = []) {
      return [
        ...indexes.map((idx) => cellText.call(this, row, idx)),
        ...extraValues,
      ].map((value) => String(value ?? "")).join(" ").toLowerCase();
    },

    tableSortClass(index, sortIndexKey, sortDirKey) {
      if (this[sortIndexKey] !== index) return "";
      return this[sortDirKey] === "asc" ? "sort-asc" : "sort-desc";
    },

    toggleTableSort(index, { sortIndexKey, sortDirKey, defaultDirForIndex, apply }) {
      if (this[sortIndexKey] === index) {
        this[sortDirKey] = this[sortDirKey] === "asc" ? "desc" : "asc";
      } else {
        this[sortIndexKey] = index;
        this[sortDirKey] = defaultDirForIndex(index);
      }
      apply();
    },

    applyTableFilterSort({
      sourceKey,
      visibleKey,
      filterKey,
      storageKey,
      sortIndexKey,
      sortDirKey,
      cellText,
      rowText,
      prefilter = null,
    }) {
      localStorage.setItem(storageKey, this[filterKey] || "");
      const q = String(this[filterKey] || "").toLowerCase().trim();
      let rows = Array.isArray(this[sourceKey]) ? this[sourceKey].slice() : [];
      if (typeof prefilter === "function") rows = rows.filter((row) => prefilter.call(this, row));
      if (q) rows = rows.filter((row) => rowText.call(this, row).includes(q));
      rows.sort((a, b) => this.compareValues(
        cellText.call(this, a, this[sortIndexKey]),
        cellText.call(this, b, this[sortIndexKey]),
      ));
      if (this[sortDirKey] === "desc") rows.reverse();
      this[visibleKey] = rows;
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
      delete claims.cookies;
      return claims;
    },

    authSessionCookieValue() {
      const claims = this.authClaims && typeof this.authClaims === "object" ? this.authClaims : null;
      if (!claims || typeof claims.cookies !== "object" || !claims.cookies) return "(No cookie data captured yet)";
      const cookieName = String(this.authSessionCookieName || "").trim();
      if (!cookieName) return "(No cookie data captured yet)";
      const value = claims.cookies[cookieName];
      return value ? String(value) : "(No cookie data captured yet)";
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
