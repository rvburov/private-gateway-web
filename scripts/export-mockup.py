#!/usr/bin/env python3
"""Export the static review mockup as one offline HTML file (no dependencies).

The source mockup remains unchanged. Client boards share one resource bundle;
the source preview controller mounts one persistent offline client document.
"""
from __future__ import annotations

import argparse
import base64
import json
import mimetypes
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
MOCKUP = ROOT / "mockup"
CLIENT = MOCKUP / "client"


def data_uri(path: Path) -> str:
    mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    return f"data:{mime};base64," + base64.b64encode(path.read_bytes()).decode("ascii")


def local_file(base: Path, reference: str) -> Path:
    path = (base / reference).resolve()
    if not path.is_relative_to(MOCKUP.resolve()) or not path.is_file():
        raise ValueError(f"Missing or non-local mockup resource: {reference}")
    return path


def embed_css(path: Path) -> str:
    def replace(match: re.Match) -> str:
        reference = match.group(2).strip()
        if reference.startswith("data:"):
            return match.group(0)
        return 'url("' + data_uri(local_file(path.parent, reference)) + '")'
    return re.sub(r"url\(\s*(['\"]?)(.*?)\1\s*\)", replace, path.read_text())


def js_json(value: object) -> str:
    # Safe inside an HTML script element, including strings with HTML content.
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).replace("<", "\\u003c")


def script(source: str) -> str:
    source = re.sub(r"</script", r"<\\/script", source, flags=re.IGNORECASE)
    return "<script>\n" + source + "\n</script>"


def client_boards() -> tuple[dict, dict]:
    boards = {}
    resources = {}
    for path in sorted((CLIENT / "boards").glob("*.html")):
        source = path.read_text()
        body_match = re.search(r"<body[^>]*>(.*?)</body>", source, flags=re.S | re.I)
        if not body_match:
            raise ValueError(f"Missing body: {path}")
        body = body_match.group(1)
        for reference in re.findall(r'\bsrc=[\"\']([^\"\']+)[\"\']', body):
            # The source design-system board points to two raster logo sizes
            # outside docs/design/html. Use the identical local SVG shield.
            if reference in {
                "../../../../shared/specifications/icons/app.iconset/icon_16x16.png",
                "../../../../shared/specifications/icons/app.iconset/icon_32x32.png",
            }:
                resources.setdefault(reference, data_uri(MOCKUP / "assets/logo.svg"))
            else:
                resources.setdefault(reference, data_uri(local_file(path.parent, reference)))
        styles = "\n".join(re.findall(r"<style[^>]*>(.*?)</style>", source, flags=re.S | re.I))
        if "url(" in styles:
            raise ValueError(f"Unexpected board-local CSS resource: {path}")
        title = re.search(r"<title[^>]*>(.*?)</title>", source, flags=re.S | re.I)
        boards[path.name] = {"body": body, "style": styles, "title": title.group(1) if title else path.stem}
    if len(boards) != 26:
        raise ValueError(f"Expected 26 client boards, found {len(boards)}")
    # The IP mask button swaps the flag dynamically, outside board markup.
    resources["../assets/countries/UNKNOWN.png"] = data_uri(CLIENT / "assets/countries/UNKNOWN.png")

    return boards, resources


def inline_local_assets(html: str, base: Path, script_replacements: dict[str, str] | None = None) -> str:
    """Inline local assets in source order, preserving controller/startup order."""
    replacements = script_replacements or {}

    def stylesheet(match: re.Match) -> str:
        tag = match.group(0)
        href = re.search(r"\bhref\s*=\s*(['\"])(.*?)\1", tag, flags=re.I)
        if not href:
            raise ValueError("Stylesheet without a local href")
        return "<style>\n" + embed_css(local_file(base, href.group(2))) + "\n</style>"

    def javascript(match: re.Match) -> str:
        source = match.group(3)
        if source in replacements:
            return script(replacements[source])
        path = local_file(base, source)
        code = path.read_text().replace("assets/logo.svg", data_uri(MOCKUP / "assets/logo.svg"))
        return script(code)

    html = re.sub(r"<link\b[^>]*\brel\s*=\s*(['\"])stylesheet\1[^>]*>", stylesheet, html, flags=re.I)
    return re.sub(r"<script\b([^>]*)\bsrc\s*=\s*(['\"])(.*?)\2([^>]*)>\s*</script>", javascript, html, flags=re.I)


def offline_client_document() -> str:
    """Bundle the same persistent runtime used by the multi-file preview."""
    boards, resources = client_boards()
    globals_script = "window.PG_CLIENT_BOARDS=" + js_json(boards) + ";\nwindow.PG_CLIENT_RESOURCES=" + js_json(resources) + ";"
    runtime = (CLIENT / "runtime.html").read_text()
    return inline_local_assets(runtime, CLIENT, {"assets/runtime-boards.js": globals_script})


def export(output: Path) -> None:
    html = (MOCKUP / "index.html").read_text()
    logo = data_uri(MOCKUP / "assets/logo.svg")
    html = html.replace('href="assets/logo.svg"', 'href="' + logo + '"')
    html = inline_local_assets(html, MOCKUP)
    start = "<script>PG.start();</script>"
    if start not in html:
        raise ValueError("PG.start call changed; preserve script ordering before export")
    notices = {
        str(path.relative_to(MOCKUP)): path.read_text()
        for path in [
            MOCKUP / "assets/fonts/golos-LICENSE", MOCKUP / "assets/fonts/geologica-LICENSE",
            CLIENT / "assets/fonts/OFL-Inter.txt", CLIENT / "assets/fonts/OFL-JetBrainsMono.txt",
        ]
    }
    notices["Font Awesome Free 6.7.2 brand icons"] = (ROOT / "docs/FONT-AWESOME-LICENSE.txt").read_text()
    bootstrap = "window.PG_CLIENT_RUNTIME_SRCDOC=" + js_json(offline_client_document()) + ";"
    html = html.replace(start, script(bootstrap) + "\n" + start)
    head, tail = html.rsplit("</body>", 1)
    html = head + '<script type="application/json" id="bundled-asset-licenses">' + js_json(notices) + '</script>\n</body>' + tail
    # All legitimate assets are data URIs or srcdoc. Disallow future accidental
    # network calls while keeping the static browser demonstrations interactive.
    policy = "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src data:; font-src data:; frame-src 'self' about:; connect-src 'none'; base-uri 'none'; form-action 'none'"
    html = html.replace('<meta charset="utf-8">', '<meta charset="utf-8">\n  <meta http-equiv="Content-Security-Policy" content="' + policy + '">', 1)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(html)
    print(f"Exported {output} ({output.stat().st_size / 1024 / 1024:.2f} MiB); 26 client boards bundled")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("/workspace/artifacts/Private-Gateway-Web.html"))
    export(parser.parse_args().output)
