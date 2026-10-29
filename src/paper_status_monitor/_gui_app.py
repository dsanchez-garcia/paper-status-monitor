"""Tk widgets of the graphical interface (see :mod:`paper_status_monitor.gui`).

This module imports :mod:`tkinter`, so it is only loaded when the window opens.
"""

from __future__ import annotations

import contextlib
import logging
import os
import queue
import sys
import threading
import tkinter as tk
import webbrowser
from collections.abc import Callable, Iterable
from dataclasses import replace
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from tkinter import font as tkfont
from types import TracebackType
from typing import Any

from paper_status_monitor import (
    autostart,
    emails,
    gui,
    i18n,
    notifications,
    organize,
    paths,
    report,
    state,
    storage,
    tray,
)
from paper_status_monitor import export as history_export
from paper_status_monitor import summary as status_summary
from paper_status_monitor._version import __version__
from paper_status_monitor.client import TrackerClient, parse_uuid
from paper_status_monitor.config import (
    EMAIL_SECURITY_PORTS,
    SMTP_PASSWORD_ENV_VAR,
    Config,
    ConfigError,
    EmailConfig,
    SubmissionConfig,
    describe_columns,
    load_config,
    save_config,
)
from paper_status_monitor.i18n import _, column_label, ngettext
from paper_status_monitor.models import DETECTED_AT_COLUMN, TRACKED_COLUMNS, TRACKER_URL_COLUMN
from paper_status_monitor.monitor import Monitor

log = logging.getLogger(__name__)

PAD = 8
DOCS_URL = "https://paper-status-monitor.readthedocs.io"
_GREY = "#5f6368"


def launch(config_path: Path) -> int:
    """Create the main window and run the Tk event loop until it is closed."""
    _enable_dpi_awareness()
    i18n.set_language(gui.configured_language(config_path))
    root = tk.Tk()
    App(root, config_path)
    root.mainloop()
    return 0


def _enable_dpi_awareness() -> None:
    """Avoid blurry text on high-resolution Windows displays."""
    if sys.platform == "win32":
        with contextlib.suppress(AttributeError, OSError):
            import ctypes

            ctypes.windll.shcore.SetProcessDpiAwareness(1)  # type: ignore[attr-defined]


