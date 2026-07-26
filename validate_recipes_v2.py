# validate_recipes.py
"""
Local orchestrator and pipeline script. Runs the recursive parser on all folders,
generates validation diagnostics, and serializes the structured results to JSON.

Usage:
    python validate_recipes_v2.py                 # warnings and errors
    python validate_recipes_v2.py --verbose       # everything, including info notices
    python validate_recipes_v2.py --errors-only   # only things the parser could not read
    python validate_recipes_v2.py --code quantity-unparsed   # filter to one code
"""

import argparse
import json
import logging
import sys
from collections import Counter
from pathlib import Path

from recipe_parser.core.orchestrator import process_recipe_document
from recipe_parser.validation.diagnostics import Severity

# Target folders to scan and evaluate
RECIPE_FOLDERS = [
    Path("recipes"),
    Path("in-progress"),
    Path("curated-untested"),
]

# Output path to store serialised recipe structures
OUTPUT_DIRECTORY = Path("temp_parsed")

SEVERITY_ORDER = {Severity.ERROR: 0, Severity.WARNING: 1, Severity.INFO: 2}


def parse_arguments():
    parser = argparse.ArgumentParser(description="Validate and structure the recipe corpus.")
    parser.add_argument("--verbose", "-v", action="store_true",
                        help="Include INFO diagnostics (inferred sections, implicit counts, inferred yields).")
    parser.add_argument("--errors-only", "-e", action="store_true",
                        help="Show only ERROR diagnostics.")
    parser.add_argument("--code", action="append", default=[],
                        help="Only show diagnostics with this code. Repeatable.")
    parser.add_argument("--no-json", action="store_true",
                        help="Skip writing structured JSON output.")
    return parser.parse_args()


def should_display(diagnostic, args) -> bool:
    if args.code and diagnostic.code not in args.code:
        return False
    if args.errors_only:
        return diagnostic.severity == Severity.ERROR
    if diagnostic.severity == Severity.INFO and not args.verbose:
        return False
    return True


def run_pipeline(args):
    print("Recipe Schema Validation Suite")
    print("=" * 78)

    files_evaluated = 0
    files_with_findings = 0
    total_recipe_blocks = 0

    severity_totals = Counter()
    code_totals = Counter()
    suppressed = 0

    if not args.no_json:
        OUTPUT_DIRECTORY.mkdir(parents=True, exist_ok=True)

    for folder in RECIPE_FOLDERS:
        if not folder.exists():
            continue

        print(f"\nScanning: {folder}/")
        for md_file in sorted(folder.glob("**/*.[mM][dD]")):
            if md_file.name == "index.md":
                continue

            files_evaluated += 1
            relative_filepath = md_file.relative_to(folder.parent) if folder.parent else md_file

            try:
                document, diagnostics = process_recipe_document(md_file)
            except Exception as process_error:
                logging.exception(f"  FAILED: {relative_filepath} - {process_error}")
                continue

            total_recipe_blocks += len(document.recipes)

            for diagnostic in diagnostics:
                severity_totals[diagnostic.severity] += 1
                code_totals[diagnostic.code] += 1

            visible = [d for d in diagnostics if should_display(d, args)]
            suppressed += len(diagnostics) - len(visible)

            if visible:
                files_with_findings += 1
                visible.sort(key=lambda d: (SEVERITY_ORDER.get(d.severity, 9), d.code, d.line_number or 0))
                print(f"\n  {relative_filepath}  ({len(document.recipes)} recipe block(s))")
                for diagnostic in visible:
                    print(diagnostic.render())

            if args.no_json:
                continue

            # Export structured outputs to matching JSON destination paths
            export_filename = md_file.relative_to(folder).with_suffix(".json")
            export_path = OUTPUT_DIRECTORY / folder.name / export_filename
            export_path.parent.mkdir(parents=True, exist_ok=True)

            # Serialize model ensuring dual Pydantic compatibility
            if hasattr(document, "model_dump"):
                serialized_data = document.model_dump(by_alias=True)
            else:
                serialized_data = document.dict(by_alias=True)

            with export_path.open("w", encoding="utf-8") as json_file:
                json.dump(serialized_data, json_file, indent=2, ensure_ascii=False)

    print("\n" + "=" * 78)
    print("Audit Summary")
    print("=" * 78)
    print(f"  Files analyzed            : {files_evaluated}")
    print(f"  Recipe blocks parsed      : {total_recipe_blocks}")
    print(f"  Files with findings shown : {files_with_findings}")
    print(f"  Files clean               : {files_evaluated - files_with_findings}")

    print("\n  Diagnostics by severity:")
    for severity in (Severity.ERROR, Severity.WARNING, Severity.INFO):
        print(f"    {severity.value:8s} : {severity_totals.get(severity, 0)}")

    if code_totals:
        print("\n  Diagnostics by code:")
        for code, count in code_totals.most_common():
            print(f"    {count:5d}  {code}")

    if suppressed:
        print(f"\n  {suppressed} diagnostic(s) hidden by the current filters. Use --verbose to see all.")

    if not args.no_json:
        print(f"\n  Structured output written to '{OUTPUT_DIRECTORY}/'")

    # Non-zero exit when the parser could not read something it should have.
    return 1 if severity_totals.get(Severity.ERROR, 0) else 0


if __name__ == "__main__":
    # The console on Windows defaults to cp1252, which cannot encode the corpus.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.exit(run_pipeline(parse_arguments()))
