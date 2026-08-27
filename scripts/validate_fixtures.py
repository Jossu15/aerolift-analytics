"""
scripts/validate_fixtures.py
----------------------------
Scans tests/fixtures/ for JSON dataset files, runs bulk analysis on each,
and prints a validation report.  Run after adding new fixture files to
verify they work correctly with the liquid-loading engine.

Usage:
    python scripts/validate_fixtures.py
    python scripts/validate_fixtures.py --method coleman
    python scripts/validate_fixtures.py --export summary.json
"""
import argparse
import json
import os
import sys

# Ensure project root is on path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from math_engine.bulk_loader import bulk_analyze, results_to_csv


FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "..", "tests", "fixtures")


def discover_fixtures():
    """Find all JSON fixture files in tests/fixtures/."""
    fixtures = {}
    if not os.path.isdir(FIXTURES_DIR):
        return fixtures
    for fname in sorted(os.listdir(FIXTURES_DIR)):
        if fname.endswith(".json") and not fname.startswith("_"):
            path = os.path.join(FIXTURES_DIR, fname)
            try:
                with open(path) as f:
                    data = json.load(f)
                if isinstance(data, list) and len(data) > 0:
                    fixtures[fname] = data
            except (json.JSONDecodeError, IOError):
                pass
    return fixtures


def validate_fixture(name, wells, method="turner"):
    """Run bulk analysis on a fixture and return summary."""
    analysis = bulk_analyze(wells, method=method)
    return analysis["summary"]


def main():
    parser = argparse.ArgumentParser(
        description="Validate fixture datasets against liquid-loading models")
    parser.add_argument("--method", default="turner",
                        choices=["turner", "coleman"],
                        help="Loading method to validate (default: turner)")
    parser.add_argument("--export", default=None,
                        help="Export summary JSON to file")
    parser.add_argument("--csv", action="store_true",
                        help="Also export CSV for each fixture")
    args = parser.parse_args()

    fixtures = discover_fixtures()
    if not fixtures:
        print("No fixture files found in {}".format(FIXTURES_DIR))
        sys.exit(1)

    print("=" * 70)
    print("AeroLift Analytics - Fixture Validation Report")
    print("Method: {} | Fixtures: {}".format(args.method.upper(),
                                             len(fixtures)))
    print("=" * 70)

    all_summaries = {}
    all_pass = True

    for name, wells in fixtures.items():
        summary = validate_fixture(name, wells, method=args.method)
        all_summaries[name] = summary

        acc = summary["accuracy_pct"]
        acc_str = "{:.1f}%".format(acc) if acc is not None else "N/A"
        rec = summary["recall_pct"]
        rec_str = "{:.1f}%".format(rec) if rec is not None else "N/A"
        fp = summary["false_positive_pct"]
        fp_str = "{:.1f}%".format(fp) if fp is not None else "N/A"

        status = "OK" if (acc is not None and acc >= 50) else "WARN"
        if acc is not None and acc < 50:
            all_pass = False

        print("\n--- {} ---".format(name))
        print("  Parsed:    {} wells".format(summary["total_parsed"]))
        print("  Errors:    {}".format(summary["parse_errors"]))
        print("  Evaluable: {}".format(summary["evaluable"]))
        print("  Accuracy:  {} {}".format(acc_str, " " * 10))
        print("  Recall:    {}".format(rec_str))
        print("  F.positv:  {}".format(fp_str))
        print("  Loaded:    {} | Unloaded: {}".format(
            summary["loaded_count"], summary["unloaded_count"]))
        print("  Status:    [{}]".format(status))

        if args.csv:
            csv_path = os.path.join(FIXTURES_DIR,
                                    name.replace(".json", "_results.csv"))
            csv_data = results_to_json(
                bulk_analyze(wells, method=args.method))
            with open(csv_path.replace(".csv", ".json"), "w") as f:
                f.write(csv_data)
            print("  Exported:  {}".format(
                os.path.basename(csv_path.replace(".csv", ".json"))))

    print("\n" + "=" * 70)
    overall = "ALL PASS" if all_pass else "SOME WARNINGS"
    print("Overall: {}".format(overall))
    print("=" * 70)

    if args.export:
        with open(args.export, "w") as f:
            json.dump(all_summaries, f, indent=2, default=str)
        print("\nSummary exported to {}".format(args.export))


if __name__ == "__main__":
    main()
