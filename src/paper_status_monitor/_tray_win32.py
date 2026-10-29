"""Windows code of the icon in the notification area (see :mod:`paper_status_monitor.tray`).

It uses the Windows API through :mod:`ctypes`: a hidden window, owned by a thread of
its own that runs its message loop, receives the clicks on the icon and shows the
menu. This module is only imported on Windows, when the icon is shown.
"""

from __future__ import annotations

import contextlib
import ctypes
import logging
import threading
from collections.abc import Callable, Sequence
from ctypes import wintypes
from typing import Any

from paper_status_monitor.tray import APP_NAME, MAX_TOOLTIP, MenuEntry, TrayError, icon_pixels

log = logging.getLogger(__name__)

_LRESULT = wintypes.LPARAM
_WNDPROC = ctypes.WINFUNCTYPE(
    _LRESULT, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM
)

_WM_NULL = 0x0000
_WM_DESTROY = 0x0002
_WM_CLOSE = 0x0010
_WM_CONTEXTMENU = 0x007B
_WM_LBUTTONUP = 0x0202
_WM_RBUTTONUP = 0x0205
_WM_APP = 0x8000
_CALLBACK_MESSAGE = _WM_APP + 1
_REFRESH_MESSAGE = _WM_APP + 2

_NIM_ADD, _NIM_MODIFY, _NIM_DELETE = 0, 1, 2
_NIF_MESSAGE, _NIF_ICON, _NIF_TIP = 0x1, 0x2, 0x4
_MF_STRING, _MF_GRAYED, _MF_SEPARATOR = 0x0, 0x1, 0x800
_TPM_RIGHTBUTTON, _TPM_NONOTIFY, _TPM_RETURNCMD = 0x2, 0x80, 0x100
_SM_CXSMICON = 49
_IDI_APPLICATION = 32512


class _GUID(ctypes.Structure):
    _fields_ = [
        ("Data1", wintypes.DWORD),
        ("Data2", wintypes.WORD),
        ("Data3", wintypes.WORD),
        ("Data4", wintypes.BYTE * 8),
    ]


class _NOTIFYICONDATAW(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("hWnd", wintypes.HWND),
        ("uID", wintypes.UINT),
        ("uFlags", wintypes.UINT),
        ("uCallbackMessage", wintypes.UINT),
        ("hIcon", wintypes.HICON),
        ("szTip", wintypes.WCHAR * 128),
        ("dwState", wintypes.DWORD),
        ("dwStateMask", wintypes.DWORD),
        ("szInfo", wintypes.WCHAR * 256),
        ("uVersion", wintypes.UINT),
        ("szInfoTitle", wintypes.WCHAR * 64),
        ("dwInfoFlags", wintypes.DWORD),
        ("guidItem", _GUID),
        ("hBalloonIcon", wintypes.HICON),
    ]


class _WNDCLASSW(ctypes.Structure):
    _fields_ = [
        ("style", wintypes.UINT),
        ("lpfnWndProc", _WNDPROC),
        ("cbClsExtra", ctypes.c_int),
        ("cbWndExtra", ctypes.c_int),
        ("hInstance", wintypes.HINSTANCE),
        ("hIcon", wintypes.HICON),
        ("hCursor", wintypes.HANDLE),
        ("hbrBackground", wintypes.HBRUSH),
        ("lpszMenuName", wintypes.LPCWSTR),
        ("lpszClassName", wintypes.LPCWSTR),
    ]


class _ICONINFO(ctypes.Structure):
    _fields_ = [
        ("fIcon", wintypes.BOOL),
        ("xHotspot", wintypes.DWORD),
        ("yHotspot", wintypes.DWORD),
        ("hbmMask", wintypes.HBITMAP),
        ("hbmColor", wintypes.HBITMAP),
    ]


class _BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", wintypes.DWORD),
        ("biWidth", wintypes.LONG),
        ("biHeight", wintypes.LONG),
        ("biPlanes", wintypes.WORD),
        ("biBitCount", wintypes.WORD),
        ("biCompression", wintypes.DWORD),
        ("biSizeImage", wintypes.DWORD),
        ("biXPelsPerMeter", wintypes.LONG),
        ("biYPelsPerMeter", wintypes.LONG),
        ("biClrUsed", wintypes.DWORD),
        ("biClrImportant", wintypes.DWORD),
    ]


def _function(library: Any, name: str, restype: Any, *argtypes: Any) -> Any:
    function = getattr(library, name)
    function.restype = restype
    function.argtypes = argtypes
    return function


_user32 = ctypes.WinDLL("user32", use_last_error=True)  # type: ignore[attr-defined]
_shell32 = ctypes.WinDLL("shell32", use_last_error=True)  # type: ignore[attr-defined]
_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)  # type: ignore[attr-defined]
_gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)  # type: ignore[attr-defined]

