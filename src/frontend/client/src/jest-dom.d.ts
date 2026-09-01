// setupTests.js imports '@testing-library/jest-dom' at runtime, but it is a .js
// file so tsc never sees the matcher augmentation. Pull the types in here so
// toBeInTheDocument/toBeDisabled/... typecheck inside .test.tsx files.
import "@testing-library/jest-dom";
