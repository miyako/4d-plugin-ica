![version](https://img.shields.io/badge/version-18%2B-EB8E5F)
![platform](https://img.shields.io/static/v1?label=platform&message=mac-intel%20|%20mac-arm&color=blue)
[![license](https://img.shields.io/github/license/miyako/4d-plugin-ica)](LICENSE)
![downloads](https://img.shields.io/github/downloads/miyako/4d-plugin-ica/total)

# 4d-plugin-ica

`4d-plugin-ica` drives document scanners on macOS through Apple's ImageCaptureCore framework. It lets you enumerate the scanners currently visible to Image Capture, read and set scanner options (folder, image format, resolution, duplex, and so on), open/close a scanner session, and run a scan — with scanned pages delivered back to a 4D method of your choice as they arrive, either as a file path or as raw pixel data in a `Blob`.

## Summary

| Command | Returns | Purpose |
|---|---|---|
| [ICA SCANNERS LIST](#ica-scanners-list) | — (fills an array) | List the scanners Image Capture currently sees, with a JSON metadata blob per scanner |
| [ICA SET SCAN OPTION](#ica-set-scan-option) | — | Set a scanner or functional-unit option (folder, format, resolution, ...) |
| [ICA Get scan option](#ica-get-scan-option) | Text | Read back a scanner or functional-unit option |
| [ICA OPEN SCANNER SESSION](#ica-open-scanner-session) | — | Open a session on a scanner and select a functional unit (flatbed, feeder, ...) |
| [ICA CLOSE SCANNER SESSION](#ica-close-scanner-session) | — | Close the scanner session opened above |
| [ICA SCAN](#ica-scan) | — | Start a scan; pages/errors are delivered to a callback method you name |
| [ICA CANCEL](#ica-cancel) | — | Cancel a scan in progress |

**Platforms:** macOS only (Intel and Apple Silicon). This plugin has no Windows build — there is no Linux runtime for 4D itself, so no Linux support is expected or applicable either.

---

## Requirements & platform notes

- **macOS only.** All plugin commands are no-ops (or simply unavailable) outside `#if VERSIONMAC` — there's no Windows equivalent in this plugin.
- **The scanner list only reflects scanners Image Capture has already discovered.** The plugin starts an `ICDeviceBrowser` when 4D starts up; if a scanner is powered on or connected *after* 4D launches, give it a moment (or re-run `ICA SCANNERS LIST`) before it appears.
- **`ICA SCAN` is asynchronous.** It returns immediately; scanned pages, blob data, and completion/error notifications arrive later via the 4D method you name as `ICA SCAN`'s second parameter. Design your calling code around that — don't assume the scan is finished when `ICA SCAN` returns.
- **Known gap — scan completion is not currently reported.** Tracing the plugin's Objective-C delegate code, a scan finishing *without* a device-level error never calls your callback method at all: only individual page/data events (see the callback's `$1` = 0 or 1 below) and device-level errors (`$1` = 3) reach it today. A plain "the scan finished successfully" notification (`$1` = 2) is not currently sent by any code path. If your calling code needs to know when a whole scan job is done, don't rely on a `$1 = 2` callback arriving — poll `ICA Get scan option` for `Scanner pixel data type`/session state, or track it via the last page/error you actually received, until this is addressed.
- **One active scanner at a time.** The plugin keeps a single internal scanner handle; opening/scanning/cancelling always acts on whichever scanner ID you last passed to `ICA OPEN SCANNER SESSION`, `ICA SCAN`, or `ICA CANCEL`. Don't interleave calls for two different scanner IDs without closing the first session — the second call silently takes over.
- **Some options require an open session first.** `Scanner folder path`, `Scanner document name`, `Scanner image type`, `Scanner max data size`, and `Scanner transfer mode` can be read/set before opening a session. Everything about the selected functional unit — orientation, duplex, document type, scale factor, resolution, bit depth, pixel data type — requires `ICA OPEN SCANNER SESSION` to have been called first; otherwise the getter silently returns an empty string and the setter silently does nothing (no 4D error is raised either way).
- **Timeouts are fixed, not a parameter.** Opening a session, selecting a functional unit, and closing a session are each capped at 30 seconds internally; there is currently no way to pass a different timeout from 4D.

---

## ICA SCANNERS LIST

### Syntax

```4d
ICA SCANNERS LIST ( arrScanners : Array Text )
```

| Parameter | Type | Description |
|---|---|---|
| `arrScanners` | Array Text | Filled by the command. Element `{0}` holds a JSON array (as text) describing every scanner currently seen by Image Capture. Elements `{1}` through `{n}` hold each scanner's `UUIDString`, in the same order as the JSON array — pass any of these strings as `scanner_id` to every other command in this plugin. |

### Description

Element `{0}` is a JSON-stringified array; parse it with `JSON PARSE ARRAY` into an array of objects. Each object carries a mix of scanner-level and (if a session is currently open on that scanner) functional-unit-level properties. What's available depends on session state:

**Before opening a session**, each object includes read-only identity/connection fields (`name`, `modulePath`, `moduleVersion`, `UUIDString`, `locationDescription`, `serialNumberString`, `transportType`, `isRemote`, `hasOpenSession`, `usbVendorID`, `usbProductID`, `usbLocationID`, `moduleExecutableArchitecture`, `iconPath`, `ipAddress`, `autolaunchApplicationPath`, `persistentIDString`) plus the settable properties `downloadsDirectory`, `documentName`, `documentUTI`, `maxMemoryBandSize`, `transferMode`.

**After opening a session** (see `ICA OPEN SCANNER SESSION`), the same object additionally includes the selected functional unit's properties: `supportedBitDepths[]`, `supportedMeasurementUnits[]`, `preferredResolutions[]`/`supportedResolutions[]`, `preferredScaleFactors[]`/`supportedScaleFactors[]`, `measurementUnit`, `resolution`, `nativeXResolution`/`nativeYResolution`, `overviewResolution`, `scaleFactor`, `thresholdForBlackAndWhiteScanning`, `scanInProgress`, and — for document-feeder/flatbed/transparency units — `documentType`, `documentSize`, `supportedDocumentTypes[]`, and, for the document feeder specifically, `duplexScanningEnabled`, `documentLoaded`, `reverseFeederPageOrder`, `supportsDuplexScanning`, `oddPageOrientation`, `evenPageOrientation`.

This is a snapshot at call time — call `ICA SCANNERS LIST` again any time you need fresh values (e.g. right after `ICA OPEN SCANNER SESSION`, since the object shape genuinely changes once a session is open).

### Example

From the plugin's own test method (`TEST.4dm`):

```4d
ARRAY TEXT($scanners; 0)
ICA SCANNERS LIST($scanners)

If (Size of array($scanners)#0)
	$scanner:=$scanners{1}
	//these options can be set/get without opening the scanner
	$folderPath:=ICA Get scan option($scanner; Scanner folder path)
End if
```

Parsing the metadata (from `get_options_1.4dm`):

```4d
ARRAY TEXT($scanners; 0)
ICA SCANNERS LIST($scanners)

$json:=$scanners{0}
ARRAY OBJECT($scannersInfo; 0)
JSON PARSE ARRAY($json; $scannersInfo)

If (Size of array($scannersInfo)>0)
	ALERT("First scanner: "+OB Get($scannersInfo{1}; "name"; Is text))
End if
```

---

## ICA SET SCAN OPTION

### Syntax

```4d
ICA SET SCAN OPTION ( scanner_id : Text ; option : Longint ; value : Text )
```

| Parameter | Type | Description |
|---|---|---|
| `scanner_id` | Text | A `UUIDString` from `ICA SCANNERS LIST`. |
| `option` | Longint | Which option to set — see the option table below. |
| `value` | Text | The new value, always passed as text (see per-option encoding below). |
| Result | — | No return value. If `scanner_id` doesn't match a known scanner, or the option requires an open session that isn't open, the call is silently ignored — no 4D error is raised. |

### Description

`option` is one of:

| Constant | Value | Requires open session? | `value` encoding |
|---|---|---|---|
| `Scanner folder path` | 0 | No | A folder path text (e.g. the result of `Temporary folder`). Internally converted to a `file://` URL — pass a plain path, not a URL string. |
| `Scanner document name` | 1 | No | Any text — used as the base file name when scanning to file. |
| `Scanner image type` | 2 | No | One of the `Scanner image type <format>` constants: `JPEG`=`"0"`, `TIFF`=`"1"`, `PNG`=`"2"`, `BMP`=`"3"`, `PDF`=`"4"`, `GIF`=`"5"`, `JPEG2000`=`"6"`. Pass the constant through `String` as shown in the samples. |
| `Scanner odd page orientation` | 3 | Yes, and only takes effect on a document-feeder unit | Text integer, Apple's `ICEXIFOrientationType` ordinal (1–8). |
| `Scanner even page orientation` | 4 | Yes, document-feeder only | Same encoding as above. |
| `Scanner duplex enabled` | 5 | Yes, document-feeder only | `"0"` or `"1"`. |
| `Scanner document type` | 6 | Yes, flatbed/feeder/transparency units | Text integer, Apple's `ICScannerDocumentType` ordinal (e.g. US Letter, A4, ...) — see the `ImageCaptureCore` headers for the exact ordinal you want; this plugin passes it straight through unvalidated. |
| `Scanner scale factor` | 7 | Yes | Text integer, percent. |
| `Scanner resolution` | 8 | Yes | Text integer, dpi. |
| `Scanner bit depth` | 9 | Yes | Text integer: `1`, `8`, or `16` (Apple's `ICScannerBitDepth` values are the literal bit depth). |
| `Scanner pixel data type` | 10 | Yes | Text integer, one of Apple's `ICScannerPixelDataType` ordinals (BW/Gray/RGB/Palette/CMY/CMYK/YUV/YUVK/CIEXYZ); values outside that set are silently ignored. |
| `Scanner max data size` | 11 | No | Text integer, max memory-band size in bytes — only relevant when `Scanner transfer mode` is `data`. |
| `Scanner transfer mode` | 12 | No | `Scanner transfer mode file` = `"0"` (deliver scans as files), `Scanner transfer mode data` = `"1"` (deliver scans as in-memory band data via `Blob`). |

### Example

From the plugin's own test method (`get_option_1.4dm`):

```4d
ICA SET SCAN OPTION($scanner; Scanner folder path; Temporary folder)
ICA SET SCAN OPTION($scanner; Scanner document name; "scan by 4D")
ICA SET SCAN OPTION($scanner; Scanner image type; String(Scanner image type PDF))
ICA SET SCAN OPTION($scanner; Scanner transfer mode; String(Scanner transfer mode file))
```

Switching to in-memory transfer instead of file-based (from `SCAN.4dm`):

```4d
ICA SET SCAN OPTION($scanner; Scanner image type; String(Scanner image type JPEG))
ICA SET SCAN OPTION($scanner; Scanner transfer mode; String(Scanner transfer mode data))
SET BLOB SIZE(<>SCANNER_DATA; 0)
```

---

## ICA Get scan option

### Syntax

```4d
ICA Get scan option ( scanner_id : Text ; option : Longint ) -> Text
```

| Parameter | Type | Description |
|---|---|---|
| `scanner_id` | Text | A `UUIDString` from `ICA SCANNERS LIST`. |
| `option` | Longint | Same option codes as `ICA SET SCAN OPTION`, above. |
| Result | Text | The current value, always returned as text (wrap numeric options in `Num` to convert). Returns an empty string if `scanner_id` is unknown or the option requires a session that isn't open. |

### Description

`Scanner folder path` is returned as a **classic Mac-style (HFS, colon-separated) path, always ending in `:`** — not a POSIX path — even though you set it with a plain POSIX-style folder path. Convert with 4D's own path-conversion commands if you need a POSIX path back.

All other options mirror the encoding described under `ICA SET SCAN OPTION` above.

### Example

From the plugin's own test method (`get_option_1.4dm` / `get_option_2.4dm`):

```4d
$folderPath:=ICA Get scan option($scanner; Scanner folder path)
$documentName:=ICA Get scan option($scanner; Scanner document name)
$imageType:=ICA Get scan option($scanner; Scanner image type)
$transferMode:=Num(ICA Get scan option($scanner; Scanner transfer mode))
$maxDataSize:=Num(ICA Get scan option($scanner; Scanner max data size))
```

Reading functional-unit options after opening a session:

```4d
ICA OPEN SCANNER SESSION($scanner; Scanner source document feeder)
$evenPageOrientation:=Num(ICA Get scan option($scanner; Scanner even page orientation))
$oddPageOrientation:=Num(ICA Get scan option($scanner; Scanner odd page orientation))
$duplexEnabled:=Num(ICA Get scan option($scanner; Scanner duplex enabled))
$resolution:=Num(ICA Get scan option($scanner; Scanner resolution))
ICA CLOSE SCANNER SESSION($scanner)
```

---

## ICA OPEN SCANNER SESSION

### Syntax

```4d
ICA OPEN SCANNER SESSION ( scanner_id : Text ; source : Longint )
```

| Parameter | Type | Description |
|---|---|---|
| `scanner_id` | Text | A `UUIDString` from `ICA SCANNERS LIST`. |
| `source` | Longint | Which functional unit to select — Apple's `ICScannerFunctionalUnitType`: `Flatbed` = 0, `PositiveTransparency` = 1, `NegativeTransparency` = 2, `DocumentFeeder` = 3. The sample files use the constant `Scanner source document feeder`. |
| Result | — | No return value; use `ICA SCANNERS LIST`/`ICA Get scan option` afterward to confirm the session actually opened (`hasOpenSession`) and which unit got selected. |

### Description

Opening blocks the calling process for up to 30 seconds while the OS negotiates the session and functional-unit selection; if it doesn't complete in that window the plugin gives up silently (no 4D error — check `hasOpenSession` in the JSON from `ICA SCANNERS LIST` afterward). If a session is already open on this scanner, the open-session step is skipped and only functional-unit selection runs.

Because the plugin keeps only one internal scanner handle, calling this for a different `scanner_id` while a previous session is still open does not close the previous one — it silently redirects the handle to the new scanner, leaving the old session dangling. Close explicitly with `ICA CLOSE SCANNER SESSION` before switching scanners.

### Example

From the plugin's own test method (`get_options_2.4dm`):

```4d
ARRAY TEXT($scanners; 0)
ICA SCANNERS LIST($scanners)

If (Size of array($scanners)#0)
	$scanner:=$scanners{1}
	ICA OPEN SCANNER SESSION($scanner; Scanner source document feeder)
	// ... read/set functional-unit options, then:
	ICA CLOSE SCANNER SESSION($scanner)
End if
```

---

## ICA CLOSE SCANNER SESSION

### Syntax

```4d
ICA CLOSE SCANNER SESSION ( scanner_id : Text )
```

| Parameter | Type | Description |
|---|---|---|
| `scanner_id` | Text | A `UUIDString` from `ICA SCANNERS LIST`. |
| Result | — | No return value. If the scanner has no open session, this is a no-op (logged, not raised as a 4D error). |

### Description

Also blocks for up to 30 seconds waiting for the OS to confirm the session closed, same as `ICA OPEN SCANNER SESSION`.

### Example

```4d
ICA CLOSE SCANNER SESSION($scanner)
```

---

## ICA SCAN

### Syntax

```4d
ICA SCAN ( scanner_id : Text ; method : Text ; user_info : Text )
```

| Parameter | Type | Description |
|---|---|---|
| `scanner_id` | Text | A `UUIDString` from `ICA SCANNERS LIST`. |
| `method` | Text | Name of a 4D method to call back as the scan progresses (see signature below). |
| `user_info` | Text | Any text you want handed back to your callback method untouched — the samples pass a JSON-stringified object. |
| Result | — | No return value; `ICA SCAN` returns immediately. If the scanner has no open session yet, it's opened automatically using `ICScannerFunctionalUnitTypeDocumentFeeder` as a default before scanning starts. |

### Description

Scanning is asynchronous. Your `method` is called once per page (or per memory band, if using data transfer mode), and again if the device reports an error — with this signature:

```4d
// $1 <Longint>  : event type - 0=file path, 1=raw band data, 2=success (see note below), 3=error
// $2 <Text>     : file path (type 0 only)
// $3 <Blob>     : raw pixel data (type 1 only)
// $4 <Text>     : user_info, exactly as passed to ICA SCAN
// $5 <Text>     : JSON metadata (type 1 only - dataSize, bytesPerRow, pixelDataType, etc; also the
//                 error description as plain text for type 3)
```

> **Type 2 ("success") is defined but never currently sent** — see the "Known gap" callout under Requirements, above. Don't build logic that waits for it.

Whether scans are delivered as file paths (type 0) or raw band data (type 1) depends on the `Scanner transfer mode` option set beforehand (`file` vs `data`).

### Example

From the plugin's own test method (`SCAN.4dm`), scanning to file:

```4d
C_TEXT($1; $scanner)
C_OBJECT($2; $userInfo)

$scanner:=$1
$userInfo:=$2

ICA SET SCAN OPTION($scanner; Scanner image type; String(Scanner image type PDF))
ICA SET SCAN OPTION($scanner; Scanner transfer mode; String(Scanner transfer mode file))

ICA OPEN SCANNER SESSION($scanner; Scanner source document feeder)

ICA SCAN($scanner; "SCAN_ONE"; JSON Stringify($userInfo))
```

And the callback method itself, from `SCAN_ONE.4dm`:

```4d
C_LONGINT($1; $type)
C_TEXT($2; $path)
C_BLOB($3; $data)
C_TEXT($4; $userInfo)
C_TEXT($5; $dataInfo)

$type:=$1
$path:=$2
$data:=$3
$userInfo:=$4
$dataInfo:=$5

Case of
	: ($type=0)  //path
		If (Test path name($path)=Is a document)
			C_PICTURE($image)
			READ PICTURE FILE($path; $image)
			<>SCAN_IMAGE:=<>SCAN_IMAGE+$image
		End if
	: ($type=1)  //blob (raw data)
		C_OBJECT($info)
		$info:=JSON Parse($dataInfo)
		COPY BLOB($data; <>SCANNER_DATA; 0; BLOB size(<>SCANNER_DATA); BLOB size($data))
	: ($type=2)  //success
		<>SCANNER_INFO:="DONE!"
	: ($type=3)  //error
		<>SCANNER_INFO:="ERROR!"
	Else
End case

POST OUTSIDE CALL(-1)
```

Requesting raw data instead of files (from `SCAN.4dm`'s alternate branch):

```4d
ICA SET SCAN OPTION($scanner; Scanner image type; String(Scanner image type JPEG))
ICA SET SCAN OPTION($scanner; Scanner transfer mode; String(Scanner transfer mode data))
SET BLOB SIZE(<>SCANNER_DATA; 0)
```

---

## ICA CANCEL

### Syntax

```4d
ICA CANCEL ( scanner_id : Text )
```

| Parameter | Type | Description |
|---|---|---|
| `scanner_id` | Text | A `UUIDString` from `ICA SCANNERS LIST`. |
| Result | — | No return value; cancellation is asynchronous — expect your `ICA SCAN` callback method to eventually be invoked with an error/type reflecting the cancellation rather than any further pages arriving. |

### Description

Cancels the scan currently in progress on this scanner, if any. Has no effect if no scan is in progress.

### Example

From the plugin's own test method (`SCAN_CANCEL.4dm`):

```4d
C_TEXT($1; $scanner)
$scanner:=$1
ICA CANCEL($scanner)
```

---

## Error handling & troubleshooting

- **Everything fails silently.** None of these commands raise a 4D error via `ON ERR CALL`. An unrecognized `scanner_id`, a missing session, or a timed-out open/close all just do nothing (sometimes with an `NSLog` message visible only in the system console). Always re-check state explicitly (`hasOpenSession`, `Size of array` on the scanner list, the value you just tried to set) rather than assuming success.
- **Functional-unit options need an open session.** `Scanner odd/even page orientation`, `Scanner duplex enabled`, `Scanner document type`, `Scanner scale factor`, `Scanner resolution`, `Scanner bit depth`, and `Scanner pixel data type` all silently no-op if read/set before `ICA OPEN SCANNER SESSION`.
- **A "successful scan finished" callback is not currently delivered** (see the Requirements callout and `ICA SCAN`'s Description). Only individual pages/bands and device-level errors reach your method today — plan your completion logic around that until this is addressed.
- **`ICA CANCEL` is asynchronous — don't assume the scan has stopped the instant it returns.** Wait for your callback method to reflect it.
- **Only one scanner session is tracked internally.** Don't call `ICA OPEN SCANNER SESSION` / `ICA SCAN` / `ICA CANCEL` for a second `scanner_id` while a session on a first one is still open — close the first session explicitly, or the plugin silently redirects to the new scanner and leaves the old session open with nothing tracking it.
- **`Scanner folder path` round-trips through an HFS-style path.** Set it with a normal POSIX folder path (e.g. `Temporary folder`); reading it back gives a colon-separated path ending in `:`, not the POSIX path you set.
- **Flatbed scanning is known to fail on macOS Catalina** on at least one tested device (HP Officejet Pro 6970); some scanners additionally need a 64-bit driver installed on Catalina for any functional unit to work at all.
- **A newly connected/powered-on scanner may not appear immediately.** The device browser only reflects scanners Image Capture has already discovered since 4D started; re-run `ICA SCANNERS LIST` after giving the OS a moment.

---

## Quick reference

```4d
// list scanners and pick the first one
ARRAY TEXT($scanners; 0)
ICA SCANNERS LIST($scanners)
If (Size of array($scanners)=0)
	ALERT("No scanner found")
Else
	$scanner:=$scanners{1}

	// configure and scan to file
	ICA SET SCAN OPTION($scanner; Scanner folder path; Temporary folder)
	ICA SET SCAN OPTION($scanner; Scanner document name; "scan by 4D")
	ICA SET SCAN OPTION($scanner; Scanner image type; String(Scanner image type PDF))
	ICA SET SCAN OPTION($scanner; Scanner transfer mode; String(Scanner transfer mode file))

	ICA OPEN SCANNER SESSION($scanner; Scanner source document feeder)
	ICA SCAN($scanner; "SCAN_ONE"; JSON Stringify(New object))

	// ... later, to stop a scan in progress:
	// ICA CANCEL($scanner)

	// ... when finished with the scanner:
	// ICA CLOSE SCANNER SESSION($scanner)
End if
```

```4d
// SCAN_ONE - callback method named above
C_LONGINT($1; $type)
C_TEXT($2; $path)
C_BLOB($3; $data)
C_TEXT($4; $userInfo)
C_TEXT($5; $dataInfo)

Case of
	: ($1=0) // a page was written to $path
	: ($1=1) // raw band data is in $data, metadata JSON in $dataInfo
	: ($1=3) // an error occurred; $dataInfo has the description
End case

POST OUTSIDE CALL(-1)
```
