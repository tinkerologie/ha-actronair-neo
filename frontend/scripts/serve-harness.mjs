import { readFile } from "node:fs/promises";
import { createServer } from "node:http";

const files = new Map([
  ["/", [new URL("../tests/browser/harness.html", import.meta.url), "text/html"]],
  [
    "/actronair-neo-cards.js",
    [
      new URL(
        "../../custom_components/actronair_neo/frontend/actronair-neo-cards.js",
        import.meta.url,
      ),
      "text/javascript",
    ],
  ],
  [
    "/axe.min.js",
    [new URL("../node_modules/axe-core/axe.min.js", import.meta.url), "text/javascript"],
  ],
]);
createServer(async (request, response) => {
  const file = files.get(request.url?.split("?")[0]);
  if (!file) {
    response.writeHead(404).end();
    return;
  }
  try {
    response.writeHead(200, { "Content-Type": file[1] });
    response.end(await readFile(file[0]));
  } catch {
    response.writeHead(500).end();
  }
}).listen(4178, "127.0.0.1");
