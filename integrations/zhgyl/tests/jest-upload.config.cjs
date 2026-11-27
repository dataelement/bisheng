const path = require('node:path');
const root = path.resolve(__dirname, '../../../src/frontend/client');

// These API contract tests use Node's File/FormData and do not need a canvas.
module.exports = {
    ...require(path.join(root, 'jest.config.cjs')),
    rootDir: root,
    testEnvironment: 'node',
    setupFilesAfterEnv: [],
    collectCoverage: false,
    testResultsProcessor: undefined,
};
