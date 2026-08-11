# Cómo funciona

Este documento explica qué hace el programa por dentro y **por qué cada decisión es como es**.

No hace falta leerlo para usar el sistema: para eso están [README.md](README.md),
[INSTALACION.md](INSTALACION.md) y [NOTION.md](NOTION.md). Se lee cuando algo no hizo lo que
esperabas, o cuando lo querés modificar.

**Este documento manda sobre el código.** Si el programa y esto no coinciden, el error está en el
programa. Los comentarios del código citan las secciones de acá por número.

---

## 1. Qué resuelve

Notion es la fuente de verdad y el tablero. Buffer ejecuta y no opina.

El principio de diseño es uno solo: **una sola acción humana en todo el ciclo, que es aprobar.**
Todo lo demás se setea solo o se deduce. Si una propiedad exige mantenimiento manual y el programa
puede deducirla, esa propiedad no va.

## 2. Lo que este sistema NO decide

No decide **qué** publicás ni **cuándo**. Eso es criterio tuyo y vive donde vos lo tengas escrito.

Los horarios (los *slots*) se declaran de dos maneras, y la elección no es de gusto:

- **`inline`** — los escribís en la configuración. Es lo que le sirve a casi cualquiera.
- **`documento`** — se leen de una tabla `### Slots` de un archivo markdown tuyo. Sirve cuando ya
  llevás tu calendario editorial escrito y no querés tenerlo duplicado en dos lugares, porque dos
  copias del mismo dato terminan discrepando.

Si los horarios no se pueden leer, **es error duro y no se publica nada**. Inventar un horario es
peor que no publicar.

## 3. Ruteo por cuenta

Cada *espacio* de la configuración es una cuenta de Buffer con sus canales y **su propia
credencial**. El programa elige por el valor de la propiedad de marca de la fila.

**No existe una credencial que vea dos cuentas.** Eso no es una limitación que haya que sortear:
es la garantía de que una pieza de una marca no puede salir por los canales de otra.

Un canal que no esté declarado (YouTube, un blog, un boletín) simplemente se ignora. **Una fila
sin marca, o con una marca que no figura en la configuración, no se procesa: se reporta.**

## 4. Modelo de estados

```
Idea  →  En producción  →  Aprobado  →  Publicado
```

Solo `Aprobado` y `Publicado` gobiernan al programa. Los demás valores son tuyos y le dan igual.

**Por qué la aprobación vive en el mismo desplegable y no en una casilla aparte:** porque los
estados son mutuamente excluyentes. Una casilla separada permitiría combinaciones sin significado
(`Idea` + aprobado) y partiría en dos la única acción manual del sistema, que es justo lo que este
diseño evita.

**El costo real del diseño, que conviene conocer:** una pieza ya publicada **no puede volver a
publicarse** mientras conserve su `Buffer Post ID`, porque la regla dura 1 prohíbe crear un post
para una fila que ya tiene uno. Es deliberado: es la regla que evita duplicados. **Para volver a
publicar algo, duplicá la fila**; la copia nace sin ese identificador.

## 5. Propiedades

Ver [NOTION.md](NOTION.md). Lo que importa acá es el reparto: cinco propiedades son de la máquina
y no se tocan a mano; el resto son tuyas.

## 6. Dónde vive el texto publicable

**El cuerpo de la página ES el texto que se publica. Todo el cuerpo, sin encabezados ni
marcadores.**

Se usa el cuerpo y no una propiedad por una razón concreta: las propiedades de Notion tienen un
tope de caracteres por debajo de un post largo de LinkedIn.

Y se usa *todo* el cuerpo, sin un marcador que delimite qué parte se publica, por otra razón: un
marcador obliga a conocer la convención para escribir una pieza. El objetivo es el contrario, que
puedas escribir sin consultar nada y que al aprobar salga tal cual.

**La contrapartida es la regla que lo sostiene: en el cuerpo no va nada que no se publique.**

