"""Past patches/degiro_portfolio-<versie>.patch toe op de GEÏNSTALLEERDE
degiro_portfolio-library (site-packages van de actieve venv).

Draai dit één keer na `pip install -r requirements.txt` (en opnieuw na elke
herinstallatie/upgrade van degiro_portfolio):

    python -m my_portfolio.scripts.apply_library_patches            # toepassen
    python -m my_portfolio.scripts.apply_library_patches --check    # alleen controleren
    python -m my_portfolio.scripts.apply_library_patches --revert   # terugdraaien

Veiligheid:
  - Weigert te draaien als de geïnstalleerde versie niet exact de versie is
    waarvoor de patch gemaakt is (zie PATCH_VERSION).
  - Doet eerst `git apply --check`: alles-of-niets, nooit half toepassen.
  - Idempotent: al toegepast -> meldt dat en doet niets (exit 0).

Vereist `git` in PATH (het werkt buiten een repo; het is alleen de
patch-engine). Geen import van degiro_portfolio zelf, zodat dit ook werkt als
de library kapot-gepatcht is.
"""
import argparse
import importlib.metadata
import importlib.util
import os
import shutil
import subprocess
import sys
from pathlib import Path

PACKAGE_NAME = "degiro_portfolio"
PATCH_VERSION = "0.5.13"
PATCH_FILE = Path(__file__).resolve().parents[2] / "patches" / f"{PACKAGE_NAME}-{PATCH_VERSION}.patch"

# Inhoudelijke controle los van git: aanwezig na de patch, afwezig in de
# pristine release. Nodig omdat git apply niet ALTIJD faalt als het niets
# kan doen (zie _git_apply).
_SENTINEL_FILE = "ticker_resolver.py"
_SENTINEL_TEXT = "def resolve_crypto_ticker("


def _package_dir() -> Path:
    spec = importlib.util.find_spec(PACKAGE_NAME)
    if spec is None or not spec.submodule_search_locations:
        sys.exit(f"FOUT: '{PACKAGE_NAME}' niet gevonden in deze Python-omgeving. "
                 f"Is de venv geactiveerd en `pip install -r requirements.txt` gedraaid?")
    return Path(list(spec.submodule_search_locations)[0]).resolve()


def _git_apply(args: list[str], cwd: Path) -> subprocess.CompletedProcess:
    # -p1: patchpaden zijn a/config.py, b/config.py. cwd = package-map.
    #
    # GIT_CEILING_DIRECTORIES: de venv staat vaak IN de projectrepo
    # (.venv/ in .gitignore). Binnen een repo behandelt `git apply` paden
    # als repo-relatief en slaat niet-gevolgde/genegeerde bestanden stil
    # over — `--check` slaagt dan zonder iets te controleren. Door git niet
    # omhoog te laten zoeken naar de projectrepo werkt het als gewone,
    # repo-loze patch-tool.
    env = {**os.environ, "GIT_CEILING_DIRECTORIES": str(cwd.parent)}
    return subprocess.run(
        ["git", "apply", "-p1", "--whitespace=nowarn", *args, str(PATCH_FILE)],
        cwd=cwd, capture_output=True, text=True, env=env,
    )


def _sentinel_present(pkg: Path) -> bool:
    return _SENTINEL_TEXT in (pkg / _SENTINEL_FILE).read_text(encoding="utf-8", errors="replace")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true", help="Alleen melden of de patch toegepast is / kan worden")
    mode.add_argument("--revert", action="store_true", help="Patch terugdraaien")
    args = parser.parse_args()

    if shutil.which("git") is None:
        sys.exit("FOUT: `git` niet gevonden in PATH (nodig als patch-engine).")
    if not PATCH_FILE.is_file():
        sys.exit(f"FOUT: patchbestand ontbreekt: {PATCH_FILE}")

    pkg = _package_dir()
    try:
        installed = importlib.metadata.version(PACKAGE_NAME)
    except importlib.metadata.PackageNotFoundError:
        installed = None
    if installed != PATCH_VERSION:
        sys.exit(f"FOUT: geïnstalleerd is {PACKAGE_NAME} {installed}, patch is voor {PATCH_VERSION}. "
                 f"Installeer exact die versie (`pip install -r requirements.txt`) of maak een nieuwe patch.")

    print(f"Library: {pkg}")

    already = _git_apply(["--reverse", "--check"], pkg).returncode == 0
    if already != _sentinel_present(pkg):
        sys.exit("FOUT: git en bestandsinhoud spreken elkaar tegen over of de patch is "
                 "toegepast (bibliotheek half gepatcht?). Niets gewijzigd. "
                 f"Tip: `pip install --force-reinstall --no-deps {PACKAGE_NAME}=={PATCH_VERSION}`.")
    can_apply = _git_apply(["--check"], pkg).returncode == 0

    if args.check:
        if already:
            print("Status: patch is TOEGEPAST.")
            sys.exit(0)
        print("Status: patch is NIET toegepast" + (" (kan schoon toegepast worden)." if can_apply else " en past ook niet schoon (library is afwijkend gewijzigd)."))
        sys.exit(1)

    if args.revert:
        if not already:
            sys.exit("Niets terug te draaien: patch is niet (volledig) toegepast.")
        r = _git_apply(["--reverse"], pkg)
        if r.returncode != 0:
            sys.exit(f"FOUT bij terugdraaien:\n{r.stderr}")
        if _sentinel_present(pkg):
            sys.exit("FOUT: git meldde succes maar de library is niet teruggedraaid.")
        print("Patch teruggedraaid.")
        return

    if already:
        print("Patch is al toegepast; niets gedaan.")
        return
    if not can_apply:
        r = _git_apply(["--check"], pkg)
        sys.exit("FOUT: patch past niet schoon op de geïnstalleerde library "
                 "(deels al aangepast, of een andere versie?). Niets gewijzigd.\n"
                 f"{r.stderr}\nTip: `pip install --force-reinstall --no-deps {PACKAGE_NAME}=={PATCH_VERSION}` "
                 f"en probeer opnieuw.")
    r = _git_apply([], pkg)
    if r.returncode != 0:
        sys.exit(f"FOUT bij toepassen:\n{r.stderr}")
    if not _sentinel_present(pkg):
        sys.exit("FOUT: git meldde succes maar de library is niet gepatcht "
                 "(verifieer handmatig met `python -m my_portfolio.scripts.audit_library_changes`).")
    print("Patch toegepast.")


if __name__ == "__main__":
    main()
