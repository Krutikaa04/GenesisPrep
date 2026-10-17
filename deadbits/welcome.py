"""Beginner menu using the same offline CLI and recovery engine."""
from datetime import datetime
import os
from pathlib import Path
import subprocess
import sys
import uuid

from . import presentation as ui


class Cancelled(Exception):
    pass


def browse_folder(title):
    """Tk is optional; headless/minimal Python installations can type a path."""
    import tkinter
    from tkinter import filedialog
    root = tkinter.Tk()
    try:
        root.withdraw()
        root.attributes('-topmost', True)
        return filedialog.askdirectory(parent=root, title=title, mustexist=True)
    finally:
        root.destroy()


def open_folder(path):
    path = str(Path(path).resolve())
    if os.name == 'nt':
        os.startfile(path)
    else:
        subprocess.run(['open' if sys.platform == 'darwin' else 'xdg-open', path],
                       check=True, timeout=15)


def suggested_output():
    stamp = datetime.now().strftime('%Y%m%d-%H%M%S') + '-' + uuid.uuid4().hex[:6]
    return Path.home() / 'Salvage Results' / stamp


def run_menu(input_stream=None, output_stream=None, chooser=None, opener=None):
    incoming = sys.stdin if input_stream is None else input_stream
    outgoing = sys.stdout if output_stream is None else output_stream
    chooser = browse_folder if chooser is None else chooser
    opener = open_folder if opener is None else opener

    def say(text):
        ui.emit(text, outgoing)

    def ask(prompt):
        outgoing.write(prompt + ' ')
        outgoing.flush()
        line = incoming.readline()
        if not line:
            raise EOFError()
        return line.strip()

    def folder(title, default=None, destination=False):
        say(ui.panel(title, 'Paste a folder path, enter B to Browse, or Q to cancel.' +
                     ('\nBrowse selects a parent folder; a new results folder is created inside it.' if destination else '') +
                     ('\nPress Enter to use: ' + ui.clean(default) if default else '')))
        while True:
            value = ask('Folder:')
            if value.lower() == 'q':
                raise Cancelled()
            if value.lower() == 'b':
                try:
                    value = chooser(title)
                except Exception:
                    say('Folder picker unavailable. Paste or type the folder path instead.')
                    continue
                if not value:
                    say('No folder selected. Choose another path or Q to cancel.')
                    continue
                if destination:
                    value = str(Path(value) / suggested_output().name)
            if not value:
                if default is None:
                    say('Choose a folder, or enter Q to return to the menu.')
                    continue
                value = str(default)
            if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
                value = value[1:-1]
            path = Path(value).expanduser().resolve()
            if destination:
                if path.exists():
                    say('Choose a new results folder. Existing folders are preserved.')
                    continue
            elif not path.is_dir():
                say('That folder was not found. Try Browse or paste its full path.')
                continue
            return path

    def offer_open(path):
        if path.is_dir() and ask('Open the results folder? [y/N]').lower() == 'y':
            try:
                opener(path)
            except Exception:
                say('Could not open a file manager. Results are saved at: ' + ui.clean(path))

    def run_cli(arguments):
        from .cli import main
        # Keep injectable menu streams consistent with the shared CLI's output.
        import contextlib
        previous = sys.stdin
        try:
            sys.stdin = incoming
            with contextlib.redirect_stdout(outgoing):
                return main(arguments)
        finally:
            sys.stdin = previous

    say(ui.banner('WELCOME'))
    say('Recover readable information from legacy files. Your input files are never edited.')
    while True:
        say(ui.panel('WHAT WOULD YOU LIKE TO DO?',
            '1  Recover files\n2  Run a guided demonstration\n'
            '3  Check recovery against expected answers\n4  Check system readiness\n5  Exit'))
        try:
            choice = ask('Choose 1-5:')
            if choice in ('5', 'q', 'Q'):
                say('Goodbye. Your saved results remain available.')
                return 0
            if choice == '1':
                inputs = folder('SELECT INPUT FOLDER')
                output = folder('SELECT A NEW RESULTS FOLDER', suggested_output(), destination=True)
                if inputs == output or output in inputs.parents or inputs in output.parents:
                    say('Results must be outside the input folder and its parent folders.')
                    continue
                say(ui.panel('READY TO RECOVER',
                    'Input: ' + ui.clean(inputs) + '\nResults: ' + ui.clean(output) +
                    '\nOnly files directly inside the input folder are processed.\n'
                    'Accuracy needs expected answers; damage and uncertainty are reported without them.'))
                if ask('Start recovery? [y/N]').lower() != 'y':
                    say('Recovery cancelled. No files were processed.')
                    continue
                from .cli import run
                report = run(inputs, output)
                say(ui.recovery(report, verbose=True))
                say('Results saved at: ' + ui.clean(output))
                if not report['files']:
                    say('No input files were processed. Check the input folder and any errors above.')
                offer_open(output)
            elif choice == '2':
                from .diagnostics import source_root
                say('The demo needs a local kit. Select the extracted Salvage source download,\n'
                    'or a kit containing samples/ and expected_outputs/. Nothing is downloaded.')
                selected = folder('SELECT DEMO KIT', source_root())
                kit = selected/'samples'/'official' if (selected/'samples'/'official').is_dir() else selected
                source = selected if (selected/'tests').is_dir() and (selected/'tools').is_dir() else None
                output = folder('SELECT A NEW DEMO RESULTS FOLDER', suggested_output(), destination=True)
                args = ['--demo', '--kit-dir', str(kit), '--output-dir', str(output), '--guided']
                if source is not None:
                    say('This source kit contains local Python tests and benchmark tools.')
                    if ask('Trust this kit and run its validation code? [y/N]').lower() == 'y':
                        args += ['--source-dir', str(source)]
                code = run_cli(args)
                say('Demo exit: %d (0 complete, 1 failed, 2 usage, 3 unavailable/skipped).' % code)
                offer_open(output)
            elif choice == '3':
                say('Expected answers must be supplied independently in the documented reference JSON format.\n'
                    'Only files and fields with answers are scored. No answers means no measured accuracy.')
                inputs = folder('SELECT INPUT FOLDER')
                answers = folder('SELECT EXPECTED ANSWERS FOLDER')
                output = folder('SELECT A NEW EVIDENCE FOLDER', suggested_output(), destination=True)
                code = run_cli(['--verify', '--samples-dir', str(inputs), '--expected-dir', str(answers),
                                '--evidence-dir', str(output)])
                say('Comparison exit: %d (0 matched, 1 failed, 2 usage, 3 unavailable).' % code)
                offer_open(output)
            elif choice == '4':
                say('Recovery does not require test data. Missing optional validation resources\n'
                    'only affect references, tests and the guided demo.')
                code = run_cli(['--doctor'])
                if code == 3:
                    say('Recovery requirements are ready. Optional validation resources are missing.')
                elif code:
                    say('A recovery requirement needs attention. Review the system checks above.')
            else:
                say('Enter a number from 1 to 5.')
        except Cancelled:
            say('Back to the menu. You can choose another task or exit.')
        except EOFError:
            say('\nInput ended. Saved results remain available.')
            return 0
        except (OSError, ValueError) as exc:
            say('Could not complete this task: ' + ui.clean(exc))
            say('Input files were preserved. Choose another folder or return to recovery.')
        except KeyboardInterrupt:
            say('\nCancelled. Existing results were preserved.')
            return 0
