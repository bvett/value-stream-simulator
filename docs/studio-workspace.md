# Simulation studio in VS Code

Open `value-stream.code-workspace`. The `.vscode` configuration also works when
opening the repository folder directly.

## First run

1. Install a current VS Code Desktop and Node **22.12+ on the 22.x line, or 24+**,
   with npm. Check `node --version` in a new VS Code terminal; Node 23 is outside
   this project's supported range. Restart VS Code after changing Node if tasks
   still find an older executable.
2. Run **Extensions: Show Recommended Extensions**. Install Python, Python
   Debugger, and Prettier. The other recommendations add Python language support,
   formatting, and testing. Edge DevTools is optional.
3. Use **Python: Create Environment** to create a `.venv` with Python 3.11+ if
   needed, then **Python: Select Interpreter** to select it. Setup, run, and debug
   commands use the selected interpreter, including an existing `.venv-3.12` or
   other environment. The `.venv` setting is only the initial default.
4. Run **Tasks: Run Task → Studio: Setup** once. This installs the Python package
   in editable mode and the locked frontend dependencies. Repeat after dependency
   changes. Select **Use Workspace Version** if prompted for TypeScript.
5. In **Run and Debug**, select **Studio: Debug (integrated browser)** and press
   **F5**. Vite starts on **http://127.0.0.1:5173**, the Python API starts on 8081,
   and the browser opens beside your code after the API begins listening. The API
   starts its own local simulation service unless `VALUE_STREAM_SERVICE_URL` is set.

Development uses the application factory directly, so no production asset build
is needed. Visit port **5173** while editing; port 8081 serves the API and any
previously built production assets.

## Run, debug, and stop

| Action | Entry point |
| --- | --- |
| Debug React/TypeScript and Python API together | **Studio: Debug (integrated browser)**, F5 |
| Use an installed Brave browser instead (macOS) | **Studio: Debug (Brave)**, F5 |
| Develop with Python and frontend hot reload | Task **Studio: Run (hot reload)**, then click the terminal's `http://127.0.0.1:5173/` link |
| Build production assets | **Run Build Task** (`Cmd+Shift+B` / `Ctrl+Shift+B`) |
| Check frontend types | Task **Studio: Typecheck** |
| Run frontend unit tests once | Task **Studio: Unit tests** |
| Install Chromium for browser tests | Task **Studio: Install test browser** (once) |
| Build and run browser tests | Task **Studio: Browser tests** |

Set a breakpoint in `src/value_stream/app/frontend/src/App.tsx` or
`editors.tsx`, then trigger the corresponding UI action. Set Python breakpoints
in `src/value_stream/app/server.py` or `coordinator.py` to inspect API requests.
The Call Stack pane lets you switch between Python and browser debug sessions.
The managed simulation service runs in the API process and can also be debugged.
Its simulation worker subprocesses (and any external service selected with
`VALUE_STREAM_SERVICE_URL`) are outside these debug sessions.

Frontend edits update through Vite hot reload in every development profile.
Python auto-reload is enabled in the run task, but disabled during F5 debugging
for stable breakpoints; restart the Python debug session after Python edits.
Restarting the API clears the in-memory simulation workspace and results.

Stopping either the browser debugger or Python debugger stops the linked debug
session. **The Vite background task remains available for the next F5 run.** To
shut down fully, use **Tasks: Terminate Task → Studio: Frontend**, or press Ctrl+C
in its terminal. For the hot-reload/visual-CSS workflow, also terminate
**Studio: API (reload)**. Stop that API task before switching to an F5 debug
profile, since both use port 8081. Stop any manually started servers first too.
Vite deliberately fails if 5173 is occupied instead of silently opening a different
port from the debugger.

Browser tests use an isolated application on port 18081 and build fresh assets
first. The task passes your selected Python interpreter to Playwright. The
Playwright extension also provides test discovery and debugging: run
**Studio: Build frontend** before using its Test Explorer, and set
`VALUE_STREAM_TEST_PYTHON` if your environment is not the root `.venv`.

## Visually adjust styles and layout

The default [VS Code integrated browser](https://code.visualstudio.com/docs/debugtest/integrated-browser)
has Developer Tools in its browser toolbar. Use the element picker and the
Elements/Styles panels to experiment with spacing, colors, flex, and grid layout.
Copy changes you want to keep into `src/value_stream/app/frontend/src/style.css`;
ordinary DevTools edits are temporary. Saving source edits updates the preview.

For edits that mirror back into your CSS editor:

1. Install Microsoft Edge and the recommended
   [Microsoft Edge Tools for VS Code](https://marketplace.visualstudio.com/items?itemName=ms-edgedevtools.vscode-edge-devtools).
2. Stop any Python debug session, then launch **Studio: Visual CSS (Edge DevTools)**.
   It starts both development servers and opens Edge DevTools with the frontend
   source directory already mapped.
3. In **Elements → Styles**, enable **CSS mirror editing**. Pick an element and
   change a rule from `src/style.css`. Vite development CSS source maps are enabled.
4. Confirm the edit appears in `style.css`, **save the file**, and review the diff.
   If a rule cannot be mapped (for example a generated Plotly style), copy the
   desired rule into the source manually.

[Microsoft's CSS mirror editing guide](https://learn.microsoft.com/en-us/microsoft-edge/visual-studio-code/microsoft-edge-devtools-extension/css-mirror-editing-styles-tab)
explains the source mapping and save behavior. This gives you visual CSS/layout
tuning. Component structure and behavior still belong in `App.tsx`, `editors.tsx`,
and `charts.tsx`; DOM changes in DevTools do not rewrite React components.

## Extension choices

The recommendations use established tools from the language/tool maintainers:

- [Prettier](https://marketplace.visualstudio.com/items?itemName=esbenp.prettier-vscode):
  formats frontend code on save using the project's installed Prettier.
- [Playwright Test](https://marketplace.visualstudio.com/items?itemName=ms-playwright.playwright):
  browser test discovery, debugging, and locator tools.
- [Vitest](https://github.com/vitest-dev/vscode): frontend unit tests in Test Explorer.
- Microsoft Python, Python Debugger, Pylance, and Black: Python development support.
- Microsoft Edge Tools: optional visual CSS mirror editing described above.

JavaScript/TypeScript language support and browser debugging are built into VS
Code. Vite provides the development server and hot reload. ESLint is not included
in the recommendations because the frontend does not currently have an ESLint
dependency or configuration.

If a browser breakpoint stays hollow, ensure you opened port 5173, installed the
frontend dependencies, and used one of the supplied profiles; each maps the nested
frontend directory as its web root. If the UI reports that the service is
unavailable, inspect the API terminal and `http://127.0.0.1:5173/ready`.
