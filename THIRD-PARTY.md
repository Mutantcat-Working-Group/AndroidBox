# Third-party code

## ApkStart

- Upstream: https://github.com/RoutineMiku/apkstart
- License: MIT
- Copyright: 2026 ApkStart contributors

Two modules in `androidbox/` were written by reading that project's source and
re-expressing its behaviour in Python. No file is copied verbatim, but the
algorithms and the decisions behind them come from there and the MIT licence
requires the notice to travel with them.

`androidbox/apps.py` follows `src/core/adb.js` and `src/core/container.js`:

- starting an app with `--windowingMode 5` (freeform) and falling back to a
  plain start and then to `monkey`;
- checking `pidof` after each attempt, because `am start` reports success for a
  process that dies immediately;
- treating a crash that names `libndk_translation` or `dlopen failed` as
  permanent rather than retrying it;
- resolving the launcher component through `cmd package resolve-activity`
  instead of trusting the activity inside the APK;
- force-stopping the apps the user is no longer looking at, never the system
  packages, and only the optional ones when deep trimming is requested;
- `am kill-all` plus `dumpsys deviceidle force-idle` when nothing is in front.

`androidbox/apkmeta.py` follows `src/core/axml.js` and `src/core/arsc.js`:

- walked chunks of a binary `AndroidManifest.xml` and its compiled
  `resources.arsc`;
- the resource-id indirection that turns `@0x7f010000` into a label or an icon
  path.

The tests in `tests/test_apkmeta.py` build their archives the way
`test/lib/make-apk.js` does, so the reader is exercised against real binary
formats rather than synthetic dictionaries.
