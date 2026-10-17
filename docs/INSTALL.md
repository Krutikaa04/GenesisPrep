# Salvage installation and removal

## Start here (no terminal commands needed after Python setup)

1. Python 3.10 or newer must already be installed; Python 3.12 is the primary
   tested version. On Windows, include the Python launcher (`py`) during Python
   setup. On macOS, install a suitable Python separately from the system Python.
2. Extract the complete `salvage-<version>-installer.zip` into a new folder.
3. Open **Install on Windows.cmd** or **Install on macOS.command**. The helper
   checks for an existing suitable Python and explains what to do if it is
   missing. It never downloads Python, changes system Python or needs admin rights.
   macOS ZIP tools may discard executable permissions; in that case use the
   terminal installation command below. OS trust/quarantine policies still apply.
4. After installation, choose **Y** to open the welcome menu immediately.
   For later use, open **Start Salvage.cmd** (Windows) or
   **Start Salvage.command** (macOS) at the installed location printed by setup.
   Linux users can run the printed `Start Salvage.sh` or `bin/salvage` command.
5. Choose **1 — Recover files**. Enter **B** to browse for the input folder,
   or paste its full path. The results step suggests a fresh folder under your
   home directory's **Salvage Results**. Browse there selects a parent for a
   new results folder; existing folders are never overwritten by this menu.
6. Confirm recovery. Read the visual summary, then choose **Y** to open the
   results folder. Look at `report.json` and the individual recovered JSON files.

The welcome menu also offers the guided demo, expected-answer comparison,
system checks and exit. `salvage` with no arguments opens it in an interactive
terminal; `salvage --interactive` selects it explicitly. EOF/cancel is safe.
If optional native folder dialogs are unavailable, paste/type paths instead.
Neither folder selection nor result opening requires a third-party package.

No answers are required for recovery. Accuracy is measured only when independent
expected answers are supplied. Missing optional test/demo resources do not stop
ordinary recovery. No menu choice silently downloads or fabricates a kit.

## Optional offline demo and validation kit

The matching **source ZIP** is the optional validation kit. The release manifest
names that artifact and its `samples/official` and source paths explicitly.
Extract it separately, then select its top-level folder in **Run a guided
demonstration**. The menu finds its samples and answers automatically and asks
before executing its local Python tests and benchmark tools. Trust only your
own kit or the matching project download. A data-only kit can demonstrate
recovery/references; unavailable tests or scoring remain explicitly unavailable.

For expected-answer comparisons, select input and answer folders separately.
Answers use the JSON schema documented in REFERENCE-RUNNER.md in the source kit.
Selecting inputs without answers never establishes accuracy.

To remove the application, open the matching **Uninstall on Windows.cmd** or
**Uninstall on macOS.command** from the installer folder. Keep that folder and
the Python interpreter used for installation. The helpers use the default prefix;
custom installations use the explicit commands below. Uninstall preserves user
recovery/evidence folders and unrelated files. There are no automatic updates,
PATH/profile/registry edits, bundled interpreter or native MSI/PKG in this build.

These release packages use Python's standard library only. Python 3.10 or newer
must already be installed; Python 3.12 is the primary tested version. There is
no bundled Python interpreter, GUI, network installer, or background service.
Install and recovery operations work offline. Download the package beforehand
and compare its SHA-256 with the release's SHA256SUMS file.

The version in filenames is the release version, for example 0.1.0 or
0.1.0-rc.1. The same engine is used by the source CLI, portable file and installer.

## Portable use

Download `salvage-<version>.pyz`. No installation is necessary:

```bash
python3 salvage-<version>.pyz --version
python3 salvage-<version>.pyz /path/to/input /path/to/output
```

On Windows use the installed Python launcher, for example:

```powershell
py -3.12 .\salvage-<version>.pyz --version
py -3.12 .\salvage-<version>.pyz "C:\Input files" "C:\Recovered output"
```

Replace the version placeholder with the actual downloaded filename.

## Install the command

Download and extract `salvage-<version>-installer.zip` to a new folder. Keep all
extracted files, including the setup helpers and SHA256SUMS, together. Run the installer
using the Python interpreter you intend to keep installed:

macOS / Linux:

```bash
python3 install.py
```

Windows PowerShell:

```powershell
py -3.12 .\install.py
```

No administrator access is required. Defaults:

- macOS/Linux: command ~/.local/bin/salvage, application ~/.local/share/salvage/.
- Windows: command %LOCALAPPDATA%\Programs\Salvage\bin\salvage.cmd, application
  under %LOCALAPPDATA%\Programs\Salvage\share\salvage\.

The installer prints the command location and a PATH instruction. It does not
edit shell profiles or the Windows registry. For the current terminal session:

```bash
export PATH="$HOME/.local/bin:$PATH"
salvage --version
salvage "/path/to/input files" "/path/to/recovered output"
```

Windows PowerShell:

```powershell
$env:PATH = "$env:LOCALAPPDATA\Programs\Salvage\bin;$env:PATH"
salvage --version
salvage "C:\Input files" "C:\Recovered output"
```

You can also run the full command path the installer prints. For permanent
access, add that bin directory through your normal shell or Windows user PATH
settings. Keep this installer folder for later removal/reinstallation.

## Custom location

```bash
python3 install.py --prefix "/path/to/Salvage tools"
```

Windows:

```powershell
py -3.12 .\install.py --prefix "$env:USERPROFILE\Salvage tools"
```

The prefix contains bin/ and share/salvage/. Use its bin directory in PATH. The
installer refuses symlinks and unrelated files at managed locations. Reinstall
or upgrade only an intact managed installation. It does not overwrite arbitrary
files, and failed managed writes are rolled back where ordinary filesystem
operations allow it. It performs a local version/adapter self-check first.

## Remove

Run install.py from the extracted installer folder:

```bash
python3 install.py --uninstall
# For a custom location, repeat the original prefix:
python3 install.py --uninstall --prefix "/path/to/Salvage tools"
```

On Windows use py -3.12 .\install.py with the same arguments. Removal validates
the managed manifest/hashes, removes only managed files and retains unrelated
files. It does not remove Python or edit your PATH settings. If you replace or
move Python, reinstall with the intended interpreter to refresh the launcher.

## Operation and scope

- Run salvage --help for usage, or salvage --version for the installed version.
- Give different input and output directories. Inputs are nonrecursive.
- Each processable file produces <full input name>.json and a combined
  report.json. Inspect statuses/damage and stderr: the recovery CLI always
  exits 0, including operational failures. The installer itself reports setup
  failures with nonzero status.
- The recovery CLI never invents missing bytes or decrypts protected documents.
  Format/profile support, verification limits and conservative resource guards
  are documented in README.md and FORMAT-SPEC.md in the source release.
- The program does not reconstruct original editable documents; its deliverable
  is structured JSON recovery and damage evidence.
- Filesystem naming collisions/limits and an unwritable output directory can
  prevent required per-file output; those failures are reported explicitly.

## Hackathon source / Docker submission

The source ZIP contains the required ./salvage launcher, Dockerfile, one-command
build, own tests, organizer fixtures and required analysis documentation.
The installer is an additional distribution route; the mandated CLI remains:

If your ZIP extractor discards executable permissions, first run
`chmod +x salvage` on macOS/Linux. Then:

```bash
./salvage input_dir output_dir
make build
```

For an offline Docker build the pinned Python base image must already be
loaded. README.md provides the exact preload/transfer prerequisite and isolated
Docker/native comparison command. Submit the exact release tag/commit so the
source and downloadable packages identify the tested release.
