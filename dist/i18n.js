/* Interface translations are bundled with the app and work offline.
   Document summaries and letter translations use the local device separately;
   switching the interface language never rewrites a source or authored letter. */
(() => {
  // Same origin in the real demo (dist/ served by the device). During local
  // development dist/ and the backend usually run on different ports, so
  // point at the backend explicitly, or override with window.AFTERWORD_API.
  const API = window.AFTERWORD_API ?? (location.port === '8080' ? 'http://127.0.0.1:8010' : '');
  // Phase 0 finding: Vietnamese needs no extra font — the app's body font
  // (Plus Jakarta Sans) already covers it. Hindi needs Noto Sans Devanagari.
  const LANGUAGES = [
    {code:'en',native:'English'},
    {code:'es',native:'Español'},
    {code:'vi',native:'Tiếng Việt'},
    // This may use an HP-installed Devanagari font when present. We do not
    // fetch a web font: the local deployment has no third-party font traffic.
    {code:'hi',native:'हिन्दी',font:{family:'Noto Sans Devanagari'}},
  ];
  // Phase 7 (L9, stretch): the 12 highest-traffic chrome strings — the 9 nav
  // page headings plus the 3 letter-page action buttons — pre-translated
  // once through POST /translate (kind: instruction) and reviewed by hand,
  // not translated live. Unlike translatedBlock, this never depends on the
  // backend being reachable, so it works even when /health is down.
  //
  // The hand review mattered: on these short, context-free strings the
  // round-trip check was noisier and the model's error rate was higher than
  // on full sentences (phase 6 saw 4/30 flags on real content; here 9 of 36
  // needed a manual fix). Two failure modes not seen on longer text:
  // - The model twice invented ⟦Tn⟧ sentinels into the output even though
  //   the input had nothing to protect (es/vi "Action plan"), the same
  //   invented-sentinel risk phase 0 flagged, just never seen on real
  //   content since the demo's actual text always contains real tokens.
  // - Flat wrong-word or garbled-transliteration errors round-trip cosine
  //   didn't catch at all: Hindi "Privacy" came back as "गुप्तचरता"
  //   (espionage, not privacy), "Activity" as the grammar term for "verb"
  //   rather than "activity", and "Gmail"/"draft" came back with garbled
  //   spelling that a native reader would need to guess at. Vietnamese
  //   "Letters" came back as "Thông báo" (notice/announcement), not
  //   correspondence. All corrected by hand below; the raw model output is
  //   in backend/dev/labels_raw.json for anyone re-reviewing this later.
  const UI_LABELS = {
    es: {
      'Overview': 'Resumen', 'Action plan': 'Plan de acción', 'Documents': 'Documentos',
      'Evidence review': 'Revisión de la evidencia', 'Letters': 'Cartas', 'Memories': 'Recuerdos',
      'Privacy': 'Privacidad', 'Activity': 'Actividad', 'Settings': 'Ajustes',
      'Save draft': 'Guardar borrador', 'Print letter': 'Imprimir la carta', 'Open in Gmail': 'Abrir en Gmail',
    },
    vi: {
      'Overview': 'Tổng quan', 'Action plan': 'Kế hoạch hành động', 'Documents': 'Các văn bản',
      'Evidence review': 'Kiểm tra bằng chứng', 'Letters': 'Thư từ', 'Memories': 'Những kỷ niệm',
      'Privacy': 'Quyền riêng tư', 'Activity': 'Hoạt động', 'Settings': 'Cài đặt',
      'Save draft': 'Lưu bản nháp', 'Print letter': 'In thư', 'Open in Gmail': 'Mở trong Gmail',
    },
    hi: {
      'Overview': 'सारांश', 'Action plan': 'कार्य योजना', 'Documents': 'दस्तावेज़',
      'Evidence review': 'साक्ष्य की जांच', 'Letters': 'पत्र', 'Memories': 'यादें',
      'Privacy': 'गोपनीयता', 'Activity': 'गतिविधि', 'Settings': 'सेटिंग्स',
      'Save draft': 'ड्राफ्ट सहेजें', 'Print letter': 'पत्र छापें', 'Open in Gmail': 'जीमेल में खोलें',
    },
  };
  // Falls back to the English string itself, so every call site is safe to
  // use unconditionally, in English and for any label outside this table.
  window.uiLabel = text => (window.AFTERWORD_I18N_CRAWL ? text : UI_LABELS[state.lang]?.[text] || text);

  const loadedFonts = new Set();
  let backendUp = null;
  const spanish = new Map(Object.entries({
    'Overview':'Resumen', 'Action plan':'Plan de acción', 'Documents':'Documentos',
    'Evidence review':'Revisión de fuentes', 'Letters':'Cartas', 'Memories':'Recuerdos',
    'Privacy':'Privacidad', 'Activity':'Actividad', 'Settings':'Configuración',
    'Workspace':'Espacio de trabajo', 'WORKSPACE':'ESPACIO DE TRABAJO',
    'YOUR WORKSPACE':'TU ESPACIO DE TRABAJO', 'FAMILY WORKSPACE':'ESPACIO FAMILIAR',
    'Family workspace':'Espacio familiar', 'Sample workspace':'Espacio de ejemplo',
    'Search workspace':'Buscar en el espacio', 'Search your workspace':'Buscar en tu espacio',
    'Search pages, documents or actions…':'Buscar páginas, documentos o acciones…',
    'Search pages, documents or actions':'Buscar páginas, documentos o acciones',
    'Questions about records':'Preguntas sobre los documentos', 'Ask about records':'Consultar documentos',
    'Skip to content':'Ir al contenido', 'Open navigation':'Abrir navegación',
    'Close navigation':'Cerrar navegación', 'Main navigation':'Navegación principal',
    'Afterword home':'Inicio de Afterword', 'How to use Afterword':'Cómo usar Afterword',
    'How to use this workspace':'Cómo usar este espacio', 'Appearance preferences':'Preferencias de lectura',
    'Changes saved in this browser':'Cambios guardados en este navegador',
    'Fictional records · Browser-local demo':'Documentos ficticios · Demostración en este navegador',
    'Make yourself comfortable':'Lee a tu manera', 'Reading preferences':'Preferencias de lectura',
    'Reading language':'Idioma de lectura', 'Language':'Idioma', 'Text size':'Tamaño del texto',
    'Set the reading size and background movement that feel comfortable.':'Elige el tamaño del texto y el movimiento de fondo que prefieras.',
    'Standard':'Estándar', 'Larger':'Más grande', 'Background motion':'Movimiento de fondo',
    'Still':'Sin movimiento', 'Gentle':'Suave', 'Gentle motion':'Movimiento suave', 'Slow daylight movement':'Movimiento suave de luz',
    'Slow daylight movement on Overview and Memories. Reading and editing areas stay still.':'Movimiento suave de luz en Resumen y Recuerdos. Las áreas de lectura y edición permanecen inmóviles.',
    'Your device has reduced motion on. The background stays still.':'Tu dispositivo tiene activada la reducción de movimiento. El fondo permanece inmóvil.',
    'These preferences stay in this browser.':'Estas preferencias se guardan en este navegador.',
    'Save preferences':'Guardar preferencias', 'Appearance preferences saved':'Preferencias guardadas',
    'Close dialog':'Cerrar ventana', 'Close':'Cerrar', 'Done':'Listo', 'Cancel':'Cancelar',
    'Not yet':'Ahora no', 'Back':'Atrás', 'Continue':'Continuar', 'Save':'Guardar', 'Edit':'Editar',
    'Change':'Cambiar', 'Remove':'Eliminar', 'Download':'Descargar', 'Refresh':'Actualizar',
    'Your family workspace.':'Tu espacio familiar.',
    'Organize the records, confirm what’s unclear, and keep track of what comes next.':'Organiza los documentos, aclara las dudas y lleva el seguimiento de los próximos pasos.',
    'Add documents':'Añadir documentos', 'Add records':'Añadir documentos',
    'Open actions':'Acciones pendientes', 'Unread findings':'Hallazgos sin leer',
    'Saved memories':'Recuerdos guardados', 'In your sample archive':'En tu archivo de ejemplo',
    'A space for the personal':'Un espacio para lo personal', 'NEXT ACTION':'PRÓXIMA ACCIÓN',
    'Review this step':'Revisar este paso', 'See your plan':'Ver tu plan',
    'Dates to keep in view':'Fechas para recordar', 'On your list':'En tu lista',
    'View all actions':'Ver todas las acciones', 'Family memories':'Recuerdos familiares',
    'Read saved letters, recipes and personal notes.':'Lee cartas, recetas y notas personales guardadas.',
    'Review the source records.':'Revisa los documentos originales.',
    'Explore the evidence':'Explorar las fuentes', 'Workspace activity':'Actividad del espacio',
    'Your next steps.':'Tus próximos pasos.', 'All actions':'Todas las acciones',
    'Ready':'Listo', 'Needs review':'Necesita revisión', 'Waiting':'En espera', 'Completed':'Completado',
    'All':'Todos', 'All categories':'Todas las categorías', 'Filter actions':'Filtrar acciones',
    'Search actions':'Buscar acciones', 'Search your actions…':'Buscar en tus acciones…',
    'Category':'Categoría', 'Status':'Estado', 'Sort by':'Ordenar por', 'Suggested order':'Orden sugerido',
    'Clear filters':'Quitar filtros', 'Export plan':'Descargar plan', 'Export plan (PDF)':'Descargar plan (PDF)',
    'A plan you can breathe with.':'Un plan que te permite respirar.',
    'A few practical steps. Every one connected to the record that brought it here.':'Pasos prácticos, cada uno vinculado al documento que lo originó.',
    'Your note':'Tu nota', 'Your notes':'Tus notas', 'Personal reminder':'Recordatorio personal',
    'Mark as completed':'Marcar como completado', 'Reopen action':'Reabrir acción',
    'Waiting for a reply':'Esperando una respuesta', 'Resume action':'Retomar acción',
    'Start with the source':'Comenzar por la fuente', 'Compare the evidence':'Comparar las fuentes',
    'Prepare a letter':'Preparar una carta', 'Prepare a question':'Preparar una consulta',
    'View source':'Ver fuente', 'Read the record':'Leer el documento', 'Original source':'Fuente original',
    'Source records':'Documentos originales', 'Mark as read':'Marcar como leído', 'Read · Undo':'Leído · Deshacer',
    'Everything, brought together.':'Todo, en un mismo lugar.',
    'A place for the records you have, and the details you’re still piecing together.':'Un lugar para tus documentos y los detalles que aún estás reuniendo.',
    'Search documents':'Buscar documentos', 'Search names, documents or details…':'Buscar nombres, documentos o detalles…',
    'Type':'Tipo', 'Document type':'Tipo de documento', 'All types':'Todos los tipos',
    'DOCUMENT':'DOCUMENTO', 'CATEGORY':'CATEGORÍA', 'RECORD DATE':'FECHA DEL DOCUMENTO',
    'REVIEW STATUS':'ESTADO DE REVISIÓN', 'Open evidence review':'Abrir revisión de fuentes',
    'Choose records':'Elegir documentos', 'Process records':'Procesar documentos',
    'Process remaining records':'Procesar documentos pendientes', 'No files selected.':'No se han elegido archivos.',
    'Date of death / reference date (optional)':'Fecha de fallecimiento o de referencia (opcional)',
    'Back to workspace':'Volver al espacio', 'Back to documents':'Volver a documentos',
    'Search records':'Buscar documentos', 'Search local records':'Buscar documentos locales',
    'Download source text':'Descargar texto original', 'Download source':'Descargar fuente',
    'Previous lines':'Líneas anteriores', 'Next lines':'Líneas siguientes',
    'Clarity starts with the source.':'La claridad empieza por la fuente.',
    'See what the records say, what they leave open, and a sensible next step.':'Revisa lo que dicen los documentos, lo que queda por aclarar y el siguiente paso.',
    'IN THE RECORD':'EN EL DOCUMENTO', 'STILL UNKNOWN':'POR ACLARAR', 'A HELPFUL NEXT STEP':'UN SIGUIENTE PASO ÚTIL',
    'Confirmation needed':'Se necesita confirmación', 'Read them side by side':'Léelos uno junto al otro',
    'A few words to get you started.':'Unas palabras para empezar.',
    'Letter':'Carta', 'Recipient':'Destinatario', 'Recipient email':'Correo del destinatario',
    'Recipient email address':'Correo del destinatario', 'Subject':'Asunto', 'Your name':'Tu nombre',
    'Your full name':'Tu nombre completo', 'Phone':'Teléfono', 'Your phone':'Tu teléfono',
    'Relationship / authority':'Relación o autorización', 'Date of death':'Fecha de fallecimiento',
    'Account reference':'Referencia de la cuenta', 'Letter type':'Tipo de carta', 'Message':'Mensaje',
    'Prepare letter':'Preparar carta', 'Review letter':'Revisar carta', 'Edit letter':'Editar carta',
    'Save draft':'Guardar borrador', 'Copy letter':'Copiar carta', 'Print letter':'Imprimir carta',
    'Download letter':'Descargar carta', 'Use my email app':'Usar mi aplicación de correo',
    'Open in Gmail':'Abrir en Gmail', 'Keep editing':'Seguir editando',
    'What you’re sharing':'Lo que vas a compartir', 'Before handoff':'Antes de abrir el correo',
    'Update your profile':'Actualizar tu perfil', 'Complete your profile':'Completar tu perfil',
    'Return to letter':'Volver a la carta', 'Profile':'Perfil', 'Your profile':'Tu perfil',
    'Save profile':'Guardar perfil', 'Edit profile':'Editar perfil', 'Workspace profile':'Perfil del espacio',
    'Getting started':'Primeros pasos', 'Set up your workspace':'Configura tu espacio',
    'Welcome to Afterword':'Bienvenido a Afterword', 'Open workspace':'Abrir espacio',
    'Sign in':'Iniciar sesión', 'Sign out':'Cerrar sesión', 'Log in':'Iniciar sesión',
    'Email':'Correo electrónico', 'Password':'Contraseña', 'Confirm password':'Confirmar contraseña',
    'Unlock workspace':'Desbloquear espacio', 'Lock workspace':'Bloquear espacio',
    'Memories, in their own time.':'Recuerdos, a su propio ritmo.',
    'All memories':'Todos los recuerdos', 'Saved':'Guardados', 'Back to memories':'Volver a recuerdos',
    'Workspace settings':'Configuración del espacio', 'Make this space yours.':'Haz tuyo este espacio.',
    'Reading preferences, local data and a clear view of what is connected.':'Preferencias de lectura, datos locales y conexiones disponibles.',
    'Your local workspace.':'Tu espacio local.', 'Text size, language and background motion.':'Tamaño del texto, idioma y movimiento de fondo.',
    'Appearance':'Apariencia', 'Keep a copy':'Guardar una copia', 'Export workspace':'Exportar espacio',
    'Connection status':'Estado de conexión', 'CONNECTIONS':'CONEXIONES',
    'Connected':'Conectado', 'Not connected':'Sin conexión', 'Not configured':'Sin configurar',
    'About this edition':'Acerca de esta versión', 'Archive':'Archivo', 'Organizer':'Organizador',
    'Working letters':'Cartas en preparación', 'Record storage':'Almacenamiento de documentos',
    'Local device database':'Base de datos del dispositivo', 'Notes and read marks':'Notas y marcas de lectura',
    'This browser':'Este navegador', 'Session only':'Solo esta sesión', 'Export notes':'Exportar notas',
    'Your activity.':'Tu actividad.', 'Export activity':'Descargar actividad',
    'Export activity (PDF)':'Descargar actividad (PDF)', 'Print':'Imprimir',
    'No activity yet.':'Aún no hay actividad.', 'No matches':'Sin resultados',
    'A SPACE FOR WHAT COMES NEXT':'UN ESPACIO PARA LO QUE VIENE',
    'A little clarity. One step at a time.':'Un poco de claridad. Un paso a la vez.',
    'Bring the records together, understand what needs attention, and take the next step when you are ready.':'Reúne los documentos, comprende qué necesita atención y da el siguiente paso cuando estés listo.',
    'Keep the important records together.':'Mantén juntos los documentos importantes.',
    'Review the details before you act.':'Revisa los detalles antes de actuar.',
    'Prepare letters and keep track of progress.':'Prepara cartas y lleva el seguimiento del progreso.',
    'A local workspace on your Afterword device.':'Un espacio local en tu dispositivo Afterword.',
    'An interactive preview with fictional records.':'Una demostración interactiva con documentos ficticios.',
    'Workspace name':'Nombre del espacio',
    'Person whose records you are organizing':'Persona cuyos documentos estás organizando',
    'These details help prepare your letters. You can complete or change them later.':'Estos datos ayudan a preparar tus cartas. Puedes completarlos o cambiarlos más adelante.',
    'Your relationship / authority':'Tu relación o autorización',
    'For example, daughter; authority not yet confirmed':'Por ejemplo, hija; autorización aún no confirmada',
    'Inbox for trying the letter workflow':'Bandeja de entrada para probar las cartas',
    'Sample providers use fictional addresses. Enter an inbox you have permission to use if you want to open a test email draft.':'Los proveedores de ejemplo usan direcciones ficticias. Introduce una bandeja de entrada que tengas permiso para usar si quieres abrir un borrador de prueba.',
    'Approved demo inbox':'Correo autorizado para la demostración',
    'I have permission to use this inbox for the demo.':'Tengo permiso para usar este correo en la demostración.',
    'Create a workspace password':'Crea una contraseña para el espacio',
    'Use at least 10 characters. This password unlocks this device workspace; it is not a cloud account.':'Usa al menos 10 caracteres. Esta contraseña desbloquea el espacio en este dispositivo; no es una cuenta en la nube.',
    'Preview profile and drafts are saved in this browser, without encryption. Use fictional details.':'El perfil y los borradores de la demostración se guardan en este navegador, sin cifrado. Usa datos ficticios.',
    'Your profile is saved in the local database on the Afterword device. It is not uploaded to a cloud account.':'Tu perfil se guarda en la base de datos local del dispositivo Afterword. No se sube a una cuenta en la nube.',
    'A few details now mean less repeated typing later.':'Añadir algunos datos ahora te evitará escribirlos de nuevo más adelante.',
    'Saving…':'Guardando…', 'Open my workspace':'Abrir mi espacio',
    'Explore sample first':'Explorar primero el ejemplo', 'Back to overview':'Volver al resumen',
    'Opening your workspace…':'Abriendo tu espacio…', 'Checking the local connection.':'Comprobando la conexión local.',
    'Reconnect to your workspace':'Vuelve a conectar con tu espacio', 'Try again':'Intentar de nuevo',
    'Welcome back':'Bienvenido de nuevo', 'Unlock the workspace on this device to continue.':'Desbloquea el espacio en este dispositivo para continuar.',
    'Workspace password':'Contraseña del espacio', 'Signing in…':'Iniciando sesión…',
    'Your records remain on the Afterword device.':'Tus documentos permanecen en el dispositivo Afterword.',
    'WELCOME TO AFTERWORD':'BIENVENIDO A AFTERWORD', 'Start with a little context.':'Empieza con un poco de contexto.',
    'Set up your profile to reuse your details in letters, or explore the fictional family workspace first.':'Configura tu perfil para reutilizar tus datos en las cartas o explora primero el espacio familiar ficticio.',
    'Set up preview':'Configurar demostración',
    'This public preview has no account sign-in or cloud database. Local sign-in is available when running Afterword on your device.':'Esta demostración pública no tiene inicio de sesión ni base de datos en la nube. El inicio de sesión local está disponible al ejecutar Afterword en tu dispositivo.',
    'Profile saved. Your details are ready to use in letters.':'Perfil guardado. Tus datos están listos para usarse en las cartas.',
    'Workspace access':'Acceso al espacio', 'Sign out when you finish on a shared computer.':'Cierra la sesión cuando termines en un equipo compartido.',
    'Edit your profile':'Editar tu perfil',
    'Your name, contact details, workspace and reading language.':'Tu nombre, datos de contacto, espacio e idioma de lectura.',
    'Add your name and workspace name.':'Añade tu nombre y el nombre del espacio.',
    'Enter a valid contact phone number.':'Introduce un número de teléfono válido.',
    'Enter a valid date of death that is not in the future.':'Introduce una fecha de fallecimiento válida que no sea futura.',
    'Use a real inbox that accepts replies.':'Usa una dirección de correo real que acepte respuestas.',
    'Confirm permission to use this inbox.':'Confirma que tienes permiso para usar este correo.',
    'The workspace service could not be reached. Try again.':'No se pudo conectar con el servicio del espacio. Inténtalo de nuevo.',
    'The workspace service returned an unexpected session. Reconnect to continue.':'El servicio devolvió una sesión inesperada. Vuelve a conectar para continuar.',
    'The workspace could not be unlocked. Try signing in again.':'No se pudo desbloquear el espacio. Intenta iniciar sesión de nuevo.',
    'Your session has ended. Sign in and try again.':'Tu sesión ha finalizado. Inicia sesión e inténtalo de nuevo.',
    'Enter the inbox before confirming permission to use it.':'Introduce el correo antes de confirmar que tienes permiso para usarlo.',
    'This request belongs to an earlier session.':'Esta solicitud pertenece a una sesión anterior.',
    'The password is incorrect.':'La contraseña es incorrecta.',
    'Too many incorrect passwords. Try again in one minute.':'Se han introducido demasiadas contraseñas incorrectas. Inténtalo de nuevo en un minuto.',
    'This workspace is already set up. Sign in with its password.':'Este espacio ya está configurado. Inicia sesión con su contraseña.',
    'Set up this workspace before signing in.':'Configura este espacio antes de iniciar sesión.',
    'Sign in to update your workspace profile.':'Inicia sesión para actualizar el perfil del espacio.',
    'Enter your display name.':'Introduce tu nombre.', 'Enter a workspace name.':'Introduce un nombre para el espacio.',
    'Choose English, Spanish, Vietnamese, or Hindi as the reading language.':'Elige inglés, español, vietnamita o hindi como idioma de lectura.',
    'Enter a valid contact phone number, or leave it blank for now.':'Introduce un número de teléfono válido o déjalo en blanco por ahora.',
    'Enter a valid date of death that is not in the future, or leave it blank.':'Introduce una fecha de fallecimiento válida que no sea futura o déjala en blanco.',
    'Enter a real mailbox you control, or leave the demo mailbox blank.':'Introduce un correo real que controles o deja en blanco el correo de demostración.',
    'Enter the mailbox before confirming that you control it.':'Introduce el correo antes de confirmar que lo controlas.',
    'Profile details cannot contain line breaks or control characters.':'Los datos del perfil no pueden contener saltos de línea ni caracteres de control.',
    'Local password storage is unavailable. Install the application requirements and try again.':'El almacenamiento local de contraseñas no está disponible. Instala los requisitos de la aplicación e inténtalo de nuevo.',
    'Check the details and try again.':'Revisa los datos e inténtalo de nuevo.',
    'Browser storage is unavailable. Allow local storage before saving this preview profile.':'El almacenamiento del navegador no está disponible. Permite el almacenamiento local antes de guardar este perfil de demostración.',
    'LETTERS':'CARTAS', 'Make the next conversation easier.':'Facilita la próxima conversación.',
    'Find the right contact, prepare a short letter, and decide what to share.':'Encuentra el contacto adecuado, prepara una carta breve y decide qué compartir.',
    'Related action':'Acción relacionada', 'LETTER TEMPLATES':'PLANTILLAS DE CARTAS',
    'Your words, your decision.':'Tus palabras, tu decisión.',
    'Afterword prepares the letter. You review the details and press Send in your email app.':'Afterword prepara la carta. Tú revisas los datos y pulsas Enviar en tu aplicación de correo.',
    'Review the evidence':'Revisar las fuentes', 'Review the action':'Revisar la acción',
    'Choose who to contact':'Elige a quién contactar', 'Refresh contacts':'Actualizar contactos',
    'Finding contacts…':'Buscando contactos…', 'Enter a contact you have verified':'Introduce un contacto que hayas verificado',
    'Prepare your letter':'Prepara tu carta', 'Use your saved profile details, or enter them below.':'Usa los datos de tu perfil guardado o introdúcelos aquí.',
    'Use profile details':'Usar datos del perfil', 'Use approved inbox':'Usar correo autorizado',
    'The contact in this fictional record cannot receive email.':'El contacto de este documento ficticio no puede recibir correos.',
    'Add an approved inbox in your profile':'Añadir un correo autorizado a tu perfil',
    'Required':'Obligatorio', 'Prepare letter from these details':'Preparar carta con estos datos',
    'Replace letter from these details':'Reemplazar carta con estos datos',
    'Review before sharing':'Revisa antes de compartir',
    'The next screen shows the exact recipient, subject, letter and attachment reminders. Nothing is sent automatically.':'La siguiente pantalla muestra el destinatario, el asunto, la carta y los recordatorios de adjuntos exactos. No se envía nada automáticamente.',
    'Complete your contact details above, then review the full letter.':'Completa tus datos de contacto arriba y revisa la carta completa.',
    'Complete these details before reviewing:':'Completa estos datos antes de revisar:',
    'All required details are complete. Review the letter before sharing.':'Todos los datos obligatorios están completos. Revisa la carta antes de compartirla.',
    'Complete the highlighted details, then review your letter.':'Completa los datos resaltados y revisa tu carta.',
    'Review & choose email app':'Revisar y elegir aplicación de correo',
    'Reset this letter':'Restablecer esta carta', 'Review what you’re about to share':'Revisa lo que vas a compartir',
    'Back to edit':'Volver a editar', 'Create Gmail draft':'Crear borrador en Gmail',
    'Full letter':'Carta completa', 'Attachments':'Adjuntos', 'To':'Para', 'From':'De', 'Source':'Fuente',
    'Chosen in your email app · not verified by Afterword':'Se elige en tu aplicación de correo · Afterword no lo ha verificado',
    'Gmail may use the account already signed in to this browser. Check the From address there before sending. For a team demonstration, use your team mailbox.':'Gmail puede usar la cuenta que ya tiene una sesión iniciada en este navegador. Comprueba la dirección del remitente antes de enviar. Para una demostración en equipo, usa el correo del equipo.',
    'I will verify the sending account in my email app before pressing Send.':'Comprobaré la cuenta del remitente en mi aplicación de correo antes de pulsar Enviar.',
    'Confirm that you will check the sending account before opening your email app.':'Confirma que comprobarás la cuenta del remitente antes de abrir tu aplicación de correo.',
    'Confirm the recipient above before continuing.':'Confirma el destinatario de arriba antes de continuar.',
    'Preparing your plan PDF…':'Preparando tu plan en PDF…',
    'Your plan PDF download has started.':'La descarga de tu plan en PDF ha comenzado.',
    'The plan PDF could not be created. Please try again.':'No se pudo crear el plan en PDF. Inténtalo de nuevo.',
    'Preparing your activity PDF…':'Preparando tu actividad en PDF…',
    'Your activity PDF download has started.':'La descarga de tu actividad en PDF ha comenzado.',
    'The activity PDF could not be created. Please try again.':'No se pudo crear la actividad en PDF. Inténtalo de nuevo.',
    'Action plan PDF downloaded.':'Se ha iniciado la descarga del plan en PDF.',
    'Activity PDF downloaded.':'Se ha iniciado la descarga de la actividad en PDF.',
    'PDF export files could not load. Reconnect to the Afterword site and try again.':'No se pudieron cargar los archivos para exportar el PDF. Vuelve a conectar con Afterword e inténtalo de nuevo.',
    'PDF export files are unavailable. Reload Afterword and try again.':'Los archivos para exportar el PDF no están disponibles. Recarga Afterword e inténtalo de nuevo.',
    'I checked this recipient and confirm it is an inbox I control or am authorized to contact.':'He comprobado este destinatario y confirmo que controlo este correo o tengo autorización para contactarlo.',
    'This recipient is outside your configured demo inbox and verified domains. Do not send test mail to a real provider. For this fictional case, use an approved demo inbox.':'Este destinatario no pertenece al correo de demostración configurado ni a los dominios verificados. No envíes pruebas a un proveedor real. Usa un correo autorizado para este caso ficticio.',
    'WORKSPACE SETTINGS':'CONFIGURACIÓN DEL ESPACIO', 'Your sample workspace':'Tu espacio de ejemplo',
    'Staged file names':'Nombres de archivos en espera', 'Browser notes & draft cache':'Notas y borradores del navegador',
    'Local browser storage · unencrypted':'Almacenamiento local del navegador · sin cifrado',
    'Local record archive':'Archivo local de documentos',
    'Text records and scans are stored by the local service when uploaded.':'Los textos y los documentos escaneados se guardan en el servicio local cuando los subes.',
    'Not connected. Staging a file name does not read its contents.':'Sin conexión. Añadir un nombre de archivo a la lista no lee su contenido.',
    'Export notes, reminders, draft text and demo preferences as JSON.':'Exporta las notas, los recordatorios, los borradores y las preferencias de la demostración en formato JSON.',
    'Start fresh':'Empezar de nuevo', 'Reset demo':'Restablecer demostración', 'Undo reset':'Deshacer restablecimiento',
    'Restore the fictional workspace. Export first if you want to keep your edits.':'Restaura el espacio ficticio. Exporta primero si quieres conservar tus cambios.',
    'Your previous workspace can be restored until you reload this page.':'Puedes recuperar tu espacio anterior mientras no recargues esta página.',
    'Text record intake':'Importación de documentos de texto', 'Connected to local service':'Conectado al servicio local',
    'Gmail drafts':'Borradores de Gmail', 'Ready to connect':'Listo para conectar', 'Not checked':'Sin comprobar',
    'Sending messages':'Envío de mensajes', 'You send from your email app':'Tú envías desde tu aplicación de correo',
    'The website uses system fonts without external font requests. It makes no AI requests and has no analytics or account integration.':'El sitio utiliza las fuentes del sistema sin solicitar fuentes externas. No hace consultas a modelos de IA ni integra analítica o cuentas.',
    'The website uses system fonts without external font requests. Local outreach can read selected records and use the configured model. Email connections require separate permission.':'El sitio utiliza las fuentes del sistema sin solicitar fuentes externas. El servicio local puede leer los documentos seleccionados y utilizar el modelo configurado. Las conexiones de correo requieren un permiso aparte.',
    'A fictional family case for trying the workflow. Documents, names, providers and amounts are examples.':'Un caso familiar ficticio para probar el proceso. Los documentos, los nombres, los proveedores y los importes son ejemplos.',
    'Provider outreach':'Contacto con proveedores', 'Outreach runtime':'Modo de contacto',
    'Choose an inbox you have permission to use for the demo. Gmail contacts use plus-address aliases; other domains use the exact approved inbox; they never point at real fictional-provider addresses.':'Elige un correo que tengas permiso para usar en la demostración. Gmail utiliza alias con el signo +; otros dominios usan el correo autorizado exacto. Nunca se envía a direcciones de proveedores ficticios.',
    'Use this site’s local service when available':'Usar el servicio local de este sitio cuando esté disponible',
    'Browser templates only':'Solo plantillas del navegador',
    'No local service connected. Browser templates and Gmail compose work without one. No records are sent to another host for processing.':'No hay un servicio local conectado. Las plantillas del navegador y los borradores de Gmail funcionan sin él. No se envían documentos a otro equipo para procesarlos.',
    'Checking this site for the local service… No records are sent to another host for processing.':'Comprobando el servicio local de este sitio… No se envían documentos a otro equipo para procesarlos.',
    'Recipient for test letters:':'Destinatario de las cartas de prueba:',
    'Your profile holds the approved recipient. The sending account is chosen separately in your email app.':'Tu perfil guarda el destinatario autorizado. La cuenta del remitente se elige por separado en tu aplicación de correo.',
    'Edit profile and demo inbox':'Editar perfil y correo de demostración',
    'Your actual team inbox':'El correo real de tu equipo',
    'Leave the inbox empty to remove demo aliases. An address is never assumed to belong to Team 102.':'Deja el correo en blanco para eliminar los alias de demostración. Nunca se da por hecho que una dirección pertenece al Equipo 102.',
    'Save outreach settings':'Guardar configuración de contacto',
    'Check local service again':'Comprobar de nuevo el servicio local',
    'Gmail draft connection':'Conexión de borradores de Gmail',
    'Reset demo clears browser outreach drafts and history. It does not delete records held by the local service.':'Restablecer la demostración borra los borradores y el historial de contacto del navegador. No elimina los documentos guardados en el servicio local.',
    'Reading preferences, connection details, and your notes.':'Preferencias de lectura, detalles de conexión y tus notas.',
    'Local model':'Modelo local', 'Contract':'Contrato',
    'Average output tokens / document':'Promedio de tokens de salida por documento',
    'Average latency / document':'Tiempo medio por documento',
    'These measurements come from the stored model responses. They are not a live hardware benchmark.':'Estas mediciones proceden de las respuestas guardadas del modelo. No son una prueba de rendimiento del equipo en tiempo real.',
    'Font files':'Archivos de fuentes', 'System fonts · no external request':'Fuentes del sistema · sin solicitudes externas',
    'Last archive refresh':'Última actualización del archivo', 'Not loaded':'Sin cargar', 'Not available':'No disponible',
    'Open sample preview':'Abrir demostración de ejemplo',
    'The sample preview is separate from your device records. Opening it does not replace or delete this archive.':'La demostración de ejemplo está separada de los documentos de tu dispositivo. Abrirla no reemplaza ni elimina este archivo.',
    'Compare each finding with its original excerpt and see what still needs confirmation.':'Compara cada hallazgo con su fragmento original y comprueba lo que aún falta por confirmar.',
    'Your review does not confirm a finding':'Leer un hallazgo no confirma su contenido',
    'Progress saved in this browser':'Progreso guardado en este navegador',
    'Your reminder':'Tu recordatorio', 'Sample provider follow-up':'Seguimiento de proveedor de ejemplo',
    'These are personal reminders and sample follow-up dates, not legal deadlines.':'Son recordatorios personales y fechas de seguimiento de ejemplo, no plazos legales.',
  }));
  const interfaceLanguage = () => state.lang === 'es' ? 'es' : 'en';
  const dynamicLabels = [
    [/^(\d+) saved drafts$/,m=>`${m[1]} borradores guardados`],
    [/^(\d+) names only · file contents not included$/,m=>`${m[1]} nombres solamente · sin contenido de los archivos`],
    [/^(\d+) completed$/,m=>`${m[1]} completadas`],
    [/^(\d+) findings · (\d+) read$/,m=>`${m[1]} hallazgos · ${m[2]} leídos`],
    [/^(\d+) measured records$/,m=>`${m[1]} documentos medidos`],
    [/^(Standard|Larger) text · (gentle background motion|still background)\. Your device’s reduced-motion preference takes priority\.$/,m=>`Texto ${m[1]==='Standard'?'estándar':'más grande'} · ${m[2]==='still background'?'fondo sin movimiento':'movimiento suave de fondo'}. La reducción de movimiento de tu dispositivo tiene prioridad.`],
    [/^Local service connected on (https?:\/\/\S+) No records are sent to another host for processing\.$/,m=>`Servicio local conectado en ${m[1]} No se envían documentos a otro equipo para procesarlos.`],
  ];
  const t = (text, lang = interfaceLanguage()) => {
    if(lang !== 'es') return text;
    if(spanish.has(text)) return spanish.get(text);
    for(const [pattern,translate] of dynamicLabels){const match=String(text).match(pattern);if(match)return translate(match);}
    return text;
  };
  // Limit automatic localization to application chrome. User-authored content,
  // document titles/excerpts, quotes and editable values are never rewritten.
  const uiSelectors = ['.sidebar','.topbar','.footnote','.skip','.page-heading',
    '.section-title','.filter-bar','.library-head','.library-tools','.workspace-metrics',
    '.modal-head','.modal-foot','.modal-body > p','.setting-action','.settings-facts','.connection-row',
    '.settings-panel > h2','.settings-panel > p','.settings-panel > .eyebrow','.settings-panel > .notice-strip',
    '.outreach-settings','.findings-panel > h2','.findings-panel > p','.findings-metric-list',
    '.review-summary','.memory-invitation','.next-step-top','.activity small','.upcoming-panel > .fine',
    '.field > span','.field > small','.compact-field > span','.type-filter > span',
    '.outreach-step-title','.outreach-template-heading','.outreach-aside-note','.outreach-profile-link',
    '.outreach-demo-choice','.outreach-finish > p','#outreach-validation','.outreach-review h3',
    '.outreach-review-envelope dt','.outreach-review-envelope > div:first-child > dd',
    '.outreach-sender-note','.outreach-check > span','.outreach-warning','#outreach-review-error',
    '.button','.text-link','button[data-action]','option[value]','.empty-state',
    '#reading-language-note','#language-interface-note','#motion-preference-note','#toast','#profile-error','.workspace-entry .form-error','.translated-label','[data-i18n]',
    'input[placeholder]','input[aria-label]','select[aria-label]','textarea[aria-label]'].join(',');
  const excluded = '[data-no-translate],[translate="no"],script,style,textarea,input,'+
    'pre,code,blockquote,[contenteditable],.record-paper,.memory-reading,.memory-card,'+
    '.finding-memory-card,.finding-source-lines,.source-link,.document-row,.source-tabs,'+
    '.letter-preview,.letter-paper,.outreach-letter-preview,.scan-contact,.finding-citations,'+
    '.estate-label strong,.profile strong,.avatar,.task-copy,.plan-content h2,.doc-title,'+
    '.finding-search-result strong';
  const originals = new WeakMap(), originalAttributes = new WeakMap();
  let applying = false;
  function applyInterface(root = document) {
    if (applying || !root?.querySelectorAll) return;
    applying = true;
    try {
      const lang = interfaceLanguage();
      document.documentElement.lang = lang;
      const elements = [...root.querySelectorAll(uiSelectors)];
      if (root.matches?.(uiSelectors)) elements.unshift(root);
      for (const element of elements) {
        // Translate field accessibility labels, never their editable values.
        if (!element.closest?.(excluded.replace('textarea,input,',''))) {
          const attrs = originalAttributes.get(element) || {};
          for (const name of ['aria-label','placeholder','title']) {
            const current = element.getAttribute?.(name);
            if (current == null) continue;
            if (!attrs[name] || current !== attrs[name].last) attrs[name] = {source:current,last:current};
            const value = t(attrs[name].source,lang);
            if (value !== current) element.setAttribute(name,value);
            attrs[name].last = value;
          }
          originalAttributes.set(element,attrs);
        }
        if (element.closest?.(excluded)) continue;
        const walker = document.createTreeWalker(element,4);
        let node;
        while ((node = walker.nextNode())) {
          if (node.parentElement?.closest(excluded)) continue;
          const factValue=node.parentElement?.closest('.settings-facts dd');
          if(factValue){const label=factValue.parentElement.querySelectorAll('dt')[0]?.textContent.trim();if(['Archive','Organizer','Archivo','Organizador'].includes(label))continue;}
          // An option without a value attribute derives its submitted value
          // from its text. Do not change filtering or form semantics by translating it.
          if (node.parentElement?.tagName === 'OPTION' && node.parentElement.getAttribute('value') === null) continue;
          if (state.route === 'evidence' && window.AfterwordFindings?.active() && node.parentElement?.closest('h1')) continue;
          if (node.parentElement?.closest('#dialog-title') && $('#dialog-content .record-paper')) continue;
          const current = node.nodeValue;
          let entry = originals.get(node);
          if (!entry || current !== entry.last) entry = {source:current,last:current};
          const trimmed = entry.source.trim(), value = t(trimmed,lang);
          const translated = value === trimmed ? entry.source : entry.source.replace(trimmed,value);
          if (translated !== current) node.nodeValue = translated;
          entry.last = translated; originals.set(node,entry);
        }
      }
      const routeName = nav.find(item => item[0] === state.route)?.[2];
      if (routeName) document.title = t(routeName,lang) + ' — Afterword';
    } finally { applying = false; }
  }
  window.AfterwordI18n = {
    t, apply:applyInterface,
    addMessages:messages=>{for(const [key,value] of Object.entries(messages||{}))if(typeof value==='string')spanish.set(key,value);applyInterface();},
    setLanguage:code=>{if(!LANGUAGES.some(language=>language.code===code))return false;state.lang=code;ensureFont(code);persist();window.AfterwordProfile?.setLanguage?.(code);render();applyInterface();return true;},
    interfaceLanguage,
  };

  function ensureFont(lang) {
    const entry = LANGUAGES.find(l => l.code === lang);
    if (!entry?.font || loadedFonts.has(lang)) return;
    loadedFonts.add(lang);
    document.documentElement.style.setProperty('--local-script-font', entry.font.family);
  }

  function readingNote() {
    if (backendUp === true) return state.lang === 'es'
      ? 'Los controles están en español. Los documentos originales no cambian; el dispositivo puede traducir resúmenes y cartas por separado.'
      : 'English and Spanish controls work offline. Original records stay unchanged; summaries and letters can be translated separately on your device.';
    return state.lang === 'es'
      ? 'El español funciona sin conexión para los controles de la aplicación. Los documentos, resúmenes y cartas conservan su idioma original. Conecta el dispositivo para traducir resúmenes y cartas.'
      : 'English and Spanish controls work offline. Documents, summaries and letters keep their original language. Connect your device to translate summaries and letters.';
  }

  function languageOptions() {
    return LANGUAGES.map(l => `<option value="${l.code}" ${state.lang === l.code ? 'selected' : ''} ${backendUp === false && !['en','es'].includes(l.code) ? 'disabled' : ''}>${l.native}</option>`).join('');
  }

  async function checkTranslationHealth() {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 3000);
    try { backendUp = (await fetch(API + '/health', {signal: controller.signal})).ok; }
    catch { backendUp = false; }
    finally { clearTimeout(timer); }
    for (const select of $$('#reading-language, .lang-toggle')) {
      select.disabled = false;
      for (const option of select.options) option.disabled = backendUp === false && !['en','es'].includes(option.value);
    }
    const note = $('#reading-language-note');
    if (note) { note.hidden = false; note.textContent = readingNote(); }
    return backendUp;
  }

  window.AfterwordLanguages = LANGUAGES;
  window.ensureFont = ensureFont;
  window.checkTranslationHealth = checkTranslationHealth;
  window.languageField = () => `<label class="field"><span>${t('Reading language')}</span><select id="reading-language" aria-describedby="reading-language-note">${languageOptions()}</select></label><p class="fine" id="reading-language-note">${readingNote()}</p>`;

  // A compact toggle for the finding and letter views, sharing state.lang with
  // the preferences dialog. Applies immediately on change — no separate save.
  window.compactLanguageToggle = () => `<label class="compact-field lang-toggle-field"><span>${t('Language')}</span><select class="lang-toggle" aria-label="${t('Reading language')}">${languageOptions()}</select></label>`;
  document.addEventListener('change', e => {
    if (!e.target.matches('.lang-toggle')) return;
    window.AfterwordI18n.setLanguage(e.target.value);
  });

  // --- Translated blocks (finding summaries, task instructions; phase 4) ---
  // Only ever sends the plain-language text already on the page — never a
  // raw source document. Cached in memory so re-rendering the same content
  // in the same language never re-fetches.
  const translationCache = new Map();
  const cacheKey = (lang, kind, text) => `${lang}|${kind}|${text}`;

  async function requestTranslation(text, kind) {
    try {
      const r = await fetch(API + '/translate', {
        method: 'POST', headers: {'content-type': 'application/json'},
        body: JSON.stringify({text, target_lang: state.lang, kind}),
      });
      if (!r.ok) throw new Error('http ' + r.status);
      return {status: 'ok', ...(await r.json())};
    } catch {
      return {status: 'error'};
    }
  }

  function translatedBlockMarkup(blockId, result) {
    const langName = LANGUAGES.find(l => l.code === state.lang)?.native || '';
    if (result.status === 'loading') return `<div class="translated-block loading" id="${blockId}"><p class="translated-label">${icon('spark')}Translating on this device…</p></div>`;
    if (result.status === 'error') {
      // Matches the preferences dialog's specific "needs the Afterword
      // device" wording when that's the actual cause, instead of a generic
      // message that doesn't tell the family whether trying again might help.
      const message = backendUp === false
        ? "The Afterword device isn't reachable right now. The English above is complete."
        : "Couldn't translate right now. The English above is complete.";
      return `<div class="translated-block error" id="${blockId}"><p class="translated-label">${message}</p></div>`;
    }
    const flagTitle = 'The back-translation (translating this back into English) differed enough from the original that this translation might not be fully accurate. The English above is always what is correct and what gets sent.';
    const flag = (result.low_confidence || !result.protected_tokens_ok) ? ` <span class="pill amber" title="${flagTitle}">Machine translation — please check</span>` : '';
    const body = escapeHTML(result.text).split(/\n{2,}/).map(p => `<p>${p.replace(/\n/g, '<br>')}</p>`).join('');
    return `<div class="translated-block" id="${blockId}" lang="${result.lang}" data-no-translate><p class="translated-label">${state.lang === 'es' ? 'Traducido en este dispositivo' : 'Translated on this device'} (${langName})${flag}</p>${body}</div>`;
  }

  // blockId -> the exact source text last successfully translated there.
  // Lets a letter's edited body be told apart from a genuinely fresh block
  // (findings/tasks never change their own text, so this only matters for
  // letters — see letterTranslationState below).
  const lastOkText = {};

  // blockId must be a stable, unique id for this content (e.g. one per
  // finding or task) so a resolved fetch can patch the right element in
  // place — this may be behind an open <dialog>, which a full render()
  // never touches, so a targeted DOM patch is used instead of re-rendering.
  window.translatedBlock = (text, kind, blockId) => {
    if (state.lang === 'en') return '';
    const key = cacheKey(state.lang, kind, text);
    let cached = translationCache.get(key);
    if (!cached) {
      cached = {status: 'loading'};
      translationCache.set(key, cached);
      requestTranslation(text, kind).then(result => {
        translationCache.set(key, result);
        if (result.status === 'ok') lastOkText[blockId] = text;
        const el = document.getElementById(blockId);
        if (el) el.outerHTML = translatedBlockMarkup(blockId, result);
        // No-op outside the letters page (its checkbox/stale-note don't exist
        // there) — this is what re-enables "send this version" once a fresh
        // fetch actually resolves, whether from editing, Update, or a plain
        // render finding the cache empty.
        window.refreshLetterControls?.(blockId, text);
      });
    } else if (cached.status === 'ok') {
      lastOkText[blockId] = text; // covers the cache-hit-at-render path too
    }
    return translatedBlockMarkup(blockId, cached);
  };

  // Raw translated string for a resolved cache entry (e.g. for a text
  // export), as opposed to translatedBlock's rendered HTML card. Returns ''
  // if nothing resolved yet — callers check letterTranslationState first.
  window.translatedText = (text, kind) => {
    const cached = translationCache.get(cacheKey(state.lang, kind, text));
    return cached?.status === 'ok' ? cached.text : '';
  };

  // A lighter-weight sibling to translatedBlock for a single line of chrome
  // that already sits inside a labelled card (the letter subject, next to
  // the body's own "Translated on this device" label) — no loading/error
  // card of its own, it just shows the English text until a translation
  // resolves, then swaps in place. Shares translatedBlock's cache, so if the
  // subject happens to match some other already-translated instruction the
  // result is instant. Gap-resolution note: earlier this was left English on
  // both sides because splitting one combined subject+body translation back
  // into two fields proved fragile — this sidesteps that entirely by never
  // combining them, two small independent requests instead of one fragile one.
  window.translatedInline = (text, kind, blockId) => {
    if (state.lang === 'en') return escapeHTML(text);
    const key = cacheKey(state.lang, kind, text);
    let cached = translationCache.get(key);
    if (!cached) {
      cached = {status: 'loading'};
      translationCache.set(key, cached);
      requestTranslation(text, kind).then(result => {
        translationCache.set(key, result);
        const el = document.getElementById(blockId);
        if (el && result.status === 'ok') el.textContent = result.text;
      });
    }
    return cached.status === 'ok' ? escapeHTML(cached.text) : escapeHTML(text);
  };

  // --- Bilingual letters (phase 5) ---------------------------------------
  // The recipient and signature stay exactly as authored in both columns —
  // only the body (via translatedBlock) and, for reading only, the subject
  // (via translatedInline above) are translated. Whichever version gets
  // sent, the subject line is always English: it's short administrative
  // text the provider needs verbatim, and translating it was never about
  // what gets sent, only about what the family can read to follow along.

  // Reports whether the cached translation for `text` is still usable to
  // send: resolved, not flagged low-confidence, and not stale from an edit
  // made since it was translated.
  window.letterTranslationState = (text, blockId) => {
    if (state.lang === 'en') return {ready: false};
    const cached = translationCache.get(cacheKey(state.lang, 'letter', text));
    const ok = cached?.status === 'ok';
    const stale = !!lastOkText[blockId] && lastOkText[blockId] !== text;
    return {ready: true, ok, stale,
            lowConfidence: ok && (!!cached.low_confidence || cached.protected_tokens_ok === false)};
  };

  // Applies letterTranslationState's verdict for `blockId` to the DOM: dims
  // the block, shows/hides the "out of date" note, and enables/disables
  // "send this version instead" — the one gate a doubtful translation can
  // never get past. Called both reactively (typing) and after a fetch
  // resolves (translatedBlock's .then(), the explicit Update action).
  //
  // translatedBlock calls this after ANY block resolves, not just a letter's
  // — a finding or task instruction finishing its translation in the
  // background while the user has since moved to (or switched templates on)
  // the letters page used to reach this function too. #send-translated-checkbox
  // and #stale-note-* are singletons scoped to whichever letter is currently
  // on screen, so acting on them for an unrelated blockId would silently
  // apply a stranger's translation state to the visible letter — flip the
  // checkbox, or its disabled state, based on content the family isn't even
  // looking at. This guard is the fix for that: only the block that actually
  // belongs to the open letter may touch them. (Best working theory for
  // phase 5's one unreproduced "stale note showing during a first-ever
  // translation" screenshot — that anomaly was never pinned down for
  // certain, but this is a real, independently confirmed way for these
  // singletons to end up reflecting the wrong letter's state.)
  window.refreshLetterControls = (blockId, text) => {
    if (blockId !== 'translated-letter-' + letterType) return;
    const s = window.letterTranslationState(text, blockId);
    $(`#${blockId}`)?.classList.toggle('dimmed', s.stale);
    const note = $('#stale-note-' + blockId.replace('translated-letter-', ''));
    if (note) note.hidden = !s.stale;
    const checkbox = $('#send-translated-checkbox');
    if (checkbox) {
      checkbox.disabled = !s.ok || s.stale || s.lowConfidence;
      if (checkbox.disabled && checkbox.checked) { checkbox.checked = false; sendTranslated = false; }
    }
  };

  // Called on every keystroke in the letter body (see pages.js's #letter-form
  // input handler) — never fires a translation itself, only reflects whether
  // the one already on screen still matches what's being edited. Retranslating
  // happens on save or the explicit "Update" action below.
  window.markLetterTranslationStale = text => {
    if (state.lang === 'en') return;
    window.refreshLetterControls('translated-letter-' + letterType, text);
  };

  Object.assign(window.actions, {
    'update-translation': () => {
      if (state.lang === 'en') return;
      const d = captureLetter(), blockId = 'translated-letter-' + letterType;
      const el = $(`#${blockId}`);
      if (el) el.outerHTML = window.translatedBlock(d.body, 'letter', blockId);
      const note = $('#stale-note-' + letterType);
      if (note) note.hidden = true; // the block's own loading state covers the wait
    },
    'open-gmail': () => modal('External sending is disabled', '<p>This HP-hosted demonstration keeps letters inside your private workspace. Export or print a reviewed draft if you choose to send it yourself.</p>', button('Close', 'close-modal', true)),
  });

  // --- Whole-page translation (phase 8) --------------------------------------
  // Every other English string on screen is swapped for its entry in the
  // static dictionary (dist/ui-strings.js, generated and reviewed by
  // backend/dev/gen_ui_strings.py). No network call, so it keeps working when
  // the backend is down; a string with no entry simply stays English.
  // English on purpose, and marked lang="en" so a screen reader switches
  // voice for them while the rest of the page reads in the chosen language.
  const KEEP_ENGLISH = [
    '.record-paper', // source documents are evidence: always verbatim
    '.memory-reading', '.memory-quote', '.quiet-archive-intro blockquote', // the family's own words
    '.letter-read', '.letter-salutation', '.letter-date', // the English letter that gets sent
    '.finding-lead', '.evidence-fact p', // translated just below, with a confidence flag
    '.user-question', // the family's own typed question, echoed back
  ];
  // Task instructions sit right above their own flagged translation. Only
  // added where :has() is supported: one unknown selector makes closest()
  // throw for the whole list, which would stop translation everywhere.
  if (window.CSS?.supports?.('selector(:has(*))')) KEEP_ENGLISH.push('.subtle-box:has(+ .translated-block)');
  const UI_SKIP_SELECTOR = [...KEEP_ENGLISH,
    '.translated-block > :not(.translated-label)', '[id$="-subject"]', // already translations
    '.lang-toggle', '#reading-language', // each language name stays in its own language
    '.doc-title small', '.staged-row strong', // file names
    '.brand', '.avatar', '.demo-label', '.letter-monogram', '.footnote > span:first-child',
    'kbd', 'code', 'script', 'style', 'textarea',
  ].join(',');
  const MARK_ENGLISH_SELECTOR = [...KEEP_ENGLISH, '#letter-form input', '#letter-form textarea'].join(',');
  const UI_ATTRS = ['placeholder', 'aria-label', 'title'];
  const hasLetter = s => /\p{L}/u.test(s);
  // Dictionary keys: runs of spaces collapsed, line breaks kept as \n.
  const normalize = s => s.replace(/[ \t\r\f\v]+/g, ' ').replace(/ ?\n ?/g, '\n').trim();
  const INLINE_TAGS = new Set(['BR', 'B', 'STRONG', 'EM', 'I']);
  const doneText = new WeakSet();
  const doneUnits = new WeakSet();
  const doneAttrs = new WeakMap();
  const uiMisses = new Set();
  window.uiTranslationMisses = () => [...uiMisses];

  // A sentence broken up only by <br> or bold/italic ("Progress can
  // be<br>one small step.", "<strong>2</strong> of 7 actions complete") is
  // translated as one unit: piece by piece the grammar falls apart, worst of
  // all in Hindi's word order. Returns its text with <br> as \n, or null if
  // the element holds anything richer.
  function inlineUnitText(el) {
    if (!el || doneUnits.has(el)) return null;
    let mixed = false;
    for (const child of el.childNodes) {
      if (child.nodeType === Node.TEXT_NODE) continue;
      if (child.nodeType !== Node.ELEMENT_NODE || !INLINE_TAGS.has(child.tagName) || child.children.length) return null;
      mixed = true;
    }
    return mixed ? [...el.childNodes].map(n => (n.nodeName === 'BR' ? '\n' : n.textContent)).join('') : null;
  }

  function visitText(node, visit) {
    if (doneText.has(node)) return;
    const parent = node.parentElement;
    if (!parent || parent.closest(UI_SKIP_SELECTOR)) return;
    const unit = INLINE_TAGS.has(parent.tagName) ? parent.parentElement : parent;
    const unitText = inlineUnitText(unit);
    if (unitText !== null) {
      const key = normalize(unitText);
      if (!hasLetter(key)) return;
      return visit(key, translated => {
        // Bold is dropped (the translation has no markup to put it back on);
        // line breaks survive when the model kept them.
        doneUnits.add(unit);
        unit.replaceChildren(...translated.split('\n').flatMap((line, i) => (i ? [document.createElement('br'), line] : [line])));
        for (const child of unit.childNodes) if (child.nodeType === Node.TEXT_NODE) doneText.add(child);
      });
    }
    const raw = node.nodeValue.trim();
    const key = normalize(raw);
    if (!key || !hasLetter(key)) return;
    visit(key, translated => {
      // An <option> with no value attribute submits its label; pin the
      // English there so filters that compare against it keep matching.
      if (parent.tagName === 'OPTION' && !parent.hasAttribute('value')) parent.value = raw;
      node.nodeValue = node.nodeValue.replace(raw, () => translated);
      doneText.add(node);
    });
  }

  // Shared by the runtime translator and the dev crawler below, so the two
  // can never disagree about what counts as translatable.
  function forEachUiString(root, visit) {
    if (root.nodeType === Node.TEXT_NODE) return visitText(root, visit);
    if (root.nodeType !== Node.ELEMENT_NODE || root.closest(UI_SKIP_SELECTOR)) return;
    // Collected up front: translating an inline unit replaces its text nodes,
    // and a TreeWalker stops dead when its current node leaves the document.
    const nodes = [];
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
    for (let node = walker.nextNode(); node; node = walker.nextNode()) nodes.push(node);
    for (const node of nodes) visitText(node, visit);
    for (const el of [root, ...root.querySelectorAll('[placeholder],[aria-label],[title]')]) {
      if (el.closest(UI_SKIP_SELECTOR)) continue;
      const done = doneAttrs.get(el) || new Set();
      for (const attr of UI_ATTRS) {
        const value = normalize(el.getAttribute(attr) || '');
        if (!value || !hasLetter(value) || done.has(attr)) continue;
        visit(value, translated => { el.setAttribute(attr, translated); done.add(attr); doneAttrs.set(el, done); });
      }
    }
  }

  // Text that is already a translation (a UI_LABELS nav label, a node an
  // earlier pass translated) isn't a miss.
  const knownTranslations = new WeakMap();
  function isTranslation(dict, text) {
    let values = knownTranslations.get(dict);
    if (!values) knownTranslations.set(dict, values = new Set([...Object.values(dict), ...Object.values(UI_LABELS[state.lang] || {})]));
    return values.has(text);
  }

  function translateUi(root) {
    if (state.lang === 'en' || window.AFTERWORD_I18N_CRAWL) return;
    const dict = window.AFTERWORD_UI_STRINGS?.[state.lang];
    if (!dict) return;
    forEachUiString(root, (text, apply) => {
      const translated = AfterwordUiTranslate.lookup(dict, text);
      if (translated) apply(translated);
      else if (!isTranslation(dict, text)) uiMisses.add(text);
    });
    if (root.nodeType === Node.ELEMENT_NODE) {
      for (const el of [root, ...root.querySelectorAll(MARK_ENGLISH_SELECTOR)]) {
        if (el.matches(MARK_ENGLISH_SELECTOR)) el.lang = 'en';
      }
    }
  }

  // The whole page now reads in the chosen language, so <html lang> follows
  // it (phase 3 kept it English while translations were islands on an
  // English page); what stays English is marked lang="en" in translateUi.
  function syncPageLanguage() {
    const translating = state.lang !== 'en' && !window.AFTERWORD_I18N_CRAWL && !!window.AFTERWORD_UI_STRINGS?.[state.lang];
    document.documentElement.lang = translating ? state.lang : 'en';
    document.documentElement.dataset.readingLang = state.lang;
    if (!translating) return;
    const [name, ...rest] = document.title.split(' — ');
    const translated = AfterwordUiTranslate.lookup(window.AFTERWORD_UI_STRINGS[state.lang], name);
    if (translated) document.title = [translated, ...rest].join(' — ');
  }

  // Dev-only: backend/dev/crawl_ui_strings.py calls this on every page and
  // dialog to build the dictionary's source list.
  window.collectUiStrings = () => {
    const found = new Set();
    for (const id of ['app', 'detail-dialog', 'toast']) {
      const root = document.getElementById(id);
      if (root) forEachUiString(root, text => found.add(text));
    }
    return [...found];
  };

  // render(), modal(), toasts and the targeted DOM patches all insert nodes,
  // so one observer catches every path. It only watches childList: the
  // translator's own edits (text values, attributes) never re-trigger it.
  new MutationObserver(records => {
    syncPageLanguage();
    for (const record of records) for (const node of record.addedNodes) translateUi(node);
  }).observe(document.body, {childList: true, subtree: true});
  syncPageLanguage();

  const previousAfterRender = afterRender;
  afterRender = () => { previousAfterRender(); applyInterface(); };
  // Dialogs and asynchronous status messages can update outside render().
  // Localize their labels in place, preserving input values and keyboard focus.
  if (typeof MutationObserver !== 'undefined') {
    let scheduled = false;
    const observer = new MutationObserver(() => {
      if (scheduled) return;
      scheduled = true;
      Promise.resolve().then(() => { scheduled = false; applyInterface(); });
    });
    observer.observe(document.body,{childList:true,subtree:true,characterData:true});
  }
  ensureFont(state.lang);
  checkTranslationHealth();
  // i18n.js loads last, after workspace.js's own trailing render() already
  // drew the first real page — before window.compactLanguageToggle and
  // window.translatedBlock existed. Re-render once so a page loaded
  // directly to a hash route (e.g. #evidence) shows them on first paint,
  // not only after some later action re-renders. Mirrors workspace.js's
  // own trailing render() call for the same reason.
  render();
})();
