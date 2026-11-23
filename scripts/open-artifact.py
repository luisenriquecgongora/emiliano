#!/usr/bin/env python3
"""
Universal Markdown Artifact / Plan HTML Renderer & Browser Opener.
Part of the agent-standards ecosystem.

Converts any markdown file (with Mermaid diagrams) to a standalone interactive HTML dashboard
and launches it directly in Chrome, Firefox, or the system default browser.

Usage:
    python scripts/open-artifact.py <path_to_markdown.md> [chrome|firefox]
"""

import sys
import os
import json
import webbrowser
from pathlib import Path

HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{title}</title>
  <script src="https://cdn.tailwindcss.com"></script>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700;800&family=JetBrains+Mono:wght@400;500;600&display=swap" rel="stylesheet">
  <script src="https://cdn.jsdelivr.net/npm/marked/marked.min.js"></script>
  <script src="https://cdn.jsdelivr.net/npm/mermaid@10/dist/mermaid.min.js"></script>
  <style>
    body {{
      font-family: 'Plus Jakarta Sans', -apple-system, BlinkMacSystemFont, sans-serif;
    }}
    code, pre, .mono {{
      font-family: 'JetBrains Mono', monospace;
    }}
    .prose h1 {{ font-size: 2rem; font-weight: 800; margin-top: 1.5rem; margin-bottom: 1rem; color: #f8fafc; border-bottom: 1px solid #334155; padding-bottom: 0.5rem; }}
    .prose h2 {{ font-size: 1.5rem; font-weight: 700; margin-top: 2rem; margin-bottom: 0.75rem; color: #f1f5f9; border-bottom: 1px solid #1e293b; padding-bottom: 0.25rem; }}
    .prose h3 {{ font-size: 1.2rem; font-weight: 600; margin-top: 1.5rem; margin-bottom: 0.5rem; color: #e2e8f0; }}
    .prose p {{ margin-bottom: 1rem; line-height: 1.75; color: #cbd5e1; font-size: 0.95rem; }}
    .prose ul, .prose ol {{ margin-bottom: 1rem; padding-left: 1.5rem; color: #cbd5e1; }}
    .prose ul {{ list-style-type: disc; }}
    .prose ol {{ list-style-type: decimal; }}
    .prose li {{ margin-bottom: 0.35rem; }}
    .prose table {{ width: 100%; border-collapse: separate; border-spacing: 0; margin-top: 1.5rem; margin-bottom: 1.5rem; border-radius: 0.5rem; overflow: hidden; border: 1px solid #334155; }}
    .prose th {{ background-color: #1e293b; color: #f8fafc; font-weight: 600; text-align: left; padding: 0.75rem 1rem; border-bottom: 1px solid #334155; font-size: 0.875rem; }}
    .prose td {{ padding: 0.75rem 1rem; border-bottom: 1px solid #1e293b; color: #cbd5e1; font-size: 0.875rem; }}
    .prose tr:last-child td {{ border-bottom: none; }}
    .prose tr:hover td {{ background-color: rgba(30, 41, 59, 0.5); }}
    .prose blockquote {{ border-left: 4px solid #6366f1; padding-left: 1rem; margin: 1rem 0; color: #94a3b8; font-style: italic; background: rgba(99, 102, 241, 0.05); padding-top: 0.5rem; padding-bottom: 0.5rem; border-radius: 0 0.5rem 0.5rem 0; }}
    .prose pre {{ background-color: #0f172a; border: 1px solid #1e293b; border-radius: 0.75rem; padding: 1rem; margin: 1rem 0; overflow-x: auto; }}
    .prose code {{ background-color: #1e293b; color: #a5b4fc; padding: 0.15rem 0.4rem; border-radius: 0.25rem; font-size: 0.85em; }}
    .prose pre code {{ background-color: transparent; padding: 0; color: #e2e8f0; font-size: 0.875rem; }}
    .prose a {{ color: #818cf8; text-decoration: underline; text-underline-offset: 3px; }}
    .prose a:hover {{ color: #a5b4fc; }}
    .mermaid-box {{ background-color: #0b1120; border: 1px solid #1e293b; border-radius: 0.75rem; padding: 1.5rem; margin: 1.5rem 0; display: flex; justify-content: center; box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.2); overflow-x: auto; }}
  </style>
</head>
<body class="bg-slate-950 text-slate-100 min-h-screen antialiased selection:bg-indigo-500 selection:text-white">

  <!-- Top Navigation Header -->
  <header class="border-b border-slate-800 bg-slate-900/90 backdrop-blur sticky top-0 z-50">
    <div class="max-w-6xl mx-auto px-6 py-3.5 flex items-center justify-between">
      <div class="flex items-center gap-3">
        <div class="h-9 w-9 rounded-xl bg-gradient-to-tr from-indigo-500 to-purple-600 flex items-center justify-center font-bold text-white shadow-lg shadow-indigo-500/25">
          ⚡
        </div>
        <div>
          <span class="font-bold text-base tracking-tight text-white">Visual Plan & Artifact Viewer</span>
          <span class="text-xs text-indigo-400 font-mono ml-2 px-2 py-0.5 rounded bg-indigo-950/80 border border-indigo-800">Oracliom Ecosystem</span>
        </div>
      </div>
      <div class="flex items-center gap-3">
        <span class="text-xs text-slate-400 font-mono">{file_name}</span>
        <button onclick="window.print()" class="px-3 py-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-200 transition text-xs font-medium border border-slate-700">
          Print / PDF
        </button>
      </div>
    </div>
  </header>

  <!-- Main Container -->
  <main class="max-w-5xl mx-auto px-6 py-10">
    <div id="content" class="prose prose-invert max-w-none">
      <!-- Rendered Markdown goes here -->
    </div>
  </main>

  <script>
    mermaid.initialize({{
      startOnLoad: false,
      theme: 'dark',
      themeVariables: {{
        darkMode: true,
        background: '#0b1120',
        primaryColor: '#6366f1',
        primaryTextColor: '#ffffff',
        primaryBorderColor: '#4f46e5',
        lineColor: '#94a3b8',
        secondaryColor: '#3b82f6',
        tertiaryColor: '#1e293b'
      }}
    }});

    const rawMarkdown = {raw_markdown_json};

    const renderer = new marked.Renderer();
    const originalCode = renderer.code.bind(renderer);

    renderer.code = function(code, language) {{
      if (typeof code === 'object') {{
        language = code.lang;
        code = code.text;
      }}
      if (language === 'mermaid') {{
        return '<div class="mermaid-box"><pre class="mermaid">' + code + '</pre></div>';
      }}
      return originalCode(code, language);
    }};

    marked.setOptions({{
      renderer: renderer,
      gfm: true,
      breaks: false
    }});

    document.getElementById('content').innerHTML = marked.parse(rawMarkdown);

    window.addEventListener('DOMContentLoaded', async () => {{
      await mermaid.run();
    }});
  </script>
</body>
</html>
"""

def render_markdown_to_html(md_path: Path, output_html: Path | None = None) -> Path:
    if not md_path.exists():
        raise FileNotFoundError(f"Markdown file not found: {md_path}")

    content = md_path.read_text(encoding="utf-8")
    title = md_path.stem.replace("-", " ").replace("_", " ").title()

    if output_html is None:
        output_html = md_path.with_suffix(".html")

    html_content = HTML_TEMPLATE.format(
        title=title,
        file_name=md_path.name,
        raw_markdown_json=json.dumps(content)
    )

    output_html.write_text(html_content, encoding="utf-8")
    return output_html

def open_in_browser(html_path: Path, browser_name: str | None = None):
    abs_path = html_path.resolve()
    file_url = abs_path.as_uri()

    chrome_path = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
    firefox_path = r"C:\Program Files\Mozilla Firefox\firefox.exe"

    if browser_name == "chrome" and os.path.exists(chrome_path):
        import subprocess
        subprocess.Popen([chrome_path, str(abs_path)])
        return
    elif browser_name == "firefox" and os.path.exists(firefox_path):
        import subprocess
        subprocess.Popen([firefox_path, str(abs_path)])
        return

    if os.name == "nt":
        os.startfile(str(abs_path))
    else:
        webbrowser.open(file_url)

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python open-artifact.py <path_to_markdown.md> [chrome|firefox]")
        sys.exit(1)

    md_file = Path(sys.argv[1])
    browser_pref = sys.argv[2] if len(sys.argv) > 2 else "chrome"

    out_html = render_markdown_to_html(md_file)
    print(f"Rendered HTML: {out_html}")
    open_in_browser(out_html, browser_pref)
    print(f"Opened {out_html.name} in {browser_pref or 'default browser'}.")
