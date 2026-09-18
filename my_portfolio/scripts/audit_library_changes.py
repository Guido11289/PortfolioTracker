"""Vergelijkt de LOKAAL GEÏNSTALLEERDE degiro_portfolio (site-packages) met
de originele PyPI-release van diezelfde versie, en rapporteert precies wat
er is gewijzigd, toegevoegd of verwijderd.

Waarom dit script anders is dan audit_core_imports.py:
audit_core_imports.py kijkt naar `import`-statements in my_portfolio/ — dat
zegt iets over afhankelijkheden, NIET over of iemand handmatig in de
site-packages-kopie van de library heeft zitten editen. Dit script doet
dat laatste: een echte diff tegen de "pristine" (ongewijzigde) versie
zoals die op PyPI staat.

Werkwijze:
  1. Vind de lokaal geïmporteerde `degiro_portfolio` (locatie + versie).
  2. Download exact diezelfde versie als wheel van PyPI naar een tijdelijke
     map (`pip download ... --no-deps`, geen install, geen dependencies).
  3. Pak de wheel uit (het is een zip-bestand, stdlib zipfile volstaat).
  4. Diff elk bestand: tekstbestanden krijgen een unified diff, binaire
     bestanden (afbeeldingen) alleen een hash-vergelijking.
  5. Rapporteer: gewijzigde bestanden (met diff), bestanden die lokaal
     bestaan maar niet in de PyPI-release (toegevoegd), en andersom
     (verwijderd).

Gebruik:
    python -m my_portfolio.scripts.audit_library_changes
    python -m my_portfolio.scripts.audit_library_changes --out docs/LIBRARY_CHANGES.md
    python -m my_portfolio.scripts.audit_library_changes --package-dir /pad/naar/.venv/Lib/site-packages/degiro_portfolio

Vereist netwerktoegang naar pypi.org / files.pythonhosted.org (dezelfde
index als een normale `pip install`).
"""
import argparse
import difflib
import importlib.metadata
import importlib.util
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

PACKAGE_NAME = "degiro_portfolio"
# Extensies die we als tekst behandelen (unified diff); alles daarbuiten
# krijgt alleen een hash-vergelijking (binaire bestanden zoals .png).
_TEXT_EXTENSIONS = {".py", ".html", ".css", ".js", ".txt", ".md", ".cfg", ".ini", ".toml"}


def _find_local_package(explicit_dir: str | None) -> Path:
    """Locatie van de lokaal geïnstalleerde degiro_portfolio-map."""
    if explicit_dir:
        p = Path(explicit_dir).resolve()
        if not p.is_dir():
            sys.exit(f"FOUT: {p} bestaat niet of is geen map.")
        return p

    spec = importlib.util.find_spec(PACKAGE_NAME)
    if spec is None or not spec.submodule_search_locations:
        sys.exit(
            f"FOUT: kon '{PACKAGE_NAME}' niet vinden in de huidige Python-omgeving. "
            f"Draai dit script met dezelfde interpreter/venv als je app "
            f"(bv. `python -m my_portfolio.scripts.audit_library_changes`), "
            f"of geef --package-dir expliciet op."
        )
    return Path(list(spec.submodule_search_locations)[0]).resolve()


def _version_from_sibling_dist_info(package_dir: Path) -> str | None:
    """Fallback als importlib.metadata niks vindt (bv. omdat --package-dir
    buiten sys.path ligt): zoek een *.dist-info/METADATA-map naast de
    package-map zelf en lees de Version-regel eruit. Dit is hoe pip een
    normale install altijd neerzet, dus werkt voor elke site-packages-map."""
    for candidate in package_dir.parent.glob(f"{PACKAGE_NAME}-*.dist-info"):
        metadata_file = candidate / "METADATA"
        if metadata_file.is_file():
            for line in metadata_file.read_text(encoding="utf-8", errors="replace").splitlines():
                if line.startswith("Version:"):
                    return line.split(":", 1)[1].strip()
    return None


