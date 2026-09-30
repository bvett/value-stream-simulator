# Simulation application validation

Validated on macOS/ARM64 with Python 3.11 and Node 22. Production browser tests use Chromium; the screenshots show desktop (1440px), mobile (390px), and the 720 CSS pixels available at 200% browser zoom on a 1440px display. `chart.png` captures the plot at desktop size. The zoom image is viewport-based reflow validation, not a native browser text-zoom test.

The full Python suite passed 177 tests. The frontend suite passed three tests, and production Playwright passed three end-to-end tests. The browser suite covers incremental results, whole-job cancellation, immutable baseline/pins, refresh, exports, all five views, keyboard tab switching, baseline differences, zoom persistence/reset, and responsive layout. Focused boundary tests additionally cover extreme ranges, finite limits, oversized/invalid upstream bodies, and retention.

`wheel-validation.json` and `docker-validation.json` record actual 100-scenario/three-task runs, 101-scenario rejection, UI assets, and CSV exports. Docker also records partial cancellation of a 100-model/1,000-task job. Peak wheel process-tree RSS includes earlier retained validation runs. Docker RSS was not peak-sampled; a post-test container observation was 533.7 MiB. These figures are local validation evidence, not benchmark guarantees.

`validate_runtime.py` reproduces those runtime checks from repository root against an already started app:

    .venv/bin/python .agent/artifacts/simulation-app/validate_runtime.py http://127.0.0.1:8081 wheel

An optional final argument is the app process ID, enabling sampled app/service/worker RSS (macOS may require permission to inspect processes). Pass `docker` instead of `wheel` to include whole-job cancellation. Each invocation creates a test workspace; restart the test server between repeated checks to reset temporary workspace limits.

The wheel was installed in a fresh environment and run with `PATH=/usr/bin:/bin`, without Node available. The Docker image was built using `Dockerfile.app` and run on loopback. The final build removes its source tree after installation. Temporary validation servers/containers were shut down after checks. The external-service integration test verifies that app shutdown leaves a separately managed simulation service running.