class App:
    """The main window.

    It is shown in the current language (see :mod:`~paper_status_monitor.i18n`);
    :meth:`change_language` rebuilds it in another one.

    Args:
        root: Tk root window.
        config_path: Configuration file shown, and written by *Save*.
        synchronous: Run the background work immediately (used by the tests).
    """

    def __init__(self, root: tk.Tk, config_path: Path, *, synchronous: bool = False) -> None:
        self.root = root
        self.config_path = config_path
        self.synchronous = synchronous
        self.submissions: list[SubmissionConfig] = []
        self.statuses: dict[str, str] = {}
        self.workbooks: dict[str, Path] = {}
        self.dirty = False
        self._loading = False
        self._busy = 0
        self._preview_job: str | None = None
        self._tasks: queue.Queue[Callable[[], None]] = queue.Queue()
        self._presets: dict[str, str] = {}
        self._outer: ttk.Frame | None = None
        self._menu: tk.Menu | None = None
        self._running = False

        self.data_dir_var = tk.StringVar(master=root)
        self.template_var = tk.StringVar(master=root)
        self.preset_var = tk.StringVar(master=root)
        self.language_var = tk.StringVar(master=root, value=i18n.language_name(i18n.get_language()))
        self.open_report_var = tk.BooleanVar(master=root, value=True)
        self.toast_var = tk.BooleanVar(master=root, value=False)
        self.email_var = tk.BooleanVar(master=root, value=False)
        self.email_settings = EmailConfig()
        self.notify_errors_var = tk.BooleanVar(master=root, value=True)
        self.time_sheet_var = tk.BooleanVar(master=root, value=False)
        self.timeout_var = tk.StringVar(master=root, value="30")
        self.wait_var = tk.StringVar(master=root, value=str(autostart.DEFAULT_WAIT))
        self.every_var = tk.StringVar(master=root, value="0")
        self.tray_var = tk.BooleanVar(master=root, value=False)
        self.status_var = tk.StringVar(master=root)
        self.selection_var = tk.StringVar(master=root)
        self.placeholders_var = tk.StringVar(master=root)
        self.preview_message_var = tk.StringVar(master=root)
        self.autostart_var = tk.StringVar(master=root)
        self.last_run_var = tk.StringVar(master=root)
        self.record_vars = {
            column: tk.BooleanVar(master=root, value=True) for column in TRACKED_COLUMNS
        }
        self.notify_vars = {
            column: tk.BooleanVar(master=root, value=True) for column in TRACKED_COLUMNS
        }

        watched = [
            self.data_dir_var,
            self.template_var,
            self.open_report_var,
            self.toast_var,
            self.email_var,
            self.notify_errors_var,
            self.time_sheet_var,
            self.timeout_var,
            *self.record_vars.values(),
            *self.notify_vars.values(),
        ]
        for variable in watched:
            variable.trace_add("write", self._on_change)
        self.template_var.trace_add("write", self._schedule_preview)
        self.data_dir_var.trace_add("write", self._schedule_preview)
        self.language_var.trace_add("write", self._on_language_selected)

        root.title(f"paper-status-monitor {__version__}")
        root.minsize(900, 620)
        root.protocol("WM_DELETE_WINDOW", self.close)
        root.report_callback_exception = self._callback_error  # type: ignore[method-assign]
        self.bold = tkfont.nametofont("TkDefaultFont", root=root).copy()
        self.bold.configure(weight="bold")
        self._build()
        self.load()
        if not synchronous:
            root.after(100, self._poll)

    # ------------------------------------------------------------------ layout

    def _build(self) -> None:
        self._build_menu()
        outer = ttk.Frame(self.root, padding=PAD)
        outer.pack(fill="both", expand=True)
        self._outer = outer
        self.notebook = ttk.Notebook(outer)
        self.notebook.pack(fill="both", expand=True)
        self._build_submissions_tab()
        self._build_notifications_tab()
        self._build_workbooks_tab()
        self._build_run_tab()
        bar = ttk.Frame(outer, padding=(0, PAD, 0, 0))
        bar.pack(fill="x")
        # The controls are packed first, so that a long status never pushes them away.
        ttk.Button(bar, text=_("Save"), command=self.save).pack(side="right")
        ttk.Button(bar, text=_("Reload"), command=self.reload).pack(side="right", padx=(0, 4))
        ttk.Combobox(
            bar,
            textvariable=self.language_var,
            values=list(i18n.LANGUAGES.values()),
            state="readonly",
            width=10,
        ).pack(side="right", padx=(0, PAD * 2))
        ttk.Label(bar, text=_("Language (window and reports)")).pack(
            side="right", padx=(PAD * 2, 4)
        )
        ttk.Label(bar, textvariable=self.status_var).pack(side="left", fill="x", expand=True)
        self.root.bind_all("<Control-s>", lambda _event: self.save())

    def _build_menu(self) -> None:
        menu = tk.Menu(self.root)
        file_menu = tk.Menu(menu, tearoff=False)
        file_menu.add_command(label=_("Save"), accelerator="Ctrl+S", command=self.save)
        file_menu.add_command(label=_("Reload"), command=self.reload)
        file_menu.add_separator()
        file_menu.add_command(label=_("Open the configuration file"), command=self.open_config_file)
        file_menu.add_command(label=_("Open the log file"), command=self.open_log_file)
        file_menu.add_separator()
        file_menu.add_command(label=_("Exit"), command=self.close)
        menu.add_cascade(label=_("File"), menu=file_menu)
        help_menu = tk.Menu(menu, tearoff=False)
        help_menu.add_command(label=_("Documentation"), command=lambda: webbrowser.open(DOCS_URL))
        help_menu.add_command(label=_("About"), command=self.about)
        menu.add_cascade(label=_("Help"), menu=help_menu)
        self.root.configure(menu=menu)
        if self._menu is not None:
            self._menu.destroy()
        self._menu = menu

    def _tab(self, title: str) -> ttk.Frame:
        tab = ttk.Frame(self.notebook, padding=PAD)
        self.notebook.add(tab, text=title)
        return tab

    def _note(self, parent: tk.Misc, text: str = "", **options: Any) -> ttk.Label:
        options.setdefault("wraplength", 840)
        return ttk.Label(parent, text=text, foreground=_GREY, justify="left", **options)

    def _build_submissions_tab(self) -> None:
        tab = self._tab(_("Submissions"))
        columns = ("label", "fields", "enabled", "status")
        self.tree = ttk.Treeview(tab, columns=columns, show="headings", selectmode="browse")
        headings = {
            "label": (_("Label"), 200),
            "fields": (_("Custom fields"), 170),
            "enabled": (_("Monitored"), 90),
            "status": (_("Last recorded status"), 380),
        }
        for column, (heading, width) in headings.items():
            self.tree.heading(column, text=heading)
            self.tree.column(column, width=width, stretch=column in ("label", "status"))
        scroll = ttk.Scrollbar(tab, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        scroll.grid(row=0, column=1, sticky="ns")
        self.tree.bind("<Double-1>", lambda _event: self.edit_submission())
        buttons = ttk.Frame(tab)
        buttons.grid(row=1, column=0, columnspan=2, sticky="w", pady=(PAD, 0))
        for text, command in (
            (_("Add..."), self.add_submission),
            (_("Edit..."), self.edit_submission),
            (_("Remove"), self.remove_submission),
            (_("Pause / resume"), self.toggle_submission),
            (_("Check now"), self.check_submission),
            (_("Open workbook"), self.open_workbook),
            (_("Refresh"), self.refresh_statuses),
            (_("Summary"), self.show_summary),
            (_("Export..."), self.export_history),
        ):
            ttk.Button(buttons, text=text, command=command).pack(side="left", padx=(0, 4))
        self._note(
            tab,
            _(
                "Double-click a submission to edit it. Use custom fields (for example paper = "
                "Tau) to name the workbooks and to group the submissions of a paper to several "
                "journals. A * means that the submission has its own choice of what is "
                "recorded and notified. Changes are kept when you click Save."
            ),
        ).grid(row=2, column=0, columnspan=2, sticky="w", pady=(PAD, 0))
        tab.columnconfigure(0, weight=1)
        tab.rowconfigure(0, weight=1)

    def _build_notifications_tab(self) -> None:
        tab = self._tab(_("Notifications"))
        self._note(
            tab,
            _(
                "For every column, choose whether a change adds a row to the workbook (Record) "
                "and whether it is included in the report that is opened for you (Notify). "
                "Example: to keep the history of 'Last review activity' without being told "
                "about it, tick Record and untick Notify."
            ),
        ).grid(row=0, column=0, columnspan=2, sticky="w")
        grid = ttk.Frame(tab)
        grid.grid(row=1, column=0, sticky="nw", pady=PAD)
        ttk.Label(grid, text=_("Column"), font=self.bold).grid(row=0, column=0, sticky="w")
        ttk.Label(grid, text=_("Record"), font=self.bold).grid(row=0, column=1, padx=PAD * 2)
        ttk.Label(grid, text=_("Notify"), font=self.bold).grid(row=0, column=2, padx=PAD * 2)
        for row, column in enumerate(TRACKED_COLUMNS, start=1):
            ttk.Label(grid, text=column_label(column)).grid(row=row, column=0, sticky="w", pady=1)
            ttk.Checkbutton(grid, variable=self.record_vars[column]).grid(row=row, column=1)
            ttk.Checkbutton(grid, variable=self.notify_vars[column]).grid(row=row, column=2)
        side = ttk.Frame(tab)
        side.grid(row=1, column=1, sticky="nw", padx=(PAD * 3, 0), pady=PAD)
        ttk.Label(side, text=_("Quick choices"), font=self.bold).pack(anchor="w")
        for text, command in (
            (_("Record every change"), lambda: self._set_all(self.record_vars, True)),
            (_("Notify every change"), lambda: self._set_all(self.notify_vars, True)),
            (
                _("Notify only status changes"),
                lambda: self._set_only(self.notify_vars, {"Status"}),
            ),
            (
                _("Do not notify review activity dates"),
                lambda: self.notify_vars["Last review activity"].set(False),
            ),
        ):
            ttk.Button(side, text=text, command=command).pack(anchor="w", fill="x", pady=2)
        reports = ttk.LabelFrame(side, text=_("When there is news"), padding=PAD)
        reports.pack(anchor="w", fill="x", pady=(PAD * 2, 0))
        ttk.Checkbutton(
            reports,
            text=_("Open the report with your text editor"),
            variable=self.open_report_var,
        ).pack(anchor="w")
        toast = ttk.Frame(reports)
        toast.pack(anchor="w", fill="x")
        ttk.Checkbutton(toast, text=_("Show a desktop notification"), variable=self.toast_var).pack(
            side="left"
        )
        ttk.Button(toast, text=_("Test"), command=self.send_test_notification).pack(
            side="left", padx=(PAD, 0)
        )
        mail = ttk.Frame(reports)
        mail.pack(anchor="w", fill="x")
        ttk.Checkbutton(mail, text=_("Send the report by e-mail"), variable=self.email_var).pack(
            side="left"
        )
        ttk.Button(mail, text=_("Settings..."), command=self.edit_email_settings).pack(
            side="left", padx=(PAD, 0)
        )
        ttk.Button(mail, text=_("Test"), command=self.send_test_email).pack(
            side="left", padx=(4, 0)
        )
        ttk.Checkbutton(
            reports,
            text=_("Also report submissions that could not be checked (recommended)"),
            variable=self.notify_errors_var,
        ).pack(anchor="w")
        self._note(
            reports,
            _("The report is always written to the 'reports' subfolder of the data folder."),
            wraplength=380,
        ).pack(anchor="w", pady=(4, 0))
        ttk.Label(side, textvariable=self.selection_var, wraplength=380, justify="left").pack(
            anchor="w", pady=(PAD * 2, 0)
        )
        self._note(
            tab,
            _(
                "New submissions are always reported. Changes that are notified but not "
                "recorded are reported only once."
            ),
        ).grid(row=2, column=0, columnspan=2, sticky="w", pady=(PAD, 0))

    def _build_workbooks_tab(self) -> None:
        tab = self._tab(_("Workbooks"))
        ttk.Label(tab, text=_("Data folder")).grid(row=0, column=0, sticky="w")
        ttk.Entry(tab, textvariable=self.data_dir_var).grid(row=0, column=1, sticky="ew", padx=4)
        ttk.Button(tab, text=_("Browse..."), command=self.browse_data_dir).grid(row=0, column=2)
        ttk.Button(tab, text=_("Open"), command=self.open_data_dir).grid(
            row=0, column=3, padx=(4, 0)
        )
        ttk.Label(tab, text=_("Workbook name")).grid(row=1, column=0, sticky="w", pady=(PAD, 0))
        ttk.Entry(tab, textvariable=self.template_var).grid(
            row=1, column=1, sticky="ew", padx=4, pady=(PAD, 0)
        )
        self._presets = {_(label): template for label, template in gui.NAME_PRESETS.items()}
        presets = ttk.Combobox(
            tab,
            textvariable=self.preset_var,
            values=list(self._presets),
            state="readonly",
            width=34,
        )
        presets.set(_("Choose a preset..."))
        presets.bind("<<ComboboxSelected>>", self.apply_preset)
        presets.grid(row=1, column=2, columnspan=2, sticky="ew", pady=(PAD, 0))
        self._note(tab, textvariable=self.placeholders_var).grid(
            row=2, column=0, columnspan=4, sticky="w", pady=(PAD, 0)
        )
        ttk.Label(tab, textvariable=self.preview_message_var, foreground="#b00020").grid(
            row=3, column=0, columnspan=4, sticky="w", pady=(4, 0)
        )
        columns = ("submission", "current", "expected")
        self.preview = ttk.Treeview(tab, columns=columns, show="headings", height=8)
        for column, heading, width in (
            ("submission", _("Submission"), 180),
            ("current", _("Current workbook"), 330),
            ("expected", _("Name with this template"), 330),
        ):
            self.preview.heading(column, text=heading)
            self.preview.column(column, width=width, stretch=True)
        self.preview.grid(row=4, column=0, columnspan=4, sticky="nsew", pady=(4, 0))
        buttons = ttk.Frame(tab)
        buttons.grid(row=5, column=0, columnspan=4, sticky="w", pady=(PAD, 0))
        ttk.Button(buttons, text=_("Update preview"), command=self.update_preview).pack(
            side="left", padx=(0, 4)
        )
        ttk.Button(buttons, text=_("Organize workbooks..."), command=self.organize_workbooks).pack(
            side="left"
        )
        ttk.Checkbutton(
            tab,
            text=_(
                "Add a 'Time in status' sheet to every workbook: how long each submission "
                "spent in each status (updated after every change)"
            ),
            variable=self.time_sheet_var,
        ).grid(row=6, column=0, columnspan=4, sticky="w", pady=(PAD, 0))
        tab.columnconfigure(1, weight=1)
        tab.rowconfigure(4, weight=1)

    def _build_run_tab(self) -> None:
        tab = self._tab(_("Run"))
        buttons = ttk.Frame(tab)
        buttons.grid(row=0, column=0, columnspan=2, sticky="w")
        self.run_button = ttk.Button(buttons, text=_("Run now"), command=self.run_check)
        self.run_button.pack(side="left", padx=(0, 4))
        self.dry_run_button = ttk.Button(
            buttons, text=_("Dry run"), command=lambda: self.run_check(dry_run=True)
        )
        self.dry_run_button.pack(side="left", padx=(0, 4))
        ttk.Button(buttons, text=_("Open last report"), command=self.open_last_report).pack(
            side="left", padx=(0, 4)
        )
        ttk.Button(buttons, text=_("Open reports folder"), command=self.open_reports_dir).pack(
            side="left"
        )
        self._note(
            tab,
            _(
                "Runs use the settings shown in this window, even before they are saved. "
                "A dry run checks the tracker without writing anything."
            ),
        ).grid(row=1, column=0, columnspan=2, sticky="w", pady=(4, 0))
        self.output = tk.Text(tab, height=14, wrap="word", state="disabled", font="TkFixedFont")
        scroll = ttk.Scrollbar(tab, orient="vertical", command=self.output.yview)
        self.output.configure(yscrollcommand=scroll.set)
        self.output.grid(row=2, column=0, sticky="nsew", pady=(PAD, 0))
        scroll.grid(row=2, column=1, sticky="ns", pady=(PAD, 0))
        ttk.Label(tab, textvariable=self.last_run_var).grid(
            row=3, column=0, columnspan=2, sticky="w", pady=(4, 0)
        )
        settings = ttk.Frame(tab)
        settings.grid(row=4, column=0, columnspan=2, sticky="w", pady=(PAD, 0))
        ttk.Label(settings, text=_("Seconds to wait for each answer from the tracker")).pack(
            side="left"
        )
        ttk.Spinbox(settings, from_=1, to=600, textvariable=self.timeout_var, width=6).pack(
            side="left", padx=4
        )
        auto = ttk.LabelFrame(tab, text=_("Run automatically at login"), padding=PAD)
        auto.grid(row=5, column=0, columnspan=2, sticky="ew", pady=(PAD, 0))
        ttk.Label(auto, textvariable=self.autostart_var, wraplength=820, justify="left").grid(
            row=0, column=0, columnspan=6, sticky="w"
        )
        ttk.Label(auto, text=_("Wait for the network and the data folder up to")).grid(
            row=1, column=0, sticky="w", pady=(4, 0)
        )
        ttk.Spinbox(auto, from_=0, to=3600, textvariable=self.wait_var, width=6).grid(
            row=1, column=1, padx=4, pady=(4, 0)
        )
        ttk.Label(auto, text=_("seconds")).grid(row=1, column=2, sticky="w", pady=(4, 0))
        self.autostart_buttons = [
            ttk.Button(auto, text=_("Enable"), command=self.enable_autostart),
            ttk.Button(auto, text=_("Disable"), command=self.disable_autostart),
            ttk.Button(auto, text=_("Refresh"), command=self.refresh_autostart),
        ]
        for index, button in enumerate(self.autostart_buttons, start=3):
            button.grid(row=1, column=index, padx=(PAD, 0), pady=(4, 0))
        ttk.Label(auto, text=_("Then check again every")).grid(
            row=2, column=0, sticky="w", pady=(4, 0)
        )
        ttk.Spinbox(auto, from_=0, to=168, textvariable=self.every_var, width=6).grid(
            row=2, column=1, padx=4, pady=(4, 0)
        )
        ttk.Label(auto, text=_("hours while you stay logged in (0 = only at login)")).grid(
            row=2, column=2, columnspan=4, sticky="w", pady=(4, 0)
        )
        tray_box = ttk.Checkbutton(
            auto,
            text=_(
                "Show an icon in the notification area while checking periodically, with the "
                "latest statuses (Windows)"
            ),
            variable=self.tray_var,
        )
        tray_box.grid(row=3, column=0, columnspan=6, sticky="w", pady=(4, 0))
        if not tray.is_supported():
            tray_box.state(["disabled"])
        tab.columnconfigure(0, weight=1)
        tab.rowconfigure(2, weight=1)

    def change_language(self, code: str) -> None:
        """Show the window in another language, keeping everything typed so far.

        The language is also that of the reports: it is written to the
        configuration file with the other settings when you click *Save*.
        """
        self._rebuild(code)
        self.status_var.set(
            _("Unsaved changes: click Save to keep them.")
            if self.dirty
            else _("Configuration: {path}").format(path=self.config_path)
        )
        self.update_selection_summary()
        self.update_placeholders()
        self.refresh_statuses()
        self.update_preview()
        self.refresh_autostart(keep_values=True)
        self.refresh_last_run()

    def _rebuild(self, code: str) -> None:
        """Build the widgets again in the language *code* (the values are kept)."""
        code = i18n.set_language(code)
        tab = self.notebook.index("current")
        output = self.output.get("1.0", "end-1c")
        if self._outer is not None:
            self._outer.destroy()
        self._build()
        self.notebook.select(tab)
        self.write_output(output)
        self._set_running(self._running)
        self._loading = True
        try:
            self.language_var.set(i18n.language_name(code))
        finally:
            self._loading = False
        self.populate_tree()

    def _selected_language(self) -> str:
        """The code of the language chosen at the bottom of the window."""
        names = {name: code for code, name in i18n.LANGUAGES.items()}
        return names.get(self.language_var.get(), i18n.get_language())

    def _on_language_selected(self, *_args: object) -> None:
        if self._loading:
            return
        code = self._selected_language()
        if code == i18n.get_language():
            return
        self.mark_dirty()
        if self.synchronous:
            self.change_language(code)
        else:  # not while the list of the combobox that triggered it is still busy
            self.root.after_idle(lambda: self.change_language(code))

    # ------------------------------------------------------------------ configuration

    def load(self) -> None:
        """Show the configuration file (or the defaults if it does not exist)."""
        problem = None
        config = Config(data_dir=paths.default_data_dir(), path=self.config_path)
        if self.config_path.is_file():
            try:
                config = load_config(self.config_path)
            except ConfigError as exc:
                problem = str(exc)
                # Keep the language of the file, even though another setting is invalid.
                config = replace(config, language=gui.configured_language(self.config_path))
        self._loading = True
        try:
            self._show_config(config)
        finally:
            self._loading = False
        if config.language != i18n.get_language():
            self._rebuild(config.language)
        if not self.config_path.is_file():
            self.dirty = True
            self.status_var.set(
                _("New configuration: it will be created at {path} when you click Save.").format(
                    path=self.config_path
                )
            )
        else:
            self.dirty = problem is not None
            self.status_var.set(_("Configuration: {path}").format(path=self.config_path))
        self.update_selection_summary()
        self.update_placeholders()
        self.refresh_statuses()
        self.update_preview()
        self.refresh_autostart()
        self.refresh_last_run()
        if problem is not None:
            self.show_error(
                _("Invalid configuration"),
                _(
                    "{problem}\n\nThe window shows the default settings. Fix the file in a text "
                    "editor and click Reload, or save these settings to replace it (the old "
                    "file is kept as {backup})."
                ).format(problem=problem, backup=f"{self.config_path.name}.bak"),
            )

    def _show_config(self, config: Config) -> None:
        self.data_dir_var.set(str(config.data_dir))
        self.template_var.set(config.workbook_name)
        self.language_var.set(i18n.language_name(config.language))
        self.open_report_var.set("report" in config.notify)
        self.toast_var.set("toast" in config.notify)
        self.email_var.set("email" in config.notify)
        self.email_settings = config.email
        self.notify_errors_var.set(config.notify_on_errors)
        self.time_sheet_var.set(config.time_in_status)
        timeout = config.request_timeout
        self.timeout_var.set(str(int(timeout)) if float(timeout).is_integer() else str(timeout))
        recorded, notified = set(config.recorded_columns), set(config.notified_columns)
        for column, variable in self.record_vars.items():
            variable.set(column in recorded)
        for column, variable in self.notify_vars.items():
            variable.set(column in notified)
        self.submissions = list(config.submissions)
        self.statuses.clear()
        self.workbooks.clear()
        self.populate_tree()

    def collect(self) -> Config:
        """Return the configuration shown in the window.

        Raises:
            ConfigError: If a value is not valid.
        """
        return gui.build_config(
            data_dir=self.data_dir_var.get(),
            workbook_name=self.template_var.get(),
            recorded=[column for column, var in self.record_vars.items() if var.get()],
            notified=[column for column, var in self.notify_vars.items() if var.get()],
            notify=self._channels(),
            notify_on_errors=self.notify_errors_var.get(),
            request_timeout=self.timeout_var.get(),
            submissions=self.submissions,
            path=self.config_path,
            time_in_status=self.time_sheet_var.get(),
            email=self.email_settings,
            language=self._selected_language(),
        )

    def _channels(self) -> list[str]:
        """How the user wants to be told about news, from the tick boxes."""
        chosen = (
            ("report", self.open_report_var),
            ("toast", self.toast_var),
            ("email", self.email_var),
        )
        return [channel for channel, variable in chosen if variable.get()]

    def save(self) -> bool:
        """Write the configuration file. Return ``True`` on success."""
        try:
            config = self.collect()
            save_config(config, self.config_path)
        except ConfigError as exc:
            self.show_error(_("The settings cannot be saved"), str(exc))
            return False
        except OSError as exc:
            self.show_error(_("The settings cannot be saved"), f"{self.config_path}: {exc}")
            return False
        self.dirty = False
        backup = self.config_path.with_name(f"{self.config_path.name}.bak")
        if backup.exists():
            message = _("Saved {path} (previous version: {backup})").format(
                path=self.config_path, backup=backup.name
            )
        else:
            message = _("Saved {path}").format(path=self.config_path)
        self.status_var.set(message)
        return True

    def reload(self) -> None:
        """Read the configuration file again, discarding unsaved changes."""
        if (
            self.dirty
            and self.config_path.is_file()
            and not self.ask_yes_no(_("Discard changes?"), _("Discard the unsaved changes?"))
        ):
            return
        self.load()

    def close(self) -> None:
        """Close the window, offering to save unsaved changes."""
        if self.dirty:
            answer = self.ask_yes_no_cancel(
                _("Unsaved changes"), _("Save the changes before closing?")
            )
            if answer is None or (answer and not self.save()):
                return
        self.root.destroy()

    def mark_dirty(self) -> None:
        """Remember that the window has unsaved changes."""
        self.dirty = True
        self.status_var.set(_("Unsaved changes: click Save to keep them."))

    def _on_change(self, *_args: object) -> None:
        if self._loading:
            return
        self.mark_dirty()
        self.update_selection_summary()

    def _data_dir(self) -> Path:
        text = os.path.expandvars(self.data_dir_var.get().strip())
        if not text:
            return paths.default_data_dir()
        path = Path(text).expanduser()
        return path if path.is_absolute() else self.config_path.parent / path

    def _timeout(self) -> float:
        try:
            return max(1.0, float(self.timeout_var.get().replace(",", ".")))
        except ValueError:
            return 30.0

    # ------------------------------------------------------------------ submissions

    def populate_tree(self, select: str | None = None) -> None:
        """Show the submissions in the list."""
        self.tree.delete(*self.tree.get_children())
        for submission in self.submissions:
            monitored = _("yes") if submission.enabled else _("no (paused)")
            if submission.overrides:
                monitored += " *"
            self.tree.insert(
                "",
                "end",
                iid=submission.uuid,
                values=(
                    submission.label or _("(no label)"),
                    gui.format_fields_inline(submission.fields),
                    monitored,
                    self.statuses.get(submission.uuid, ""),
                ),
            )
        if select and self.tree.exists(select):
            self.tree.selection_set(select)
            self.tree.see(select)

    def selected_submission(self, *, quiet: bool = False) -> SubmissionConfig | None:
        """Return the submission selected in the list, or ``None``."""
        selection = self.tree.selection()
        uuid = selection[0] if selection else None
        submission = next((s for s in self.submissions if s.uuid == uuid), None)
        if submission is None and not quiet:
            self.show_info(_("No submission selected"), _("Select a submission in the list first."))
        return submission

    def add_submission(self) -> SubmissionDialog:
        """Open the window to add a submission."""
        return SubmissionDialog(self, None)

    def edit_submission(self) -> SubmissionDialog | None:
        """Open the window to edit the selected submission."""
        submission = self.selected_submission()
        return SubmissionDialog(self, submission) if submission is not None else None

    def store_submission(
        self, submission: SubmissionConfig, original: SubmissionConfig | None = None
    ) -> None:
        """Add *submission*, or put it in place of *original*."""
        if original is None:
            self.submissions.append(submission)
        else:
            self.submissions[self.submissions.index(original)] = submission
        self.populate_tree(select=submission.uuid)
        self.mark_dirty()
        self.update_placeholders()
        self.refresh_statuses()

    def remove_submission(self) -> None:
        """Remove the selected submission (its workbook is kept)."""
        submission = self.selected_submission()
        if submission is None:
            return
        question = _(
            "Stop monitoring {name}?\n\nIts workbook is not deleted. To stop checking it "
            "temporarily, use Pause / resume instead."
        ).format(name=submission.display_name)
        if self.ask_yes_no(_("Remove submission"), question):
            self.submissions.remove(submission)
            self.populate_tree()
            self.mark_dirty()
            self.update_placeholders()

    def toggle_submission(self) -> None:
        """Pause or resume the selected submission."""
        submission = self.selected_submission()
        if submission is None:
            return
        self.store_submission(replace(submission, enabled=not submission.enabled), submission)

    def verify_and_store(self, submission: SubmissionConfig, dialog: SubmissionDialog) -> None:
        """Check a new submission with the tracker, then add it."""
        timeout = self._timeout()

        def work() -> Any:
            with TrackerClient(timeout=timeout) as client:
                return client.fetch(submission.uuid)

        def done(snapshot: Any) -> None:
            dialog.close()
            self.store_submission(submission)
            self.show_info(
                _("Submission added"),
                _(
                    "Found: {title}\n{journal} - {number} - {status}\n\nClick Save to keep it."
                ).format(
                    title=snapshot.display_title,
                    journal=snapshot.journal,
                    number=snapshot.manuscript_number,
                    status=snapshot.status,
                ),
            )

        def failed(error: BaseException) -> None:
            question = _(
                "The tracker could not confirm this link:\n{error}\n\nAdd the submission anyway?"
            ).format(error=error)
            if self.ask_yes_no(_("Add it anyway?"), question, parent=dialog.window):
                dialog.close()
                self.store_submission(submission)

        self.run_in_background(work, done, failed)

    def check_submission(self) -> None:
        """Show what the tracker says now about the selected submission."""
        submission = self.selected_submission()
        if submission is None:
            return
        timeout = self._timeout()

        def work() -> Any:
            with TrackerClient(timeout=timeout) as client:
                return client.fetch(submission.uuid)

        def done(snapshot: Any) -> None:
            record = snapshot.to_record()
            record[TRACKER_URL_COLUMN] = submission.tracker_url
            labels = {column: column_label(column) for column in record}
            width = max(len(label) for label in labels.values()) + 1
            text = "\n".join(
                f"{labels[column] + ':':<{width}} {value or '-'}"
                for column, value in record.items()
            )
            title = _("Current status - {name}").format(name=submission.display_name)
            self.text_window(title, text)

        self.run_in_background(work, done)

    def open_workbook(self) -> None:
        """Open the workbook of the selected submission with the default application."""
        submission = self.selected_submission()
        if submission is None:
            return
        path = self.workbooks.get(submission.uuid)
        if path is None or not path.exists():
            self.show_info(
                _("No workbook yet"),
                _("This submission has not been recorded yet: run a check first."),
            )
            return
        report.open_path(path)

    def refresh_statuses(self) -> None:
        """Read the last recorded status of every submission from the workbooks."""
        data_dir = self._data_dir()
        submissions = list(self.submissions)

        def work() -> dict[str, storage.WorkbookLocation | None]:
            store = storage.WorkbookStore(data_dir)
            return {s.uuid: store.locate_uuid(s.uuid) for s in submissions}

        def done(locations: dict[str, storage.WorkbookLocation | None]) -> None:
            self.statuses.clear()
            self.workbooks.clear()
            for uuid, location in locations.items():
                if location is None or location.last_record is None:
                    self.statuses[uuid] = _("not recorded yet")
                    continue
                record = location.last_record
                detected = record.get(DETECTED_AT_COLUMN) or _("unknown date")
                status = record.get("Status") or "-"
                self.statuses[uuid] = _("{status} ({date}) in {workbook}").format(
                    status=status, date=detected, workbook=location.path.name
                )
                self.workbooks[uuid] = location.path
            selected = self.selected_submission(quiet=True)
            self.populate_tree(select=selected.uuid if selected else None)

        self.run_in_background(work, done)

    def show_summary(self) -> None:
        """Show the latest recorded status of every submission in one table."""
        try:
            config = self.collect()
        except ConfigError as exc:
            self.show_error(_("Invalid settings"), str(exc))
            return

        def done(rows: list[status_summary.SummaryRow]) -> None:
            self.text_window(
                _("Summary"),
                status_summary.render_summary(rows, "text"),
                action=(_("Save..."), lambda: self.save_summary(rows)),
                wrap="none",
            )

        self.run_in_background(lambda: status_summary.summary_rows(config), done)

    def export_history(self) -> Path | None:
        """Save the recorded history of every submission as CSV or JSON, as chosen."""
        try:
            config = self.collect()
        except ConfigError as exc:
            self.show_error(_("Invalid settings"), str(exc))
            return None
        target = filedialog.asksaveasfilename(
            parent=self.root,
            title=_("Export the history (without the tracking links)"),
            initialfile="paper-status-history.csv",
            defaultextension=".csv",
            filetypes=[("CSV", "*.csv"), ("JSON", "*.json")],
        )
        if not target:
            return None
        path = Path(target)
        fmt = "json" if path.suffix.lower() == ".json" else "csv"
        try:
            histories = history_export.collect_history(config)
            path.write_bytes(history_export.render_export(histories, fmt).encode("utf-8"))
        except OSError as exc:
            self.show_error(_("The history cannot be exported"), f"{path}: {exc}")
            return None
        self.status_var.set(_("History exported to {path}").format(path=path))
        return path

    def save_summary(self, rows: list[status_summary.SummaryRow]) -> Path | None:
        """Save the summary as an HTML page, a Markdown table or text, as chosen."""
        target = filedialog.asksaveasfilename(
            parent=self.root,
            title=_("Save the summary"),
            initialfile="paper-status-summary.html",
            defaultextension=".html",
            filetypes=[(_("HTML page"), "*.html"), ("Markdown", "*.md"), (_("Text"), "*.txt")],
        )
        if not target:
            return None
        path = Path(target)
        fmt = {".md": "markdown", ".txt": "text"}.get(path.suffix.lower(), "html")
        try:
            path.write_text(status_summary.render_summary(rows, fmt), encoding="utf-8")
        except OSError as exc:
            self.show_error(_("The summary cannot be saved"), f"{path}: {exc}")
            return None
        self.status_var.set(_("Summary saved to {path}").format(path=path))
        return path

    # ------------------------------------------------------------------ notifications

    def _set_all(self, variables: dict[str, tk.BooleanVar], value: bool) -> None:
        for variable in variables.values():
            variable.set(value)

    def _set_only(self, variables: dict[str, tk.BooleanVar], columns: Iterable[str]) -> None:
        chosen = set(columns)
        for column, variable in variables.items():
            variable.set(column in chosen)

    def send_test_notification(self) -> None:
        """Show a desktop notification, to check that this computer displays them."""

        def done(_result: object) -> None:
            self.show_info(
                _("Test notification"),
                _(
                    "A test notification was sent. If you did not see it, check the "
                    "notification settings of your system (focus assist, do not disturb...)."
                ),
            )

        def failed(error: BaseException) -> None:
            hint = notifications.unavailable_reason()
            message = _("The notification could not be shown: {error}").format(error=error)
            self.show_error(_("No desktop notification"), message + (f"\n\n{hint}" if hint else ""))

        sample = notifications.sample_notification()
        self.run_in_background(lambda: notifications.show(sample), done, failed)

    def edit_email_settings(self) -> EmailDialog:
        """Open the window to choose how e-mails are sent."""
        return EmailDialog(self)

    def send_test_email(self) -> None:
        """Send a test e-mail with the settings shown in the window (even if not saved)."""
        settings = self.email_settings
        if settings.missing:
            self.show_error(
                _("E-mail settings needed"),
                _("Fill in {settings} with Settings... first.").format(
                    settings=", ".join(settings.missing)
                ),
            )
            return

        def work() -> None:
            password = emails.smtp_password(settings)
            emails.send(emails.sample_message(settings), settings, password=password)

        def done(_result: object) -> None:
            self.show_info(
                _("Test e-mail"),
                _(
                    "A test e-mail was sent to {recipients}. Check the inbox (and the spam folder)."
                ).format(recipients=", ".join(settings.to)),
            )

        def failed(error: BaseException) -> None:
            self.show_error(
                _("No e-mail"), _("The e-mail could not be sent: {error}").format(error=error)
            )

        self.run_in_background(work, done, failed)

    def update_selection_summary(self) -> None:
        """Describe in words what is recorded and what is notified."""
        recorded = [column for column, var in self.record_vars.items() if var.get()]
        notified = [column for column, var in self.notify_vars.items() if var.get()]
        self.selection_var.set(
            _("Recorded: {recorded}.\n\nNotified: {notified}.").format(
                recorded=describe_columns(recorded), notified=describe_columns(notified)
            )
        )

    # ------------------------------------------------------------------ workbooks

    def update_placeholders(self) -> None:
        """List the placeholders, including the custom fields of the submissions."""
        names = {name for submission in self.submissions for name in submission.fields}
        self.placeholders_var.set(gui.placeholders_help(names))

    def browse_data_dir(self) -> None:
        """Choose the data folder with a folder dialog."""
        current = self._data_dir()
        chosen = filedialog.askdirectory(
            parent=self.root,
            title=_("Folder for the workbooks and the reports"),
            initialdir=str(current if current.is_dir() else Path.home()),
        )
        if chosen:
            self.data_dir_var.set(str(Path(chosen)))
            self.refresh_statuses()

    def open_data_dir(self) -> None:
        """Open the data folder in the file manager."""
        folder = self._data_dir()
        if not folder.is_dir():
            self.show_info(
                _("Folder not found"),
                _("{folder} does not exist yet; the first run creates it.").format(folder=folder),
            )
            return
        report.open_path(folder)

    def apply_preset(self, _event: object = None) -> None:
        """Copy the chosen preset into the workbook name."""
        template = self._presets.get(self.preset_var.get())
        if template:
            self.template_var.set(template)
            self.update_preview()

    def _schedule_preview(self, *_args: object) -> None:
        if self._loading or self.synchronous:
            return
        if self._preview_job is not None:
            self.root.after_cancel(self._preview_job)
        self._preview_job = self.root.after(700, self._scheduled_preview)

    def _scheduled_preview(self) -> None:
        self._preview_job = None
        self.update_preview()

    def update_preview(self) -> None:
        """Show the name every submission gets with the current template."""
        try:
            config = self.collect()
        except ConfigError as exc:
            self.preview_message_var.set(str(exc))
            self._fill_preview([])
            return
        self.preview_message_var.set("")
        self.run_in_background(lambda: gui.preview_rows(config), self._fill_preview)

    def _fill_preview(self, rows: list[tuple[str, str, str]]) -> None:
        self.preview.delete(*self.preview.get_children())
        for row in rows:
            self.preview.insert("", "end", values=row)

    def organize_workbooks(self) -> None:
        """Show (and optionally apply) the renames and merges needed by the template."""
        if self.dirty:
            question = _(
                "Workbooks are organized with the saved settings. Save the current settings now?"
            )
            if not self.ask_yes_no(_("Save first?"), question) or not self.save():
                return
        try:
            config = self.collect()
        except ConfigError as exc:
            self.show_error(_("Invalid settings"), str(exc))
            return
        self.run_in_background(
            lambda: organize.plan_organize(config), lambda plan: self._show_plan(config, plan)
        )

    def _show_plan(self, config: Config, plan: organize.OrganizePlan) -> tk.Toplevel:
        if plan.actions:
            lines = [action.describe() for action in plan.actions]
        elif any(name.current is not None for name in plan.names):
            lines = [_("Nothing to do: the workbooks follow the naming template.")]
        else:
            lines = [_("No recorded submissions yet.")]
        if plan.skipped:
            lines += ["", _("Left as they are:"), *(f"- {line}" for line in plan.skipped)]
        action = None
        if plan.actions:
            lines += [
                "",
                _(
                    "Before merging or splitting, a copy of every workbook involved is saved in "
                    "the 'backups' subfolder of the data folder. Close the workbooks in Excel "
                    "first."
                ),
            ]
            action = (_("Apply"), lambda: self.apply_plan(config, plan))
        return self.text_window(_("Organize workbooks"), "\n".join(lines), action=action)

    def apply_plan(self, config: Config, plan: organize.OrganizePlan) -> None:
        """Rename and merge the workbooks as planned."""

        def work() -> organize.OrganizeOutcome:
            with state.single_instance():
                return organize.apply_organize(plan, config)

        def done(outcome: organize.OrganizeOutcome) -> None:
            lines = list(outcome.done)
            if outcome.backup_dir is not None:
                lines.append(
                    _("Copies of the workbooks before merging or splitting: {folder}").format(
                        folder=outcome.backup_dir
                    )
                )
            lines += [_("Problem: {problem}").format(problem=line) for line in outcome.errors]
            message = "\n".join(lines) or _("Nothing was changed.")
            if outcome.errors:
                self.show_error(_("Organize workbooks"), message)
            else:
                self.show_info(_("Organize workbooks"), message)
            self.refresh_statuses()
            self.update_preview()

        self.run_in_background(work, done)

    # ------------------------------------------------------------------ run

    def run_check(self, dry_run: bool = False) -> None:
        """Check every enabled submission now (like ``paper-status-monitor run``)."""
        try:
            config = self.collect()
        except ConfigError as exc:
            self.show_error(_("Invalid settings"), str(exc))
            return
        if not config.enabled_submissions:
            self.show_info(
                _("Nothing to check"), _("There are no monitored submissions: add one first.")
            )
            return
        self._set_running(True)
        count = len(config.enabled_submissions)
        if dry_run:
            start = ngettext(
                "Dry run of {count} submission...", "Dry run of {count} submissions...", count
            )
        else:
            start = ngettext(
                "Checking {count} submission...", "Checking {count} submissions...", count
            )
        self.write_output(start.format(count=count) + "\n")

        def work() -> tuple[Any, Path | None]:
            with state.single_instance():
                monitor = Monitor(config)
                try:
                    summary = monitor.run(dry_run=dry_run)
                finally:
                    monitor.client.close()
                path = None
                if not dry_run:
                    path = report.publish_report(summary, config)
                    state.save_last_run(summary)
            return summary, path

        def done(result: tuple[Any, Path | None]) -> None:
            summary, path = result
            text = report.render_console(summary)
            if path is not None:
                text += "\n" + _("Report: {path}").format(path=path)
            if dry_run:
                text += "\n" + _("(dry run: nothing was written)")
            self.write_output(text + "\n\n")
            self._set_running(False)
            self.refresh_statuses()
            self.refresh_last_run()

        def failed(error: BaseException) -> None:
            self._set_running(False)
            self.write_output(_("Error: {error}").format(error=error) + "\n\n")
            self.show_error(_("The check could not run"), str(error))

        self.run_in_background(work, done, failed)

    def _set_running(self, running: bool) -> None:
        self._running = running
        for button in (self.run_button, self.dry_run_button):
            button.state(["disabled"] if running else ["!disabled"])

    def write_output(self, text: str) -> None:
        """Append *text* to the output box of the Run tab."""
        self.output.configure(state="normal")
        self.output.insert("end", text)
        self.output.see("end")
        self.output.configure(state="disabled")

    def open_last_report(self) -> None:
        """Open the report of the last run, if there is one."""
        last_run = state.load_last_run() or {}
        name = last_run.get("report")
        if name and Path(name).exists():
            report.open_path(Path(name))
        else:
            self.show_info(
                _("No report"), _("The last run did not write a report (nothing changed).")
            )

    def open_reports_dir(self) -> None:
        """Open the folder that holds the reports."""
        folder = self._data_dir() / "reports"
        if not folder.is_dir():
            folder = paths.fallback_reports_dir()
        if not folder.is_dir():
            self.show_info(_("No reports yet"), _("No report has been written yet."))
            return
        report.open_path(folder)

    def refresh_last_run(self) -> None:
        """Show when the last run finished."""
        last_run = state.load_last_run()
        if not last_run:
            self.last_run_var.set(_("No completed run recorded yet."))
            return
        finished = str(last_run.get("finished_at", "?")).replace("T", " ")
        self.last_run_var.set(
            _(
                "Last run: {finished} - {checked} checked, {changed} with news, {failed} failed."
            ).format(
                finished=finished,
                checked=last_run.get("checked", 0),
                changed=last_run.get("changed", 0),
                failed=last_run.get("failed", 0),
            )
        )

    def refresh_autostart(self, *, keep_values: bool = False) -> None:
        """Show whether the monitor runs at login.

        Args:
            keep_values: Only describe the launcher, without replacing the waiting
                time, the interval and the icon choice typed in the window.
        """
        if not autostart.is_supported():
            self.autostart_var.set(
                _(
                    "Built-in autostart is not available on this system. See 'Running at "
                    "login' in the documentation."
                )
            )
            for button in self.autostart_buttons:
                button.state(["disabled"])
            return

        def done(info: autostart.LauncherInfo | None) -> None:
            if info is None:
                self.autostart_var.set(
                    _(
                        "Not enabled: the monitor does not run when you log in. Enable creates "
                        "{launcher}."
                    ).format(launcher=autostart.describe_launcher())
                )
                return
            if not keep_values:
                if info.wait is not None:
                    self.wait_var.set(str(info.wait))
                self.every_var.set(gui.format_hours(info.every))
                self.tray_var.set(info.tray)
            if not info.target_exists:
                self.autostart_var.set(
                    _(
                        "Broken: the interpreter {target} does not exist any more. Click "
                        "Enable to repair it."
                    ).format(target=info.target)
                )
                return
            if info.every is None:
                when = _("every time you log in")
            elif info.tray:
                when = _(
                    "every time you log in and then every {hours} hours, with an icon in the "
                    "notification area"
                ).format(hours=gui.format_hours(info.every))
            else:
                when = _("every time you log in and then every {hours} hours").format(
                    hours=gui.format_hours(info.every)
                )
            self.autostart_var.set(
                _("Enabled: {when}, {launcher} runs {target} {arguments}").format(
                    when=when,
                    launcher=info.path.name,
                    target=info.target,
                    arguments=info.arguments,
                )
            )

        def failed(error: BaseException) -> None:
            self.autostart_var.set(
                _("The autostart launcher could not be read: {error}").format(error=error)
            )

        self.run_in_background(autostart.status, done, failed)

    def enable_autostart(self) -> None:
        """Run the monitor at every login (Startup shortcut, autostart entry or launchd agent)."""
        if self.dirty or not self.config_path.is_file():
            question = _(
                "The monitor started at login reads the saved configuration. Save the current "
                "settings now?"
            )
            if not self.ask_yes_no(_("Save first?"), question) or not self.save():
                return
        try:
            wait = int(self.wait_var.get())
        except ValueError:
            self.show_error(
                _("Invalid value"), _("The waiting time must be a whole number of seconds.")
            )
            return
        try:
            every = gui.parse_hours(self.every_var.get())
        except ConfigError as exc:
            self.show_error(_("Invalid value"), str(exc))
            return
        show_icon = self.tray_var.get() and tray.is_supported()
        if show_icon and every is None:
            self.show_error(
                _("Invalid value"),
                _(
                    "The icon is shown while the periodic checks run: choose how often to check "
                    "again (at least every hour), or untick the icon."
                ),
            )
            return
        custom = self.config_path.resolve() != paths.default_config_path().resolve()
        config_path = self.config_path.resolve() if custom else None

        def done(path: Path) -> None:
            if every is None:
                when = _("every time you log in")
            else:
                when = _(
                    "every time you log in, and then every {hours} hours while you stay logged "
                    "in (starting with your next login)"
                ).format(hours=gui.format_hours(every))
            message = _("The monitor will run in the background {when}.\n\n{path}").format(
                when=when, path=path
            )
            if show_icon:
                message += "\n\n" + _(
                    "An icon in the notification area shows the latest statuses while the "
                    "periodic checks run."
                )
            self.show_info(_("Autostart enabled"), message)
            self.refresh_autostart()

        self.run_in_background(
            lambda: autostart.enable(
                wait=wait, config_path=config_path, every=every, tray=show_icon
            ),
            done,
        )

    def disable_autostart(self) -> None:
        """Stop running the monitor at login."""

        def done(removed: bool) -> None:
            self.show_info(
                _("Autostart"),
                _("Autostart disabled.") if removed else _("Autostart was not enabled."),
            )
            self.refresh_autostart()

        self.run_in_background(autostart.disable, done)

    # ------------------------------------------------------------------ helpers

    def open_config_file(self) -> None:
        """Open the configuration file in the default text editor."""
        if not self.config_path.is_file():
            self.show_info(
                _("Not saved yet"), _("The configuration file does not exist yet: click Save.")
            )
            return
        report.open_path(self.config_path)

    def open_log_file(self) -> None:
        """Open the log file."""
        log_file = paths.log_file_path()
        if log_file.is_file():
            report.open_path(log_file)
        else:
            self.show_info(_("No log file"), _("{path} does not exist yet.").format(path=log_file))

    def about(self) -> None:
        """Show the version and where things are."""
        self.show_info(
            _("About paper-status-monitor"),
            f"paper-status-monitor {__version__}\n\n"
            + _(
                "Monitor the peer-review status of your Elsevier submissions.\n"
                "Not affiliated with Elsevier.\n\n"
                "Configuration: {config}\nLog file: {log}"
            ).format(config=self.config_path, log=paths.log_file_path())
            + f"\n\n{DOCS_URL}",
        )

    def text_window(
        self,
        title: str,
        text: str,
        *,
        action: tuple[str, Callable[[], None]] | None = None,
        wrap: str = "word",
    ) -> tk.Toplevel:
        """Open a window that shows *text*, with an optional action button.

        With ``wrap="none"`` (for tables), lines are not wrapped: the window is as wide
        as the longest line, up to a limit, and scrolls horizontally.
        """
        window = tk.Toplevel(self.root)
        window.title(title)
        window.transient(self.root)
        frame = ttk.Frame(window, padding=PAD)
        frame.pack(fill="both", expand=True)
        height = min(30, max(8, text.count("\n") + 2))
        width = 100
        if wrap == "none":
            longest = max((len(line) for line in text.splitlines()), default=0)
            width = max(40, min(180, longest + 2))
        box = tk.Text(frame, wrap=wrap, width=width, height=height, font="TkFixedFont")
        box.insert("1.0", text)
        box.configure(state="disabled")
        box.pack(fill="both", expand=True)
        if wrap == "none":
            scroll = ttk.Scrollbar(frame, orient="horizontal", command=box.xview)
            box.configure(xscrollcommand=scroll.set)
            scroll.pack(fill="x")
        buttons = ttk.Frame(frame)
        buttons.pack(fill="x", pady=(PAD, 0))
        ttk.Button(buttons, text=_("Close"), command=window.destroy).pack(side="right")
        if action is not None:
            label, callback = action

            def run_action() -> None:
                window.destroy()
                callback()

            ttk.Button(buttons, text=label, command=run_action).pack(side="right", padx=(0, 4))
        window.bind("<Escape>", lambda _event: window.destroy())
        return window

    def show_error(self, title: str, message: str, *, parent: tk.Misc | None = None) -> None:
        """Show an error message."""
        messagebox.showerror(title, message, parent=parent or self.root)

    def show_info(self, title: str, message: str, *, parent: tk.Misc | None = None) -> None:
        """Show an information message."""
        messagebox.showinfo(title, message, parent=parent or self.root)

    def ask_yes_no(self, title: str, message: str, *, parent: tk.Misc | None = None) -> bool:
        """Ask a yes/no question."""
        return bool(messagebox.askyesno(title, message, parent=parent or self.root))

    def ask_yes_no_cancel(self, title: str, message: str) -> bool | None:
        """Ask a yes/no/cancel question (``None`` means cancel)."""
        return messagebox.askyesnocancel(title, message, parent=self.root)

    # ------------------------------------------------------------------ background work

    def run_in_background(
        self,
        work: Callable[[], Any],
        on_done: Callable[[Any], None],
        on_error: Callable[[BaseException], None] | None = None,
    ) -> None:
        """Run *work* in a thread and pass its result to *on_done* in the Tk thread."""
        handle_error = on_error or self._background_error
        if self.synchronous:
            try:
                value = work()
            except Exception as exc:
                handle_error(exc)
            else:
                on_done(value)
            return
        self._busy += 1
        self._update_cursor()

        def target() -> None:
            try:
                value = work()
            except Exception as exc:
                error = exc
                self._tasks.put(lambda: self._finish(handle_error, error))
            else:
                self._tasks.put(lambda: self._finish(on_done, value))

        threading.Thread(target=target, daemon=True).start()

    def _finish(self, callback: Callable[[Any], None], value: Any) -> None:
        self._busy -= 1
        self._update_cursor()
        callback(value)

    def _update_cursor(self) -> None:
        with contextlib.suppress(tk.TclError):
            self.root.configure(cursor="watch" if self._busy else "")

    def _poll(self) -> None:
        while True:
            try:
                task = self._tasks.get_nowait()
            except queue.Empty:
                break
            try:
                task()
            except Exception:
                log.exception("Error in the graphical interface")
        with contextlib.suppress(tk.TclError):
            self.root.after(100, self._poll)

    def _background_error(self, error: BaseException) -> None:
        log.error("Background task failed: %s", error)
        self.show_error(_("Error"), str(error) or type(error).__name__)

    def _callback_error(
        self,
        exc_type: type[BaseException],
        exc: BaseException,
        traceback: TracebackType | None,
    ) -> None:
        log.error("Error in the graphical interface", exc_info=(exc_type, exc, traceback))
        self.show_error(_("Unexpected error"), f"{exc_type.__name__}: {exc}")


class SubmissionDialog:
    """Window to add a submission or edit one.

    Besides the link, the label and the custom fields, the submission can have its own
    choice of what is recorded and notified; it is only written if the user changes
    it, so own settings written by hand are kept otherwise.

    Args:
        app: The main window.
        submission: Submission to edit, or ``None`` to add a new one.
    """

    def __init__(self, app: App, submission: SubmissionConfig | None) -> None:
        self.app = app
        self.original = submission
        self.window = tk.Toplevel(app.root)
        self.window.title(_("Edit submission") if submission else _("Add submission"))
        self.window.transient(app.root)
        self.link_var = tk.StringVar(
            master=self.window, value=submission.tracker_url if submission else ""
        )
        self.label_var = tk.StringVar(
            master=self.window, value=submission.label if submission else ""
        )
        self.enabled_var = tk.BooleanVar(
            master=self.window, value=submission.enabled if submission else True
        )
        self.verify_var = tk.BooleanVar(master=self.window, value=submission is None)
        overrides = submission.overrides if submission is not None else {}
        general_recorded = [c for c, var in app.record_vars.items() if var.get()]
        general_notified = [c for c, var in app.notify_vars.items() if var.get()]
        recorded = set(gui.effective_columns(general_recorded, overrides, "record"))
        notified = set(gui.effective_columns(general_notified, overrides, "notify"))
        self.own_var = tk.BooleanVar(master=self.window, value=bool(overrides))
        self.own_record_vars = {
            column: tk.BooleanVar(master=self.window, value=column in recorded)
            for column in TRACKED_COLUMNS
        }
        self.own_notify_vars = {
            column: tk.BooleanVar(master=self.window, value=column in notified)
            for column in TRACKED_COLUMNS
        }
        self.own_changed = False
        for variable in (
            self.own_var,
            *self.own_record_vars.values(),
            *self.own_notify_vars.values(),
        ):
            variable.trace_add("write", self._mark_own_changed)

        frame = ttk.Frame(self.window, padding=PAD)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text=_("Tracking link (or UUID) from the journal's e-mail")).grid(
            row=0, column=0, sticky="w"
        )
        link = ttk.Entry(frame, textvariable=self.link_var, width=80)
        link.grid(row=1, column=0, sticky="ew")
        ttk.Label(frame, text=_("Label (optional short name)")).grid(
            row=2, column=0, sticky="w", pady=(PAD, 0)
        )
        ttk.Entry(frame, textvariable=self.label_var).grid(row=3, column=0, sticky="ew")
        ttk.Label(frame, text=_("Custom fields, one per line (optional)")).grid(
            row=4, column=0, sticky="w", pady=(PAD, 0)
        )
        self.fields_text = tk.Text(frame, width=60, height=4)
        self.fields_text.grid(row=5, column=0, sticky="ew")
        if submission is not None:
            self.fields_text.insert("1.0", gui.format_fields_text(submission.fields))
        ttk.Label(
            frame,
            text=_(
                "Example: paper = Tau. Use it in the workbook name as {paper}; it is also "
                "written to an extra column. Give the same value to the submissions of one "
                "paper to several journals."
            ),
            foreground=_GREY,
            wraplength=560,
            justify="left",
        ).grid(row=6, column=0, sticky="w")
        ttk.Checkbutton(
            frame,
            text=_("Monitor this submission (untick to pause it)"),
            variable=self.enabled_var,
        ).grid(row=7, column=0, sticky="w", pady=(PAD, 0))
        if submission is None:
            ttk.Checkbutton(
                frame,
                text=_("Check the link with the tracker before adding it"),
                variable=self.verify_var,
            ).grid(row=8, column=0, sticky="w")
        self._build_own_settings(frame)
        buttons = ttk.Frame(frame)
        buttons.grid(row=9, column=0, columnspan=2, sticky="e", pady=(PAD, 0))
        ttk.Button(buttons, text=_("Cancel"), command=self.close).pack(side="right")
        ttk.Button(buttons, text=_("OK"), command=self.submit).pack(side="right", padx=(0, 4))
        frame.columnconfigure(0, weight=1)
        self.window.bind("<Escape>", lambda _event: self.close())
        link.focus_set()

    def _build_own_settings(self, frame: ttk.Frame) -> None:
        own = ttk.LabelFrame(frame, text=_("What is recorded and notified"), padding=PAD)
        own.grid(row=0, column=1, rowspan=9, sticky="nw", padx=(PAD * 2, 0))
        ttk.Checkbutton(
            own,
            text=_("Its own choice (instead of the Notifications tab)"),
            variable=self.own_var,
            command=self.update_own_state,
        ).grid(row=0, column=0, columnspan=3, sticky="w")
        ttk.Label(own, text=_("Column"), font=self.app.bold).grid(row=1, column=0, sticky="w")
        ttk.Label(own, text=_("Record"), font=self.app.bold).grid(row=1, column=1, padx=PAD)
        ttk.Label(own, text=_("Notify"), font=self.app.bold).grid(row=1, column=2, padx=PAD)
        self.own_buttons: list[ttk.Checkbutton] = []
        for row, column in enumerate(TRACKED_COLUMNS, start=2):
            ttk.Label(own, text=column_label(column)).grid(row=row, column=0, sticky="w")
            for position, variables in ((1, self.own_record_vars), (2, self.own_notify_vars)):
                button = ttk.Checkbutton(own, variable=variables[column])
                button.grid(row=row, column=position)
                self.own_buttons.append(button)
        self.update_own_state()

    def _mark_own_changed(self, *_args: object) -> None:
        self.own_changed = True

    def update_own_state(self) -> None:
        """Enable the column tick boxes only when the submission has its own choice."""
        for button in self.own_buttons:
            button.state(["!disabled"] if self.own_var.get() else ["disabled"])

    def own_overrides(self) -> dict[str, tuple[str, ...] | None]:
        """Return the own settings chosen in the window (unchanged unless edited)."""
        original = dict(self.original.overrides) if self.original is not None else {}
        if not self.own_changed:
            return original
        if not self.own_var.get():
            return {}
        return gui.own_settings(
            recorded=[c for c, var in self.own_record_vars.items() if var.get()],
            notified=[c for c, var in self.own_notify_vars.items() if var.get()],
        )

    def set_fields_text(self, text: str) -> None:
        """Replace the custom fields text."""
        self.fields_text.delete("1.0", "end")
        self.fields_text.insert("1.0", text)

    def submit(self) -> SubmissionConfig | None:
        """Validate the values and add or update the submission.

        Returns:
            The new submission, or ``None`` if a value is invalid.
        """
        try:
            uuid = parse_uuid(self.link_var.get())
            fields = gui.parse_fields_text(self.fields_text.get("1.0", "end"))
        except (ValueError, ConfigError) as exc:
            self.app.show_error(_("Invalid submission"), str(exc), parent=self.window)
            return None
        if any(s.uuid == uuid and s is not self.original for s in self.app.submissions):
            self.app.show_error(
                _("Duplicate submission"),
                _("{uuid} is already in the list.").format(uuid=uuid),
                parent=self.window,
            )
            return None
        submission = SubmissionConfig(
            uuid,
            self.label_var.get().strip(),
            self.enabled_var.get(),
            fields,
            self.own_overrides(),
        )
        if self.original is None and self.verify_var.get():
            self.app.verify_and_store(submission, self)
        else:
            self.close()
            self.app.store_submission(submission, self.original)
        return submission

    def close(self) -> None:
        """Close the window."""
        with contextlib.suppress(tk.TclError):
            self.window.destroy()


