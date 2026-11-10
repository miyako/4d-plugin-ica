"""Selective physical cleanup and separate unsigned/final ICA bundle validation."""

import sys

sys.dont_write_bytecode = True

import argparse
from pathlib import Path
import subprocess

import native_policy as policy
import physical
import repository
import source_version


def preflight_cleanup(sha, root=Path(".")):
    selected = repository.selected_entries(sha, root)
    targets = [(path, "file") for path in sorted(policy.GENERATED_LEAVES)]
    targets += [(path, "directory") for path in policy.DIRECTORY_TARGETS]

    def allowed(path):
        if path in selected and path not in policy.GENERATED_LEAVES:
            raise ValueError(f"Cleanup would delete selected input: {path}")
        return policy.generated_file(path)

    plan = physical.cleanup_plan(
        root, targets, allowed_file=allowed, allowed_directory=policy.generated_directory,
    )
    repository.verify_checkout(sha, root=root)
    return plan


def cleanup(sha, root=Path(".")):
    physical.execute_cleanup(preflight_cleanup(sha, root))


def verify_bundle(sha, *, final=False, root=Path("."), assets=()):
    selected = repository.verify_checkout(sha, root=root, final=True, assets=assets)
    leaves = policy.PACKAGE_LEAVES if final else policy.PACKAGE_LEAVES - {policy.SIGNATURE}
    for leaf in sorted(leaves):
        physical.regular_file(root, leaf)
    for destination, source in policy.COPIED_RESOURCES.items():
        if (Path(root) / destination).read_bytes() != physical.regular_file(root, source).read_bytes():
            raise ValueError(f"Copied source resource differs: {destination}")
    for leaf in policy.PRESERVED_LEAVES:
        if repository.actual_blob(leaf, root) != selected[leaf]:
            raise ValueError(f"Selected prebuilt resource differs: {leaf}")
    source_version.verify_bundle(Path(root) / policy.BUNDLE, root)


def verify_architectures(sha):
    verify_bundle(sha)
    tokens = subprocess.check_output(["lipo", "-archs", policy.EXECUTABLE]).decode("ascii").split()
    if not {"arm64", "x86_64"}.issubset(tokens):
        raise ValueError("Universal binary requires exact arm64 and x86_64 architecture tokens")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("cleanup", "unsigned", "architectures", "final"))
    parser.add_argument("--sha", required=True)
    args = parser.parse_args(argv)
    if args.phase == "cleanup":
        cleanup(args.sha)
    elif args.phase == "architectures":
        verify_architectures(args.sha)
    else:
        verify_bundle(args.sha, final=args.phase == "final")


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, subprocess.CalledProcessError) as error:
        print(f"Native gate stopped: {error}", file=sys.stderr)
        sys.exit(1)
