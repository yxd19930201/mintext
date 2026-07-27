const fs = require("node:fs");
const path = require("node:path");

exports.default = async function afterPack(context) {
  if (context.electronPlatformName !== "win32") {
    return;
  }

  const source = path.join(context.appOutDir, "d3dcompiler_47.dll");
  const staged = `${source}.install`;

  if (fs.existsSync(staged)) {
    fs.rmSync(staged, { force: true });
  }
  fs.renameSync(source, staged);
};
