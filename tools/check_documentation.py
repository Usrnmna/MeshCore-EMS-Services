"""Check maintained documentation against source command contracts without network access."""

from __future__ import annotations

import ast
import json
from pathlib import Path
import re
import subprocess
from urllib.parse import unquote, urlsplit
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
PACKAGES = ("meshcore_mqtt_service", "meshcore_mqtt_service_windows")


def git(*arguments, input_bytes=None):
    """Run a read-only Git query in the repository and return its captured bytes."""
    return subprocess.check_output(
        ["git", *arguments], cwd=ROOT, input=input_bytes, stderr=subprocess.PIPE
    )


def read_text(path):
    """Read UTF-8 or legacy CP1252 documentation without rewriting its encoding."""
    raw = path.read_bytes()
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = raw.decode("cp1252")
    return text.replace("\r\n", "\n")


def maintained_paths():
    """Include tracked and new publishable files, excluding deleted paths and local outputs."""
    names = git("ls-files", "--cached", "--others", "--exclude-standard", "-z")
    return sorted(
        {ROOT / name for name in names.decode("utf-8").split("\0") if name and (ROOT / name).is_file()},
        key=str,
    )


def prose(text):
    """Remove fenced examples before interpreting Markdown links or heading anchors."""
    lines = []
    fence = None
    for line in text.splitlines():
        marker = re.match(r"^\s*(`{3,}|~{3,})", line)
        if marker:
            if fence is None:
                fence = marker[1][0], len(marker[1])
            elif marker[1][0] == fence[0] and len(marker[1]) >= fence[1]:
                fence = None
            continue
        if fence is None:
            lines.append(line)
    if fence is not None:
        raise ValueError("Unclosed Markdown code fence")
    return "\n".join(lines)


def anchors(text):
    """Collect explicit HTML anchors and duplicate-aware GitHub-style heading IDs."""
    text = prose(text)
    result = set(re.findall(r'<a\s+(?:id|name)=["\x27]([^"\x27]+)', text))
    counts = {}
    for line in text.splitlines():
        heading = re.match(r"^#{1,6}\s+(.+?)\s*#*$", line)
        if heading:
            label = re.sub(r"<[^>]*>", "", heading[1]).lower()
            label = re.sub(r"[^\w\-\s]", "", label)
            label = re.sub(r"\s", "-", label)
            suffix = counts.get(label, 0)
            counts[label] = suffix + 1
            result.add(label if suffix == 0 else f"{label}-{suffix}")
    return result


def source_constant(path, name):
    """Read a literal published vocabulary without importing application or provider code."""
    for node in ast.parse(read_text(path)).body:
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == name for target in node.targets
        ):
            return ast.literal_eval(node.value)
    raise ValueError(f"Missing literal {name} in {path.relative_to(ROOT)}")


