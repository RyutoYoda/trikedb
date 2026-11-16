import { createHash } from "node:crypto";
import { copyFile, mkdir, readFile, writeFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import { parse } from "yaml";

const root = fileURLToPath(new URL("../", import.meta.url));
const dist = fileURLToPath(new URL("./dist/", import.meta.url));
await mkdir(dist, { recursive: true });
for (const file of ["index.html", "app.css", "app.js"]) {
  await copyFile(new URL(`../${file}`, import.meta.url), new URL(`./dist/${file}`, import.meta.url));
}
await copyFile(new URL("../../../src/trikedb/trikedb-horizontal.png", import.meta.url), new URL("./dist/logo.png", import.meta.url));
const yaml = await readFile(new URL("../demo.yaml", import.meta.url), "utf8");
const versionFile = await readFile(new URL("../../../pyproject.toml", import.meta.url), "utf8");
const version = versionFile.match(/^version\s*=\s*"([^"]+)"/m)?.[1];
if (!version) throw new Error("TrikeDB version missing from pyproject.toml");
await writeFile(new URL("./dist/demo-data.json", import.meta.url), JSON.stringify({
  sha: createHash("sha256").update(yaml).digest("hex"),
  graph: parse(yaml),
  yaml,
  version,
}));
