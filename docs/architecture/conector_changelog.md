# Changelog del contrato del conector MCP

`CONECTOR_VERSION` (en `src/conector/version.py`) versiona el CONTRATO que ve Claude: qué herramientas hay, con qué parámetros y
con qué anotaciones. Sube cuando ese contrato cambia, no con cada despliegue. `HUELLAS` guarda la huella de cada versión publicada y
`tests/unit/test_conector_servidor.py::test_el_contrato_no_cambia_sin_subir_la_version` falla si las herramientas reales ya no la
cumplen. Una versión publicada no se edita: se agrega una fila nueva y se sube la constante. Afinar el texto de una descripción no es
otro contrato (la huella no lo incluye).

## 1.0.0 — 2026-11-10

Primera versión. Cinco herramientas, todas `readOnlyHint: true`, síncronas, sin texto íntegro de ningún fallo:

| Herramienta | Parámetros | Cupo |
|---|---|---|
| `buscar` | `consulta`, `despacho?`, `anno?`, `desde?`, `hasta?` | 1 unidad (15 por ventana de 4 h, 60 por semana) |
| `ficha` | `id` | 60 por día, entra al tope global |
| `verificar_cita` | `id`, `frase` | 100 por día |
| `ayuda` | (ninguno) | no gasta |
| `reportar` | `resumen`, `problema` | 20 por día |

Reglas de este contrato que un cambio futuro debe respetar o versionar:

- El servicio atiende de 6:00 a 23:00, hora de Costa Rica; fuera de ese horario toda herramienta contesta `error: fuera_de_horario`.
- Un error de la base o del servicio de embebido vuelve como `error` en palabras (`base_no_disponible`, `embebido_no_disponible`,
  `presupuesto_agotado`, `error_interno`), nunca como una lista vacía de resultados.
- Un límite agotado vuelve como `error: limite_alcanzado` con lo que se agotó y la hora exacta de renovación en hora de Costa Rica.
- La respuesta de `buscar` abre con `cobertura` y trae `cupo` con lo que le queda a la persona.
- No se emite refresh token; el token vence a los 90 días y la persona vuelve a poner su código de invitado.

## Correcciones sin cambio de contrato — 2026-11-10

La huella de las herramientas no cambia (`CONECTOR_VERSION` sigue en 1.0.0): cambian reglas y campos de la RESPUESTA, no los parámetros.

- **Un error de la entrada gasta la unidad.** Tampoco se devuelve una vez llamado el servicio de embebido. Solo se devuelve si el
  fallo es del servicio y no se llegó a ese llamado.
- La entrada de `buscar` se valida entera antes de embeber: consulta con términos útiles y de hasta 2.000 caracteres, fechas estrictas
  `AAAA-MM-DD`, hasta 3 frases entre comillas, `despacho` de hasta 200 caracteres. `ficha` y `verificar_cita`: `id` de hasta 100;
  `frase` de hasta 8.000 antes de normalizar. `reportar`: hasta 4.000 por campo.
- **Respuesta de `buscar` sin búsqueda por significado** (presupuesto agotado, servicio de embebido caído, falta la clave o el
  opt-out): ya no es un `error`. Responde por la vía literal con `via: literal`, `semantica_usada: false`,
  `semantica_no_disponible` (`presupuesto_agotado` o `embebido_no_disponible`) y un `aviso` que lo dice. Un error de la base sigue
  siendo un `error` en palabras.
- `ayuda` tiene un tope de 200 llamadas por día e invitado; `verificar_cita` cuenta en el tope global de 1.000 por día.
- Los fragmentos se arman con los 8 términos más largos de la consulta.
- Presupuesto de embebido: el techo es de la cuenta y es configurable. El libro de gasto del índice corta en el techo menos la
  reserva; el embebido de las consultas del conector corta en el techo menos la reserva de consultas.
- Intentos de código de invitado: el contador global (ahora 1.000 por hora) solo se toma si el de la IP pasó; la IP se guarda hasheada.
- Operación: el servicio se conecta con el rol de base `conector` (`scripts/conector_rol.sql`), de mínimo privilegio, y no con el
  rol administrador; usa un ejecutor de 16 hilos, `--concurrency=16` y un timeout de 12 s para las consultas de embebido. La URL
  pública debe ser `https://`.

