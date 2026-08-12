#!/usr/bin/env node

import http from "node:http";
import fs from "node:fs/promises";
import path from "node:path";
import process from "node:process";
import { chromium } from "playwright";

function parseArgs(argv) {
  const result = {};
  for (let index = 0; index < argv.length; index += 1) {
    const value = argv[index];
    if (!value.startsWith("--")) throw new Error(`unexpected argument: ${value}`);
    const next = argv[index + 1];
    if (!next || next.startsWith("--")) throw new Error(`missing value for ${value}`);
    result[value.slice(2)] = next;
    index += 1;
  }
  for (const required of ["root", "skin-package", "pet-package", "output"]) {
    if (!result[required]) throw new Error(`--${required} is required`);
  }
  return result;
}

function relativeUrl(root, target) {
  const relative = path.relative(root, target);
  if (!relative || relative.startsWith("..") || path.isAbsolute(relative)) {
    throw new Error(`test asset is outside the served repository: ${target}`);
  }
  return `/${relative.split(path.sep).map(encodeURIComponent).join("/")}`;
}

function contentType(file) {
  switch (path.extname(file).toLowerCase()) {
    case ".html": return "text/html; charset=utf-8";
    case ".css": return "text/css; charset=utf-8";
    case ".js":
    case ".mjs": return "text/javascript; charset=utf-8";
    case ".json": return "application/json; charset=utf-8";
    case ".png": return "image/png";
    case ".webp": return "image/webp";
    case ".jpg":
    case ".jpeg": return "image/jpeg";
    default: return "application/octet-stream";
  }
}

async function startServer(root) {
  const resolvedRoot = await fs.realpath(root);
  const server = http.createServer(async (request, response) => {
    try {
      const url = new URL(request.url ?? "/", "http://127.0.0.1");
      const relative = decodeURIComponent(url.pathname).replace(/^\/+/, "");
      const candidate = path.resolve(resolvedRoot, relative);
      if (candidate !== resolvedRoot && !candidate.startsWith(`${resolvedRoot}${path.sep}`)) {
        response.writeHead(403).end("forbidden");
        return;
      }
      const body = await fs.readFile(candidate);
      response.writeHead(200, { "content-type": contentType(candidate), "cache-control": "no-store" });
      response.end(body);
    } catch (error) {
      response.writeHead(error?.code === "ENOENT" ? 404 : 500).end("not found");
    }
  });
  await new Promise((resolve, reject) => {
    server.once("error", reject);
    server.listen(0, "127.0.0.1", resolve);
  });
  const address = server.address();
  if (!address || typeof address === "string") throw new Error("static server did not bind a TCP port");
  return { server, origin: `http://127.0.0.1:${address.port}` };
}

