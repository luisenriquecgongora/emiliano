/**
 * Cross-Browser Extension Build Script
 * Builds production-ready unpacked directories for Chrome and Firefox.
 */

const fs = require('fs');
const path = require('path');

const ROOT_DIR = __dirname;
const DIST_DIR = path.join(ROOT_DIR, 'dist');
const TARGET_CHROME = path.join(DIST_DIR, 'chrome');
const TARGET_FIREFOX = path.join(DIST_DIR, 'firefox');

const COMMON_FILES = [
  'background.js',
  'hud_overlay.js',
  'hud_overlay.css',
  'recorder.js',
  'popup.html',
  'popup.js',
  'popup.css',
];

function ensureDir(dir) {
  if (!fs.existsSync(dir)) {
    fs.mkdirSync(dir, { recursive: true });
  }
}

function copyFile(src, dest) {
  fs.copyFileSync(src, dest);
}

function copyDir(src, dest) {
  ensureDir(dest);
  const entries = fs.readdirSync(src, { withFileTypes: true });
  for (const entry of entries) {
    const srcPath = path.join(src, entry.name);
    const destPath = path.join(dest, entry.name);
    if (entry.isDirectory()) {
      copyDir(srcPath, destPath);
    } else {
      copyFile(srcPath, destPath);
    }
  }
}

function buildChrome() {
  console.log('[Build] Building Chrome extension into dist/chrome...');
  ensureDir(TARGET_CHROME);

  // Copy manifest.json (Chrome MV3)
  copyFile(path.join(ROOT_DIR, 'manifest.json'), path.join(TARGET_CHROME, 'manifest.json'));

  // Copy common scripts and UI
  for (const f of COMMON_FILES) {
    const src = path.join(ROOT_DIR, f);
    if (fs.existsSync(src)) {
      copyFile(src, path.join(TARGET_CHROME, f));
    }
  }

  // Copy icons
  const iconsSrc = path.join(ROOT_DIR, 'icons');
  if (fs.existsSync(iconsSrc)) {
    copyDir(iconsSrc, path.join(TARGET_CHROME, 'icons'));
  }

  console.log('  ✓ Chrome extension ready at: dist/chrome');
}

function buildFirefox() {
  console.log('[Build] Building Firefox extension into dist/firefox...');
  ensureDir(TARGET_FIREFOX);

  // Copy manifest.firefox.json as manifest.json
  const firefoxManifest = path.join(ROOT_DIR, 'manifest.firefox.json');
  if (fs.existsSync(firefoxManifest)) {
    copyFile(firefoxManifest, path.join(TARGET_FIREFOX, 'manifest.json'));
  } else {
    copyFile(path.join(ROOT_DIR, 'manifest.json'), path.join(TARGET_FIREFOX, 'manifest.json'));
  }

  // Copy common scripts and UI
  for (const f of COMMON_FILES) {
    const src = path.join(ROOT_DIR, f);
    if (fs.existsSync(src)) {
      copyFile(src, path.join(TARGET_FIREFOX, f));
    }
  }

  // Copy icons
  const iconsSrc = path.join(ROOT_DIR, 'icons');
  if (fs.existsSync(iconsSrc)) {
    copyDir(iconsSrc, path.join(TARGET_FIREFOX, 'icons'));
  }

  console.log('  ✓ Firefox add-on ready at: dist/firefox');
}

const target = process.argv[2] || 'all';

if (target === 'chrome') {
  buildChrome();
} else if (target === 'firefox') {
  buildFirefox();
} else {
  buildChrome();
  buildFirefox();
}

console.log('[Build] Extension build complete for target(s):', target);