## 1.1.0 — 2026-11-10

- **`reportar` deja de ser `readOnlyHint: true`**: escribe una fila en `conector_reporte`. Queda `readOnlyHint: false`,
  `destructiveHint: false`, `openWorldHint: false`. Las otras cuatro siguen de solo lectura. Los clientes de Claude usan la anotación
  para decidir si piden permiso, así que es un cambio de contrato: la huella cambia, se agregó `HUELLAS["1.1.0"]` y la de 1.0.0 no
  se tocó. Es un cambio menor (no quita ni cambia parámetros). Corrige la regla de 1.0.0 («todas `readOnlyHint`»), que declaraba una
  anotación falsa para esta herramienta.

## Correcciones de estructura — 2026-11-10 (sin otro cambio de contrato)

- **Fuera de horario o con la base caída, el OAuth no responde 500.** `Envoltura` (`asgi.py`) corta `/register`, `/authorize`,
  `/token` y `/revoke` fuera de 6:00-23:00 con **503** y cuerpo OAuth `{"error": "temporarily_unavailable", "error_description":
  MENSAJE_FUERA_DE_HORARIO}`. Dentro del horario, si la base no responde (`BDNoDisponible`, suelta o dentro de un grupo de
  excepciones), descarta el 500 de Starlette y contesta el mismo 503 con `bd.MENSAJE_NO_DISPONIBLE`. Cualquier otra falla sigue
  saliendo como 500, para no disfrazar un defecto propio. Las cuatro rutas llevan `Cache-Control: no-store` y `Retry-After: 600`. Los
  metadatos no tocan la base y siguen respondiendo. En el modo de desarrollo sin autenticación no se corta nada (no hay rutas OAuth).
  `/authorize` también contesta JSON y no HTML. `resource` sigue siendo obligatorio en `/authorize`.
- **Logging.** La función `configurar_logging` de `servidor` (la llama `main`) pone un handler a stdout con la raíz y `mcp` en WARNING, y
  `src.conector` en INFO, sin depender del nivel de uvicorn. Líneas nuevas: `[conector-oauth] codigo emitido cliente=<8
  caracteres> retorno=web|local` (pantalla, sin el código ni el invitado), `[conector] token rechazado: firma o vencimiento` y
  `[conector] token rechazado: revocado, vencido en la tabla o invitado inactivo jti=<8>`. También se registran `autorizado` y
  `revocada por /revoke`. El texto de las consultas no aparece en los logs: el test de producción comprueba que la frase de una
  consulta no se imprime.
- **Imagen reproducible.** `requirements-conector.txt` fija las 35 dependencias del cierre de `mcp` y `pg8000`. La imagen las
  instala con `pip install --no-deps` + `pip check`, sin resolver nada el día del build. El test de empaque compara el lock con lo
  que tiene instalado la suite (marcadores evaluados para Linux), en los dos sentidos. **La imagen pasa de Python 3.12 a 3.14**, la
  versión menor con que corre la suite, y otro test lo compara. No se usa `uv sync --frozen` porque el repo no es un proyecto `uv`
  y armar el `uv.lock` exige resolver contra PyPI.
  - `Dockerfile.conector` instala con `--require-hashes`: el build falla si un paquete no coincide con el hash del lock.
- El despliegue indica que la invitación lleva exactamente `${URL}/mcp` y que la URL con hash da 421.
- `--set-env-vars` usa el delimitador `^@^` en vez de la coma (`CONECTOR_HOSTS_EXTRA` es una lista con comas).
- Con retorno local (Claude Desktop), la pantalla avisa que hay que escribir el código en menos de 2 minutos. Con Claude web no se muestra.
- Tests: `tests/unit/test_conector_analisis_estructura.py` y los de empaque, comprobados mutando cada corrección y viendo fallar el test.

## 1.2.0 — 2026-11-11

