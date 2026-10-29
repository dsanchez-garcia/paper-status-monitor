"""Spanish translation (español).

Terminology: submission = envío, workbook = libro, report = informe, tracker =
sistema de seguimiento, tracking page = página de seguimiento, record = registrar,
notify = notificar, label = etiqueta, custom field = campo personalizado, dry run =
simulación, autostart = inicio automático. The user is addressed as *tú*.
"""

from __future__ import annotations


def plural(count: int) -> int:
    """Index of the plural form: ``0`` for one, ``1`` for any other number."""
    return 0 if count == 1 else 1


MESSAGES: dict[str, str | tuple[str, ...]] = {
    # ------------------------------------------------------------------ workbook columns
    # The workbooks always keep the English names; these are only shown.
    "Detected at": "Detectado el",
    "Title": "Título",
    "Revision": "Número de revisión",
    "Status": "Estado",
    "Status code": "Código de estado",
    "Last review activity": "Última actividad de revisión",
    "Reviews completed": "Revisiones completadas",
    "Review invitations accepted": "Invitaciones de revisión aceptadas",
    "Review invitations sent": "Invitaciones de revisión enviadas",
    "Journal": "Revista",
    "Corresponding author": "Autor de correspondencia",
    "First author": "Primer autor",
    "Date of submission": "Fecha de envío",
    "Manuscript number": "Número de manuscrito",
    "Tracker URL": "Enlace de seguimiento",
    # ------------------------------------------------------------------ report
    "Paper status monitor - report": "Informe del estado de los envíos",
    "Run started: {moment}": "Comprobación iniciada: {moment}",
    "CHANGES ({count})": "CAMBIOS ({count})",
    "NOW TRACKING ({count})": "NUEVOS EN SEGUIMIENTO ({count})",
    "ERRORS ({count})": "ERRORES ({count})",
    "Label: {label}": "Etiqueta: {label}",
    "Tracker: {link}": "Seguimiento: {link}",
    "Workbook: {path}": "Libro: {path}",
    "Reviews completed / invitations accepted / invitations sent: {counts}": (
        "Revisiones completadas / invitaciones aceptadas / invitaciones enviadas: {counts}"
    ),
    "No changes.": "Sin cambios.",
    "Checked {count} submission at {moment}": (
        "{count} envío comprobado el {moment}",
        "{count} envíos comprobados el {moment}",
    ),
    "[ERROR]": "[ERROR]",
    "[NEW]": "[NUEVO]",
    "[CHANGED]": "[CAMBIOS]",
    "[RECORDED]": "[REGISTRADO]",
    "[NO CHANGE]": "[SIN CAMBIOS]",
    "(not notified)": "(no notificado)",
    # ------------------------------------------------------------------ desktop notifications
    "Status changed: {name}": "Cambio de estado: {name}",
    "Now tracking: {name}": "En seguimiento: {name}",
    "Paper status: a check failed": "Estado de los envíos: una comprobación falló",
    "Paper status: {counts}": "Estado de los envíos: {counts}",
    "{count} changed": ("{count} con cambios", "{count} con cambios"),
    "{count} new": ("{count} nuevo", "{count} nuevos"),
    "{count} failed": ("{count} con error", "{count} con errores"),
    "{name}: now tracked": "{name}: ahora en seguimiento",
    "{name}: could not be checked": "{name}: no se pudo comprobar",
    "unknown error": "error desconocido",
    "changed": "con cambios",
    "(+{count} more)": ("(+{count} más)", "(+{count} más)"),
    "Recorded for the first time.": "Registrado por primera vez.",
    "... and {count} more change: see the report": (
        "... y {count} cambio más: consulta el informe",
        "... y {count} cambios más: consulta el informe",
    ),
    "... and {count} more submission: see the report": (
        "... y {count} envío más: consulta el informe",
        "... y {count} envíos más: consulta el informe",
    ),
    "Open report": "Abrir informe",
    "Open workbook": "Abrir libro",
    "Tracking page": "Ver seguimiento",
    "Open folder": "Abrir carpeta",
    "Desktop notifications work: you will see one like this when there is news about your "
    "submissions.": (
        "Las notificaciones de escritorio funcionan: verás una como esta cuando haya novedades "
        "sobre tus envíos."
    ),
    "powershell.exe was not found: Windows PowerShell shows the notifications": (
        "No se encontró powershell.exe: Windows PowerShell muestra las notificaciones"
    ),
    "osascript was not found": "No se encontró osascript",
    "notify-send was not found: install libnotify-bin (Debian, Ubuntu) or libnotify (Fedora, "
    "Arch...)": (
        "No se encontró notify-send: instala libnotify-bin (Debian, Ubuntu) o libnotify "
        "(Fedora, Arch...)"
    ),
    # ------------------------------------------------------------------ e-mails
    "Sent by paper-status-monitor. The tracking links in this message are personal: do not "
    "forward it.": (
        "Enviado por paper-status-monitor. Los enlaces de seguimiento de este mensaje son "
        "personales: no lo reenvíes."
    ),
    "E-mail notifications work: you will receive a message like this one, with the report, "
    "when there is news about your submissions.": (
        "Las notificaciones por correo electrónico funcionan: recibirás un mensaje como este, "
        "con el informe, cuando haya novedades sobre tus envíos."
    ),
    "Test message": "Mensaje de prueba",
    # ------------------------------------------------------------------ summary
    "Paper status summary": "Resumen del estado de los envíos",
    "Submission": "Envío",
    "Since": "Desde",
    "Reviews": "Revisiones",
    "{date} ({count} day)": ("{date} ({count} día)", "{date} ({count} días)"),
    "Generated on {moment}.": "Generado el {moment}.",
    "[paused] {name}": "[en pausa] {name}",
    "No submissions in the configuration.": "No hay envíos en la configuración.",
    "not recorded yet": "aún sin registrar",
    # ------------------------------------------------------------------ settings
    "all columns": "todas las columnas",
    "all columns except {columns}": "todas las columnas excepto {columns}",
    "no columns": "ninguna columna",
    "only {columns}": "solo {columns}",
    "a shortcut in the Startup folder": "un acceso directo en la carpeta Inicio",
    "an XDG autostart entry": "una entrada de inicio automático XDG",
    "a launchd agent": "un agente de launchd",
    "no launcher": "ningún lanzador",
    # ------------------------------------------------------------------ organize
    "Rename  {source}\n    ->  {target}": "Renombrar  {source}\n    ->  {target}",
    "Split   {workbook}": "Dividir  {workbook}",
    "Merge into  {workbook}": "Combinar en  {workbook}",
    "(kept here)": "(se queda aquí)",
    "(existing workbook)": "(libro existente)",
    "Renamed {source} -> {target}": "Renombrado {source} -> {target}",
    "Merged {sources} into {target} ({count} row)": (
        "Combinación de {sources} en {target} ({count} fila)",
        "Combinación de {sources} en {target} ({count} filas)",
    ),
    "{workbook} ({count} row)": ("{workbook} ({count} fila)", "{workbook} ({count} filas)"),
    "Split {workbook}: kept {count} row, moved the others to {targets}": (
        "División de {workbook}: se queda con {count} fila; las demás pasan a {targets}",
        "División de {workbook}: se queda con {count} filas; las demás pasan a {targets}",
    ),
    "Split {workbook} into {targets}": "División de {workbook} en {targets}",
    "{workbook} already exists": "{workbook} ya existe",
    "{workbook}: it also holds {count} row of submissions that are not in the configuration; "
    "rename or merge it by hand.": (
        "{workbook}: también contiene {count} fila de envíos que no están en la configuración; "
        "renómbralo o combínalo a mano.",
        "{workbook}: también contiene {count} filas de envíos que no están en la configuración; "
        "renómbralo o combínalo a mano.",
    ),
    "{workbook}: its submissions ({names}) now go to different workbooks, but {count} of its "
    "rows belongs to none of them (or to several); split it by hand.": (
        "{workbook}: sus envíos ({names}) ahora van a libros distintos, pero {count} de sus "
        "filas no pertenece a ninguno de ellos (o pertenece a varios); divídelo a mano.",
        "{workbook}: sus envíos ({names}) ahora van a libros distintos, pero {count} de sus "
        "filas no pertenecen a ninguno de ellos (o pertenecen a varios); divídelo a mano.",
    ),
    "{workbook}: it is renamed or merged itself; run 'organize' again afterwards to finish.": (
        "{workbook}: también se renombra o se combina; vuelve a organizar los libros después "
        "para terminar."
    ),
    "{workbook}: it takes part in another change; run 'organize' again afterwards to split it.": (
        "{workbook}: participa en otro cambio; vuelve a organizar los libros después para "
        "dividirlo."
    ),
    "{action}: {error}. Close the workbooks in Excel and try again.": (
        "{action}: {error}. Cierra los libros en Excel y vuelve a intentarlo."
    ),
    "{source} was merged into {target} but could not be removed ({error}); delete it by hand "
    "(a copy is in {folder}).": (
        "{source} se combinó en {target} pero no se pudo eliminar ({error}); bórralo a mano "
        "(hay una copia en {folder})."
    ),
    "{workbook} was split but could not be removed ({error}); delete it by hand (a copy is "
    "in {folder}).": (
        "{workbook} se dividió pero no se pudo eliminar ({error}); bórralo a mano (hay una "
        "copia en {folder})."
    ),
    # ------------------------------------------------------------------ window: general
    "Language (window and reports)": "Idioma (ventana e informes)",
    "Save": "Guardar",
    "Reload": "Recargar",
    "File": "Archivo",
    "Open the configuration file": "Abrir el archivo de configuración",
    "Open the log file": "Abrir el archivo de registro",
    "Exit": "Salir",
    "Help": "Ayuda",
    "Documentation": "Documentación",
    "About": "Acerca de",
    "About paper-status-monitor": "Acerca de paper-status-monitor",
    "Monitor the peer-review status of your Elsevier submissions.\nNot affiliated with "
    "Elsevier.\n\nConfiguration: {config}\nLog file: {log}": (
        "Sigue el estado de la revisión por pares de tus envíos a Elsevier.\nSin relación con "
        "Elsevier.\n\nConfiguración: {config}\nArchivo de registro: {log}"
    ),
    "Close": "Cerrar",
    "Cancel": "Cancelar",
    "OK": "Aceptar",
    "Apply": "Aplicar",
    "Open": "Abrir",
    "Test": "Probar",
    "Error": "Error",
    "Unexpected error": "Error inesperado",
    "Error: {error}": "Error: {error}",
    "Problem: {problem}": "Problema: {problem}",
    "Configuration: {path}": "Configuración: {path}",
    "New configuration: it will be created at {path} when you click Save.": (
        "Configuración nueva: se creará en {path} cuando pulses Guardar."
    ),
    "Unsaved changes: click Save to keep them.": (
        "Cambios sin guardar: pulsa Guardar para conservarlos."
    ),
    "Unsaved changes": "Cambios sin guardar",
    "Save the changes before closing?": "¿Guardar los cambios antes de cerrar?",
    "Discard changes?": "¿Descartar los cambios?",
    "Discard the unsaved changes?": "¿Descartar los cambios sin guardar?",
    "Save first?": "¿Guardar primero?",
    "Saved {path}": "Guardado {path}",
    "Saved {path} (previous version: {backup})": "Guardado {path} (versión anterior: {backup})",
    "The settings cannot be saved": "No se puede guardar la configuración",
    "Invalid configuration": "Configuración no válida",
    "Invalid settings": "Ajustes no válidos",
    "Invalid value": "Valor no válido",
    "{problem}\n\nThe window shows the default settings. Fix the file in a text editor and "
    "click Reload, or save these settings to replace it (the old file is kept as {backup}).": (
        "{problem}\n\nLa ventana muestra la configuración predeterminada. Corrige el archivo "
        "en un editor de texto y pulsa Recargar, o guarda esta configuración para sustituirlo "
        "(el archivo anterior se conserva como {backup})."
    ),
    "Not saved yet": "Aún sin guardar",
    "The configuration file does not exist yet: click Save.": (
        "El archivo de configuración aún no existe: pulsa Guardar."
    ),
    "No log file": "Sin archivo de registro",
    "{path} does not exist yet.": "{path} aún no existe.",
    # ------------------------------------------------------------------ window: submissions
    "Submissions": "Envíos",
    "Label": "Etiqueta",
    "Custom fields": "Campos personalizados",
    "Monitored": "Activo",
    "Last recorded status": "Último estado registrado",
    "yes": "sí",
    "no (paused)": "no (en pausa)",
    "(no label)": "(sin etiqueta)",
    "Add...": "Añadir...",
    "Edit...": "Editar...",
    "Remove": "Quitar",
    "Pause / resume": "Pausar / reanudar",
    "Check now": "Comprobar ahora",
    "Refresh": "Actualizar",
    "Summary": "Resumen",
    "Export...": "Exportar...",
    "Double-click a submission to edit it. Use custom fields (for example paper = Tau) to "
    "name the workbooks and to group the submissions of a paper to several journals. A * "
    "means that the submission has its own choice of what is recorded and notified. Changes "
    "are kept when you click Save.": (
        "Haz doble clic en un envío para editarlo. Usa campos personalizados (por ejemplo "
        "paper = Tau) para nombrar los libros y agrupar los envíos de un artículo a varias "
        "revistas. Un * indica que el envío tiene su propia elección de qué se registra y qué "
        "se notifica. Los cambios se conservan al pulsar Guardar."
    ),
    "No submission selected": "Ningún envío seleccionado",
    "Select a submission in the list first.": "Selecciona primero un envío de la lista.",
    "Remove submission": "Quitar envío",
    "Stop monitoring {name}?\n\nIts workbook is not deleted. To stop checking it "
    "temporarily, use Pause / resume instead.": (
        "¿Dejar de seguir {name}?\n\nSu libro no se borra. Para dejar de comprobarlo "
        "temporalmente, usa Pausar / reanudar."
    ),
    "Submission added": "Envío añadido",
    "Found: {title}\n{journal} - {number} - {status}\n\nClick Save to keep it.": (
        "Encontrado: {title}\n{journal} - {number} - {status}\n\nPulsa Guardar para conservarlo."
    ),
    "Add it anyway?": "¿Añadirlo de todos modos?",
    "The tracker could not confirm this link:\n{error}\n\nAdd the submission anyway?": (
        "El sistema de seguimiento no pudo confirmar este enlace:\n{error}\n\n¿Añadir el envío "
        "de todos modos?"
    ),
    "Current status - {name}": "Estado actual - {name}",
    "No workbook yet": "Aún no hay libro",
    "This submission has not been recorded yet: run a check first.": (
        "Este envío aún no se ha registrado: haz primero una comprobación."
    ),
    "unknown date": "fecha desconocida",
    "{status} ({date}) in {workbook}": "{status} ({date}) en {workbook}",
    "Save...": "Guardar...",
    "Save the summary": "Guardar el resumen",
    "HTML page": "Página HTML",
    "Text": "Texto",
    "The summary cannot be saved": "No se puede guardar el resumen",
    "Summary saved to {path}": "Resumen guardado en {path}",
    "Export the history (without the tracking links)": (
        "Exportar el historial (sin los enlaces de seguimiento)"
    ),
    "The history cannot be exported": "No se puede exportar el historial",
    "History exported to {path}": "Historial exportado a {path}",
    # ------------------------------------------------------------------ window: submission form
    "Add submission": "Añadir envío",
    "Edit submission": "Editar envío",
    "Tracking link (or UUID) from the journal's e-mail": (
        "Enlace de seguimiento (o UUID) del correo de la revista"
    ),
    "Label (optional short name)": "Etiqueta (nombre corto opcional)",
    "Custom fields, one per line (optional)": "Campos personalizados, uno por línea (opcional)",
    "Example: paper = Tau. Use it in the workbook name as {paper}; it is also written to an "
    "extra column. Give the same value to the submissions of one paper to several "
    "journals.": (
        "Ejemplo: paper = Tau. Úsalo en el nombre del libro como {paper}; también se escribe "
        "en una columna adicional. Da el mismo valor a los envíos de un artículo a varias "
        "revistas."
    ),
    "Monitor this submission (untick to pause it)": (
        "Seguir este envío (desmárcalo para pausarlo)"
    ),
    "Check the link with the tracker before adding it": (
        "Comprobar el enlace con el sistema de seguimiento antes de añadirlo"
    ),
    "What is recorded and notified": "Qué se registra y qué se notifica",
    "Its own choice (instead of the Notifications tab)": (
        "Elección propia (en lugar de la pestaña Notificaciones)"
    ),
    "Invalid submission": "Envío no válido",
    "Duplicate submission": "Envío duplicado",
    "{uuid} is already in the list.": "{uuid} ya está en la lista.",
    "Custom fields, line {number}: {line} must look like 'paper = Tau'.": (
        "Campos personalizados, línea {number}: {line} debe tener la forma 'paper = Tau'."
    ),
    "Custom fields, line {number}: {error}": "Campos personalizados, línea {number}: {error}",
    "The custom field {name} is written twice.": (
        "El campo personalizado {name} está escrito dos veces."
    ),
    # ------------------------------------------------------------------ window: notifications
    "Notifications": "Notificaciones",
    "For every column, choose whether a change adds a row to the workbook (Record) and "
    "whether it is included in the report that is opened for you (Notify). Example: to keep "
    "the history of 'Last review activity' without being told about it, tick Record and "
    "untick Notify.": (
        "Para cada columna, elige si un cambio añade una fila al libro (Registrar) y si se "
        "incluye en el informe que se abre para ti (Notificar). Ejemplo: para conservar el "
        "historial de 'Última actividad de revisión' sin que se te avise, marca Registrar y "
        "desmarca Notificar."
    ),
    "Column": "Columna",
    "Record": "Registrar",
    "Notify": "Notificar",
    "Quick choices": "Opciones rápidas",
    "Record every change": "Registrar todos los cambios",
    "Notify every change": "Notificar todos los cambios",
    "Notify only status changes": "Notificar solo los cambios de estado",
    "Do not notify review activity dates": "No notificar las fechas de actividad de revisión",
    "When there is news": "Cuando haya novedades",
    "Open the report with your text editor": "Abrir el informe con tu editor de texto",
    "Show a desktop notification": "Mostrar una notificación de escritorio",
    "Send the report by e-mail": "Enviar el informe por correo electrónico",
    "Settings...": "Configurar...",
    "Also report submissions that could not be checked (recommended)": (
        "Notificar también los envíos que no se pudieron comprobar (recomendado)"
    ),
    "The report is always written to the 'reports' subfolder of the data folder.": (
        "El informe siempre se escribe en la subcarpeta 'reports' de la carpeta de datos."
    ),
    "New submissions are always reported. Changes that are notified but not recorded are "
    "reported only once.": (
        "Los envíos nuevos siempre se notifican. Los cambios que se notifican pero no se "
        "registran se notifican una sola vez."
    ),
    "Recorded: {recorded}.\n\nNotified: {notified}.": (
        "Se registra: {recorded}.\n\nSe notifica: {notified}."
    ),
    "Test notification": "Notificación de prueba",
    "A test notification was sent. If you did not see it, check the notification settings "
    "of your system (focus assist, do not disturb...).": (
        "Se ha enviado una notificación de prueba. Si no la has visto, revisa la configuración "
        "de notificaciones del sistema (asistente de concentración, no molestar...)."
    ),
    "No desktop notification": "Sin notificación de escritorio",
    "The notification could not be shown: {error}": ("No se pudo mostrar la notificación: {error}"),
    "E-mail settings needed": "Falta configurar el correo",
    "Fill in {settings} with Settings... first.": "Rellena primero {settings} con Configurar...",
    "Test e-mail": "Correo de prueba",
    "A test e-mail was sent to {recipients}. Check the inbox (and the spam folder).": (
        "Se ha enviado un correo de prueba a {recipients}. Revisa la bandeja de entrada (y la "
        "carpeta de spam)."
    ),
    "No e-mail": "Sin correo",
    "The e-mail could not be sent: {error}": "No se pudo enviar el correo: {error}",
    # ------------------------------------------------------------------ window: e-mail settings
    "E-mail settings": "Configuración del correo",
    "SMTP server": "Servidor SMTP",
    "Port (empty: the usual one)": "Puerto (vacío: el habitual)",
    "Security": "Seguridad",
    "User name (empty: no login)": "Usuario (vacío: sin inicio de sesión)",
    "From (empty: the user name)": "Remitente (vacío: el usuario)",
    "To (separated by commas)": "Para (separados por comas)",
    "Password": "Contraseña",
    "The password is never written to the configuration file.": (
        "La contraseña nunca se escribe en el archivo de configuración."
    ),
    "Save it in the system keyring here, or set the {variable} environment variable.": (
        "Guárdala aquí en el almacén de claves del sistema, o define la variable de entorno "
        "{variable}."
    ),
    "Set the {variable} environment variable, or install the keyring package (python -m pip "
    "install keyring) to save it in the system keyring.": (
        "Define la variable de entorno {variable}, o instala el paquete keyring (python -m pip "
        "install keyring) para guardarla en el almacén de claves del sistema."
    ),
    "Save in the keyring": "Guardar en el almacén de claves",
    "Invalid e-mail settings": "Configuración de correo no válida",
    "No password": "Sin contraseña",
    "Type the password first.": "Escribe primero la contraseña.",
    "The password was not saved": "No se guardó la contraseña",
    "Password saved": "Contraseña guardada",
    "The password of {user} is now kept in the system keyring.": (
        "La contraseña de {user} se guarda ahora en el almacén de claves del sistema."
    ),
    "The port must be a number, such as 587 (empty: the usual port).": (
        "El puerto debe ser un número, como 587 (vacío: el puerto habitual)."
    ),
    # ------------------------------------------------------------------ window: workbooks
    "Workbooks": "Libros",
    "Data folder": "Carpeta de datos",
    "Browse...": "Examinar...",
    "Folder for the workbooks and the reports": "Carpeta para los libros y los informes",
    "Folder not found": "Carpeta no encontrada",
    "{folder} does not exist yet; the first run creates it.": (
        "{folder} aún no existe; la primera ejecución la crea."
    ),
    "Workbook name": "Nombre del libro",
    "Choose a preset...": "Elige una plantilla...",
    "Manuscript number - Journal - Title (default)": (
        "Número de manuscrito - Revista - Título (predeterminado)"
    ),
    "Paper - Journal - Manuscript number": "Artículo - Revista - Número de manuscrito",
    "Paper - Date of submission - Journal": "Artículo - Fecha de envío - Revista",
    "One workbook per paper (all journals)": "Un libro por artículo (todas las revistas)",
    "Journal acronym - Manuscript number - Title": (
        "Siglas de la revista - Número de manuscrito - Título"
    ),
    "Placeholders: {placeholders}": "Marcadores: {placeholders}",
    "Custom fields: {fields}": "Campos personalizados: {fields}",
    "none yet (add them to a submission, e.g. paper = Tau)": (
        "ninguno todavía (añádelos a un envío, p. ej. paper = Tau)"
    ),
    "Write {title:.40} to keep only the first 40 characters. Submissions whose names "
    "coincide share a workbook, so {paper} keeps all the submissions of a paper (to any "
    "journal) in one file. Existing workbooks keep their names until you click 'Organize "
    "workbooks'.": (
        "Escribe {title:.40} para quedarte solo con los primeros 40 caracteres. Los envíos "
        "cuyos nombres coinciden comparten un libro, así que {paper} guarda todos los envíos "
        "de un artículo (a cualquier revista) en un solo archivo. Los libros existentes "
        "conservan su nombre hasta que pulses 'Organizar libros'."
    ),
    "Current workbook": "Libro actual",
    "Name with this template": "Nombre con esta plantilla",
    "(not recorded yet)": "(aún sin registrar)",
    "{name} (example)": "{name} (ejemplo)",
    "Update preview": "Actualizar vista previa",
    "Organize workbooks...": "Organizar libros...",
    "Organize workbooks": "Organizar libros",
    "Workbooks are organized with the saved settings. Save the current settings now?": (
        "Los libros se organizan con la configuración guardada. ¿Guardar ahora la "
        "configuración actual?"
    ),
    "Nothing to do: the workbooks follow the naming template.": (
        "Nada que hacer: los libros siguen la plantilla de nombres."
    ),
    "No recorded submissions yet.": "Aún no hay envíos registrados.",
    "Left as they are:": "Se dejan como están:",
    "Before merging or splitting, a copy of every workbook involved is saved in the "
    "'backups' subfolder of the data folder. Close the workbooks in Excel first.": (
        "Antes de combinar o dividir, se guarda una copia de cada libro afectado en la "
        "subcarpeta 'backups' de la carpeta de datos. Cierra antes los libros en Excel."
    ),
    "Copies of the workbooks before merging or splitting: {folder}": (
        "Copias de los libros antes de combinar o dividir: {folder}"
    ),
    "Nothing was changed.": "No se ha cambiado nada.",
    "Add a 'Time in status' sheet to every workbook: how long each submission spent in each "
    "status (updated after every change)": (
        "Añadir una hoja 'Time in status' a cada libro: cuánto tiempo pasó cada envío en cada "
        "estado (se actualiza tras cada cambio)"
    ),
    # ------------------------------------------------------------------ window: run
    "Run": "Ejecutar",
    "Run now": "Ejecutar ahora",
    "Dry run": "Simulación",
    "Open last report": "Abrir el último informe",
    "Open reports folder": "Abrir la carpeta de informes",
    "Runs use the settings shown in this window, even before they are saved. A dry run "
    "checks the tracker without writing anything.": (
        "Las ejecuciones usan la configuración que muestra esta ventana, aunque aún no esté "
        "guardada. Una simulación consulta el sistema de seguimiento sin escribir nada."
    ),
    "Nothing to check": "Nada que comprobar",
    "There are no monitored submissions: add one first.": (
        "No hay envíos en seguimiento: añade uno primero."
    ),
    "Dry run of {count} submission...": (
        "Simulación de {count} envío...",
        "Simulación de {count} envíos...",
    ),
    "Checking {count} submission...": (
        "Comprobando {count} envío...",
        "Comprobando {count} envíos...",
    ),
    "Report: {path}": "Informe: {path}",
    "(dry run: nothing was written)": "(simulación: no se escribió nada)",
    "The check could not run": "No se pudo hacer la comprobación",
    "No report": "Sin informe",
    "The last run did not write a report (nothing changed).": (
        "La última ejecución no escribió ningún informe (no cambió nada)."
    ),
    "No reports yet": "Aún no hay informes",
    "No report has been written yet.": "Todavía no se ha escrito ningún informe.",
    "No completed run recorded yet.": "Aún no consta ninguna ejecución completa.",
    "Last run: {finished} - {checked} checked, {changed} with news, {failed} failed.": (
        "Última ejecución: {finished} - comprobados: {checked}, con novedades: {changed}, "
        "con errores: {failed}."
    ),
    "Seconds to wait for each answer from the tracker": (
        "Segundos de espera para cada respuesta del sistema de seguimiento"
    ),
    "The timeout must be a number of seconds, for example 30.": (
        "El tiempo de espera debe ser un número de segundos, por ejemplo 30."
    ),
    "Run automatically at login": "Ejecutar automáticamente al iniciar sesión",
    "Wait for the network and the data folder up to": (
        "Esperar a la red y a la carpeta de datos hasta"
    ),
    "seconds": "segundos",
    "Then check again every": "Después, volver a comprobar cada",
    "hours while you stay logged in (0 = only at login)": (
        "horas mientras sigas con la sesión iniciada (0 = solo al iniciar sesión)"
    ),
    "Enable": "Activar",
    "Disable": "Desactivar",
    "Built-in autostart is not available on this system. See 'Running at login' in the "
    "documentation.": (
        "El inicio automático integrado no está disponible en este sistema. Consulta 'Running "
        "at login' en la documentación."
    ),
    "Not enabled: the monitor does not run when you log in. Enable creates {launcher}.": (
        "No activado: el monitor no se ejecuta al iniciar sesión. Activar crea {launcher}."
    ),
    "Broken: the interpreter {target} does not exist any more. Click Enable to repair it.": (
        "Roto: el intérprete {target} ya no existe. Pulsa Activar para repararlo."
    ),
    "every time you log in": "cada vez que inicies sesión",
    "every time you log in and then every {hours} hours": (
        "cada vez que inicies sesión y después cada {hours} horas"
    ),
    "Enabled: {when}, {launcher} runs {target} {arguments}": (
        "Activado: {when}, {launcher} ejecuta {target} {arguments}"
    ),
    "The autostart launcher could not be read: {error}": (
        "No se pudo leer el lanzador del inicio automático: {error}"
    ),
    "The monitor started at login reads the saved configuration. Save the current settings now?": (
        "El monitor que se ejecuta al iniciar sesión lee la configuración guardada. ¿Guardar "
        "ahora la configuración actual?"
    ),
    "The waiting time must be a whole number of seconds.": (
        "El tiempo de espera debe ser un número entero de segundos."
    ),
    "The interval must be a number of hours, for example 12 (0 = only at login).": (
        "El intervalo debe ser un número de horas, por ejemplo 12 (0 = solo al iniciar sesión)."
    ),
    "Checking every {value} hours is too often: the minimum is {minimum}. Review statuses "
    "change over days, and frequent checks only load the tracker.": (
        "Comprobar cada {value} horas es demasiado frecuente: el mínimo es {minimum}. Los "
        "estados de revisión cambian en cuestión de días, y las comprobaciones frecuentes solo "
        "sobrecargan el sistema de seguimiento."
    ),
    "every time you log in, and then every {hours} hours while you stay logged in (starting "
    "with your next login)": (
        "cada vez que inicies sesión, y después cada {hours} horas mientras sigas con la "
        "sesión iniciada (a partir del próximo inicio de sesión)"
    ),
    "Autostart enabled": "Inicio automático activado",
    "The monitor will run in the background {when}.\n\n{path}": (
        "El monitor se ejecutará en segundo plano {when}.\n\n{path}"
    ),
    "Autostart": "Inicio automático",
    "Autostart disabled.": "Inicio automático desactivado.",
    "Autostart was not enabled.": "El inicio automático no estaba activado.",
    "Show an icon in the notification area while checking periodically, with the latest "
    "statuses (Windows)": (
        "Mostrar un icono en el área de notificación durante las comprobaciones periódicas, "
        "con los últimos estados (Windows)"
    ),
    "every time you log in and then every {hours} hours, with an icon in the notification area": (
        "cada vez que inicies sesión y después cada {hours} horas, con un icono en el área de "
        "notificación"
    ),
    "The icon is shown while the periodic checks run: choose how often to check again (at "
    "least every hour), or untick the icon.": (
        "El icono se muestra durante las comprobaciones periódicas: elige cada cuánto volver "
        "a comprobar (como mínimo cada hora), o desmarca el icono."
    ),
    "An icon in the notification area shows the latest statuses while the periodic checks run.": (
        "Un icono en el área de notificación muestra los últimos estados durante las "
        "comprobaciones periódicas."
    ),
    # ------------------------------------------------------------------ tray icon
    "The icon in the notification area is only available on Windows.": (
        "El icono del área de notificación solo está disponible en Windows."
    ),
    "Checking now...": "Comprobando ahora...",
    "No check yet.": "Aún no se ha hecho ninguna comprobación.",
    "Last check: {moment}, {result}": "Última comprobación: {moment}, {result}",
    "no news": "sin novedades",
    "{count} with news": ("{count} con novedades", "{count} con novedades"),
    "Next check: {moment}": "Próxima comprobación: {moment}",
    "since {date}": "desde {date}",
    "... and {count} more": ("... y {count} más", "... y {count} más"),
    "Open the window": "Abrir la ventana",
    "Open the last report": "Abrir el último informe",
    "Open the data folder": "Abrir la carpeta de datos",
    "Stop the periodic checks": "Detener las comprobaciones periódicas",
}
