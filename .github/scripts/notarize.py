"""Require successful Accepted JSON for both original assets, then staple and verify."""

import sys

sys.dont_write_bytecode = True

import argparse
from pathlib import Path
import subprocess

import native_policy
import physical
import publication
import source_version
import strict_json


def notarize(keychain):
    names = publication.asset_names(source_version.read())
    for name in names:
        physical.regular_file(Path("."), name)
        result = subprocess.run(
            ["xcrun", "notarytool", "submit", name, "--keychain-profile", "notarytool-profile",
             "--keychain", keychain, "--wait", "--output-format", "json"],
            check=True, stdout=subprocess.PIPE,
        )
        value = strict_json.loads(result.stdout)
        if not isinstance(value, dict) or value.get("status") != "Accepted":
            raise ValueError(f"Notarization was not Accepted: {name}")
    subprocess.run(["xcrun", "stapler", "staple", names[1]], check=True)
    subprocess.run(["xcrun", "stapler", "validate", names[1]], check=True)
    subprocess.run(
        ["codesign", "--verify", "--deep", "--strict", "--verbose=2", native_policy.BUNDLE],
        check=True,
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--keychain", required=True)
    args = parser.parse_args()
    try:
        notarize(args.keychain)
    except (ValueError, OSError, subprocess.CalledProcessError) as error:
        parser.exit(1, f"Notarization stopped: {error}\n")
