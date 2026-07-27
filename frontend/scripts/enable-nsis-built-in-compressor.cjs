const fs = require("node:fs");
const path = require("node:path");

const target = path.resolve(
  __dirname,
  "..",
  "node_modules",
  "app-builder-lib",
  "out",
  "targets",
  "nsis",
  "NsisTarget.js",
);

const original = fs.readFileSync(target, "utf8");
const disabled = "const USE_NSIS_BUILT_IN_COMPRESSOR = false;";
const enabled = "const USE_NSIS_BUILT_IN_COMPRESSOR = true;";

if (original.includes(enabled)) {
  process.exit(0);
}
if (!original.includes(disabled)) {
  throw new Error("Unsupported app-builder-lib version: NSIS compressor flag was not found.");
}

fs.writeFileSync(target, original.replace(disabled, enabled), "utf8");
console.log("Enabled the NSIS built-in application file installer.");
