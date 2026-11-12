# Ownership regressions

`run.sh <source-root> <fixed|baseline>` builds the real plugin source
(`4DPlugin-ImageCaptureCore.cpp`), the helper sources (`4D Plugin API/Classes/*.cpp`,
`support/4DPlugin-JSON.cpp`) and the bundled, unmodified `4DPluginAPI.c` with
ASan/UBSan, links them against `engine_harness.mm` (a synthetic 4D engine that
replaces only `gCall4D`) and runs every test in its own process.

No camera or scanner is touched: `PluginMain` is never called, so no
`ICDeviceBrowser` is created. Tests push one synthetic scan result onto the
plugin's callback queue and dispatch it with the real `listenerLoopExecuteMethod`.

```sh
tests/ownership/run.sh . fixed                     # every test must pass

B=$(mktemp -d)                                     # same harness, immutable baseline
git archive <base-sha> | tar -x -C "$B"
tests/ownership/run.sh "$B" baseline               # named defects must fail, controls pass
```

| Test | Contract |
| --- | --- |
| `defect_byid_param_owner_leak`, `defect_1007_param_owner_leak` | callback parameters are created `eVK_Undefined`; `eVK_Unistring`/`eVK_Blob` allocate an owner that the shallow setters leak (LIVE) |
| `defect_byid_result_not_cleared` | the `PA_ExecuteMethodByID` result is cleared when the call succeeded (LIVE) |
| `guard_byid_error_result_untouched` | a failed call's result is not cleared (error captured before the parameter clears) |
| `defect_ob_set_{s,a,p}_owner_leak` | `support/4DPlugin-JSON.cpp` setters create `eVK_Undefined` (UNREACHABLE) |
| `defect_ob_get_*` | `PA_GetObjectProperty` copies are released; matching object/collection references go to the caller (UNREACHABLE) |
| `guard_ob_get_error_result_untouched` | a failed get is never cleared |
| `control_*` | callback arguments delivered on both paths, `ARRAY_TEXT` transfer/borrow, object/collection transfer, scalars and `JSON Stringify` |

The `EXECUTE METHOD` (1007) fallback is called without `*`, so it returns
nothing; its result is not claimed or cleared. `support/4DPlugin-JSON.cpp` is
compiled into the macOS target but none of its functions are called by the
plugin (UNREACHABLE). The model is synthetic: it does not replace validation in
4D or on Windows.