_get_module_handle = _function(_kernel32, "GetModuleHandleW", wintypes.HMODULE, wintypes.LPCWSTR)
_register_class = _function(_user32, "RegisterClassW", wintypes.ATOM, ctypes.POINTER(_WNDCLASSW))
_unregister_class = _function(
    _user32, "UnregisterClassW", wintypes.BOOL, wintypes.LPCWSTR, wintypes.HINSTANCE
)
_create_window = _function(
    _user32,
    "CreateWindowExW",
    wintypes.HWND,
    wintypes.DWORD,
    wintypes.LPCWSTR,
    wintypes.LPCWSTR,
    wintypes.DWORD,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
    wintypes.HWND,
    wintypes.HMENU,
    wintypes.HINSTANCE,
    wintypes.LPVOID,
)
_destroy_window = _function(_user32, "DestroyWindow", wintypes.BOOL, wintypes.HWND)
_default_window_proc = _function(
    _user32,
    "DefWindowProcW",
    _LRESULT,
    wintypes.HWND,
    wintypes.UINT,
    wintypes.WPARAM,
    wintypes.LPARAM,
)
_get_message = _function(
    _user32,
    "GetMessageW",
    wintypes.BOOL,
    ctypes.POINTER(wintypes.MSG),
    wintypes.HWND,
    wintypes.UINT,
    wintypes.UINT,
)
_translate_message = _function(
    _user32, "TranslateMessage", wintypes.BOOL, ctypes.POINTER(wintypes.MSG)
)
_dispatch_message = _function(_user32, "DispatchMessageW", _LRESULT, ctypes.POINTER(wintypes.MSG))
_post_message = _function(
    _user32,
    "PostMessageW",
    wintypes.BOOL,
    wintypes.HWND,
    wintypes.UINT,
    wintypes.WPARAM,
    wintypes.LPARAM,
)
_post_quit_message = _function(_user32, "PostQuitMessage", None, ctypes.c_int)
_register_window_message = _function(
    _user32, "RegisterWindowMessageW", wintypes.UINT, wintypes.LPCWSTR
)
_create_popup_menu = _function(_user32, "CreatePopupMenu", wintypes.HMENU)
_append_menu = _function(
    _user32,
    "AppendMenuW",
    wintypes.BOOL,
    wintypes.HMENU,
    wintypes.UINT,
    ctypes.c_size_t,
    wintypes.LPCWSTR,
)
_destroy_menu = _function(_user32, "DestroyMenu", wintypes.BOOL, wintypes.HMENU)
_get_cursor_pos = _function(_user32, "GetCursorPos", wintypes.BOOL, ctypes.POINTER(wintypes.POINT))
_set_foreground_window = _function(_user32, "SetForegroundWindow", wintypes.BOOL, wintypes.HWND)
_track_popup_menu = _function(
    _user32,
    "TrackPopupMenu",
    wintypes.BOOL,
    wintypes.HMENU,
    wintypes.UINT,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
    wintypes.HWND,
    wintypes.LPVOID,
)
_get_system_metrics = _function(_user32, "GetSystemMetrics", ctypes.c_int, ctypes.c_int)
_create_icon_indirect = _function(
    _user32, "CreateIconIndirect", wintypes.HICON, ctypes.POINTER(_ICONINFO)
)
_destroy_icon = _function(_user32, "DestroyIcon", wintypes.BOOL, wintypes.HICON)
_load_icon = _function(_user32, "LoadIconW", wintypes.HICON, wintypes.HINSTANCE, wintypes.LPVOID)
_shell_notify_icon = _function(
    _shell32, "Shell_NotifyIconW", wintypes.BOOL, wintypes.DWORD, ctypes.POINTER(_NOTIFYICONDATAW)
)
_create_dib_section = _function(
    _gdi32,
    "CreateDIBSection",
    wintypes.HBITMAP,
    wintypes.HDC,
    ctypes.POINTER(_BITMAPINFOHEADER),
    wintypes.UINT,
    ctypes.POINTER(ctypes.c_void_p),
    wintypes.HANDLE,
    wintypes.DWORD,
)
_create_bitmap = _function(
    _gdi32,
    "CreateBitmap",
    wintypes.HBITMAP,
    ctypes.c_int,
    ctypes.c_int,
    wintypes.UINT,
    wintypes.UINT,
    wintypes.LPVOID,
)
_delete_object = _function(_gdi32, "DeleteObject", wintypes.BOOL, wintypes.HGDIOBJ)


def _notify(message: int, data: _NOTIFYICONDATAW) -> bool:
    """Call ``Shell_NotifyIconW`` (replaced by the tests, which show no real icon)."""
    return bool(_shell_notify_icon(message, ctypes.byref(data)))


