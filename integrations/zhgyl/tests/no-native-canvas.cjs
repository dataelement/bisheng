const Module = require('node:module');
const originalLoad = Module._load;

// These upload tests exercise DOM controls, not native canvas rendering.
// The normal repository setup still installs jest-canvas-mock.
Module._load = function (name, ...args) {
    if (name === 'canvas') return {};
    return originalLoad.call(this, name, ...args);
};