class EmailDialog:
    """Window to choose how e-mails are sent (the ``[email]`` table).

    The password is never written to the configuration: it can be saved in the system
    keyring (when the ``keyring`` package is installed) or given through an
    environment variable.

    Args:
        app: The main window.
    """

    def __init__(self, app: App) -> None:
        self.app = app
        settings = app.email_settings
        self.window = tk.Toplevel(app.root)
        self.window.title(_("E-mail settings"))
        self.window.transient(app.root)
        port = "" if settings.smtp_port is None else str(settings.smtp_port)
        self.host_var = tk.StringVar(master=self.window, value=settings.smtp_host)
        self.port_var = tk.StringVar(master=self.window, value=port)
        self.security_var = tk.StringVar(master=self.window, value=settings.security)
        self.username_var = tk.StringVar(master=self.window, value=settings.username)
        self.sender_var = tk.StringVar(master=self.window, value=settings.sender)
        self.to_var = tk.StringVar(master=self.window, value=", ".join(settings.to))
        self.password_var = tk.StringVar(master=self.window)
        frame = ttk.Frame(self.window, padding=PAD)
        frame.pack(fill="both", expand=True)
        security = ttk.Combobox(
            frame,
            textvariable=self.security_var,
            values=list(EMAIL_SECURITY_PORTS),
            state="readonly",
            width=10,
        )
        rows: tuple[tuple[str, tk.Widget], ...] = (
            (_("SMTP server"), ttk.Entry(frame, textvariable=self.host_var, width=40)),
            (
                _("Port (empty: the usual one)"),
                ttk.Entry(frame, textvariable=self.port_var, width=8),
            ),
            (_("Security"), security),
            (_("User name (empty: no login)"), ttk.Entry(frame, textvariable=self.username_var)),
            (_("From (empty: the user name)"), ttk.Entry(frame, textvariable=self.sender_var)),
            (_("To (separated by commas)"), ttk.Entry(frame, textvariable=self.to_var, width=40)),
        )
        for row, (text, widget) in enumerate(rows):
            ttk.Label(frame, text=text).grid(row=row, column=0, sticky="w", pady=2)
            widget.grid(row=row, column=1, sticky="ew", pady=2, padx=(PAD, 0))
        box = ttk.LabelFrame(frame, text=_("Password"), padding=PAD)
        box.grid(row=len(rows), column=0, columnspan=2, sticky="ew", pady=(PAD, 0))
        keyring = emails.keyring_available()
        if keyring:
            where = _(
                "Save it in the system keyring here, or set the {variable} environment variable."
            )
        else:
            where = _(
                "Set the {variable} environment variable, or install the keyring package "
                "(python -m pip install keyring) to save it in the system keyring."
            )
        note = (
            _("The password is never written to the configuration file.")
            + " "
            + where.format(variable=SMTP_PASSWORD_ENV_VAR)
        )
        ttk.Label(box, text=note, foreground=_GREY, wraplength=440, justify="left").grid(
            row=0, column=0, columnspan=2, sticky="w"
        )
        if keyring:
            ttk.Entry(box, textvariable=self.password_var, show="*", width=30).grid(
                row=1, column=0, sticky="w", pady=(4, 0)
            )
            ttk.Button(box, text=_("Save in the keyring"), command=self.save_password).grid(
                row=1, column=1, sticky="w", padx=(4, 0), pady=(4, 0)
            )
        buttons = ttk.Frame(frame)
        buttons.grid(row=len(rows) + 1, column=0, columnspan=2, sticky="e", pady=(PAD, 0))
        ttk.Button(buttons, text=_("Cancel"), command=self.close).pack(side="right")
        ttk.Button(buttons, text=_("OK"), command=self.submit).pack(side="right", padx=(0, 4))
        frame.columnconfigure(1, weight=1)
        self.window.bind("<Escape>", lambda _event: self.close())

    def settings(self) -> EmailConfig:
        """Return the settings typed in the window.

        Raises:
            ConfigError: If a value is not valid.
        """
        return gui.email_settings(
            smtp_host=self.host_var.get(),
            smtp_port=self.port_var.get(),
            security=self.security_var.get(),
            username=self.username_var.get(),
            sender=self.sender_var.get(),
            to=self.to_var.get(),
        )

    def submit(self) -> EmailConfig | None:
        """Keep the settings in the main window (they are written by Save)."""
        try:
            settings = self.settings()
        except ConfigError as exc:
            self.app.show_error(_("Invalid e-mail settings"), str(exc), parent=self.window)
            return None
        self.close()
        if settings != self.app.email_settings:
            self.app.email_settings = settings
            self.app.mark_dirty()
        return settings

    def save_password(self) -> bool:
        """Save the password typed in the window in the system keyring."""
        password = self.password_var.get()
        if not password:
            self.app.show_error(_("No password"), _("Type the password first."), parent=self.window)
            return False
        try:
            settings = self.settings()
            emails.store_password(settings, password)
        except (ConfigError, emails.EmailError) as exc:
            self.app.show_error(_("The password was not saved"), str(exc), parent=self.window)
            return False
        self.password_var.set("")
        self.app.show_info(
            _("Password saved"),
            _("The password of {user} is now kept in the system keyring.").format(
                user=settings.username
            ),
            parent=self.window,
        )
        return True

    def close(self) -> None:
        """Close the window."""
        with contextlib.suppress(tk.TclError):
            self.window.destroy()