def _enable_dpi_awareness() -> None:
    """Draw the icon at the real size of the screen (it is blurry when scaled up)."""
    with contextlib.suppress(AttributeError, OSError):  # older Windows, or already set
        ctypes.windll.shcore.SetProcessDpiAwareness(1)  # type: ignore[attr-defined]


def _choose_from_menu(menu: Any, window: Any) -> int:
    """Show *menu* at the mouse pointer and return the chosen item (``0``: none).

    Replaced by the tests: the real menu waits for the user.
    """
    point = wintypes.POINT()
    _get_cursor_pos(ctypes.byref(point))
    _set_foreground_window(window)  # without it, the menu does not close when it should
    flags = _TPM_RIGHTBUTTON | _TPM_RETURNCMD | _TPM_NONOTIFY
    chosen = _track_popup_menu(menu, flags, point.x, point.y, 0, window, None)
    _post_message(window, _WM_NULL, 0, 0)
    return int(chosen)


def create_icon(size: int) -> Any:
    """Return a Windows icon of *size* pixels, drawn by :func:`.tray.icon_pixels`.

    Falls back to the default application icon if it cannot be created.
    """
    pixels = icon_pixels(size)
    header = _BITMAPINFOHEADER(
        biSize=ctypes.sizeof(_BITMAPINFOHEADER),
        biWidth=size,
        biHeight=-size,  # rows from the top
        biPlanes=1,
        biBitCount=32,
    )
    bits = ctypes.c_void_p()
    colour = _create_dib_section(None, ctypes.byref(header), 0, ctypes.byref(bits), None, 0)
    mask_bytes = (ctypes.c_ubyte * (((size + 15) // 16) * 2 * size))()
    mask = _create_bitmap(size, size, 1, 1, mask_bytes)
    try:
        if not colour or not mask or not bits.value:
            raise ctypes.WinError(ctypes.get_last_error())
        ctypes.memmove(bits.value, (ctypes.c_uint32 * len(pixels))(*pixels), 4 * len(pixels))
        info = _ICONINFO(fIcon=True, hbmMask=mask, hbmColor=colour)
        icon = _create_icon_indirect(ctypes.byref(info))
        if not icon:
            raise ctypes.WinError(ctypes.get_last_error())
        return icon
    except OSError as exc:
        log.warning("The icon could not be drawn (%s); the default one is used.", exc)
        return _load_icon(None, ctypes.c_void_p(_IDI_APPLICATION))
    finally:
        for bitmap in (colour, mask):
            if bitmap:
                _delete_object(bitmap)


class Win32Tray:
    """An icon in the notification area, with a tooltip and a menu.

    Args:
        tooltip: Returns the tooltip (read every time the icon is refreshed).
        menu: Returns the lines of the menu (read every time the menu opens).
        on_command: Called, in the thread of the icon, with the command chosen.
    """

    def __init__(
        self,
        *,
        tooltip: Callable[[], str],
        menu: Callable[[], Sequence[MenuEntry]],
        on_command: Callable[[str], None],
    ) -> None:
        self._tooltip = tooltip
        self._menu = menu
        self._on_command = on_command
        self._class_name = f"PaperStatusMonitorTray{id(self)}"
        self._ready = threading.Event()
        self._error: BaseException | None = None
        self._window: Any = None
        self._instance: Any = None
        self._icon: Any = None
        self._added = False
        self._taskbar_created = 0
        self._procedure = _WNDPROC(self._window_procedure)  # kept alive while the window lives
        self._thread = threading.Thread(target=self._run, name="tray-icon", daemon=True)

    def start(self, timeout: float = 10.0) -> None:
        """Create the icon in a thread of its own.

        Raises:
            TrayError: If the window or the icon could not be created.
        """
        self._thread.start()
        if not self._ready.wait(timeout):
            raise TrayError("the icon did not start in time")
        if self._error is not None:
            raise TrayError(str(self._error)) from self._error

    def refresh(self) -> None:
        """Read the tooltip again (from any thread)."""
        if self._window:
            _post_message(self._window, _REFRESH_MESSAGE, 0, 0)

    def close(self, timeout: float = 5.0) -> None:
        """Remove the icon and end its thread (from any thread)."""
        if self._window:
            _post_message(self._window, _WM_CLOSE, 0, 0)
        if self._thread.is_alive() and threading.current_thread() is not self._thread:
            self._thread.join(timeout)

    # ------------------------------------------------------------------ the icon thread

    def _run(self) -> None:
        try:
            self._create()
        except BaseException as exc:  # reported by start()
            self._error = exc
            if self._window:
                _destroy_window(self._window)
            self._cleanup()
            self._ready.set()
            return
        self._ready.set()
        message = wintypes.MSG()
        while _get_message(ctypes.byref(message), None, 0, 0) > 0:
            _translate_message(ctypes.byref(message))
            _dispatch_message(ctypes.byref(message))
        self._cleanup()

    def _create(self) -> None:
        _enable_dpi_awareness()
        self._instance = _get_module_handle(None)
        window_class = _WNDCLASSW(
            lpfnWndProc=self._procedure,
            hInstance=self._instance,
            lpszClassName=self._class_name,
        )
        if not _register_class(ctypes.byref(window_class)):
            raise ctypes.WinError(ctypes.get_last_error())
        self._window = _create_window(
            0, self._class_name, APP_NAME, 0, 0, 0, 0, 0, None, None, self._instance, None
        )
        if not self._window:
            raise ctypes.WinError(ctypes.get_last_error())
        self._taskbar_created = _register_window_message("TaskbarCreated")
        self._icon = create_icon(_get_system_metrics(_SM_CXSMICON) or 16)
        if not self._add():
            # Typically, the taskbar is not ready yet at login: the icon is added when
            # it broadcasts "TaskbarCreated".
            log.warning("The taskbar did not accept the icon yet; it is added when it starts.")

    def _data(self, flags: int) -> _NOTIFYICONDATAW:
        data = _NOTIFYICONDATAW()
        data.cbSize = ctypes.sizeof(_NOTIFYICONDATAW)
        data.hWnd = self._window
        data.uID = 1
        data.uFlags = flags
        data.uCallbackMessage = _CALLBACK_MESSAGE
        data.hIcon = self._icon
        data.szTip = self._safe_tooltip()
        return data

    def _safe_tooltip(self) -> str:
        try:
            return self._tooltip()[:MAX_TOOLTIP]
        except Exception:
            log.exception("The tooltip of the icon could not be built")
            return APP_NAME

    def _add(self) -> bool:
        """Add the icon to the taskbar; return ``True`` if it is there.

        ``NIM_ADD`` also fails when the icon is already there, and the taskbar may
        report a failure (a timeout while Explorer is busy, typically at login) and
        add the icon anyway: ``NIM_MODIFY`` then tells whether it is there.
        """
        data = self._data(_NIF_MESSAGE | _NIF_ICON | _NIF_TIP)
        self._added = _notify(_NIM_ADD, data) or _notify(_NIM_MODIFY, data)
        return self._added

    def _modify(self) -> None:
        if not self._added or not _notify(_NIM_MODIFY, self._data(_NIF_TIP)):
            self._add()  # not added yet, or the taskbar restarted without telling us

    def _delete(self) -> None:
        """Remove the icon (harmless if it is not there: a failed add may have worked)."""
        if self._window:
            _notify(_NIM_DELETE, self._data(0))
        self._added = False

    def _cleanup(self) -> None:
        if self._added:
            self._delete()
        if self._icon:
            _destroy_icon(self._icon)
            self._icon = None
        if self._instance is not None:
            _unregister_class(self._class_name, self._instance)
        self._window = None

    def _window_procedure(self, window: Any, message: int, wparam: Any, lparam: Any) -> int:
        try:
            if message == _CALLBACK_MESSAGE:
                if lparam & 0xFFFF in (_WM_LBUTTONUP, _WM_RBUTTONUP, _WM_CONTEXTMENU):
                    self.show_menu()
                return 0
            if message == _REFRESH_MESSAGE:
                self._modify()
                return 0
            if self._taskbar_created and message == self._taskbar_created:
                self._add()
                return 0
            if message == _WM_CLOSE:
                _destroy_window(window)
                return 0
            if message == _WM_DESTROY:
                self._delete()
                _post_quit_message(0)
                return 0
        except Exception:
            log.exception("Error in the icon in the notification area")
        return int(_default_window_proc(window, message, wparam, lparam))

    def show_menu(self) -> None:
        """Show the menu at the mouse pointer and carry out the command chosen."""
        entries = list(self._menu())
        commands: dict[int, str] = {}
        menu = _create_popup_menu()
        try:
            for number, entry in enumerate(entries, start=1):
                if entry.separator:
                    _append_menu(menu, _MF_SEPARATOR, 0, None)
                    continue
                flags = _MF_STRING if entry.enabled and entry.command else _MF_GRAYED
                _append_menu(menu, flags, number, entry.label.replace("&", "&&"))
                if entry.command and entry.enabled:
                    commands[number] = entry.command
            chosen = _choose_from_menu(menu, self._window)
        finally:
            _destroy_menu(menu)
        command = commands.get(chosen)
        if command is not None:
            try:
                self._on_command(command)
            except Exception:
                log.exception("The command %r of the icon failed", command)
