import fs from "node:fs/promises";
import path from "node:path";
import { chromium } from "playwright";
import { JSON_OPEN } from "./core/json-envelope.js";
import {
  playwrightChannelOption,
  readConfiguredBrowserChannel,
  resolveBrowserChannel,
} from "./providers/browser-channel.js";
import { loadProviderDefinitions } from "./providers/definitions.js";

const providerId = process.argv[2] ?? "";
const targetUrl = process.argv[3];
const definition = loadProviderDefinitions()[providerId];
if (!definition) {
  console.error(`未知渠道：${providerId || "(未提供)"}`);
  process.exit(1);
}

const outputDir = path.resolve("output/playwright");
await fs.mkdir(outputDir, { recursive: true });
const profilePath = path.resolve(
  process.env.WEB_AI_PROFILE_ROOT ?? ".profiles",
  definition.id,
);
const channel = await resolveBrowserChannel(readConfiguredBrowserChannel(definition.id));
const headless = process.env.WEB_AI_HEADLESS !== "false";
const context = await chromium.launchPersistentContext(profilePath, {
  headless,
  chromiumSandbox: true,
  viewport: { width: 1440, height: 960 },
  ...playwrightChannelOption(channel),
});

try {
  const page = context.pages()[0] ?? (await context.newPage());
  await page.goto(targetUrl ?? definition.homeUrl, { waitUntil: "domcontentloaded", timeout: 60_000 });
  await page.waitForTimeout(providerId === "chatgpt" ? 12_000 : 2_000);
  const screenshotPath = path.join(outputDir, `${definition.id}-diagnostic.png`);
  await page.screenshot({ path: screenshotPath, fullPage: true });

  const selectors = [] as Array<{ selector: string; count: number; samples: string[] }>;
  for (const selector of definition.assistantSelectors) {
    const locator = page.locator(selector);
    const count = await locator.count();
    selectors.push({
      selector,
      count,
      samples: (await locator.allInnerTexts()).slice(-3).map((text) => text.slice(-500)),
    });
  }

  const markerElements = await page.locator("body").evaluate((body, marker) => {
    const matches: Array<{ tag: string; className: string; text: string }> = [];
    for (const element of body.querySelectorAll("*")) {
      const text = (element as HTMLElement).innerText;
      if (!text?.includes(marker)) continue;
      const childContainsMarker = [...element.children].some((child) =>
        (child as HTMLElement).innerText?.includes(marker),
      );
      if (!childContainsMarker) {
        matches.push({
          tag: element.tagName.toLowerCase(),
          className: typeof element.className === "string" ? element.className : "",
          text: text.slice(-1_000),
        });
      }
    }
    return matches.slice(-10);
  }, JSON_OPEN);

  const controls = {
    buttons: (await page.getByRole("button").allInnerTexts())
      .map((text) => text.trim())
      .filter(Boolean)
      .slice(-80),
    radios: await page.getByRole("radio").allInnerTexts(),
    checkboxes: await page.getByRole("checkbox").allInnerTexts(),
    textboxes: await page.locator('textarea, [contenteditable="true"]').evaluateAll((elements) =>
      elements.map((element) => ({
        tag: element.tagName.toLowerCase(),
        placeholder: element.getAttribute("placeholder"),
        ariaLabel: element.getAttribute("aria-label"),
      })),
    ),
    links: (await page.locator("a[href]").evaluateAll((elements) =>
      elements.map((element) => ({
        text: (element as HTMLElement).innerText?.trim() ?? "",
        href: (element as HTMLAnchorElement).href,
      })),
    )).filter((item) => item.text || item.href).slice(-80),
    namedControls: await Promise.all(
      ["快速模式", "专家模式", "深度思考", "智能搜索", "联网搜索"].map(async (name) => {
        const locator = page.getByText(name, { exact: true }).first();
        if ((await locator.count()) === 0) return { name, found: false };
        return {
          name,
          found: true,
          visible: await locator.isVisible(),
          tag: await locator.evaluate((element) => element.tagName.toLowerCase()),
          className: await locator.getAttribute("class"),
          parentClassName: await locator.evaluate((element) =>
            typeof element.parentElement?.className === "string"
              ? element.parentElement.className
              : "",
          ),
          parentStyle: await locator.evaluate((element) => {
            if (!element.parentElement) return null;
            const style = getComputedStyle(element.parentElement);
            return {
              backgroundColor: style.backgroundColor,
              borderColor: style.borderColor,
              color: style.color,
            };
          }),
          ariaPressed: await locator.getAttribute("aria-pressed"),
          ariaChecked: await locator.getAttribute("aria-checked"),
        };
      }),
    ),
  };

  console.log(
    JSON.stringify(
      {
        provider: definition.id,
        title: await page.title(),
        url: page.url(),
        screenshotPath,
        assistantSelectors: selectors,
        markerElements,
        controls,
      },
      null,
      2,
    ),
  );
} finally {
  await context.close();
}