Misma entrada que 1.1.0 (la huella no cambia); cambia la **salida** de `buscar`. Se sube la versión para que `registro` y
`reportar` distingan las respuestas anteriores y posteriores a la señal.

- Cada resultado con `via` `semantica` o `ambas` trae `distancia` (coseno `voyage-4`, 3 decimales). Los `literal` y `solo_literal`
  no la traen: ausencia no es cero.
- En la raíz: `distancia_corte` (la del último candidato semántico; `null` si no hubo) y `senal_semantica` con `estado`
  (`sin_vector_de_consulta`, `filtro_sin_vectores`, `grupo_chico` con menos de 50 fallos con vector en el filtro, o `sin_evaluar`)
  y `comparados` (fallos con vector del filtro).
- Con `grupo_chico` y resultados por significado, el `aviso` dice que son los más parecidos de un grupo pequeño. Si hay fallos que
  contienen todos los términos (o la frase), lo agrega en vez de contradecirlo.
- Orden de los avisos: degradación, frase truncada, pertinencia, vacío.
- La consulta semántica selecciona la distancia (el vector pasa a ser el primer parámetro) y desempata por id. Se agrega un
  `count(*)` del filtro, sin distancias, solo cuando hay vector.
- No hay etiqueta de «cercano»: ninguna señal de distancia resultó confiable para rotular un resultado así.
- Instrucciones al modelo y descripción de `buscar` actualizadas; la descripción ya no fija «2022-2025»: remite a la COBERTURA.

## 1.3.0 — 2026-11-11

Misma entrada que 1.2.0 (la huella no cambia); cambia la **salida** de `buscar`, `ficha` y `verificar_cita`. Ningún
rótulo afirma ya que algo sea criterio de la Sala.

- **`mayoria` desaparece de toda salida.** `seccion` toma uno de: `encabezado_del_fallo`, `resultando`, `considerando_sin_clasificar`,
  `antecedente`, `alegato`, `veredicto`, `por_tanto`, `posterior_a_dispositiva`, `voto_salvado`, `nota`, `estructura_no_confiable`
  (`fragmentos.SECCIONES`). Lo que en la 1.2.0 era `mayoria` sale, en general, `considerando_sin_clasificar`.
- **`antecedente`, `alegato` y `veredicto` solo se emiten en la familia de despachos que pasó la medición de acuerdo** (constante
  `secciones_fondo.EMISION`). Mientras una familia no pase la medición, su contenido de fondo cae a `considerando_sin_clasificar`.
  El clasificador está completo y probado; el banco de pruebas usa `EMISION_TOTAL`.
- **`verificar_cita`:** veredictos nuevos (`LITERAL_EN_CONSIDERANDO_SIN_CLASIFICAR`, `LITERAL_EN_VEREDICTO`, `LITERAL_EN_ALEGATO`,
  `LITERAL_EN_ANTECEDENTE`, `LITERAL_EN_ENCABEZADO`, `LITERAL_DESPUES_DE_DISPOSITIVA`, `LITERAL_ESTRUCTURA_NO_CONFIABLE`);
  `LITERAL_EN_MAYORIA` ya no existe. Campos nuevos: `citable_como_criterio` (`no` o `indeterminado`; **nunca `si`**),
  `tambien_en_parte_no_criterio` y `estructura`. Prioridad: `por_tanto` > `veredicto` > `considerando_sin_clasificar` >
  `estructura_no_confiable` > `encabezado_del_fallo` > `posterior_a_dispositiva` > `antecedente` > `alegato` > `resultando` > `nota` >
  `voto_salvado`. Lee el `despacho` del fallo.
- **Guarda de estructura:** con dos o más encabezados de dispositiva (forma de `extracto._encabezados`) u otra resolución
  pegada después de la primera, `por_tanto` es `null` en `buscar` y `ficha`, con `dispositiva_localizada: false` y `por_tanto_aviso`
  («el fallo tiene N encabezados de dispositiva…»). En la muestra de desarrollo marcó 3 de 72 fallos.
