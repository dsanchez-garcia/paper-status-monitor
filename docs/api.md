# Python API

The command-line tool is a thin layer over a small Python API that you can use in
your own scripts:

```python
from paper_status_monitor import Monitor, TrackerClient, load_config

# One-off check of a single submission.
with TrackerClient() as client:
    snapshot = client.fetch("00000000-0000-0000-0000-000000000000")
print(snapshot.display_title, snapshot.status, snapshot.reviews_completed)

# Full run with the user's configuration (same as `paper-status-monitor run`).
summary = Monitor(load_config()).run()
for result in summary.changed:
    print(result.name, [str(change) for change in result.changes])
for result in summary.recorded:
    print(result.name, "recorded:", [str(change) for change in result.recorded_changes])
```

The public names are re-exported by the top-level package. Everything else may
change between minor versions until 1.0.

## Tracker client

```{eval-rst}
.. automodule:: paper_status_monitor.client
```

## Data model

```{eval-rst}
.. automodule:: paper_status_monitor.models
```

## Monitor

```{eval-rst}
.. automodule:: paper_status_monitor.monitor
```

## Configuration

```{eval-rst}
.. automodule:: paper_status_monitor.config
```

## Workbook names

```{eval-rst}
.. automodule:: paper_status_monitor.naming
```

## Workbook storage

```{eval-rst}
.. automodule:: paper_status_monitor.storage
```

## Organizing workbooks

```{eval-rst}
.. automodule:: paper_status_monitor.organize
```

## Reports

```{eval-rst}
.. automodule:: paper_status_monitor.report
```

## Desktop notifications

```{eval-rst}
.. automodule:: paper_status_monitor.notifications
```

## Periodic checks

```{eval-rst}
.. automodule:: paper_status_monitor.scheduling
```

## Summary table

```{eval-rst}
.. automodule:: paper_status_monitor.summary
```

## Run state

```{eval-rst}
.. automodule:: paper_status_monitor.state
```

## Graphical interface

```{eval-rst}
.. automodule:: paper_status_monitor.gui
```

## Autostart (Windows)

```{eval-rst}
.. automodule:: paper_status_monitor.autostart
```

## Default paths

```{eval-rst}
.. automodule:: paper_status_monitor.paths
```

