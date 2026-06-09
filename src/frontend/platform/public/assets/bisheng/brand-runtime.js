(function () {
  var SCRIPT_MARKER = "/assets/bisheng/brand-runtime.js";
  var RUNTIME_CONFIG_PATH = "/api/v1/brand/runtime-config";
  var ABSOLUTE_URL_PATTERN = /^(?:https?:|data:|blob:|\/\/)/i;

  function mergeObject(base, next) {
    var result = {};
    Object.keys(base || {}).forEach(function (key) {
      result[key] = base[key];
    });
    Object.keys(next || {}).forEach(function (key) {
      result[key] = next[key];
    });
    return result;
  }

  function getRuntimeBaseUrl() {
    var currentScript = (document.currentScript && document.currentScript.src) || "";
    var markerIndex = currentScript.indexOf(SCRIPT_MARKER);
    if (markerIndex === -1) return "";

    var path = currentScript.slice(0, markerIndex);
    try {
      path = new URL(path).pathname;
    } catch (error) {
      path = "";
    }
    return path.replace(/\/$/, "");
  }

  var runtimeBaseUrl = getRuntimeBaseUrl();

  function withRuntimeBaseUrl(url) {
    if (!url || ABSOLUTE_URL_PATTERN.test(url)) return url || "";
    if (runtimeBaseUrl && (url === runtimeBaseUrl || url.indexOf(runtimeBaseUrl + "/") === 0)) {
      return url;
    }
    return url.charAt(0) === "/" ? runtimeBaseUrl + url : runtimeBaseUrl + "/" + url;
  }

  function normalizeAsset(asset) {
    if (asset && asset.url) {
      asset.url = withRuntimeBaseUrl(asset.url);
    }
    return asset;
  }

  function normalizeAssetUrls(assets) {
    Object.keys(assets || {}).forEach(function (key) {
      normalizeAsset(assets[key]);
    });
  }

  function normalizeLoading(loading) {
    if (!loading) return loading;
    normalizeAsset(loading.icon);
    (loading.iconOptions || []).forEach(normalizeAsset);
    return loading;
  }

  function getBrandLanguage() {
    var savedLanguage = "";
    try {
      savedLanguage = (window.localStorage && window.localStorage.getItem("i18nextLng")) || "";
    } catch (error) {
      savedLanguage = "";
    }
    var normalized = savedLanguage === "zh" ? "zh-Hans" : savedLanguage === "en" ? "en-US" : savedLanguage;
    var language = normalized || navigator.language || "en";
    return language.toLowerCase().indexOf("zh") === 0 ? "zh" : "en";
  }

  function getBrandTitle(brandName) {
    var language = getBrandLanguage();
    return language === "zh"
      ? ((brandName && (brandName.zh || brandName.en)) || "")
      : ((brandName && (brandName.en || brandName.zh)) || "");
  }

  function applyDocumentBrand(config) {
    var title = getBrandTitle(config && config.brandName);
    if (title) {
      document.title = title;
    }

    var favicon = config && config.assets && config.assets.favicon && config.assets.favicon.url;
    if (favicon) {
      var link = document.querySelector("link[rel*='icon']") || document.createElement("link");
      link.rel = "icon";
      link.href = favicon;
      document.head.appendChild(link);
    }
  }

  function applyBrandConfig(incoming) {
    var previous = window.BRAND_CONFIG || {};
    var next = mergeObject(previous, incoming);
    next.brandName = mergeObject(previous.brandName, incoming && incoming.brandName);

    if (previous.linsightAgentName || (incoming && incoming.linsightAgentName)) {
      next.linsightAgentName = mergeObject(previous.linsightAgentName, incoming && incoming.linsightAgentName);
    }

    next.assets = mergeObject(previous.assets, incoming && incoming.assets);
    normalizeAssetUrls(next.assets);

    var previousLoading = previous.loading || {};
    var incomingLoading = (incoming && incoming.loading) || {};
    next.loading = mergeObject(previousLoading, incomingLoading);
    if (previousLoading.icon || incomingLoading.icon) {
      next.loading.icon = mergeObject(previousLoading.icon, incomingLoading.icon);
    }
    normalizeLoading(next.loading);

    var loadingIcon = withRuntimeBaseUrl(
      (incoming && incoming.URLLoadingIcon)
      || (next.loading && next.loading.icon && next.loading.icon.url)
      || previous.loadingIcon
      || previous.URLLoadingIcon
      || ""
    );
    next.URLLoadingIcon = loadingIcon;
    next.loadingIcon = loadingIcon;
    next.loadingAnimation = (next.loading && next.loading.animation) || previous.loadingAnimation || "";

    window.BRAND_CONFIG = next;
    applyDocumentBrand(next);
    return next;
  }

  function readRuntimeConfig(response) {
    if (!response.ok) {
      throw new Error("Failed to load brand runtime config");
    }
    return response.json().then(function (body) {
      return body && Object.prototype.hasOwnProperty.call(body, "data") ? body.data : body;
    });
  }

  applyBrandConfig(window.BRAND_CONFIG || {});

  window.__BRAND_CONFIG_READY__ = (window.fetch
    ? fetch(withRuntimeBaseUrl(RUNTIME_CONFIG_PATH), { cache: "no-store" }).then(readRuntimeConfig)
    : Promise.resolve({})
  )
    .then(function (config) {
      return applyBrandConfig(config || {});
    })
    .catch(function () {
      applyDocumentBrand(window.BRAND_CONFIG || {});
      return window.BRAND_CONFIG || {};
    });
})();