- **Votos salvados por forma:** «Voto parcialmente/particular salvado de…», «VOTO PARCIALMENTE SALVADO…», «Voto Salvado
  de…», plurales, y «La magistrada X salva el voto» sin punto después de la dispositiva. La mención en minúscula no es marca. En la
  muestra de 72 fallos, los que tenían más de 3.000 caracteres sin marca después de las firmas pasan de 6 a 0. `ficha.disidencias` y
  `hay_disidencia` los ven.
- **Campos nuevos en `buscar` (por resultado):** `dispositiva_localizada`, `por_tanto_aviso`, `tipo_resolucion` (`admisibilidad` |
  `sin_determinar`); cada fragmento trae `abre_con_veredicto`. En la vía semántica, si hay veredicto emitido, el primer fragmento
  arranca en el primer veredicto del fallo y sigue hasta 600 caracteres como `considerando_sin_clasificar`.
- **`ficha`:** suma `dispositiva_localizada`, `por_tanto_aviso`, `tipo_resolucion` y `estructura`.
- Instrucciones al modelo, `COMO_CITAR` y descripciones de `buscar`, `ficha` y `verificar_cita` actualizadas: no presentar como
  criterio una frase `no` o `indeterminado` sin leer el fallo; `ficha` puede no traer dispositiva.
- Módulos nuevos: `src/conector/secciones_fondo.py` y `secciones_cortador.py`.

**Criterios de implementación** (todos fallan hacia lo neutro):

1. **Emisión antes de medir.** Un rótulo cuya familia no pasó la medición no se emite; `EMISION` arranca vacía y se llena según
   los resultados.
2. **«Previa termina en número de párrafo».** Se implementa como «termina en un número de 1 a 4 cifras seguido de punto» (o letra
   mayúscula y punto, o barra), sin distinguir un año; en la muestra eso excluye un veredicto real cuya oración previa termina en una fecha.
3. **Marcadores de voz de la Sala (condición 3 de `alegato`).** Primera letra en cualquier caja («Esta Sala…» al abrir oración
   también veta); «Analizad» solo con mayúscula, como en la lista. En la muestra no cambia ninguna cifra.
4. **Subjuntivo e infinitivo.** Además de exigir indicativo en la forma, una oración con «declare», «acoja», «admita», «rechace»
   (o «declarar», «acoger», «admitir», «rechazar») no es veredicto. «declararse» sí se admite («debe declararse inadmisible»).
5. **«Se» + verbo con sujeto de la lista**: el sujeto se exige con artículo («el motivo», «la demanda»), no la palabra suelta.
6. **Sin «Considerando» localizable o sin dispositiva**: el fallo no tiene tramos y lo que no es resultando sale
   `considerando_sin_clasificar` (no `encabezado_del_fallo`). Un «considerando» que aparece después de la dispositiva no abre la zona.
7. **`tambien_en_parte_no_criterio`**: vale `true` si la frase aparece en `alegato`, `antecedente` o `resultando` además de en la
   sección que manda (aunque la que manda sea otra de esas tres): avisa de más, no de menos.
8. **`por_tanto` sin dispositiva hallada** (no por la guarda): sigue siendo `""` como en la 1.2.0, con `dispositiva_localizada: false`;
   `null` queda reservado a la guarda de estructura.

### 1.3.0 — decisión de emisión medida (2026-11-12, sin cambio de contrato)

Medición sobre una reserva de 60 fallos (489 oraciones, acuerdo entre jueces κ 0,94-0,95): `secciones_fondo.EMISION` enciende
`antecedente` en la Sala Constitucional y la Sala Segunda. `alegato` falló en la Sala Segunda (0,754) y en la familia de la Sala
Tercera (0,861), por títulos de motivo dentro del tramo; `veredicto` no llegó al mínimo de 35 oraciones ni con el lote de ampliación
(30). Ambos quedan apagados: lo que no se emite es `considerando_sin_clasificar`.

## 1.4.0 — 2026-11-12

La entrada es la misma que en la 1.3.0, así que la huella no cambia. Cambia la **salida** de `buscar`, `ficha` y `verificar_cita`
en los fallos que marca la guarda de estructura: 26.730 de 325.869 sentencias, el 8,2 %.

