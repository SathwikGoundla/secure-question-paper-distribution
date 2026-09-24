/** @type {import('jest').Config} */
module.exports = {
  preset: "ts-jest",
  testEnvironment: "node",
  testMatch: ["**/tests/**/*.test.ts"],
  // @noble/curves (a transitive dependency of @hyperledger/fabric-gateway,
  // used for its cryptographic signing implementation) ships ESM-only
  // JavaScript. Jest ignores node_modules for transformation by
  // default; this narrow exception lets ts-jest transpile just that
  // one dependency (and its @noble/hashes sibling) to CommonJS, rather
  // than disabling the node_modules ignore rule project-wide.
  transform: {
    "^.+\\.(ts|js)$": ["ts-jest", { isolatedModules: true, tsconfig: "tsconfig.jest.json" }],
  },
  transformIgnorePatterns: ["node_modules/(?!(@noble)/)"],
};
