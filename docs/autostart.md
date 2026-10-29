# Running at login

The monitor is designed to run unattended, typically once every time you log in.

## Enable it

```console
paper-status-monitor autostart enable
```

This creates a launcher that runs the monitor in the background, without a window,
every time you log in:

| System | Launcher |
| --- | --- |
| Windows | A shortcut, `paper-status-monitor.lnk`, in your *Startup* folder (`shell:startup`, i.e. `%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup`). |
| Linux | An XDG autostart entry, `~/.config/autostart/paper-status-monitor.desktop` (in `$XDG_CONFIG_HOME/autostart` if that variable is set). |
| macOS | A launchd agent, `~/Library/LaunchAgents/io.github.paper-status-monitor.plist`. |

The launcher runs:

```text
<python> -m paper_status_monitor run --wait 300
```

- `<python>` is the interpreter that ran `autostart enable` (on Windows, the
  `pythonw.exe` next to it, which runs without a console window). You only see
  something when there is news: the report opens in your text editor, or a desktop
  notification is shown (see `notify` in {doc}`configuration`).
- `--wait 300` gives the network and cloud drives (Google Drive, OneDrive...) up to
  five minutes to become available. Change it with `autostart enable --wait SECONDS`.
- No administrator rights are needed, and the launcher takes effect at your next
  login.
- With the global `--config PATH` option (`paper-status-monitor --config my.toml
  autostart enable`), the launcher uses that configuration file.

Check or remove it with:

```console
paper-status-monitor autostart status
paper-status-monitor autostart disable
```

```{warning}
The launcher points to the Python interpreter that ran `autostart enable`. If you
uninstall or replace that Python (for example, when upgrading to a new Python
version, or when you delete the virtual environment you installed the package in),
the launcher stops working. Install the package in the new interpreter and run
`paper-status-monitor autostart enable` again. `paper-status-monitor doctor`
reports this problem.
```

(periodic-checks)=
## Periodic checks while you stay logged in

If your computer stays on, with your session open, for days, also check
periodically:

```console
paper-status-monitor autostart enable --every 12h
```

The program started at login then stays in the background, without a window, and
checks again every 12 hours (`1d`, `6h`, `1h30m`... are also accepted; the minimum
is `1h`). It starts with your next login and stops when you log out. The waiting
time (`--wait`) also applies after the computer wakes up, and a computer that was
asleep or hibernated catches up with one check shortly after waking up. The
configuration file is read again before every check, so nothing needs to be
restarted after you change it. The graphical interface offers the same (*Run → Then
check again every ... hours*), and `autostart status` shows when the checks run.

On any system, `paper-status-monitor run --every 12h` does the same in a terminal,
until you press `Ctrl+C`. Only one loop of periodic checks runs at a time: while the
one started at login runs, a second `run --every` is refused (a single `run` is
still allowed), and `paper-status-monitor doctor` shows which process runs them.

(tray-icon)=
### An icon in the notification area (Windows)

Add `--tray` to see that the periodic checks are running:

```console
paper-status-monitor autostart enable --every 12h --tray
```

An icon (a blue disc with a white tick) then stays in the notification area of the
taskbar while the checks run. Its tooltip says when the last check ran, whether it
found news, and when the next one is due. Click it (with either button) for a menu
with the latest status of every submission and:

- **Check now**: check at once, without waiting for the next check;
- **Open the window**: the graphical interface (also when you click a submission);
- **Open the last report** and **Open the data folder**;
- **Stop the periodic checks**: until your next login (the launcher is kept).

The icon follows the `language` setting. Windows may place new icons in the hidden
part of the notification area (the `^` arrow); drag it to the taskbar, or turn it on
in *Settings → Personalization → Taskbar → Other system tray icons*, to keep it in
sight. In the graphical interface, tick *Show an icon in the notification area*
under *Run automatically at login*. `run --every 12h --tray` shows it from a
terminal too. If the icon cannot be shown, the problem is logged and the checks go on
without it.

## Windows

The shortcut is created through PowerShell, which is part of Windows. You can also
see it, and turn it off, in *Settings → Apps → Startup* (or in the *Startup* tab of
the Task Manager).

### Alternative: Task Scheduler

If you prefer the Task Scheduler (for example, to check every day at a fixed time
rather than at an interval), create a task from PowerShell:

```powershell
$python = (Get-Command pythonw.exe).Source   # or the full path to your pythonw.exe
$action = New-ScheduledTaskAction -Execute $python -Argument "-m paper_status_monitor run --wait 300"
$triggers = @(
    New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
    New-ScheduledTaskTrigger -Daily -At 9am
)
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -RunOnlyIfNetworkAvailable
Register-ScheduledTask -TaskName "paper-status-monitor" -Action $action -Trigger $triggers -Settings $settings
```

Creating tasks with a logon trigger may require an elevated PowerShell. Do not
enable both the Startup shortcut and a logon task: the second run would find the
lock of the first one and exit.

## Linux

XDG autostart entries are started by the desktop environment (GNOME, KDE Plasma,
Xfce, Cinnamon, MATE...) when you log in to the desktop, so the report can be opened
and notifications can be shown. Most desktops also list the entry in their startup
settings (for example, *GNOME Tweaks → Startup Applications*), where you can turn it
off.

On a computer without a desktop, such as a server used through SSH, autostart
entries are never started (`autostart enable` warns you when it finds no graphical
session). Use cron or a systemd user timer instead, and write the report without
opening it (`--notify none`). A cron job that runs at boot and every day:

```text
@reboot   sleep 60 && $HOME/.local/bin/paper-status-monitor run --wait 300 --notify none
0 9 * * * $HOME/.local/bin/paper-status-monitor run --notify none
```

or a [systemd user timer](https://wiki.archlinux.org/title/Systemd/Timers) that
checks at 9:00 and 21:00 (and catches up after the computer was off), in
`~/.config/systemd/user/paper-status-monitor.service`:

```ini
[Unit]
Description=Check the status of your manuscripts (paper-status-monitor)

[Service]
Type=oneshot
ExecStart=%h/.local/bin/paper-status-monitor run --wait 300 --notify none
```

and `~/.config/systemd/user/paper-status-monitor.timer`:

```ini
[Unit]
Description=Check the status of your manuscripts twice a day

[Timer]
OnCalendar=*-*-* 09,21:00
Persistent=true

[Install]
WantedBy=timers.target
```

Enable it with `systemctl --user enable --now paper-status-monitor.timer`, and run
`loginctl enable-linger $USER` if it must also run while you are not logged in. Use
`which paper-status-monitor` to find the right path.

## macOS

launchd loads the agent at your next login. macOS 13 and later announce it as a new
background item, and list it in *System Settings → General → Login Items*, where you
can also turn it off. To start it now, without logging out (this also runs a check
immediately):

```console
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/io.github.paper-status-monitor.plist
```

A loaded agent keeps running until you log out, even after `autostart disable`; to
stop it earlier, run `launchctl bootout gui/$(id -u)/io.github.paper-status-monitor`.

## How often should it run?

Review statuses change over days or weeks. Checking once per login, or every few
hours to once a day, is plenty — and it keeps the load on the tracker negligible.
`--every` therefore refuses intervals shorter than one hour; please do not run the
monitor in a tight loop.