El título es tuyo y el programa no lo toca nunca: es la etiqueta con la que navegás el tablero, así
que conviene que nombre el ángulo de la pieza y no que repita su texto.

**Longitud:** si una pieza supera el límite de su red, no se publica y se reporta. **No se corta,
no se resume, no se reescribe.**

## 7. Fecha y hora

Si la fecha está vacía al aprobar, el programa le asigna **el próximo hueco libre de ese canal** y
**lo escribe de vuelta en Notion**, así lo ves. Si vos pusiste una fecha, se respeta.

**Lo ya agendado no se reprograma.** Si cambiás tus horarios, el cambio rige para lo que se agende
después; la cola existente sale en el horario que ya tiene.

La fecha viaja siempre **con el huso horario explícito**. Nunca en UTC pelado: una fecha sin hora
interpretada como medianoche UTC publicaría a las 21 h del día anterior.

Una fila aprobada con fecha pasada no se publica: se reporta como vencida.

## 8. La huella (el *hash*)

Es cómo el sistema sabe si cambiaste algo, sin guardar una copia del texto en ningún lado:

```
huella = sha256( texto + fecha + canal + dirección de la imagen )
```

Tres reglas la sostienen, y las tres se aprendieron rompiendo algo:

1. **Se calcula siempre con los datos de Notion, nunca con los de Buffer.** Buffer transforma el
   texto (acorta links), así que comparar un lado contra el otro detectaría un cambio falso todos
   los días.
2. **La dirección de la imagen entra solo si es estable.** Una dirección que rota en cada lectura
   metería un valor distinto en cada corrida. Por eso la regla de la sección 9 no es una
   preferencia estética.
3. **Todo salto de línea se colapsa a uno solo.** Notion no distingue, al releer una página, entre
   un corte de párrafo y un salto suave: los dos vuelven igual. Sin esta regla, el mismo texto da
   huellas distintas de los dos lados y **la primera corrida reescribiría la cola entera** sin que
   nadie hubiera tocado una palabra.

   *El precio aceptado: no se detecta un cambio que solo agregue o quite líneas en blanco. A
   cambio, el sistema deja de reescribir todo cada vez que corre.*

## 9. Imágenes — la dirección tiene que ser pública y estable

**Buffer no se guarda una copia de la imagen cuando programás el post.** El post queda apuntando a
la dirección de origen hasta el día que sale. Está verificado, no inferido.

**Consecuencia:** la dirección que Notion le da a un archivo adjunto vence en aproximadamente una
hora, así que **rompería la imagen** de un post programado para dentro de una semana. El adjunto de
Notion no sirve como origen.

**Por eso:** vos arrastrás el archivo a `Placa` y el programa lo copia a un lugar público y
estable, y escribe esa dirección en `Imagen`. Vos no entrás nunca al lugar donde se guardan.

**El nombre del archivo guardado no significa nada:** es la huella de su contenido, sin carpetas.
No revela marca, ni fecha, ni de qué pieza es, y no se puede enumerar. De arriba da tres cosas:
el mismo archivo no se sube dos veces, una versión nueva es un nombre nuevo (que es lo que hace
que la actualización se dispare sola), y la misma imagen usada en dos piezas es un solo archivo.

**Del almacenamiento no se borra nunca.** Si una red no se guardó su copia, borrar el archivo
apagaría la imagen de un post ya publicado, meses después y sin autor visible. El costo de no
borrar es despreciable; el de borrar, invisible hasta que es tarde.

**El tipo de archivo se detecta por los bytes, no por la extensión:** el nombre de un archivo lo
pone una persona y puede mentir.

**El programa no comprime ni redimensiona.** Avisa si una imagen es pesada y rechaza la que pase el
máximo, pero no la toca. El motivo decisivo: como el nombre del archivo es la huella de su
contenido, si comprimiera, ese nombre pasaría a depender del resultado de la compresión. El día que
cambiara la librería o un parámetro, **cambiarían todos los nombres de golpe: se resubirían todas
las imágenes y se editarían todos los posts.**

## 10. El cupo

