# Instalación

Son seis pasos y se hacen una sola vez. Calculá una hora la primera vez, la mayor parte esperando
pantallas de Notion y de Buffer.

**Nada de lo que hagas acá publica nada.** El programa arranca en modo seco y hay que pedirle
explícitamente que actúe. Podés llegar hasta el paso 5 sin ningún riesgo.

> **Sobre las credenciales.** Vas a crear tres archivos de texto con claves adentro. Van en tu
> carpeta de usuario, **fuera de cualquier carpeta que subas a algún lado**. El archivo de
> configuración nunca guarda una clave: guarda la *ruta* al archivo que la tiene. Por eso podés
> compartir tu configuración sin exponer nada.

---

## Paso 0 — Python

Necesitás Python 3.9 o más nuevo. Probá en una terminal:

```bash
python --version
```

Si dice `3.9` o más, listo. Si no lo tenés, bajalo de [python.org](https://www.python.org/downloads/)
y en Windows **marcá la casilla "Add Python to PATH"** durante la instalación.

No hay que instalar nada más. El programa usa solo lo que Python trae de fábrica, y eso es a
propósito: una herramienta que corre sola todos los días no debería depender de librerías que se
actualizan y se rompen.

---

## Paso 1 — La clave de Buffer

1. Entrá a [publish.buffer.com/settings/api](https://publish.buffer.com/settings/api) y generá
   una clave (*access token*).
2. Guardala en un archivo de texto plano, sin comillas y sin espacios de más:

   - Windows: `C:\Users\TU_USUARIO\.buffer\api_key`
   - Mac o Linux: `~/.buffer/api_key`

3. Comprobá que sirve y, de paso, sacá los identificadores que vas a necesitar:

```bash
python ids_buffer.py
```

Te va a imprimir el id de tu organización y el de cada canal conectado, ya con el formato que va
en la configuración. Copialos a un lado; los usás en el paso 4.

> **Si manejás más de una cuenta de Buffer** (la tuya y la de tu empresa, por ejemplo), cada una
> necesita su propia clave, en su propio archivo. Una clave no ve las cuentas de la otra, y eso es
> bueno: es lo que hace imposible que una pieza salga por los canales equivocados.

---

## Paso 2 — La clave de Notion

Notion no da una clave general: se crea una "integración" y se le da acceso a lo que vos elijas.

1. Entrá a [notion.so/my-integrations](https://www.notion.so/my-integrations) y creá una
   **integración interna**. Ponele el nombre que quieras.
2. Copiá el *Internal Integration Secret* (empieza con `ntn_` o `secret_`).
3. Guardalo en:

   - Windows: `C:\Users\TU_USUARIO\.notion\api_key`
   - Mac o Linux: `~/.notion/api_key`

4. **Dale acceso a tu base.** Este paso se olvida siempre y produce un error confuso. Abrí en
   Notion la base donde viven tus piezas, tocá el menú `···` de arriba a la derecha, entrá a
   **Conexiones** y agregá la integración que acabás de crear.

---

## Paso 3 — La base de Notion

Si todavía no la tenés armada, seguí **[NOTION.md](NOTION.md)**: dice exactamente qué propiedades
crear y por qué existe cada una. Son doce, y cinco ya las tenés si venís llevando un calendario.

Cuando esté lista, copiá su dirección del navegador (con la base abierta) y corré:

```bash
python ids_notion.py "PEGA_ACA_LA_URL"
```

Te devuelve el identificador que va en la configuración, y además te lista las propiedades que
encontró y te avisa cuáles faltarían. **El identificador que necesitás no es el que se ve en la
dirección**, por eso hace falta este paso.

---

## Paso 4 — La configuración

Copiá `sync_config.ejemplo.json` a un archivo nuevo llamado `sync_config.json`, en la misma
carpeta, y completá con lo tuyo. El archivo está comentado línea por línea; lo mínimo que hay que
tocar es:

| Qué | De dónde sale |
|---|---|
| `zona_horaria` | Tu huso. Argentina `-03:00`, España `+01:00`, México centro `-06:00`. |
| `notion.data_source` | Del paso 3. |
| `notion.propiedades` | Los nombres tal como los escribiste en tu base. |
| `espacios` | El nombre de tu marca, y los ids del paso 1. |
| `slots` | Los días y horas en que publicás en cada canal. |

**El nombre del espacio tiene que ser idéntico al valor que uses en la propiedad de marca en
Notion.** Si en Notion escribís `Mi Estudio`, en la configuración también. Una fila con un valor
que no figure en la configuración no se procesa: se reporta y se deja quieta, que es lo correcto
—adivinar de quién es una pieza es exactamente lo que no queremos.

Si no vas a publicar imágenes todavía, **borrá el bloque `almacenamiento` entero**. El sistema
funciona igual. Podés agregarlo después.

---

## Paso 5 — La primera corrida, en seco

```bash
python sync_notion_buffer.py
```

Esto **lee todo y no escribe nada**. Te va a decir qué haría: qué programaría, qué actualizaría,
qué está esperando lugar, y cuánto cupo libre queda por canal.

Leelo con calma. Es el momento de descubrir que una propiedad está mal escrita en la
configuración, y no cuando ya hay diez posts programados.

Cuando quieras confirmar lo que ves con una fuente independiente:

```bash
python estado_buffer.py
```

Eso mira **solo Buffer** y cuenta lo que hay de verdad. Sirve para no creerle a un programa
verificándolo con él mismo.

### Y recién ahí, de verdad

Aprobá **una sola pieza** en Notion (estado `Aprobado`) y corré:

```bash
python sync_notion_buffer.py --apply
```

Andá a Buffer y mirá que esté, en el canal correcto y a la hora correcta. Después corré lo mismo
otra vez: **la segunda corrida no tiene que hacer nada**. Si dice `0 programadas, 0 actualizadas`,
el sistema está sano. Si duplicó algo, pará y revisá la configuración.

---

## Paso 6 — Que corra solo (opcional)

Hasta acá el sistema anda, pero lo tenés que llamar vos. Para que corra solo, cualquier
programador de tareas sirve: el Programador de tareas de Windows, `cron` en Mac o Linux, o lo que
ya uses.

Poné la corrida **antes del primer horario de publicación del día**. Si tu primer slot es a las
09:10, que corra a las 07:40. Así hay margen si algo falla.

El programa está pensado para correr sin nadie mirando:

- Deja un registro de cada corrida en la ruta que digas en `log`.
- Devuelve **0** si salió todo bien, **1** si corrió pero hay algo que necesita una persona, y
  **2** si un espacio no pudo correr. Es lo que hace que el programador te muestre la corrida en
  rojo en vez de en verde con los errores escondidos adentro.
- Toda llamada de red corta a los 30 segundos, así que no se queda colgado para siempre.

> **Que corra solo no significa que publique solo.** Lo que la corrida diaria hace es mover a
> Buffer lo que vos ya aprobaste. Si no aprobaste nada, no hace nada. El punto de control sigue
> siendo tuyo, todos los días.

---

## Cuando algo no funciona

| Lo que ves | Casi siempre es |
|---|---|
| `no se encontro la configuracion` | Todavía no copiaste `sync_config.ejemplo.json` a `sync_config.json` (paso 4). El repo no trae el archivo real a propósito. |
| `falta la credencial de ...` | El archivo no está donde dice la configuración. Fijate en mayúsculas y en que no tenga extensión `.txt` escondida. |
| Notion responde **404** | La base no está compartida con tu integración (paso 2.4). |
| Notion responde **401** | El token está mal copiado o se regeneró. |
| Buffer responde **403** | La clave es de otra cuenta, o venció. Generá una nueva. |
| `no se encontro la seccion '### Slots'` | Estás en modo `documento` y el archivo no tiene esa tabla. Pasá a modo `inline`. |
| Una fila no aparece nunca | Su marca o su canal no coinciden **exactamente** con la configuración. Revisá mayúsculas y acentos. |
| Dice `esperando cupo` | No es un error. Tu plan admite 10 programados por canal y ya están llenos. Entra sola cuando se libere lugar. |

Si tocaste el código, antes de confiar en él:

```bash
python probar_config.py
python probar_placas.py
python probar_sync.py
```

Son 88 comprobaciones con la instalación completa. Antes de tener las credenciales corren 82: las
seis restantes lanzan el programa de verdad y se saltean solas diciéndote por qué. Ninguna publica
nada ni toca tus redes.
