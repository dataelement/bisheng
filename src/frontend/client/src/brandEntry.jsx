const brandReady = window.__BRAND_CONFIG_READY__ || Promise.resolve();

brandReady.then(
  () => import('./main.jsx'),
  () => import('./main.jsx'),
);
