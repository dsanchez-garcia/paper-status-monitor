# Running at login

The monitor is designed to run unattended, typically once every time you log in.

## Windows (built in)

```console
paper-status-monitor autostart enable
```

This creates `paper-status-monitor.lnk` in your *Startup* folder
(`shell:startup`, i.e. `%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup`).
The shortcut runs:

```text
<python folder>\pythonw.exe -m paper_status_monitor run --wait 300
```

- `pythonw.exe` runs without a console window. You only see something when there is
  news: the report opens in your text editor.
- `--wait 300` gives the network and cloud drives (Google Drive, OneDrive...) up to
  five minutes to become available. Change it with `autostart enable --wait SECONDS`.
- No administrator rights are needed.

Check or remove it with:

```console
paper-status-monitor autostart status
paper-status-monitor autostart disable
```

```{warning}
The shortcut points to the Python interpreter that ran `autostart enable`. If you
uninstall or replace that Python (for example, when upgrading to a new Python
version), the shortcut stops working. Install the package in the new interpreter and
run `paper-status-monitor autostart enable` again. `paper-status-monitor doctor`
reports this problem.
```

(periodic-checks)=
### Periodic checks while you stay logged in

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
until you press `Ctrl+C`.

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

Use a cron job that runs at boot and every day:

```text
@reboot   sleep 60 && $HOME/.local/bin/paper-status-monitor run --wait 300 --no-open
0 9 * * * $HOME/.local/bin/paper-status-monitor run --no-open
```

or a [systemd user timer](https://wiki.archlinux.org/title/Systemd/Timers). With a
graphical session you can also create `~/.config/autostart/paper-status-monitor.desktop`:

```ini
[Desktop Entry]
Type=Application
Name=paper-status-monitor
Exec=paper-status-monitor run --wait 300
Terminal=false
```

Add `--every 12h` to the `Exec` line to keep checking every 12 hours while you stay
logged in (see {ref}`periodic-checks`).

## macOS

Create `~/Library/LaunchAgents/io.github.paper-status-monitor.plist`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>io.github.paper-status-monitor</string>
  <key>ProgramArguments</key>
  <array>
    <string>/usr/local/bin/paper-status-monitor</string>
    <string>run</string>
    <string>--wait</string>
    <string>300</string>
  </array>
  <key>RunAtLoad</key>
  <true/>
</dict>
</plist>
```

and load it with `launchctl load ~/Library/LaunchAgents/io.github.paper-status-monitor.plist`.
Use `which paper-status-monitor` to find the right path. Add `<string>--every</string>`
and `<string>12h</string>` to `ProgramArguments` to keep checking every 12 hours while
you stay logged in.

## How often should it run?

Review statuses change over days or weeks. Checking once per login, or every few
hours to once a day, is plenty — and it keeps the load on the tracker negligible.
`--every` therefore refuses intervals shorter than one hour; please do not run the
monitor in a tight loop.