const colorProbe = `() => {
  const parse = (value) => {
    const hex = String(value).trim().match(/^#([0-9a-f]{6})$/i);
    if (hex) {
      return {
        r: Number.parseInt(hex[1].slice(0, 2), 16),
        g: Number.parseInt(hex[1].slice(2, 4), 16),
        b: Number.parseInt(hex[1].slice(4, 6), 16),
        a: 1,
      };
    }
    const match = String(value).match(/rgba?\\(([^)]+)\\)/i);
    if (!match) throw new Error('unsupported computed color: ' + value);
    const parts = match[1].replaceAll(',', ' ').split(/\\s+/).filter(Boolean).map(Number);
    return { r: parts[0], g: parts[1], b: parts[2], a: parts.length > 3 ? parts[3] : 1 };
  };
  const linear = (channel) => {
    const value = channel / 255;
    return value <= 0.04045 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4;
  };
  const ratio = (first, second) => {
    const a = parse(first), b = parse(second);
    const lum = (c) => 0.2126 * linear(c.r) + 0.7152 * linear(c.g) + 0.0722 * linear(c.b);
    const values = [lum(a), lum(b)].sort((x, y) => y - x);
    return (values[0] + 0.05) / (values[1] + 0.05);
  };
  const composite = (foreground, background) => {
    const front = parse(foreground), back = parse(background);
    return 'rgb(' + [front.r, front.g, front.b].map((channel, index) => {
      const base = [back.r, back.g, back.b][index];
      return Math.round(channel * front.a + base * (1 - front.a));
    }).join(', ') + ')';
  };
  const style = (selector) => getComputedStyle(document.querySelector(selector));
  const panel = style('[data-app-shell-focus-area="right-panel"]');
  const section = style('[data-testid="right-panel-section"]');
  const primary = style('[data-testid="right-panel-section"] .text-token-text-primary');
  const secondary = style('[data-testid="right-panel-section"] .text-token-text-secondary');
  const mainText = style('h1');
  const mainSurface = style('main.main-surface');
  const sidebar = style('.app-shell-left-panel');
  const sidebarText = style('.nav-item.active');
  const turnCarrier = getComputedStyle(document.querySelector('[data-turn-key]'), '::before');
  const composerCarrier = style('[data-thread-scroll-footer] [data-pip-obstacle]');
  const before = getComputedStyle(document.body, '::before');
  const after = getComputedStyle(document.body, '::after');
  const root = style(':root');
  const semanticSurface = root.getPropertyValue('--chromapaw-surface').trim();
  return {
    skinLoaded: Boolean(document.querySelector('link[data-test-skin]')?.sheet),
    scene: {
      display: before.display,
      backgroundImage: before.backgroundImage,
      wash: after.backgroundColor,
      sceneFilter: before.filter,
      localProtection: mainSurface.backgroundImage,
      mainText: mainText.color,
      semanticContrast: ratio(mainText.color, semanticSurface),
      turnCarrier: {
        background: turnCarrier.backgroundColor,
        border: turnCarrier.borderTopColor,
        backdropFilter: turnCarrier.backdropFilter || turnCarrier.webkitBackdropFilter,
      },
      composerCarrier: {
        background: composerCarrier.backgroundColor,
        border: composerCarrier.borderTopColor,
      },
    },
    sidebar: {
      background: sidebar.backgroundColor,
      color: sidebarText.color,
      contrast: ratio(sidebarText.color, sidebar.backgroundColor),
    },
    panel: { background: panel.backgroundColor, color: panel.color },
    section: { background: section.backgroundColor },
    primary: { color: primary.color, contrast: ratio(primary.color, section.backgroundColor) },
    secondary: { color: secondary.color, contrast: ratio(secondary.color, section.backgroundColor) },
    panelContrast: ratio(panel.color, panel.backgroundColor),
  };
}`;

const overlayProbe = `() => {
  const parse = (value) => {
    const match = String(value).match(/rgba?\\(([^)]+)\\)/i);
    if (!match) throw new Error('unsupported computed color: ' + value);
    const parts = match[1].replaceAll(',', ' ').split(/\\s+/).filter(Boolean).map(Number);
    return { r: parts[0], g: parts[1], b: parts[2] };
  };
  const linear = (channel) => {
    const value = channel / 255;
    return value <= 0.04045 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4;
  };
  const ratio = (first, second) => {
    const a = parse(first), b = parse(second);
    const lum = (c) => 0.2126 * linear(c.r) + 0.7152 * linear(c.g) + 0.0722 * linear(c.b);
    const values = [lum(a), lum(b)].sort((x, y) => y - x);
    return (values[0] + 0.05) / (values[1] + 0.05);
  };
  const body = getComputedStyle(document.body);
  const root = getComputedStyle(document.querySelector('#root'));
  const frame = getComputedStyle(document.querySelector('[data-avatar-overlay-content-frame="true"]'));
  const before = getComputedStyle(document.body, '::before');
  const after = getComputedStyle(document.body, '::after');
  const card = getComputedStyle(document.querySelector('.notification-card'));
  const title = getComputedStyle(document.querySelector('.notification-title'));
  const copy = getComputedStyle(document.querySelector('[data-avatar-overlay-measure-body="true"]'));
  const control = getComputedStyle(document.querySelector('[data-avatar-overlay-control="dismiss"] button'));
  const sprite = getComputedStyle(document.querySelector('.codex-avatar-root'));
  return {
    skinLoaded: Boolean(document.querySelector('link[data-test-skin]')?.sheet),
    backgrounds: { body: body.backgroundColor, root: root.backgroundColor, frame: frame.backgroundColor },
    pseudo: { beforeDisplay: before.display, afterDisplay: after.display },
    sprite: { backgroundImage: sprite.backgroundImage, width: sprite.width, height: sprite.height },
    notification: {
      background: card.backgroundColor,
      title: title.color,
      body: copy.color,
      controlBackground: control.backgroundColor,
      controlColor: control.color,
      titleContrast: ratio(title.color, card.backgroundColor),
      bodyContrast: ratio(copy.color, card.backgroundColor),
      controlContrast: ratio(control.color, control.backgroundColor),
    },
  };
}`;