- En la 1.3.0, `por_tanto` salía en null en esos fallos. Ahora trae la dispositiva que elige `extracto.por_tanto`, con
  `dispositiva_localizada = true`.
- `por_tanto_aviso` va siempre en esos fallos. Dice: «el conector encontró N encabezados de dispositiva en el fallo (los demás
  suelen ser resoluciones transcritas o el título de un voto salvado); se muestra el que toma por el de este voto, que acertó
  en 40 de 40 fallos de una muestra al azar, pero puede ser el de otra resolución: abrí el enlace y verificalo en el fallo antes
  de citarlo».
- Medición: dos jueces a ciegas, con intervalo de Wilson de 0,912.
- Las secciones siguen como `estructura_no_confiable`, y `citable_como_criterio` sigue en `indeterminado`.
- `verificar_cita` da `dispositiva_localizada = true`, pero `antes_de_dispositiva` sigue en null.
- Las instrucciones al modelo y la descripción de `ficha` piden transmitir el aviso.

## 1.5.0 — 2026-11-12

- **Corte del «por tanto» al final de una oración.** `buscar` y `ficha` cortan el «por tanto» al final de una oración, terminado en
  «[…]», y agregan `por_tanto_recortado`. Antes se cortaba por palabra, y en una prueba en vivo el corte cayó a media oración de un
  voto salvado, de modo que el modelo atribuyó a una magistrada una condena en costas que en realidad la resolución le niega. Las
  instrucciones piden la `ficha` antes de afirmar algo de la parte recortada.
- **Registro de uso.** Sin cambio de parámetros: la huella es la misma.
  - **Aviso de privacidad v2** (`pantalla.AVISO_VERSION = 2`): dice que el texto de las búsquedas y de las frases verificadas, con
    sus filtros y los fallos pedidos, se guarda 90 días y solo lo ve quien administra Aiéntika. La versión que la persona tuvo
    delante viaja con el código de autorización (`oauth_codigo.aviso_version`) y `/token` la copia a `credencial.aviso_version`;
    `load_access_token` la lee en la misma consulta de siempre.
  - **`conector_consulta`** (tabla nueva): texto de `buscar` con `despacho`, `anno`, `desde` y `hasta`; id de `ficha`; frase e id
    de `verificar_cita`. Solo con `aviso_version >= 2` (`registro.AVISO_MINIMO_TEXTO`): las credenciales emitidas antes conservan la
    promesa anterior hasta que la persona reconecte. Se guarda con cualquier resultado de la llamada (ok, error o límite), junto a su
    fila de `conector_llamada`, y cada inserción borra lo anterior a 90 días. `ayuda` y `reportar` no dejan texto.
  - El texto de las consultas no sale en los logs: vive solo en la tabla; si el registro falla, el aviso lleva el tipo de error y
    nunca voltea la llamada.
  - Migración (con el rol dueño, antes del despliegue): `python scripts/conector_invitados.py esquema` crea la tabla y aplica
    `esquema_conector.MIGRACIONES` (`ADD COLUMN IF NOT EXISTS aviso_version` en `credencial` y `oauth_codigo`); después, volver a
    correr `scripts/conector_rol.sql` (SELECT, INSERT y DELETE sobre `conector_consulta`). El código anterior ignora lo nuevo.
  - Informe: `python scripts/conector_actividad.py` (por invitado) y `--consultas [--invitado ID] [--dias N]` (el texto).
- **Cupo de administrador**: los ids de `CONECTOR_ADMINISTRADORES` tienen 10 veces los topes por invitado (`limites.FACTOR_ADMINISTRADOR`: 150 búsquedas cada 4 h, 600 por semana, 600 fichas y 1.000 verificaciones por día). El tope global del servicio no cambia.
- **La fuente se declara bien.** Las instrucciones, la línea COBERTURA y `ayuda` dicen que Aiéntika busca en su propia base, con su fecha de
  actualización; cada fallo lleva su enlace oficial. Nada de lo que lee el modelo nombra otro sistema como origen de los datos.