def check_commands():
    """Check registered command programs, subcommand vocabulary, paired guides, and badges."""
    mappings = []
    for package in PACKAGES:
        base = ROOT / package
        commands = json.loads((base / "config.json").read_bytes())["responder"]["commands"]
        mappings.append(commands)
        reference = read_text(base / "COMMAND_REFERENCE.md")
        listed = set(re.findall(r"\|\s*\[(![a-z]+)\]\(#cmd-[a-z]+\)", reference))
        if listed != set(commands):
            raise ValueError(f"{package}: command index differs from config.json")
        programs = [spec["script"] for spec in commands.values()]
        if len(programs) != len(set(programs)):
            raise ValueError(f"{package}: several commands share an executable program")
        for command, spec in commands.items():
            program = base / spec["script"]
            if program.parent != base / "scripts" or not program.is_file():
                raise ValueError(f"{package}: missing dedicated program for {command}")
            if f'\n## {command}' not in reference:
                raise ValueError(f"{package}: missing explanation for {command}")
        fields = source_constant(base / "scripts/gis_data.py", "SUBCOMMANDS")
        for kind, words in fields.items():
            row = re.search(rf"\| `!{kind}` \| ([^\n]+)", reference)
            if not row or any(f"`{word}`" not in row[1] for word in words):
                raise ValueError(f"{package}: incomplete {kind} subcommand index")
        categories = source_constant(base / "scripts/wildfire_settings.py", "CONTEXT_NAMES")
        if any(f"`{category}`" not in reference for category in categories):
            raise ValueError(f"{package}: incomplete firedata category index")
        for command, controls in {
            "floodalarm": ("conditions LOCATION", "status", "stop", "help"),
            "firealarm": ("on ZONE", "on LOCATION", "status", "off", "help"),
            "slidealarm": ("on LOCATION", "status", "off", "help"),
        }.items():
            row = re.search(rf"\| `!{command}` \| ([^\n]+)", reference)
            if not row or any(f"`{word}`" not in row[1] for word in controls):
                raise ValueError(f"{package}: incomplete {command} controls")
    if mappings[0] != mappings[1]:
        raise ValueError("Paired command configurations differ")
    for name in (
        "COMMAND_REFERENCE.md", "BOT_USER_GUIDE.md", "MULTI_CHANNEL_GUIDE.md",
        "WATER_GUIDE.md", "WATER_STATION_REVIEW.md", "WILDFIRE_GUIDE.md", "LANDSLIDE_GUIDE.md",
        "WATER_FUNCTION_REFERENCE.md", "WILDFIRE_FUNCTION_REFERENCE.md",
        "RESPONSE_FORMATTING.md", "RESPONSE_EXAMPLES.md",
    ):
        if (ROOT / PACKAGES[0] / name).read_bytes() != (ROOT / PACKAGES[1] / name).read_bytes():
            raise ValueError(f"Paired documentation differs: {name}")
    count = len(mappings[0])
    for name in ("README.md", *(f"{p}/COMMAND_REFERENCE.md" for p in PACKAGES)):
        if not re.search(rf"\b{count} (?:shipped |registered )?commands\b", read_text(ROOT / name)):
            raise ValueError(f"Stale command count: {name}")
    badge = read_text(ROOT / "docs/assets/commands-badge.svg")
    if not re.search(rf">{count}</text>", badge):
        raise ValueError("Command-count badge is stale")
    if f"{count} commands" not in read_text(ROOT / "docs/assets/readme-hero.svg"):
        raise ValueError("README banner command count is stale")
    version = source_constant(ROOT / "tools/build_installers.py", "VERSION")
    if version not in read_text(ROOT / "docs/assets/version-badge.svg"):
        raise ValueError("Distribution-version badge is stale")
    for path in (ROOT / "docs/assets").glob("*.svg"):
        ET.parse(path)
    return count



def check_response_examples():
    """Check tagged byte counts and executable vocabulary coverage in both example catalogs."""
    total = 0
    for package in PACKAGES:
        base = ROOT / package
        text = read_text(base / "RESPONSE_EXAMPLES.md")
        examples = re.findall(
            r"^### (![a-z]+[^\n]*)\n\n(\d+) UTF-8 bytes\.\n\n```text\n([^\n]+)\n```",
            text, re.M,
        )
        commands = json.loads((base / "config.json").read_bytes())["responder"]["commands"]
        headings = [heading for heading, _, _ in examples]
        if {heading.split()[0] for heading in headings} != set(commands):
            raise ValueError(f"{package}: response examples do not cover every command")
        for heading, byte_count, reply in examples:
            size = len(reply.encode("utf-8"))
            if not reply.startswith("@Alice ") or size != int(byte_count) or size > 150:
                raise ValueError(f"{package}: invalid tagged response example: {heading}")
        fields = source_constant(base / "scripts/gis_data.py", "SUBCOMMANDS")
        for kind, words in fields.items():
            for word in words:
                if not any(heading.startswith(f"!{kind} ") and word in heading.split()[1:]
                           for heading in headings):
                    raise ValueError(f"{package}: missing response for {kind} {word}")
        categories = source_constant(base / "scripts/wildfire_settings.py", "CONTEXT_NAMES")
        for category in categories:
            if not any(heading.startswith(f"!firedata {category} ") for heading in headings):
                raise ValueError(f"{package}: missing firedata response for {category}")
        for command, controls in {
            "floodalarm": ("conditions", "status", "stop", "help"),
            "firealarm": ("on", "status", "off", "help"),
            "slidealarm": ("on", "status", "off", "help"),
        }.items():
            for control in controls:
                if not any(heading == f"!{command} {control}" or
                           heading.startswith(f"!{command} {control} ") for heading in headings):
                    raise ValueError(f"{package}: missing {command} {control} response")
        total += len(examples)
    return total


