import fs from "node:fs/promises";
import path from "node:path";
import { chromium } from "playwright";
import {
  playwrightChannelOption,
  readConfiguredBrowserChannel,
  resolveBrowserChannel,
} from "./providers/browser-channel.js";
import { loadProviderDefinitions } from "./providers/definitions.js";

const providerId = process.argv[2] ?? "";
const definition = loadProviderDefinitions()[providerId];
if (!definition) throw new Error(`未知渠道：${providerId}`);

const outputDir = path.resolve("output/playwright");
await fs.mkdir(outputDir, { recursive: true });
const profilePath = path.resolve(
  process.env.WEB_AI_PROFILE_ROOT ?? ".profiles",
  definition.id,
);
const channel = await resolveBrowserChannel(readConfiguredBrowserChannel(definition.id));
const headless = process.env.WEB_AI_HEADLESS !== "false";
const context = await chromium.launchPersistentContext(profilePath, {
  chromiumSandbox: true,
  headless,
  viewport: { width: 1440, height: 960 },
  ...playwrightChannelOption(channel),
});

try {
  const page = context.pages()[0] ?? (await context.newPage());
  await page.goto(definition.homeUrl, { waitUntil: "domcontentloaded", timeout: 60_000 });
  await page.waitForTimeout(2_000);
  await page.screenshot({
    path: path.join(outputDir, `${providerId}-mode-before.png`),
    fullPage: true,
  });

  const modeButtons = page.getByRole("button", { name: "快速", exact: true });
  const candidates = await modeButtons.all();
  let clicked = false;
  for (const candidate of candidates) {
    if (await candidate.isVisible()) {
      await candidate.click();
      clicked = true;
      break;
    }
  }
  await page.waitForTimeout(700);
  await page.screenshot({
    path: path.join(outputDir, `${providerId}-mode-after.png`),
    fullPage: true,
  });

  console.log(
    JSON.stringify(
      {
        provider: providerId,
        url: page.url(),
        clicked,
        buttons: (await page.getByRole("button").allInnerTexts())
          .map((text) => text.trim())
          .filter(Boolean),
        links: (await page.getByRole("link").allInnerTexts())
          .map((text) => text.trim())
          .filter(Boolean),
        anchors: await page.locator("a").evaluateAll((elements) =>
          elements.slice(0, 80).map((element) => ({
            text: (element.textContent ?? "").trim().slice(0, 100),
            href: element.getAttribute("href"),
            className: element.getAttribute("class"),
          })),
        ),
        newConversationCandidates: await page
          .getByText("新对话", { exact: true })
          .evaluateAll((elements) =>
            elements.map((element) => ({
              tag: element.tagName,
              className: element.getAttribute("class"),
              ariaLabel: element.getAttribute("aria-label"),
              testId: element.getAttribute("data-testid"),
              outerHTML: element.outerHTML.slice(0, 500),
              parentHTML: element.parentElement?.outerHTML.slice(0, 1_500) ?? null,
              ancestors: (() => {
                const result: Array<Record<string, string | null>> = [];
                let current = element.parentElement;
                for (let depth = 0; current && depth < 5; depth += 1) {
                  result.push({
                    tag: current.tagName,
                    className: current.getAttribute("class"),
                    role: current.getAttribute("role"),
                    tabIndex: current.getAttribute("tabindex"),
                    testId: current.getAttribute("data-testid"),
                  });
                  current = current.parentElement;
                }
                return result;
              })(),
            })),
          ),
        menuItems: (await page.getByRole("menuitem").allInnerTexts())
          .map((text) => text.trim())
          .filter(Boolean),
        visibleText: (await page.locator("body").innerText()).slice(-4_000),
      },
      null,
      2,
    ),
  );
} finally {
  await context.close();
}
