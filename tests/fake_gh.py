"""Fixture-only independent canonical API oracle; no network or publication services."""

import sys

sys.dont_write_bytecode = True

import json
import os
from pathlib import Path
import subprocess


root = Path.cwd()
assert root.name.startswith(".ica-offline-")
state_path = root / ".git/fake-api.json"
state = json.loads(state_path.read_text())
args = sys.argv[1:]
assert args.pop(0) == "api"
method, headers, input_path = None, [], None
while args[0].startswith("--"):
    option = args.pop(0)
    if option == "--method":
        method = args.pop(0)
    elif option == "--header":
        headers.append(args.pop(0))
    elif option == "--input":
        input_path = args.pop(0)
    else:
        raise AssertionError(option)
assert len(args) == 1
endpoint = args[0]
payload = json.load(sys.stdin) if input_path == "-" else None
file = Path(input_path) if input_path not in (None, "-") else None
state["calls"].append({"method": method, "endpoint": endpoint, "payload": payload,
                       "size": file.stat().st_size if file else None})
state_path.write_text(json.dumps(state))
assert os.environ["GH_TOKEN"] == "offline-installation-token"
assert "Accept: application/vnd.github+json" in headers
assert "X-GitHub-Api-Version: 2022-11-28" in headers
base = "repos/miyako/4d-plugin-ica"
tag, sha = state["tag"], state["sha"]
ref = "refs/tags/" + tag
mode = state["mode"]


def respond(value):
    print(json.dumps(value))
    sys.exit(0)


def fail():
    print("offline fixture API failure", file=sys.stderr)
    sys.exit(1)