**10 posts programados por canal**, no 10 en total. Un hilo de X ocupa **un** lugar, no varios.

Si hay más piezas aprobadas que cupo, entran las de fecha más próxima y el resto espera. **No es un
error**: entran solas en una corrida posterior.

Para contar bien **hay que paginar**. La consulta de Buffer devuelve 10 por defecto y eso *parece*
la cola completa, justo porque 10 coincide con el tope por canal.

## 11. La rutina

Corre **en seco por defecto**: lee todo, no escribe nada, dice qué haría. Solo escribe con
`--apply`. Es idempotente: si corre dos veces seguidas, la segunda no cambia nada.

**Paso 1 — Leer los dos lados, paginando.**

**Paso 2 — Reconciliar.** ¿Hay un post en Buffer que no figure en ninguna fila? **No se borra.** Se
reporta con su texto y su fecha, y se deja intacto. Borrar contenido por deducción es la clase de
error que no se deshace.

**Paso 3 — Procesar cada fila.** Se evalúan de arriba hacia abajo y **manda el primer caso que
coincida**. El orden no es cosmético: es lo que hace que una pieza ya publicada sea intocable.

> **Paso 0 de cada fila aprobada: resolver la imagen**, antes de calcular la huella, porque la
> dirección entra en la huella y es lo que hace que una imagen nueva dispare sola la actualización.
>
> | La fila tiene | Qué hace |
> |---|---|
> | `Placa` con adjunto | lo baja mientras su dirección está viva, lo valida y, si no está guardado, lo sube. Escribe `Imagen` |
> | `Placa` ya subida | **nada**, ni siquiera consulta el almacenamiento |
> | Sin `Placa`, con `Imagen` propia | la imagen estuvo y se la sacaron → limpia `Imagen` |
> | Sin `Placa`, con `Imagen` de otro origen | la respeta y no la toca |

**a) Terminal.** Estado `Publicado` → no hacer nada, nunca.

**b) Ya salió.** Tiene identificador de post y Buffer confirma que se envió → se marca `Publicado`
con la **fecha real de salida** y el **link real**.

*Va antes que cancelación y que actualización, y por eso mover una pieza ya publicada a cualquier
otro estado no borra ni edita nada: solo la devuelve a `Publicado`.*

**c) Cancelación.** Tiene identificador, ya no está `Aprobado`, **y el post está programado** →
se borra de Buffer y se limpian los campos de máquina.

> **Esa última condición no es un detalle: sin ella la regla borra borradores.** Un borrador es,
> por definición, algo que todavía no se aprobó, así que cumpliría "no está aprobado" y se
> eliminaría en la primera corrida. **El programa administra solo posts programados**; los
> borradores quedan fuera del modelo, se reportan y no se tocan.

**d) Actualización.** Tiene identificador, está `Aprobado`, y la huella cambió → se aplica el
cambio en Buffer.

> **La huella vigila cuatro cosas y una edición no puede aplicarlas todas.** Lo que no se puede
> aplicar se reporta y **no se guarda la huella nueva**:
>
> | Cambió | ¿Se puede? | Qué hace |
> |---|---|---|
> | Texto, fecha | sí | lo aplica |
> | Imagen nueva o distinta | sí | lo aplica |
> | **Canal** | **no** — Buffer no mueve un post de canal | reporta: cancelá y volvé a aprobar |
> | **Quitar la imagen** | **no** — una edición no puede dejar el post sin imagen | reporta |
>
> **Guardar la huella de un cambio que no se aplicó es el peor modo de falla posible:** deja la
> fila marcada como sincronizada mintiendo, y no vuelve a avisar nunca más.

**e) Creación.** `Aprobado`, sin identificador, y hay cupo → se crea el post programado.

**Paso 4 — Cierre.** Una línea, no un informe:

```
Sync 04/08 09:00 - 2 programadas, 1 actualizada, 1 publicada, 0 canceladas. Sin errores.
```

## 12. Reglas duras