- `catalogo` devuelve una ficha por fuente activa (publica, contiene, cantidad, período, `actualizado_al`, `mas_reciente`,
  `se_actualiza`, enlace oficial), `jurisprudencia_por_despacho` (cada Sala y tribunal con sus resoluciones, años, primera y más
  reciente), las tablas `tabla` y `tabla_jurisprudencia` para mostrar tal cual, y `en_incorporacion` (fuentes en incorporación).
- Las fechas por despacho salen de `cobertura.despachos`, solo de resoluciones cuya fecha cae en su propio año: unas 440 traen una
  fecha de metadato imposible (por ejemplo «1990-01-05» en un voto de 2023) y con `min(fecha)` el catálogo decía «desde 1990» de una
  base que empieza en 2022.
- Lo que no se pudo leer dice «NO DISPONIBLE ahora», nunca cero. Los trámites del MEIC pasan a `activa` en el registro de fuentes.

## 1.8.0 — 2026-11-14

Nueva herramienta `visitar_sitio` (sin parámetros, `readOnlyHint: true`, sin cupo): devuelve el enlace al sitio de Aiéntika con
`utm_source` según el cliente y apunta a la interfaz `ui://agentika/sitio.html` (`text/html;profile=mcp-app`, extensión MCP Apps, y
`openai/outputTemplate` de ChatGPT). Las instrucciones piden llamarla al terminar cada respuesta que usó el conector. Objetivo:
medir si Claude y ChatGPT gratuitos dibujan la tarjeta (que el modelo no reescribe) y cuántas personas llegan al sitio
(`utm_campaign=tarjeta_sitio`).

## 1.9.0 — 2026-11-14

Misma entrada. `buscar` agrega `fuente`, la línea lista para copiar «Fuente: base de Aiéntika (datos al <fecha>) · Conocé más en
<enlace con utm_source>», y `fuente_instruccion`. Con la instrucción sola, Claude seguía escribiendo la línea anterior: guarda
las instrucciones del conector de cuando se conectó, pero el resultado de cada herramienta lo lee en cada llamada.

## 1.10.0 — 2026-11-14

Misma entrada. La línea `fuente` de `buscar` trae el enlace en markdown. Claude copiaba el texto visible de las instrucciones
guardadas (sin enlace) y la URL larga quedaba afuera; con el markdown, el texto visible es el mismo y queda clickeable, con la
marca de origen para contar las visitas.

## 1.11.0 — 2026-11-15

La marca pasa a «Aiéntika». Misma entrada (misma huella que 1.8.0-1.10.0). Cambian los textos: el nombre del servidor es «Aiéntika»;
`fuente` dice «Fuente: base de Aiéntika (datos al <fecha>)»; las instrucciones aceptan «aientika» y también «agentika» (instalaciones
anteriores); la pantalla «Listo» enseña «aientika,» en Claude y «@aien» en ChatGPT. El aviso de privacidad nombra a Aiéntika como
quien administra: lo que se guarda no cambia, así que `AVISO_VERSION` sigue en 2.

## 1.12.0 — 2026-11-15

Misma entrada. Con credenciales del aviso v3 (`pantalla.AVISO_VERSION` = 3), el enlace de `fuente` lleva `&r=<referencia>`: invitado y
hora de la búsqueda cifrados con AES-GCM (`referencia_visita.py`). `/visita` la abre y anota la visita en `conector_llamada`
(`visita_sitio`); `scripts/conector_actividad.py --visitas` la une al texto de la búsqueda. Las credenciales v2 siguen sin referencia.

## 1.13.0 — 2026-11-18

