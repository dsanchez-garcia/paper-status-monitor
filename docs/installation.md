# Installation

`paper-status-monitor` needs **Python 3.10 or newer**. It works on Windows, Linux
and macOS; the built-in autostart is currently Windows-only (see {doc}`autostart`
for the alternatives).

## From PyPI

```console
python -m pip install paper-status-monitor
```

Check that the command is available:

```console
paper-status-monitor --version
```

```{tip}
If the `paper-status-monitor` command is not found, the folder where pip installs
scripts is not on your `PATH`. You can always use
`python -m paper_status_monitor ...` instead.
```

## In an isolated environment

Tools such as [pipx](https://pipx.pypa.io) or [uv](https://docs.astral.sh/uv/)
install command-line applications in their own environment:

```console
pipx install paper-status-monitor
# or
uv tool install paper-status-monitor
```

## From the source code

```console
git clone https://github.com/dsanchez-garcia/paper-status-monitor.git
cd paper-status-monitor
python -m pip install .
```

See {doc}`development` for an editable installation with the test and documentation
tools.

## Upgrading

```console
python -m pip install --upgrade paper-status-monitor
```

```{important}
**Autostart is tied to one Python interpreter.** If you reinstall or upgrade Python
itself (not just the package), install the package again in the new interpreter and
run `paper-status-monitor autostart enable` again. `paper-status-monitor doctor`
detects this situation.
```

## Dependencies

Only two third-party packages are required: [requests](https://requests.readthedocs.io)
(HTTP) and [openpyxl](https://openpyxl.readthedocs.io) (Excel files), plus
[tomli](https://pypi.org/project/tomli/) on Python 3.10. No browser, Selenium or
ChromeDriver is needed.

