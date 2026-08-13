import { readFile } from "node:fs/promises";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const destination = resolve(root, "lib/adapter-contract.js");
const current = await readFile(destination, "utf8").catch(() => "");

// The upstream contract is vendored into this extension so the desktop
// installer is self-contained and does not depend on the original repository.
if (!current.includes("globalThis.MaliangFanqieContract =")) {
  process.stderr.write("Bundled Fanqie adapter contract is missing or invalid.\n");
  process.exitCode = 1;
} else if (!process.argv.includes("--check")) {
  process.stdout.write("The vendored Fanqie adapter contract is already current.\n");
}
