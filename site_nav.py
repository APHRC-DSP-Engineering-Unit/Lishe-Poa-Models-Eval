"""Shared top navigation for the generated site pages (site/*.html).

The nav is inlined into each page (not loaded from a separate file) so every
page still works when opened on its own, including from sandboxed browsers
that can only read the single file that was opened.
"""

PAGES = [
    ("index.html", "home", "Overview"),
    ("regex.html", "regex", "① Regex comparison"),
    ("llm-judge.html", "llm", "② LLM judge"),
    ("manual-review.html", "manual", "③ Manual review"),
]

NAV_CSS = """
.lp-nav { position: relative; z-index: 10; display: flex; align-items: center; gap: 4px; flex-wrap: wrap;
  padding: 8px 20px; background: #0b0b0b; color: #f0efec;
  font: 600 13.5px/1.2 system-ui, -apple-system, "Segoe UI", Roboto, sans-serif; }
.lp-nav .lp-brand { margin-right: 14px; font-weight: 700; letter-spacing: .2px; color: #f0efec; text-decoration: none; }
.lp-nav .lp-brand small { font-weight: 500; color: #a3a29b; margin-left: 6px; }
.lp-nav a.lp-link { color: #c3c2b7; text-decoration: none; padding: 7px 12px; border-radius: 6px; }
.lp-nav a.lp-link:hover { background: #262624; color: #fff; }
.lp-nav a.lp-link.active { background: #f0efec; color: #0b0b0b; }
"""


def nav_html(active: str) -> str:
    current = ' class="lp-link active" aria-current="page"'
    links = "".join(
        f'<a{current if key == active else " class=lp-link"} href="{href}">{label}</a>'
        for href, key, label in PAGES if key != "home"
    )
    return (f'<nav class="lp-nav" aria-label="Validation pages"><a class="lp-brand" href="index.html">'
            f'LishePoa<small>Product validation</small></a>{links}</nav>')


def inject(html: str, active: str) -> str:
    """Add the nav CSS before </head> and the nav bar right after <body>."""
    html = html.replace("</head>", f"<style>{NAV_CSS}</style>\n</head>", 1)
    return html.replace("<body>", "<body>\n" + nav_html(active), 1)
