"""Create a new tag and public release only; leave partial failures for manual recovery."""

import sys

sys.dont_write_bytecode = True

import argparse
import json
import os
from pathlib import Path
import re
import subprocess
from urllib.parse import quote

import native
import physical
import repository
import source_version
import strict_json


CANONICAL = "miyako/4d-plugin-ica"
REPOSITORY_ID = 102801855
API = f"repos/{CANONICAL}"


def api(method, endpoint, payload=None, *, file=None, content_type=None):
    command = [
        "gh", "api", "--method", method,
        "--header", "Accept: application/vnd.github+json",
        "--header", "X-GitHub-Api-Version: 2022-11-28",
    ]
    data = None
    if file is not None:
        command += ["--header", f"Content-Type: {content_type}", "--input", str(file)]
    elif payload is not None:
        command += ["--input", "-"]
        data = json.dumps(payload, allow_nan=False).encode()
    command.append(endpoint)
    result = subprocess.run(command, input=data, check=True, stdout=subprocess.PIPE)
    return strict_json.loads(result.stdout)


def object_ref(value, expected_ref=None, expected_sha=None):
    if not isinstance(value, dict) or type(value.get("ref")) is not str \
            or not isinstance(value.get("object"), dict):
        raise ValueError("Malformed Git ref response")
    obj = value["object"]
    if obj.get("type") not in ("commit", "tag") or type(obj.get("sha")) is not str \
            or not re.fullmatch(r"[0-9a-f]{40}", obj["sha"]):
        raise ValueError("Malformed Git ref target")
    if expected_ref is not None and (
        value["ref"] != expected_ref or obj["sha"] != expected_sha or obj["type"] != "commit"
    ):
        raise ValueError("Created tag ref does not identify the selected commit")


def remote_tag(tag):
    return repository.run(
        "git", "ls-remote", "--tags", "--refs", "origin", f"refs/tags/{tag}",
    )


def availability(version):
    if os.environ.get("GITHUB_REPOSITORY") != CANONICAL:
        raise ValueError("GITHUB_REPOSITORY must equal API-canonical miyako/4d-plugin-ica")
    if not os.environ.get("GH_TOKEN", "").strip():
        raise ValueError("Explicit nonempty GH_TOKEN is required")
    repo = api("GET", API)
    if not isinstance(repo, dict) or type(repo.get("id")) is not int \
            or repo["id"] != REPOSITORY_ID or repo.get("full_name") != CANONICAL:
        raise ValueError("Authenticated canonical repository identity mismatch")
    tag = "v" + version
    prior = set()
    page = 1
    while True:
        releases = api("GET", f"{API}/releases?per_page=100&page={page}")
        if not isinstance(releases, list):
            raise ValueError("Release page is not an array")
        if not releases:
            break
        for release in releases:
            if not isinstance(release, dict) or not strict_json.positive_integer(release.get("id")) \
                    or type(release.get("tag_name")) is not str \
                    or type(release.get("draft")) is not bool \
                    or type(release.get("prerelease")) is not bool:
                raise ValueError("Malformed release inventory, including drafts")
            if release["id"] in prior:
                raise ValueError("Duplicate release ID across inventory")
            prior.add(release["id"])
            if release["tag_name"] == tag:
                raise ValueError(f"Release already exists for {tag}, including drafts")
        page += 1
    refs = api("GET", f"{API}/git/matching-refs/tags/{tag}")
    if not isinstance(refs, list):
        raise ValueError("Matching-ref inventory is not an array")
    seen_refs = set()
    for ref in refs:
        object_ref(ref)
        if not ref["ref"].startswith("refs/tags/" + tag) or ref["ref"] in seen_refs:
            raise ValueError("Malformed or duplicate matching-ref inventory")
        seen_refs.add(ref["ref"])
        repository.run("git", "check-ref-format", ref["ref"])
        if ref["ref"] == "refs/tags/" + tag:
            raise ValueError(f"Tag already exists: {tag}")
    if remote_tag(tag):
        raise ValueError(f"Advertised tag already exists: {tag}")
    return prior


def asset_names(version):
    return tuple(f"ImageCaptureCore-{version}.{suffix}" for suffix in ("zip", "dmg"))


