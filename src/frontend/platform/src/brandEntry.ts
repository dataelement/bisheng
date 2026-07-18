const brandReady = window.__BRAND_CONFIG_READY__ || Promise.resolve();

brandReady.then(
    () => import("./index"),
    () => import("./index")
);
