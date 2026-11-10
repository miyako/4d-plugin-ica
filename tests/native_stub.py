"""Closed-PATH fixture native boundary; never delegates native or credential commands."""

import sys

sys.dont_write_bytecode = True

import json
import os
from pathlib import Path
import plistlib


root = Path.cwd()
assert root.name.startswith(".ica-offline-")
state_path = root / ".git/native-state.json"
state = json.loads(state_path.read_text())
name = Path(sys.argv[0]).name
args = sys.argv[1:]
state["calls"].append([name, *args])
state_path.write_text(json.dumps(state))
mode = state["mode"]
bundle = root / "test/Plugins/ImageCaptureCore.bundle"
contents = bundle / "Contents"


def write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


if name == "xcodebuild":
    assert args == [
        "-project", "ImageCaptureCore.xcodeproj", "-target", "ImageCaptureCore",
        "-configuration", "Default", "ARCHS=arm64 x86_64", "ONLY_ACTIVE_ARCH=NO",
        "MACOSX_DEPLOYMENT_TARGET=11.0", "build",
    ]
    assert os.environ.get("PYTHONDONTWRITEBYTECODE") is None
    assert os.environ.get("PYTHONPYCACHEPREFIX") is None
    sys.path.insert(0, str(root / ".github/scripts"))
    import source_version
    source_version.read()
    write(contents / "Info.plist", plistlib.dumps(
        plistlib.loads((root / "Info.plist").read_bytes()), fmt=plistlib.FMT_BINARY,
    ))
    fields = source_version.localized_fields(
        source_version.decode((root / "English.lproj/InfoPlist.strings").read_bytes())[0],
    )
    write(contents / "Resources/English.lproj/InfoPlist.strings",
          plistlib.dumps({key: value[0] for key, value in fields.items()}, fmt=plistlib.FMT_BINARY))
    write(contents / "MacOS/ImageCaptureCore", b"new stub universal Mach-O; NOT a real native build")
    write(contents / "_CodeSignature/CodeResources", b"new builtin Xcode signature")
    write(root / "test/Plugins/XCBuildData/build.db", b"fresh native DB retained")
    write(root / "test/Plugins/XCBuildData/build.db-wal", b"fresh WAL retained")
    write(root / ("test/Plugins/XCBuildData/" + "a"*32 + ".xcbuilddata/description.msgpack"), b"stub build description")
    write(root / "test/Plugins/ImageCaptureCore.build/Default/ImageCaptureCore.build/Objects-normal/arm64/C_TEXT.o", b"stub object")
elif name == "lipo":
    assert args[0] in ("-info", "-archs")
    assert args[1] == "test/Plugins/ImageCaptureCore.bundle/Contents/MacOS/ImageCaptureCore"
    print(os.environ.get("FIXTURE_ARCHS", "x86_64 arm64 arm64e"))
elif name == "security":
    assert args[0] in (
        "create-keychain", "set-keychain-settings", "unlock-keychain", "import",
        "list-keychain", "set-key-partition-list", "find-identity",
    )
    if args[0] == "find-identity":
        print('  1) 1234 "Developer ID Application: Offline Fixture (OFFLINE)"')
elif name == "base64":
    assert args[:2] == ["--decode", "-o"]
    assert sys.stdin.read() == "offline-not-a-certificate"
    write(Path(args[2]), b"fixture certificate; no secret")
elif name == "codesign":
    if "--sign" in args:
        assert args == [
            "--verbose", "--deep", "--timestamp", "--force", "--options=runtime", "--sign",
            "Developer ID Application: Offline Fixture (OFFLINE)",
            "test/Plugins/ImageCaptureCore.bundle",
        ]
        write(contents / "_CodeSignature/CodeResources", b"new forced runtime signature")
    else:
        assert args == ["--verify", "--deep", "--strict", "--verbose=2", "test/Plugins/ImageCaptureCore.bundle"]
        if mode == "strict-signature":
            sys.exit(17)
elif name == "ditto":
    assert args[:4] == ["-c", "-k", "--keepParent", "test/Plugins/ImageCaptureCore.bundle"]
    assert args[4] == "ImageCaptureCore-2.1.6.zip"
    write(root / args[4], b"new ZIP bytes retained")
elif name == "hdiutil":
    assert args == [
        "create", "-format", "UDBZ", "-volname", "ImageCaptureCore",
        "-srcfolder", "test/Plugins/ImageCaptureCore.bundle", "ImageCaptureCore-2.1.6.dmg",
    ]
    write(root / args[-1], b"new DMG bytes retained")
elif name == "xcrun":
    if args[:2] == ["notarytool", "store-credentials"]:
        assert args[2] == "notarytool-profile"
    elif args[:2] == ["notarytool", "submit"]:
        archive = args[2]
        assert archive in ("ImageCaptureCore-2.1.6.zip", "ImageCaptureCore-2.1.6.dmg")
        assert args[3:5] == ["--keychain-profile", "notarytool-profile"]
        assert args[-3:] == ["--wait", "--output-format", "json"]
        suffix = "zip" if archive.endswith(".zip") else "dmg"
        if mode == suffix + "-duplicate":
            print('{"status":"Rejected","status":"Accepted"}')
        elif mode == suffix + "-nonfinite":
            print('{"status":"Accepted","unexpected":NaN}')
        elif mode == suffix + "-overflow":
            print('{"status":"Accepted","unexpected":1e9999}')
        elif mode == suffix + "-malformed":
            print('{"status":')
        elif mode == suffix + "-schema":
            print('["Accepted"]')
        else:
            print(json.dumps({"id": "offline-notary-id", "status":
                              "Invalid" if mode == suffix + "-rejected" else "Accepted"}))
        if mode == suffix + "-exit":
            sys.exit(17)
    else:
        assert args[0] == "stapler" and args[1] in ("staple", "validate")
        assert args[2] == "ImageCaptureCore-2.1.6.dmg"
        if mode == "staple" or mode == "validate":
            if args[1] == mode:
                sys.exit(17)
        if args[1] == "staple":
            path = root / args[2]
            write(path, path.read_bytes() + b"; staple retained")
else:
    raise AssertionError((name, args))
