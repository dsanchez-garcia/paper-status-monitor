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

### Alternative: Task Scheduler

If you prefer the Task Scheduler (for example, to also run the check every day at a
fixed time), create a task from PowerShell:

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
Use `which paper-status-monitor` to find the right path.

## How often should it run?

Review statuses change over days or weeks. Checking once per login, or once a day,
is plenty — and it keeps the load on the tracker negligible. Please do not run the
monitor in a tight loop.

