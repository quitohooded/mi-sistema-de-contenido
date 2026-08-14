# Mi sistema de contenido

**Un sistema de contenido con un solo punto de control.** Escribís y decidís en Notion. El sistema
se ocupa de todo lo demás. Nada se publica sin que vos lo apruebes, una vez, en un solo lugar.

**Para quién es:** para vos, si publicás en varias redes con cierta regularidad y ya estás
llevando tus ideas en Notion. Sirve igual con una marca o con varias cuentas separadas. No hace
falta saber programar para usarlo: hay que seguir una guía de instalación de seis pasos, una sola
vez, y después es Notion y nada más.

**Para quién no es:** si publicás una vez cada tanto y sin planificar, esto es más maquinaria de
la que necesitás.

Es el sistema que uso todos los días, entregado tal cual: el programa que está acá es el mismo
archivo que corre en mi operación, no una versión de muestra.

---

## Qué problema resuelve

Publicar en varias redes con cierta regularidad tiene un trabajo escondido que nadie cuenta:
copiar el mismo texto a tres lados, acordarse de a qué hora va cada uno, revisar si la cola se
vació, volver a cargar, corregir una pieza que ya estaba programada, cancelar otra. Ese trabajo no
es escribir. Es mudanza.

La tentación es automatizarlo entero y que una máquina publique sola. El problema de eso es obvio
apenas lo pensás dos segundos: lo que sale con tu nombre lo tenés que haber leído vos.

**Este sistema separa las dos cosas.** La máquina hace la mudanza. Vos hacés una sola cosa, y es
la única que importa: **decir que sí**.

## Cómo se siente usarlo

1. Escribís la pieza en Notion, como escribirías cualquier nota. Le ponés el canal y la marca.
2. Si lleva imagen, la arrastrás al campo `Placa`. Nada más.
3. Cuando estás conforme, cambiás el estado a **Aprobado**.
4. No hacés nada más.

De ahí en adelante el sistema la programa en Buffer en el próximo horario libre de ese canal, sube
la imagen a un lugar donde no se vaya a romper, y cuando la pieza efectivamente sale, vuelve a
Notion y la marca como publicada con la fecha real y el link.

Si te arrepentís antes de que salga, sacás el estado de `Aprobado` y el post programado desaparece.
Si corregís una palabra, la corrección viaja sola. Si le cambiás la fecha, se reprograma.

**Nunca abrís Buffer.** Ni para cargar, ni para corregir, ni para cancelar, ni para ver qué salió.

## Qué NO hace, a propósito

Esta lista es tan importante como la anterior. Un sistema que no dice dónde se planta termina
haciendo cosas que nadie le pidió.

- **No escribe por vos.** No genera texto, no sugiere, no reescribe.
- **No aprueba nada.** El estado `Aprobado` solo lo podés poner vos, a mano. Es el punto de
  control, y por diseño el programa no lo puede escribir ni por error.
- **No corta, no resume, no acorta.** Si una pieza se pasa del límite de la red, no se publica y
  te lo dice. Prefiere no publicar antes que publicar algo que vos no escribiste.
- **No adivina.** Si algo es ambiguo —una fila con una marca que no reconoce, un post en Buffer
  que no tiene su fila— lo reporta y lo deja quieto. Nunca borra por deducción.
- **No toca lo que ya se publicó.** Una pieza publicada es intocable, pase lo que pase después.

## Lo que necesitás para usarlo

- Una cuenta de **Notion** (sirve la gratuita).
- Una cuenta de **Buffer** (sirve la gratuita: hasta 3 canales y 10 posts programados por canal).
- **Python 3.9 o más nuevo**. No hay que instalar ninguna librería: el programa usa solo lo que
  Python trae de fábrica.
- Si querés publicar imágenes, un lugar público donde alojarlas. Está resuelto con
  **Cloudflare R2**, que en su plan gratuito alcanza y sobra. Si no vas a publicar imágenes,
  salteás esa parte entera y el sistema funciona igual.

Todo esto se hace una vez y no se vuelve a tocar. Está paso a paso en **[INSTALACION.md](INSTALACION.md)**.

## La base de Notion ya está armada

No hace falta que crees nada a mano. Hay una plantilla lista para duplicar, con las doce
propiedades que el programa espera —con sus nombres y sus tipos exactos, que es donde se pierde
todo el mundo—, las vistas de trabajo y una página que explica el sistema en diez líneas.

**[Duplicar la plantilla de Notion →](https://estebanaguilar.notion.site/Sistema-de-contenido-3ba34b7f9d25813d9b7fe3f44a8e3a36)**

Duplicala en tu espacio, y cuando la instalación te pida el identificador de la base, corré
`python ids_notion.py` con la dirección de la base duplicada. Si te dice que no falta ninguna
propiedad, ya está: no tenés que editar el config.

Si preferís armarla vos, o ya tenés una base andando con otros nombres, no hay problema —
**[NOTION.md](NOTION.md)** tiene el detalle y el config traduce cualquier nombre al que el
programa entiende.

## Los archivos

| Archivo | Qué es |
|---|---|
| **[INSTALACION.md](INSTALACION.md)** | El paso a paso para dejarlo andando. Empezá por acá. |
| **[NOTION.md](NOTION.md)** | Cómo tiene que estar armada tu base de Notion. |
| **[COMO_FUNCIONA.md](COMO_FUNCIONA.md)** | Qué hace por dentro y por qué cada decisión es así. Se lee cuando algo no hace lo que esperabas, o cuando lo querés modificar. |
| `sync_notion_buffer.py` | El programa. |
| `almacenamiento.py` | La parte que sube las imágenes. |
| `sync_config.ejemplo.json` | Tu configuración, comentada línea por línea. |
| `ids_buffer.py` | Te imprime los identificadores de Buffer que el config necesita. |
| `ids_notion.py` | Te da el identificador de tu base de Notion y revisa que no le falte nada. |
| `estado_buffer.py` | Te muestra qué hay en Buffer ahora, sin tocar nada. |
| `probar_sync.py` · `probar_config.py` · `probar_placas.py` | Las pruebas. Corrélas después de tocar cualquier cosa. |

## Antes de la primera corrida, una sola advertencia

El programa arranca **en modo seco**: lee todo, no escribe nada, y te dice qué haría. Es el modo
por defecto y hay que pedirle explícitamente que actúe, con `--apply`.

Corrélo en seco tantas veces como quieras hasta entender qué va a hacer. No hay apuro y no hay
riesgo: en seco no puede cambiar nada, ni en Notion, ni en Buffer, ni en tus redes.

```
python sync_notion_buffer.py
```

## Licencia

MIT ([LICENSE](LICENSE)). En castellano llano: hacé lo que quieras con esto —usalo, cambialo,
integralo en algo tuyo, cobrá por lo que construyas encima—. Lo único que se pide es que no borres
el aviso de copyright.

Y lo que dice el párrafo en mayúsculas de la licencia, que importa de verdad en una herramienta
que publica en tus redes: **se entrega tal cual y sin garantía.** Corrélo en seco, entendé qué
hace y probá con una pieza sola antes de confiarle tu cola entera.