def partial_state(sha):
    return {
        "version": None, "tag": None, "selected_sha": sha,
        "tag_attempted": False, "tag_confirmed": False, "tag_verified": False,
        "tag_response": "not_attempted",
        "release_attempted": False, "release_id": None, "release_confirmed": False,
        "release_id_status": "not_attempted",
        "confirmed_uploaded_names": [], "attempted_upload": None,
        "attempted_upload_may_have_succeeded": False,
    }


def publish(sha, state=None):
    if state is None:
        state = partial_state(sha)
    version = source_version.read()
    state.update(version=version, tag="v" + version)
    names = asset_names(version)
    native.verify_bundle(sha, final=True, assets=names)
    assets = [(name, physical.regular_file(Path("."), name)) for name in names]
    sizes = {name: path.stat().st_size for name, path in assets}
    # All local gates precede even the authentication GET.
    prior = availability(version)
    tag = "v" + version
    ref = "refs/tags/" + tag
    state.update(tag_attempted=True, tag_response="unknown_or_lost_response")
    created_ref = api("POST", f"{API}/git/refs", {"ref": ref, "sha": sha})
    state["tag_response"] = "received_unvalidated"
    object_ref(created_ref, ref, sha)
    state.update(tag_confirmed=True, tag_response="validated_create_response")
    object_ref(api("GET", f"{API}/git/ref/tags/{tag}"), ref, sha)
    if remote_tag(tag) != f"{sha}\t{ref}":
        raise ValueError("Created tag advertisement does not match selected SHA")
    state.update(tag_verified=True, release_attempted=True, release_id_status="unknown_or_lost_response")
    release = api("POST", f"{API}/releases", {
        "tag_name": tag, "name": tag, "target_commitish": sha,
        "draft": False, "prerelease": False, "body": "", "generate_release_notes": False,
    })
    if isinstance(release, dict) and strict_json.positive_integer(release.get("id")):
        state.update(release_id=release["id"], release_id_status="provided_positive_response_id")
    else:
        state["release_id_status"] = "unknown_invalid_or_missing_response_id"
    if not isinstance(release, dict) or not strict_json.positive_integer(release.get("id")) \
            or release["id"] in prior or release.get("tag_name") != tag \
            or release.get("name") != tag or release.get("target_commitish") != sha \
            or release.get("draft") is not False or release.get("prerelease") is not False \
            or release.get("body") != "":
        raise ValueError("New release response does not match the create-only request")
    release_id = release["id"]
    expected_upload = f"https://uploads.github.com/{API}/releases/{release_id}/assets"
    if release.get("upload_url") != expected_upload + "{?name,label}":
        raise ValueError("Unexpected new-release upload URL")
    state["release_confirmed"] = True
    uploaded_ids = set()
    for name, path in assets:
        state.update(attempted_upload=name, attempted_upload_may_have_succeeded=True)
        result = api(
            "POST", expected_upload + "?name=" + quote(name, safe=""),
            file=path, content_type="application/zip" if name.endswith(".zip") else "application/x-apple-diskimage",
        )
        if not isinstance(result, dict) or not strict_json.positive_integer(result.get("id")) \
                or result["id"] in uploaded_ids \
                or result.get("name") != name or type(result.get("size")) is not int \
                or result["size"] != sizes[name] or result.get("state") != "uploaded":
            raise ValueError(f"New-release asset verification failed: {name}")
        uploaded_ids.add(result["id"])
        state["confirmed_uploaded_names"].append(name)
        state.update(attempted_upload=None, attempted_upload_may_have_succeeded=False)
    return release_id


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("check", "publish"))
    parser.add_argument("--sha", required=True)
    args = parser.parse_args(argv)
    state = partial_state(args.sha)
    try:
        if args.phase == "check":
            native.preflight_cleanup(args.sha)
            version = source_version.read()
            state.update(version=version, tag="v" + version)
            availability(version)
            print(version)
        else:
            print(publish(args.sha, state))
    except (ValueError, OSError, subprocess.CalledProcessError) as error:
        print(
            f"Publication stopped: {error}\n"
            f"Publication partial state: {json.dumps(state, sort_keys=True, allow_nan=False)}\n"
            "Any created tag/release/assets are retained. Inspect them manually; "
            "do not retry, overwrite, delete or roll back automatically.",
            file=sys.stderr,
        )
        sys.exit(1)


if __name__ == "__main__":
    main()