def function_definitions(node, prefix=""):
    """Yield qualified function names and definitions, including methods and nested callbacks."""
    for child in ast.iter_child_nodes(node):
        if isinstance(child, ast.ClassDef):
            yield from function_definitions(child, prefix + child.name + ".")
        elif isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
            name = prefix + child.name
            yield name, child
            yield from function_definitions(child, name + ".")
        else:
            yield from function_definitions(child, prefix)


def check_function_references():
    """Compare focused water/wildfire signatures with the current source definitions."""
    count = 0
    for package in PACKAGES:
        base = ROOT / package
        for name in ("WATER_FUNCTION_REFERENCE.md", "WILDFIRE_FUNCTION_REFERENCE.md"):
            reference = read_text(base / name)
            sections = re.findall(r"^## ([^\n]+\.py)\n(.*?)(?=^## |\Z)", reference, re.M | re.S)
            documented = {module for module, _ in sections}
            pattern = "water*.py" if name.startswith("WATER_") else "wildfire_*.py"
            required = {p.relative_to(base).as_posix() for p in (base / "scripts").glob(pattern)}
            if not required <= documented:
                raise ValueError(f"Missing focused module reference: {required - documented}")
            for module, section in sections:
                tree = ast.parse(read_text(base / module))
                for qualified, node in function_definitions(tree):
                    signature = ("async " if isinstance(node, ast.AsyncFunctionDef) else "")
                    signature += qualified + "(" + ast.unparse(node.args) + ")"
                    if node.returns:
                        signature += " -> " + ast.unparse(node.returns)
                    if "`" + signature.replace("|", "\\|") + "`" not in section:
                        raise ValueError(f"Missing/stale function reference: {package}/{module}: {qualified}")
                    count += 1
    return count


def check_links(paths):
    """Check local paths/fragments; recognize explicitly ignored generated water outputs."""
    documents = [p for p in paths if p.is_file() and p.suffix == ".md" and "dist" not in p.parts]
    pending = []
    for path in documents:
        for match in re.finditer(r"\]\(([^\n)]+)\)", prose(read_text(path))):
            target = match[1].strip().strip("<>")
            if urlsplit(target).scheme:
                continue
            filename, _, fragment = target.partition("#")
            destination = (path.parent / unquote(filename)).resolve() if filename else path
            if not destination.is_relative_to(ROOT):
                raise ValueError(f"Link escapes workspace: {path.relative_to(ROOT)} -> {target}")
            pending.append((path, target, destination, unquote(fragment)))
    candidates = sorted({dest.relative_to(ROOT).as_posix() for _, _, dest, _ in pending})
    # Git check-ignore returns 1 when no candidates match; that is a valid result.
    result = subprocess.run(
        ["git", "check-ignore", "--no-index", "-z", "--stdin"], cwd=ROOT,
        input=("\0".join(candidates) + "\0").encode("utf-8"), capture_output=True,
    )
    if result.returncode not in (0, 1):
        raise ValueError(result.stderr.decode("utf-8", errors="replace"))
    ignored = set(result.stdout.decode("utf-8").rstrip("\0").split("\0"))
    generated = 0
    errors = []
    for path, target, dest, fragment in pending:
        relative = dest.relative_to(ROOT).as_posix()
        if relative in ignored and relative.startswith(
            ("data/basin_plans/", "data/flood_impacts/", "data/usgs_water/")
        ):
            generated += 1
            continue
        if not dest.exists():
            errors.append(f"Missing link: {path.relative_to(ROOT)} -> {target}")
        elif fragment and dest.suffix == ".md" and fragment not in anchors(read_text(dest)):
            errors.append(f"Missing anchor: {path.relative_to(ROOT)} -> {target}")
    if errors:
        raise ValueError("\n".join(errors))
    return len(documents), len(pending), generated


