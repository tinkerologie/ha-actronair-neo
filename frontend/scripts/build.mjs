import { mkdir, readFile, writeFile } from "node:fs/promises";
import { build } from "esbuild";

const directory = new URL("../../custom_components/actronair_neo/frontend/", import.meta.url);
const result = await build({
  entryPoints: ["src/index.ts"],
  bundle: true,
  minify: true,
  format: "esm",
  target: "es2022",
  legalComments: "inline",
  write: false,
});
const files = new Map([
  ["actronair-neo-cards.js", `${result.outputFiles[0].text.replaceAll("\t", "\\t").trimEnd()}\n`],
]);
const licenses = await Promise.all(
  ["lit", "lit-html", "@lit/reactive-element"].map(
    async (name) =>
      `${name}\n${await readFile(new URL(`../node_modules/${name}/LICENSE`, import.meta.url), "utf8")}`,
  ),
);
files.set("THIRD_PARTY_LICENSES.txt", `${licenses.join("\n\n").trimEnd()}\n`);
if (process.argv.includes("--check")) {
  for (const [name, content] of files)
    if ((await readFile(new URL(name, directory), "utf8")) !== content)
      throw new Error(`Rebuild frontend: ${name} differs`);
} else {
  await mkdir(directory, { recursive: true });
  for (const [name, content] of files) await writeFile(new URL(name, directory), content);
}