Estas no se negocian y están en el código, no en la buena voluntad:

1. **Nunca crear un post para una fila que ya tiene identificador.** Es la regla que evita
   duplicados, y la más importante de todas.
2. **El programa nunca escribe `Aprobado`.** Es lo que garantiza que nada llegue a tus redes sin
   pasar por una persona.
3. **Nunca marcar `Publicado`** sin haber visto en Buffer que la pieza salió. No se infiere porque
   la fecha ya pasó.
4. **Nunca exceder el cupo por canal**, y para saberlo hay que paginar.
5. **Nunca borrar un post que no tiene fila.** Reportar y dejar.
6. **Nunca cortar, resumir ni reescribir** un texto que excede el límite de la red.
7. **Nunca tocar una fila publicada.**
8. **Nunca mezclar cuentas:** cada una, su credencial y sus canales.
9. **Nunca borrar una imagen ya subida.**
10. **Si algo es ambiguo, no decidir: reportar y seguir.**

## 13. Errores

- **Falla una pieza puntual** (texto largo, imagen rechazada): no se reintenta en bucle. Se anota,
  se deja la fila como está y se sigue con las demás. Un error no frena todo.
- **No se puede conectar** con Notion o con Buffer al arrancar: se corta sin tocar nada.
- Toda llamada de red **corta a los 30 segundos**, y se lee el cuerpo del error, no solo su
  número: es donde la API dice *qué* propiedad falló.

## 14. Qué está verificado contra las APIs reales

Lo de esta lista se midió, no se dedujo. Se deja escrito porque varias de estas cosas parecían
ciertas y no lo eran.

- ✅ **Los archivos adjuntos se preservan en una edición** aunque no se vuelvan a mandar. Mandar la
  lista vacía, en cambio, los borra.
- ❌ **Buffer NO se guarda una copia de la imagen al crear el post.** Medido: el post siguió
  apuntando a la dirección de origen. **Era el error más caro de todos: habría dado imágenes rotas
  recién el día de publicar.**
- ✅ **El tope es de 10 posts programados por canal**, no en total.
- ✅ **Las credenciales de dos cuentas están realmente separadas:** la clave de una sobre la otra
  responde prohibido.
- ✅ **La forma exacta de dos estructuras que nunca se habían ejercitado**, y las dos estaban mal
  escritas: el texto alternativo de una imagen va *dentro* de los metadatos, no al lado de la
  dirección; y un hilo de X es una lista de objetos, no una lista de textos. **Las dos habrían
  fallado la primera vez que una pieza llevara imagen o fuera un hilo**, y convivieron con cinco
  pruebas en vivo que salieron bien porque ninguna las tocaba.
- ✅ **Editar un post de Facebook exige declarar el tipo**, no solo crearlo. Se descubrió en
  producción, porque todas las pruebas de edición previas habían sido sobre X.

**El patrón que dejaron las tres últimas, y es la lección más útil de todo el proyecto:** *una ruta
que nunca se ejecutó no está verificada, por más que esté escrita y revisada.*

**Lo que sigue sin verificarse**, y conviene mirarlo el día que te pase:

- Si las redes se guardan su propia copia de la imagen al publicar. No se puede saber sin publicar
  de verdad. **No cambia ninguna regla**, porque la dirección igual tiene que estar viva ese día.

---

## Si vas a modificar el código

Corré las tres baterías de pruebas antes y después. Son 88 comprobaciones con la instalación
completa (82 si todavía no cargaste las credenciales), y ninguna publica nada:

```bash
python probar_config.py && python probar_placas.py && python probar_sync.py
```

Tres de esas comprobaciones son **controles negativos**: prueban que la prueba puede fallar. Sin
ellas, una batería que solo verifica que nada explota pasaría igual con el programa entero
comentado.

Y la señal que más vale, sobre tus datos reales: **una corrida en seco tiene que dar `0
actualizadas`.** Si da otra cosa después de un cambio tuyo, la huella dejó de reproducirse y la
próxima corrida reescribiría la cola entera.
