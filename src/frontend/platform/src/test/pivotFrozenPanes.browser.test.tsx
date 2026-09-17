import { execFileSync } from "node:child_process"
import { mkdtempSync, rmSync, writeFileSync } from "node:fs"
import { tmpdir } from "node:os"
import path from "node:path"
import { pathToFileURL } from "node:url"
import postcss from "postcss"
import { renderToStaticMarkup } from "react-dom/server"
import tailwindcss from "tailwindcss"
import loadConfig from "tailwindcss/loadConfig"
import { describe, expect, it } from "vitest"

import { PivotTable } from "@/pages/Dashboard/components/charts/PivotTable"
import { PivotTableDataResponse } from "@/pages/Dashboard/types/chartData"
import { DataConfig } from "@/pages/Dashboard/types/dataConfig"

// jsdom cannot verify sticky positioning or which cell is painted on top.
// Set CHROME_BIN to run headlessly, or PIVOT_BROWSER_FIXTURE_DIR to generate
// pages for browser inspection; fixture generation explicitly skips assertions.
const chrome = process.env.CHROME_BIN
const fixtureDirectory = process.env.PIVOT_BROWSER_FIXTURE_DIR

describe.skipIf(!chrome && !fixtureDirectory)("pivot frozen panes in a real browser", () => {
  it.for([false, true])("keeps frozen corners above scrolling rows (grouped: %s)", async (grouped, context) => {
    const columns = Array.from({ length: 12 }, (_, index) => `部门${index + 1}`)
    const data: PivotTableDataResponse = {
      rowHeaders: grouped ? ["公司", "时间(周)"] : ["时间(周)"],
      columnHeader: "部门",
      metricName: "新增文件数",
      columns,
      columnPaths: grouped ? columns.map(label => ["2026", label]) : undefined,
      groupDimensionIndex: grouped ? 0 : undefined,
      rows: Array.from({ length: 30 }, (_, index) => ({
        key: grouped ? [`公司${Math.floor(index / 5)}`, `第${index + 1}周`] : [`第${index + 1}周`],
        values: columns.map(() => 1),
        total: 12,
      })),
      columnTotals: columns.map(() => 30),
      grandTotal: 360,
    }
    const markup = renderToStaticMarkup(
      <PivotTable data={data} dataConfig={{ metrics: [] } as DataConfig} isDark={false} />,
    )
    const config = loadConfig(path.resolve("tailwind.config.js"))
    const { css } = await postcss([tailwindcss({ ...config, content: [{ raw: markup, extension: "html" }] })])
      .process("@tailwind base; @tailwind components; @tailwind utilities;", { from: undefined })
    const directory = mkdtempSync(path.join(tmpdir(), "pivot-frozen-panes-"))
    try {
      const file = path.join(directory, "index.html")
      const html = `<!doctype html><html><head><meta charset="utf-8"><style>${css}
        :root { --background: 0 0% 100%; --foreground: 222 47% 11%; }
        #fixture { width: 700px; height: 250px; margin: 20px; }
      </style></head><body><div id="fixture">${markup}</div><pre id="result"></pre>
      <script>
        const table = document.querySelector('table');
        const scroller = table.parentElement;
        const header = table.tHead.rows[0].cells[0];
        const footer = table.tFoot.rows[0].cells[0];
        const initial = header.getBoundingClientRect();
        const results = [];
        for (const [left, top] of [[0, 15], [180, 115], [180, 215]]) {
          scroller.scrollTo(left, top);
          const rect = header.getBoundingClientRect();
          const bottom = footer.getBoundingClientRect();
          const hit = (x, y) => document.elementFromPoint(x, y)?.closest('th, td');
          results.push({
            scrolled: scroller.scrollTop === top && scroller.scrollLeft === left,
            headerVisible: hit(rect.x + rect.width / 2, rect.y + rect.height / 2) === header,
            footerVisible: hit(rect.x + rect.width / 2, bottom.y + bottom.height / 2) === footer,
            footerDimensionVisible: hit(bottom.x + bottom.width - 10, bottom.y + bottom.height / 2) === footer,
            headerFixed: rect.x === initial.x && rect.y === initial.y,
          });
        }
        document.querySelector('#result').textContent = JSON.stringify(results);
      </script></body></html>`
      if (fixtureDirectory) {
        writeFileSync(path.join(fixtureDirectory, `pivot-${grouped ? "grouped" : "plain"}.html`), html)
        context.skip()
      }
      writeFileSync(file, html)
      const output = execFileSync(chrome!, [
        "--headless", "--disable-gpu", "--no-first-run", "--no-default-browser-check",
        "--use-mock-keychain", "--disable-background-networking", "--disable-extensions",
        `--user-data-dir=${path.join(directory, "profile")}`, "--dump-dom", pathToFileURL(file).href,
      ], { encoding: "utf8", timeout: 20000, stdio: ["ignore", "pipe", "pipe"] })
      const result = output.match(/<pre id="result">(.*?)<\/pre>/)?.[1]
      expect(result).toBeDefined()
      expect(JSON.parse(result!)).toEqual(Array.from({ length: 3 }, () => ({
        scrolled: true,
        headerVisible: true,
        footerVisible: true,
        footerDimensionVisible: true,
        headerFixed: true,
      })))
    } finally {
      rmSync(directory, { recursive: true, force: true })
    }
  }, 30000)
})