Sitio propio en aientika.ai. Misma entrada. La raíz `https://aientika.ai/` sirve la página de Aiéntika (`sitio.py`, archivos en
`src/conector/sitio/`); no toca la base y responde también fuera de horario. `fuente` dice «Conocé más en
[aientika.ai](https://aientika.ai/?utm_source=…)» y la tarjeta de `visitar_sitio` lleva a aientika.ai. El aviso de autorización pasa
a v4 («el enlace a aientika.ai»); la referencia cifrada de la visita va solo con credenciales v4
(`referencia_visita.AVISO_MINIMO_VISITA` = 4): las v3 nombraban el dominio anterior y siguen funcionando sin referencia.

## 1.14.0 — 2026-11-18

Nueva base de datos gestionada. Misma entrada. **El horario pasa a 7:00-23:00**, hora de Costa Rica (`limites.HORA_APERTURA` = 7),
porque la base se enciende unos minutos antes de abrir y se apaga a las 23:00. Esto cambia la regla del 1.0.0 «de 6:00 a 23:00».
Todos los textos que dicen el horario usan la constante, y lo vigila
`test_todo_texto_del_horario_dice_la_hora_de_apertura_de_la_constante`. Con `REPLICA_DB_CA`, la conexión va con TLS que verifica la
CA de la base. Cuando una conexión falla en horario, el conector registra «[conector-bd] base no disponible en horario» y el
monitoreo avisa por correo.

**Corrección del 2026-11-19, misma versión.** Con la base gestionada, toda conexión dio `SSLCertVerificationError` con la CA
correcta: Python 3.14 verifica en modo estricto (`VERIFY_X509_STRICT`) y los certificados de la base no traen Authority Key
Identifier. `contexto_tls` quita solo ese modo; la cadena, la firma y la vigencia se siguen verificando. La prueba anterior miraba el
contexto sin apretón de manos y con un certificado «perfecto»; la nueva hace el apretón real con un certificado de la forma del de
la base y con una CA ajena como control negativo.

## 2.0.0 — 2026-11-19

Aiéntika descubrible. **Cambia la entrada: los nombres MCP.** `buscar` → `aientika_buscar_jurisprudencia_cr`, `ficha` → `aientika_ficha_de_fallo`,
`verificar_cita` → `aientika_verificar_cita_de_fallo`, `ayuda` → `aientika_ayuda`, `tramites_buscar` → `aientika_buscar_tramites_cr`,
`tramite` → `aientika_ficha_de_tramite`, `catalogo` → `aientika_catalogo_de_fuentes`, `visitar_sitio` → `aientika_visitar_sitio`,
`reportar` → `aientika_reportar_respuesta`. Mismos parámetros y anotaciones; sin alias. Los cupos y el registro siguen con el nombre
interno. El servidor se presenta como «Aiéntika: jurisprudencia y trámites de Costa Rica» y el sitio indica ese nombre al instalar.
Las descripciones de búsqueda abren con país y materias; las instrucciones piden consultar Aiéntika antes que la web en cualquier
materia, separar lo que no viene de Aiéntika y no mostrar las etiquetas de sección. `tramites_buscar` pesa las palabras por rareza
(IDF) y por cobertura de la consulta: una consulta sobre divorcio ya no trae registro sanitario de medicamentos.

## 2.1.0 — 2026-11-19

Cobertura honesta por Salas y tribunales. Misma entrada. La línea COBERTURA decía «búsqueda por significado en 2022, 2023, 2024, 2026
(Salas y tribunales)», pero los tribunales de 2022, 2024 y 2026 no tenían ni un vector: solo se encontraban por palabras. Ahora mide
lo embebible por año y despacho de todos los despachos y dice por separado qué años tienen búsqueda por significado en las Salas y
en los tribunales (`cobertura.por_grupo`).

## 2.1.1 — 2026-11-19

Sin vías procesales de memoria; `ficha` con el extracto de la dispositiva corregido. Misma entrada. Ante una pregunta de cobro,
Claude usó Aiéntika para el proceso monitorio y agregó «Otras vías (de mi conocimiento, no verificadas por Aiéntika)», con un
«proceso ejecutivo simple»; la instrucción lo invitaba («lo que venga de tu propio conocimiento, marcalo como no verificado»). Ahora
las instrucciones prohíben ofrecer de memoria vías procesales, tipos de proceso, plazos o requisitos: cada una se busca en la base o
se dice que no se encontró, sin describirla. La imagen lleva además la corrección del extracto de la parte dispositiva, que usa
`aientika_ficha_de_fallo`.

El servicio atiende las 24 horas (interruptor `SERVICIO_24_HORAS` en `limites.py`).