def remote(value):
    command = [os.environ["FIXTURE_REAL_GIT"], "--git-dir", str(root / ".git/offline-api.git"), "update-ref"]
    subprocess.run(command + [ref, value], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def reference(value=sha):
    return {"ref": ref, "object": {"type": "commit", "sha": value}}


def save():
    state_path.write_text(json.dumps(state))


if method == "GET" and endpoint == base:
    if mode in ("repo-404", "repo-network"):
        print("HTTP 404" if mode == "repo-404" else "offline network failure", file=sys.stderr)
        sys.exit(1)
    if mode == "auth-failure":
        fail()
    value = {"id": 102801855, "full_name": "miyako/4d-plugin-ica"}
    if mode == "repo-id":
        value["id"] = 102801856
    elif mode == "repo-id-bool":
        value["id"] = True
    elif mode == "repo-case":
        value["full_name"] = "miyako/4d-plugin-ICA"
    respond(value)
if method == "GET" and endpoint.startswith(base + "/releases?per_page=100&page="):
    page = int(endpoint.rsplit("=", 1)[1])
    if page == 2:
        if mode == "later-page-failure":
            fail()
        if mode == "duplicate-json":
            print('{"hidden":1,"hidden":2}')
            sys.exit(0)
        if mode == "nonfinite-json":
            print('[NaN]')
            sys.exit(0)
        if mode == "overflow-json":
            print('[1e9999]')
            sys.exit(0)
        if mode == "malformed-json":
            print('[broken')
            sys.exit(0)
        if mode == "scalar-page":
            respond({})
        if mode == "draft-match":
            respond([{"id": 8, "tag_name": tag, "draft": True, "prerelease": False}])
        if mode == "duplicate-release-id":
            respond([{"id": 7, "tag_name": "v0.0.2", "draft": False, "prerelease": False}])
        if mode == "release-id-bool":
            respond([{"id": True, "tag_name": "v0.0.2", "draft": False, "prerelease": False}])
        if mode == "release-draft-type":
            respond([{"id": 8, "tag_name": "v0.0.2", "draft": 0, "prerelease": False}])
        if mode == "three-pages":
            respond([{"id": 8, "tag_name": "v0.0.2", "draft": False, "prerelease": False}])
    respond([{"id": 7, "tag_name": "v0.0.1", "draft": True, "prerelease": False}] if page == 1 else [])
if method == "GET" and endpoint == base + "/git/matching-refs/tags/" + tag:
    if mode == "matching-refs-failure":
        fail()
    if mode == "matching-refs-schema":
        respond({"ref": ref})
    if mode == "matching-ref-object":
        respond([{"ref": ref}])
    if mode == "matching-ref-duplicate":
        respond([reference(), reference()])
    if mode == "matching-ref-unrelated":
        value = reference()
        value["ref"] = "refs/tags/unrelated"
        respond([value])
    if mode == "matching-ref-sha":
        respond([{"ref": ref, "object": {"type": "commit", "sha": "wrong"}}])
    if mode == "api-tag":
        respond([reference()])
    value = reference()
    value["ref"] += "-lookalike"
    respond([value])
if method == "POST" and endpoint == base + "/git/refs":
    assert payload == {"ref": ref, "sha": sha}
    if mode == "tag-race":
        remote(sha)
        state["ref_created"] = True
        save()
        fail()
    remote(sha)
    state["ref_created"] = True
    save()
    if mode == "post-ref-failure":
        fail()
    if mode == "post-ref-lost-response":
        print("offline lost response after creating tag", file=sys.stderr)
        sys.exit(1)
    respond(reference("0" * 40 if mode == "post-ref-sha" else sha))
if method == "GET" and endpoint == base + "/git/ref/tags/" + tag:
    if mode == "verify-ref-failure":
        fail()
    if mode == "verify-remote-sha":
        remote(state["other_sha"])
    value = reference("0" * 40 if mode == "verify-ref-sha" else sha)
    if mode == "verify-ref-type":
        value["object"]["type"] = "tag"
    respond(value)
if method == "POST" and endpoint == base + "/releases":
    assert payload == {"tag_name": tag, "name": tag, "target_commitish": sha,
                       "draft": False, "prerelease": False, "body": "", "generate_release_notes": False}
    state["release_created"] = True
    state["created_release_id"] = 101
    save()
    if mode == "post-release-failure":
        fail()
    if mode == "release-lost-response":
        print("offline lost response after creating release", file=sys.stderr)
        sys.exit(1)
    if mode == "release-malformed-response":
        print('{"id":101,')
        sys.exit(0)
    value = {**payload, "id": 101, "upload_url":
             "https://uploads.github.com/repos/miyako/4d-plugin-ica/releases/101/assets{?name,label}"}
    changes = {
        "new-id-bool": ("id", True), "new-id-zero": ("id", 0), "reused-id": ("id", 7),
        "new-tag": ("tag_name", "v9.9.9"), "new-name": ("name", "wrong"),
        "new-target": ("target_commitish", "0" * 40), "new-draft": ("draft", True),
        "new-prerelease": ("prerelease", True), "new-body": ("body", "invented"),
        "new-upload-url": ("upload_url", "https://example.invalid/upload"),
    }
    if mode in changes:
        key, value[key] = changes[mode]
    if mode == "release-missing-id":
        del value["id"]
    respond(value)
if method == "POST" and endpoint.startswith(
    "https://uploads.github.com/repos/miyako/4d-plugin-ica/releases/101/assets?name="
):
    name = endpoint.rsplit("=", 1)[1]
    assert name in ("ImageCaptureCore-2.1.6.zip", "ImageCaptureCore-2.1.6.dmg")
    assert file == root / name and file.read_bytes()
    assert f"Content-Type: {'application/zip' if name.endswith('.zip') else 'application/x-apple-diskimage'}" in headers
    ordinal = len(state["assets"]) + 1
    if mode == f"upload-{ordinal}-failure":
        fail()
    state["assets"].append(name)
    save()
    if mode == f"upload-{ordinal}-lost-response":
        print("offline lost response after uploading " + name, file=sys.stderr)
        sys.exit(1)
    if mode == f"upload-{ordinal}-malformed-response":
        print('{"name":')
        sys.exit(0)
    value = {"id": 200 + ordinal, "name": name, "size": file.stat().st_size, "state": "uploaded"}
    if mode == "asset-id-duplicate":
        value["id"] = 201
    changes = {
        "asset-id-bool": ("id", True), "asset-name": ("name", "wrong"),
        "asset-size-bool": ("size", True), "asset-size": ("size", file.stat().st_size + 1),
        "asset-state": ("state", "new"),
    }
    if mode in changes:
        key, value[key] = changes[mode]
    respond(value)
raise AssertionError((method, endpoint))