function requireGate(condition, message) {
  if (!condition) throw new Error(message);
}

async function run() {
  const args = parseArgs(process.argv.slice(2));
  const root = path.resolve(args.root);
  const skinPackage = path.resolve(args["skin-package"]);
  const petPackage = path.resolve(args["pet-package"]);
  const output = path.resolve(args.output);
  const skinStylesheets = {};
  const manifest = JSON.parse(await fs.readFile(path.join(skinPackage, "skin.json"), "utf8"));
  const petManifest = JSON.parse(await fs.readFile(path.join(petPackage, "pet.json"), "utf8"));
  for (const mode of ["light", "dark"]) {
    skinStylesheets[mode] = relativeUrl(
      root,
      path.join(skinPackage, manifest.assets.stylesheets[mode]),
    );
  }
  const petUrl = relativeUrl(root, path.join(petPackage, petManifest.spritesheetPath));
  await fs.mkdir(output, { recursive: true });
  const { server, origin } = await startServer(root);
  const launchOptions = { headless: true, timeout: 15000 };
  if (process.env.CHROMAPAW_PLAYWRIGHT_EXECUTABLE) {
    launchOptions.executablePath = process.env.CHROMAPAW_PLAYWRIGHT_EXECUTABLE;
  }
  const browser = await chromium.launch(launchOptions);
  const results = {};
  try {
    for (const mode of ["light", "dark"]) {
      const skinUrl = skinStylesheets[mode];
      const mainPage = await browser.newPage({ viewport: { width: 1440, height: 900 }, deviceScaleFactor: 1 });
      mainPage.setDefaultTimeout(15000);
      const mainUrl = new URL("/tests/fixtures/macos-harness/index.html", origin);
      mainUrl.searchParams.set("mode", mode);
      mainUrl.searchParams.set("skin", skinUrl);
      await mainPage.goto(mainUrl.toString(), { waitUntil: "domcontentloaded", timeout: 15000 });
      await mainPage.waitForFunction(
        () => Boolean(document.querySelector('link[data-test-skin]')?.sheet),
        undefined,
        { timeout: 15000 },
      );
      const main = await mainPage.evaluate(`(${colorProbe})()`);
      requireGate(main.skinLoaded, `${mode}: generated skin stylesheet did not load`);
      requireGate(main.scene.display !== "none" && main.scene.backgroundImage !== "none", `${mode}: main scene background is missing`);
      requireGate(main.scene.wash === "rgba(0, 0, 0, 0)", `${mode}: a full-window scene wash is still active`);
      requireGate(!main.scene.sceneFilter.includes("blur"), `${mode}: scene fidelity filter blurs the artwork`);
      requireGate(main.scene.localProtection !== "none", `${mode}: local main-content protection is missing`);
      requireGate(main.scene.turnCarrier.background !== "rgba(0, 0, 0, 0)", `${mode}: conversation turn carrier is transparent`);
      requireGate(main.scene.turnCarrier.border !== "rgba(0, 0, 0, 0)", `${mode}: conversation turn carrier border is missing`);
      requireGate(main.scene.composerCarrier.background !== "rgba(0, 0, 0, 0)", `${mode}: composer carrier is transparent`);
      requireGate(main.scene.semanticContrast >= 4.5, `${mode}: semantic main text contrast is below 4.5`);
      requireGate(main.sidebar.contrast >= 4.5, `${mode}: sidebar contrast is below 4.5`);
      requireGate(main.panelContrast >= 4.5, `${mode}: right panel contrast ${main.panelContrast.toFixed(2)} is below 4.5`);
      requireGate(main.primary.contrast >= 4.5, `${mode}: section primary contrast is below 4.5`);
      requireGate(main.secondary.contrast >= 4.5, `${mode}: section secondary contrast is below 4.5`);
      const mainScreenshot = path.join(output, `macos-main-${mode}.png`);
      await mainPage.screenshot({ path: mainScreenshot, fullPage: false });
      await mainPage.close();

      const overlayPage = await browser.newPage({ viewport: { width: 480, height: 360 }, deviceScaleFactor: 1 });
      overlayPage.setDefaultTimeout(15000);
      const overlayUrl = new URL("/tests/fixtures/macos-harness/pet-overlay.html", origin);
      overlayUrl.searchParams.set("mode", mode);
      overlayUrl.searchParams.set("skin", skinUrl);
      overlayUrl.searchParams.set("pet", petUrl);
      await overlayPage.goto(overlayUrl.toString(), { waitUntil: "domcontentloaded", timeout: 15000 });
      await overlayPage.waitForFunction(
        () => Boolean(document.querySelector('link[data-test-skin]')?.sheet),
        undefined,
        { timeout: 15000 },
      );
      const overlay = await overlayPage.evaluate(`(${overlayProbe})()`);
      requireGate(overlay.skinLoaded, `${mode}: overlay skin stylesheet did not load`);
      requireGate(overlay.backgrounds.body === "rgba(0, 0, 0, 0)", `${mode}: pet body is not transparent`);
      requireGate(overlay.backgrounds.root === "rgba(0, 0, 0, 0)", `${mode}: pet root is not transparent`);
      requireGate(overlay.backgrounds.frame === "rgba(0, 0, 0, 0)", `${mode}: pet frame is not transparent`);
      requireGate(overlay.pseudo.beforeDisplay === "none" && overlay.pseudo.afterDisplay === "none", `${mode}: skin scene leaked into pet overlay`);
      requireGate(overlay.sprite.backgroundImage !== "none", `${mode}: pet spritesheet was cleared`);
      requireGate(overlay.notification.titleContrast >= 4.5, `${mode}: notification title contrast is below 4.5`);
      requireGate(overlay.notification.bodyContrast >= 4.5, `${mode}: notification body contrast is below 4.5`);
      requireGate(overlay.notification.controlContrast >= 4.5, `${mode}: notification control contrast is below 4.5`);
      const overlayScreenshot = path.join(output, `macos-pet-overlay-${mode}.png`);
      await overlayPage.screenshot({ path: overlayScreenshot, fullPage: false, omitBackground: true });
      await overlayPage.close();
      results[mode] = {
        main,
        overlay,
        screenshots: { main: mainScreenshot, overlay: overlayScreenshot },
      };
    }
  } finally {
    await browser.close();
    await new Promise((resolve) => server.close(resolve));
  }
  const report = {
    ok: true,
    renderer: "Playwright Chromium",
    realCodexGuiTested: false,
    simulatedCodexRendererTested: true,
    modes: results,
  };
  const reportPath = path.join(output, "visual-report.json");
  await fs.writeFile(reportPath, `${JSON.stringify(report, null, 2)}\n`, "utf8");
  process.stdout.write(`${reportPath}\n`);
}

run().catch((error) => {
  process.stderr.write(`ERROR: ${error.stack || error.message}\n`);
  process.exitCode = 1;
});
