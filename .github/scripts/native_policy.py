"""ICA Default output policy, corroborated by original intake native step5."""

import re


PRODUCT = "ImageCaptureCore"
OUTPUT = "test/Plugins"
BUNDLE = OUTPUT + "/" + PRODUCT + ".bundle"
CONTENTS = BUNDLE + "/Contents"
EXECUTABLE = CONTENTS + "/MacOS/" + PRODUCT
BUILT_PLIST = CONTENTS + "/Info.plist"
BUILT_ENGLISH = CONTENTS + "/Resources/English.lproj/InfoPlist.strings"
SIGNATURE = CONTENTS + "/_CodeSignature/CodeResources"
GENERATED_LEAVES = frozenset((EXECUTABLE, BUILT_PLIST, BUILT_ENGLISH, SIGNATURE))
COPIED_RESOURCES = {
    CONTENTS + "/Resources/manifest.json": "manifest.json",
    CONTENTS + "/Resources/constants.xlf": "constants.xlf",
}
PRESERVED_LEAVES = (
    CONTENTS + "/Windows64/" + PRODUCT + ".4DX",
    CONTENTS + "/QuickLook/Thumbnail.png",
)
PACKAGE_LEAVES = GENERATED_LEAVES | COPIED_RESOURCES.keys() | set(PRESERVED_LEAVES)
PROJECT_TEMP = OUTPUT + "/" + PRODUCT + ".build"
TARGET_TEMP = PROJECT_TEMP + "/Default/" + PRODUCT + ".build"
XC = OUTPUT + "/XCBuildData"
DIRECTORY_TARGETS = (
    PROJECT_TEMP, XC, OUTPUT + "/ExplicitPrecompiledModules",
    OUTPUT + "/SwiftExplicitPrecompiledModules", OUTPUT + "/EagerLinkingTBDs",
)
SOURCES = (
    "C_TEXT", "C_LONGINT", "C_BLOB", "ARRAY_TEXT", "4DPluginAPI",
    "4DPlugin-JSON", "4DPlugin-ImageCaptureCore",
)
_target = re.escape(TARGET_TEMP)
_project = re.escape(PROJECT_TEMP)
_object_names = "|".join(map(re.escape, SOURCES))
_intermediate = re.compile(
    rf"(?:{_target}/(?:"
    rf"Script-D1292E7B22C4A91E00CB5A8C\.sh|"
    rf"ImageCaptureCore(?:-(?:(?:project|own-target|all-target|all-non-framework-target)-headers|generated-files))?\.hmap|"
    rf"ImageCaptureCore\.Dependency(?:Static)?MetadataFileList|"
    rf"Objects-normal/(?:arm64|x86_64)/(?:"
    rf"(?:{_object_names})\.(?:o|d|dia)|"
    rf"[0-9a-f]{{32}}-common-args\.resp|ImageCaptureCore\.LinkFileList|"
    rf"ImageCaptureCore_dependency_info\.dat|Binary/ImageCaptureCore))|"
    rf"{_project}/Default/ImageCaptureCore-[0-9a-f]{{32}}-VFS/all-product-headers\.yaml)"
)


def generated_file(path):
    if path in GENERATED_LEAVES or _intermediate.fullmatch(path):
        return True
    if path in (XC + "/build.db", XC + "/build.db-wal", XC + "/build.db-shm"):
        return True
    return re.fullmatch(re.escape(XC) + r"/[0-9a-f]{32}\.xcbuilddata/(?!.*(?:^|/)\.git(?:/|$)).+", path) is not None


def generated_directory(path):
    if path in DIRECTORY_TARGETS or path in (
        PROJECT_TEMP + "/Default", TARGET_TEMP, TARGET_TEMP + "/Objects-normal",
        OUTPUT + "/EagerLinkingTBDs/Default",
    ):
        return True
    if re.fullmatch(_target + r"/Objects-normal/(?:arm64|x86_64)(?:/Binary)?", path):
        return True
    if re.fullmatch(_project + r"/Default/ImageCaptureCore-[0-9a-f]{32}-VFS", path):
        return True
    return re.fullmatch(re.escape(XC) + r"/[0-9a-f]{32}\.xcbuilddata(?:/.+)?", path) is not None
