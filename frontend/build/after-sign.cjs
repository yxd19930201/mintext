const fs = require("node:fs");
const path = require("node:path");

function stageExecutables(directory) {
  for (const entry of fs.readdirSync(directory, { withFileTypes: true })) {
    const fullPath = path.join(directory, entry.name);
    if (entry.isDirectory()) {
      stageExecutables(fullPath);
      continue;
    }

    const extension = path.extname(entry.name).toLowerCase();
    if (extension !== ".exe" && extension !== ".dll") {
      continue;
    }

    fs.renameSync(fullPath, `${fullPath}.install`);
  }
}

exports.default = async function afterSign(context) {
  if (context.electronPlatformName === "win32") {
    stageExecutables(context.appOutDir);
  }
};
