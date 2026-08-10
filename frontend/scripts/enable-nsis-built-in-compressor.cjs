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
  fs.writeFileSync(target, original.replace(enabled, disabled), "utf8");
  console.log("Enabled the checksum-verified 7z application file installer.");
} else if (!original.includes(disabled)) {
  throw new Error("Unsupported app-builder-lib version: NSIS compressor flag was not found.");
}

const installSection = path.resolve(
  __dirname,
  "..",
  "node_modules",
  "app-builder-lib",
  "templates",
  "nsis",
  "installSection.nsh",
);
const checkCall = /^[ \t]*!insertmacro CHECK_APP_RUNNING[ \t]*$/gm;
const safeCall = "; Mintext uses the exact-name process cleanup from customInit.";
const sectionSource = fs.readFileSync(installSection, "utf8");
if (checkCall.test(sectionSource)) {
  fs.writeFileSync(installSection, sectionSource.replace(checkCall, safeCall), "utf8");
  console.log("Disabled electron-builder's ambiguous install-directory process check.");
} else if (!sectionSource.includes("Mintext uses the exact-name process cleanup")) {
  throw new Error("Unsupported app-builder-lib version: install process-check block was not found.");
}
