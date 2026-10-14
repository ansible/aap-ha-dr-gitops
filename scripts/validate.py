#!/usr/bin/env python3
"""Validate customer inputs without cluster access."""
import argparse
import sys
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools" / "hadr_inventory"))
from inventory import InventoryError, load_inventory

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("deployment", nargs="?", default="examples/aws-rosa-pair")
    parser.add_argument("--deploy", action="store_true", help="also reject synthetic example values")
    args = parser.parse_args()
    try:
        load_inventory(args.deployment, deploy=args.deploy)
    except (InventoryError, TypeError, KeyError) as exc:
        print(f"INVALID: {exc}", file=sys.stderr)
        sys.exit(1)
    print("PASS: customer inventory" + (" (deployment inputs)" if args.deploy else " (synthetic values allowed)"))