def _local_version(package_dir: Path) -> str:
    try:
        return importlib.metadata.version(PACKAGE_NAME)
    except importlib.metadata.PackageNotFoundError:
        pass

    fallback = _version_from_sibling_dist_info(package_dir)
    if fallback:
        return fallback

    sys.exit(
        f"FOUT: kon de versie van '{PACKAGE_NAME}' niet bepalen (niet via "
        f"importlib.metadata, en geen *.dist-info naast {package_dir} "
        f"gevonden). Geef de versie expliciet op met --version."
    )


def _download_pristine_wheel(version: str, dest_dir: Path) -> Path:
    """Download de exacte PyPI-wheel voor `version` naar dest_dir, geeft
    het pad naar het .whl-bestand terug. Faalt hard met een duidelijke
    melding als de versie niet bestaat of er geen netwerk is — we willen
    nooit stilzwijgend tegen de verkeerde versie diffen."""
    cmd = [
        sys.executable, "-m", "pip", "download",
        f"{PACKAGE_NAME}=={version}",
        "--no-deps", "--only-binary=:all:",
        "-d", str(dest_dir),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        sys.exit(
            f"FOUT: kon {PACKAGE_NAME}=={version} niet downloaden van PyPI.\n"
            f"--- pip download stderr ---\n{result.stderr}\n"
            f"Check je netwerkverbinding, of dat versie {version} echt op "
            f"PyPI staat (bv. een lokale/dev-versie is dat soms niet)."
        )
    wheels = list(dest_dir.glob("*.whl"))
    if not wheels:
        sys.exit(f"FOUT: download leek te slagen maar er staat geen .whl in {dest_dir}.")
    return wheels[0]


def _extract_wheel(wheel_path: Path, extract_to: Path) -> Path:
    with zipfile.ZipFile(wheel_path) as zf:
        zf.extractall(extract_to)
    pkg_dir = extract_to / PACKAGE_NAME
    if not pkg_dir.is_dir():
        sys.exit(f"FOUT: verwachte map {pkg_dir} niet gevonden na uitpakken van de wheel.")
    return pkg_dir


def _sha256(path: Path) -> str:
    import hashlib
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()


def diff_directories(local_dir: Path, pristine_dir: Path) -> dict:
    """Geeft {"modified": [...], "added_locally": [...], "removed_locally": [...]}
    terug. 'added_locally' = bestand bestaat lokaal maar niet in de
    PyPI-release (bv. mijn_hack.py); 'removed_locally' = andersom."""
    def _relevant_files(root: Path):
        # __pycache__ en .pyc/.pyo zijn runtime-artefacten die vanzelf
        # ontstaan bij importeren, geen handmatige wijziging — negeren,
        # anders verdrinkt elke echte wijziging in ruis.
        for p in root.rglob("*"):
            if not p.is_file():
                continue
            if "__pycache__" in p.parts or p.suffix in (".pyc", ".pyo"):
                continue
            yield p.relative_to(root)

    local_files = set(_relevant_files(local_dir))
    pristine_files = set(_relevant_files(pristine_dir))

    added_locally = sorted(local_files - pristine_files)
    removed_locally = sorted(pristine_files - local_files)
    common = sorted(local_files & pristine_files)

    modified = []
    for rel in common:
        local_path = local_dir / rel
        pristine_path = pristine_dir / rel
        if _sha256(local_path) == _sha256(pristine_path):
            continue

        entry = {"path": rel}
        if rel.suffix in _TEXT_EXTENSIONS:
            try:
                local_lines = local_path.read_text(encoding="utf-8", errors="replace").splitlines()
                pristine_lines = pristine_path.read_text(encoding="utf-8", errors="replace").splitlines()
                entry["diff"] = "\n".join(difflib.unified_diff(
                    pristine_lines, local_lines,
                    fromfile=f"pypi/{rel}", tofile=f"lokaal/{rel}", lineterm="",
                ))
            except UnicodeDecodeError:
                entry["diff"] = None  # binair ondanks de extensie
        else:
            entry["diff"] = None
        modified.append(entry)

    return {"modified": modified, "added_locally": added_locally, "removed_locally": removed_locally}


def render_markdown(result: dict, version: str, local_dir: Path) -> str:
    lines = [
        "# Lokale wijzigingen t.o.v. de PyPI-release",
        "",
        f"Vergelijking van `{local_dir}` tegen `{PACKAGE_NAME}=={version}` "
        f"zoals gepubliceerd op PyPI. Gegenereerd door "
        f"`python -m my_portfolio.scripts.audit_library_changes`.",
        "",
    ]

    if not result["modified"] and not result["added_locally"] and not result["removed_locally"]:
        lines.append("**Geen verschillen gevonden.** De lokale installatie is identiek aan de PyPI-release.")
        return "\n".join(lines)

    lines.append(
        "⚠️ Dit betekent dat de geïnstalleerde library lokaal is aangepast — "
        "in strijd met het architectuurprincipe dat de core-library nooit "
        "wordt gewijzigd. Elke wijziging hieronder verdwijnt bij de "
        "volgende `pip install --upgrade` en moet dus ofwel teruggeport "
        "worden naar `my_portfolio/`, ofwel bewust losgelaten worden."
    )
    lines.append("")

    if result["modified"]:
        lines.append(f"## Gewijzigde bestanden ({len(result['modified'])})")
        lines.append("")
        for entry in result["modified"]:
            lines.append(f"### `{entry['path']}`")
            lines.append("")
            if entry["diff"]:
                lines.append("```diff")
                lines.append(entry["diff"].rstrip("\n"))
                lines.append("```")
            else:
                lines.append("*(binair bestand, geen tekst-diff — hashes verschillen)*")
            lines.append("")

    if result["added_locally"]:
        lines.append(f"## Lokaal toegevoegde bestanden ({len(result['added_locally'])})")
        lines.append("")
        lines.append("Bestaan in de geïnstalleerde map maar niet in de PyPI-release:")
        lines.append("")
        for rel in result["added_locally"]:
            lines.append(f"- `{rel}`")
        lines.append("")

    if result["removed_locally"]:
        lines.append(f"## Lokaal verwijderde bestanden ({len(result['removed_locally'])})")
        lines.append("")
        lines.append("Bestaan in de PyPI-release maar ontbreken lokaal:")
        lines.append("")
        for rel in result["removed_locally"]:
            lines.append(f"- `{rel}`")
        lines.append("")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--package-dir", default=None, help="Pad naar de lokale degiro_portfolio-map (default: auto-detect via import)")
    parser.add_argument("--version", default=None, help="Versie om tegen te diffen (default: geïnstalleerde versie)")
    parser.add_argument("--out", default=None, help="Schrijf naar dit pad i.p.v. stdout")
    args = parser.parse_args()

    local_dir = _find_local_package(args.package_dir)
    version = args.version or _local_version(local_dir)
    print(f"Lokale map: {local_dir}", file=sys.stderr)
    print(f"Vergelijken met PyPI-versie: {version}", file=sys.stderr)

    with tempfile.TemporaryDirectory(prefix="degiro_portfolio_pristine_") as tmp:
        tmp_path = Path(tmp)
        wheel = _download_pristine_wheel(version, tmp_path)
        pristine_dir = _extract_wheel(wheel, tmp_path / "extracted")
        result = diff_directories(local_dir, pristine_dir)

    md = render_markdown(result, version, local_dir)

    if args.out:
        Path(args.out).write_text(md, encoding="utf-8")
        print(f"Geschreven naar {args.out}", file=sys.stderr)
    else:
        print(md)

    n_changes = len(result["modified"]) + len(result["added_locally"]) + len(result["removed_locally"])
    sys.exit(1 if n_changes else 0)


if __name__ == "__main__":
    main()
