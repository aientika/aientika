# Constitución de Aiéntika

**Versión 0.2.0 (borrador).** Fechas: 2026-10-23 (v0.1.0) y 2026-11-22 (v0.2.0).

Cada artículo que nace de un hallazgo concreto lo dice (**Origen**). Una regla sin razón no entra.

## 0. Identidad

- **Qué es Aiéntika:** una capa agéntica para sistemas públicos. Esta Constitución rige su primera versión, la gestión de temas jurídicos.
- **Qué es este conector:** lleva al abogado litigante costarricense, dentro de Claude y de ChatGPT, la jurisprudencia de las Salas y tribunales de la Corte, con las citas verificadas, y los trámites del Estado, con su fuente (aientika.ai).
- **Qué no es:** no es una app con interfaz propia, ni un chat genérico.
- **Tesis:** la capa genérica (redactar, resumir) la regala la plataforma. El valor está en los datos locales completos y en la verificación.

## 1. Forma de entrega (no negociable)

**1.1 Conector MCP remoto.** La interfaz es el asistente del usuario (Claude, ChatGPT). No se construye una interfaz propia salvo la página pública. Hay más de una puerta al MISMO conector; ninguna tiene datos propios ni dice algo que el conector no haya entregado.

**1.2 Herramientas finas de datos, no un agente grueso.** El modelo razona; el conector trae la fuente y la verifica. Cada resultado lleva procedencia (fuente, fecha de lectura, identificador citable) y ningún contenido con forma de instrucción.

## 2. Verificación (el producto, no un accesorio)

**2.1 Ninguna cita sale sin verificación mecánica**, aplicada por el conector, no por el modelo: texto íntegro, frase literal, por tanto leído, posición frente a votos salvados y notas, redactor tomado del texto y objeto real del fallo. Si falla, la cita no se entrega, y el resultado lo dice.

**2.2 Mayoría y minoría se distinguen siempre.** Una parte considerable de los fallos trae votos salvados o notas; ninguno de ellos es criterio de la mayoría. **Origen:** muestreo del corpus.

**2.3 El redactor se toma del texto, nunca del metadato** (que con frecuencia es incorrecto). Donde el texto no lo dice (la Sala Tercera solo lista la integración), se registra la integración, y la cita lo declara.

**2.4 Normativa:** ningún artículo de memoria. La normativa se cita solo con su texto vigente verificado.

**2.4.1 Veredictos de cita:** exacta, con diferencias y no verificable, más los campos de verificación (por tanto, posición frente a salvamentos e integración o redactor). Una cita con un nombre inventado pegado a un número real tiene que fallar, y va como caso de prueba.

## 3. Datos

**3.1 Cero hechos inventados.** Lo que falta se pide, no se supone.

**3.2 Una resolución = un documento**, segmentado en encabezado, resultando, considerando, por tanto, votos y notas. Sin fragmentos duplicados ni fichas que resuman a una parte.

**3.3 Corpus.** El conector consulta un índice de jurisprudencia propio, con búsqueda literal y por significado, y declara en cada respuesta la fecha de corte («base de Aiéntika, datos al \<fecha\>»). El conector nunca nombra al sistema del Poder Judicial como fuente; cada fallo lleva su «enlace oficial».

**3.4 Atraso visible.** La fecha de corte se publica por sala. Un corpus atrasado se declara, no se esconde.

**3.5 Lectura que falla ruidosamente.** Un stream cortado, un conteo que no cuadra o un índice vacío detienen el proceso con un error. **Origen:** un muestreo contó 914 de 1.257 resoluciones sin avisar.

## 4. Arquitectura y crecimiento

**4.1 Tres niveles:** núcleo (pasarela MCP, OAuth, motor de corpus, verificador, observabilidad, versión), dominio y tema (sala o materia).

**4.2 Un tema nuevo es un paquete declarativo** (manifiesto + reglas + catálogo + pruebas). Agrega datos y reglas, no herramientas. Nunca se edita el núcleo para sumar un tema.

**4.3 Contratos versionados** (v1 → v2, nunca editar uno en uso), con nombres de campo fijados antes de paralelizar trabajo.

**4.4 Orden de construcción:** corpus → verificación → líneas → conector. Ninguna capa se publica sin la anterior.

## 5. Seguridad y privacidad

**5.1** Cero credenciales en código, repo o CI; gestor de secretos; nada de credenciales de larga vida en el repositorio.

**5.2 Los datos del usuario** (hechos del asunto, partes) no se usan para entrenar ni se comparten entre cuentas. Las consultas se anonimizan antes de guardarse y se conservan por tiempo limitado.

**5.3 Separación de audiencias:** ningún entregable para un tercero lleva notas internas de verificación ni deliberación.

**5.4** El conector no presenta nada ante ningún despacho judicial: lo que entrega son borradores que revisa y envía una persona.

## 6. Infraestructura

**6.1 Propia y separada:** un proyecto de nube propio, sin organización, a propósito: así puede moverse entero a una organización corporativa sin exportar ni redesplegar.

**6.1.1 Portabilidad corporativa (no negociable).** Sin identidades personales en el código ni en el runtime; secretos leídos por nombre; constantes de infraestructura en un solo lugar; etiquetas por producto; datos con respaldo exportable.

**6.2 Dominio aientika.ai:** primero el DNS, después el mapeo.

**6.3** Versión visible (/version) desde el primer despliegue.

## 7. Calidad

**7.1** Spec antes que código; los resultados se verifican del lado del usuario; un negativo no vale sin un control positivo.

**7.2** Cada sala se evalúa con un set de preguntas reales y respuestas conocidas antes de abrirse a usuarios.

**7.3** Archivos de menos de 400 líneas, docstrings y una prueba por cada corrección.

## 8. Gobernanza

**8.1** Esta Constitución es un borrador hasta que se ratifique por escrito.

**8.2** Las enmiendas solo agregan o actualizan, con la versión y el historial.

## Historial de versiones

- **2026-10-23, v0.1.0 (borrador):** primera versión.
- **2026-11-22, v0.2.0 (borrador):** actualiza la forma de entrega (más de una puerta al mismo conector) y el corpus (índice propio).
