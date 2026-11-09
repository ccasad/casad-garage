"""Build app/static/css/app.css from input.css with the Tailwind standalone CLI.

    uv run python scripts/build_css.py           # one-off minified build
    uv run python scripts/build_css.py --watch   # rebuild on template changes

The built app.css is committed so Vercel deploys it as-is, with no build step.
"""

import sys
from pathlib import Path

import pytailwindcss

TAILWIND_VERSION = "v4.3.4"
ROOT = Path(__file__).resolve().parent.parent
CSS_DIR = ROOT / "app" / "static" / "css"


def main() -> None:
    args = ["-i", str(CSS_DIR / "input.css"), "-o", str(CSS_DIR / "app.css")]
    args.append("--watch" if "--watch" in sys.argv[1:] else "--minify")
    result = pytailwindcss.run(
        args, cwd=ROOT, live_output=True, auto_install=True, version=TAILWIND_VERSION
    )
    sys.exit(result.returncode)


if __name__ == "__main__":
    main()
