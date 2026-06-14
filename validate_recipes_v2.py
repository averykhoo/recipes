# validate_recipes.py
"""
Local orchestrator and pipeline script. Runs the recursive parser on all folders,
generates validation warning audits, and serializes the structured results to JSON.
"""

import json
import logging
from pathlib import Path

from recipe_parser.core.orchestrator import process_recipe_document

# Target folders to scan and evaluate
RECIPE_FOLDERS = [
    Path("recipes"),
    Path("in-progress"),
    Path("curated-untested"),
]

# Output path to store serialised recipe structures
OUTPUT_DIRECTORY = Path("temp_parsed")


def run_pipeline():
    print("🚀 Initiating Recipe Schema Validation Suite...")

    files_evaluated = 0
    files_with_warnings = 0
    total_recipe_blocks = 0

    OUTPUT_DIRECTORY.mkdir(parents=True, exist_ok=True)

    for folder in RECIPE_FOLDERS:
        if not folder.exists():
            continue

        print(f"\nScanning Folder: {folder}/")
        for md_file in folder.glob("**/*.[mM][dD]"):
            if md_file.name == "index.md":
                continue

            files_evaluated += 1
            relative_filepath = md_file.relative_to(folder.parent) if folder.parent else md_file

            try:
                document, warning_messages = process_recipe_document(md_file)
            except Exception as process_error:
                logging.exception(f"  ❌ File: {relative_filepath} - Processing Error: {process_error}")
                continue

            total_recipe_blocks += len(document.recipes)

            if warning_messages:
                files_with_warnings += 1
                print(f"  📄 File: {relative_filepath} ({len(document.recipes)} block(s) detected)")
                for message in warning_messages:
                    print(f"       └─ ⚠️  {message}")

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

    print("\n📊 --- Pipeline Audit Summary ---")
    print(f"Total recipe folders scanned   : {len([f for f in RECIPE_FOLDERS if f.exists()])}")
    print(f"Total files analyzed           : {files_evaluated}")
    print(f"Total standalone recipe blocks : {total_recipe_blocks}")
    print(f"Files flagged with warnings    : {files_with_warnings} "
          f"({(files_with_warnings / max(1, files_evaluated) * 100):.1f}%)")
    print(f"Files fully conforming         : {files_evaluated - files_with_warnings}")
    print(f"📁 Structured outputs successfully exported to path: '{OUTPUT_DIRECTORY}/'")


if __name__ == "__main__":
    run_pipeline()