def check_cli_options(paths):
    """Require every literal argparse flag/subcommand from maintained entry points in the CLI guide."""
    guide = read_text(ROOT / "docs/CLI_REFERENCE.md")
    count = 0
    helpers = {"wildfire_lookup.py", "fire_environment.py", "gis_lookup.py"}
    for path in paths:
        if path.suffix != ".py" or path.name.startswith("test_") or "tests" in path.parts:
            continue
        source = read_text(path)
        if "__main__" not in source and path.name not in helpers:
            continue
        for node in ast.walk(ast.parse(source)):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                continue
            if node.func.attr not in ("add_argument", "add_parser"):
                continue
            for argument in node.args:
                if not isinstance(argument, ast.Constant) or not isinstance(argument.value, str):
                    continue
                token = argument.value
                if (token.startswith("--") or node.func.attr == "add_parser") and token not in guide:
                    raise ValueError(f"Undocumented CLI option: {path.relative_to(ROOT)} -> {token}")
                count += 1
    return count


def check_publication():
    """Keep generated/private files out of Git and retain required maintained sources."""
    excluded = git("ls-files", "-ci", "--exclude-standard").decode("utf-8").strip()
    if excluded:
        raise ValueError("Tracked files violate ignore policy:\n" + excluded)
    expected = {
        ".build/probe.log": True,
        "docs/superpowers/plans/example.md": True,
        "dist/unified-desktop/KIT.json": True,
        "MeshCore-EMS-Dataset-Manager.spec": True,
        "MeshCore-EMS-Service-Setup.spec": True,
        ".env": True,
        "meshcore_mqtt_service/runtime/water_index.sqlite3": True,
        "meshcore_mqtt_service_windows/runtime/water_current.sqlite3": True,
        "data/usgs_water/observations/current/readings.parquet": True,
        "data/basin_plans/snapshots/example/sources.json": True,
        "data/flood_impacts/static/example/manifest.json": True,
        "data/usgs_water/local_review_rules.json": False,
        "meshcore_mqtt_service/WATER_STATION_REVIEW.json": False,
        "meshcore_mqtt_service_windows/scripts/floodstatus.py": False,
        "docs/assets/readme-hero.svg": False,
        ".github/workflows/ci.yml": False,
        ".github/dependabot.yml": False,
        "installers/desktop/unified_backend.py": False,
        "installers/datasets/gui/main_window.ui": False,
        "tests/fixtures/authorization.log": False,
        "environment.json.example": False,
    }
    for path, should_ignore in expected.items():
        result = subprocess.run(["git", "check-ignore", "--no-index", "--quiet", path], cwd=ROOT)
        if result.returncode not in (0, 1) or (result.returncode == 0) != should_ignore:
            raise ValueError(f"Unexpected publication policy: {path}")


def main():
    """Run offline documentation gates and report checks separately from generated links."""
    try:
        commands = check_commands()
        responses = check_response_examples()
        signatures = check_function_references()
        paths = maintained_paths()
        documents, links, generated = check_links(paths)
        cli_inputs = check_cli_options(paths)
        check_publication()
    except (OSError, ValueError, KeyError, SyntaxError, subprocess.CalledProcessError) as exc:
        print(f"Documentation check failed: {exc}")
        return 1
    print(f"Verified {commands} commands and all indexed subcommand families in both packages.")
    print(f"Verified {responses} tagged response examples across the paired catalogs.")
    print(f"Checked {documents} Markdown files and {links} local links/fragments.")
    print(f"Checked {cli_inputs} literal argparse inputs against the terminal reference.")
    print(f"Verified {signatures} focused function signatures across the paired packages.")
    print(f"Recognized {generated} generated water-data destinations; run their setup steps to create them.")
    print("Verified badges, paired guides, and Git publication exclusions. No network calls performed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
