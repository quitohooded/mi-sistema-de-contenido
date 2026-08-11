# Tu base de Notion

Una base de datos, doce propiedades y una regla sobre el cuerpo de la página. Nada más.

No hace falta que la base sea nueva ni que sea solo para esto: si ya tenés una donde llevás tus
notas o tu calendario, agregale lo que falte y listo. El sistema solo mira las filas cuya marca y
cuyo canal reconoce; el resto ni las ve.

---

## Las doce propiedades

Los nombres de esta tabla son los que el ejemplo de configuración trae puestos, pero **podés
llamarlas como quieras**: si en tu base la columna se llama `Estado pieza` en vez de `Estado`,
declarás esa equivalencia en `notion.propiedades` de la configuración y funciona igual. Lo que no
se puede cambiar es el **tipo**.

### Las que tocás vos

| Propiedad | Tipo | Para qué |
|---|---|---|
| `Name` | Título | El nombre con el que navegás el tablero. **No es lo que se publica.** Ponele el ángulo de la pieza, no su texto. |
| `Estado` | Selección | El punto de control. Ver abajo. |
| `Canal` | Selección | `LinkedIn`, `X`, `Facebook`. Tiene que coincidir **exactamente** con lo que declaraste en la configuración. |
| `Marca` | Selección | De qué cuenta es la pieza. Si tenés una sola, igual hace falta: es lo que impide que una pieza salga por la cuenta equivocada. |
| `Fecha de publicación` | Fecha | Cuándo sale. **Podés dejarla vacía:** el sistema le asigna el próximo horario libre de ese canal y te la escribe. |
| `Placa` | Archivos y multimedia | Arrastrás la imagen acá y no hacés nada más. |
| `Archivo` | Casilla | Marcala para sacar una fila de circulación sin borrarla. Las archivadas se ignoran. |

### Las que toca solo el programa

Estas no se completan nunca a mano. Son la memoria del sistema, y **conviene ocultarlas en todas
tus vistas**: no aportan nada mirándolas y ensucian el tablero.

| Propiedad | Tipo | Qué guarda |
|---|---|---|
| `Buffer Post ID` | Texto | El identificador del post programado. Es lo que evita que se cree dos veces. |
| `Buffer Hash` | Texto | Una huella del contenido. Es cómo el sistema sabe si cambiaste algo. |
| `Buffer Last Sync` | Fecha | Cuándo se sincronizó por última vez. |
| `Imagen` | URL | La dirección pública de la placa, ya subida. |
| `URL` | URL | El link al post real, que se completa cuando la pieza sale. |

> **`Imagen` y `Placa` no son lo mismo, y la diferencia importa.** `Placa` es el archivo que vos
> arrastrás: es la superficie humana, la que ves al lado del texto mientras escribís. `Imagen` es
> la dirección pública a la que el sistema la subió: es lo que Buffer va a leer el día que
> publique. Vos tocás la primera; la segunda se escribe sola.

---

## Los cuatro estados

```
Idea  →  En producción  →  Aprobado  →  Publicado
```

| Estado | Quién lo pone | Qué pasa |
|---|---|---|
| `Idea` | Vos | Nada. |
| `En producción` | Vos | Nada. |
| **`Aprobado`** | **Solo vos** | Se programa en Buffer. |
| `Publicado` | **Solo el programa** | Se marca cuando Buffer confirma que salió de verdad. |

Los dos primeros pueden llamarse como quieras, o pueden ser diez en vez de dos: al sistema le da
igual, porque solo mira `Aprobado` y `Publicado`. Esos dos sí se declaran en la configuración.

**`Aprobado` es la única acción manual de todo el sistema, y el programa no lo puede escribir.** No
es una convención ni una buena intención: es una regla dura del código. Nada llega a tus redes sin
que una persona haya movido ese desplegable.

Dos cosas que **no** son estados, porque se deducen solas:

- **"En cola"** es una fila que ya tiene `Buffer Post ID`.
- **"Cancelar"** es sacar una fila de `Aprobado`: el post programado se borra de Buffer.

> **Ojo con esto último.** Sacar algo de `Aprobado` borra el post programado. Es lo que tiene que
> pasar, pero significa que un cambio distraído de desplegable tiene efecto. Se recupera volviendo
> a aprobar: se vuelve a crear. Y solo aplica **antes** de que la pieza salga; lo ya publicado es
> intocable.

---

## La regla del cuerpo, que es la más importante

**El cuerpo de la página ES el texto que se publica. Todo el cuerpo, tal cual, sin encabezados ni
marcadores.**

No hay que aprender ninguna convención: escribís la pieza como escribirías una nota, y sale así.

**La contrapartida es la regla que lo sostiene: en el cuerpo no va nada que no se publique.** Ni
notas para vos, ni variantes descartadas, ni recordatorios, ni links de referencia. Eso va a una
propiedad, a un comentario de Notion o a otro lado. **Lo que está en el cuerpo, sale.**

Qué pasa con el formato:

- Párrafos y listas se conservan (las listas salen con `— ` o `1. ` adelante).
- **Negrita, cursiva y subrayado se pierden:** las redes no los soportan.
- Citas, bloques de código, tablas, desplegables e imágenes insertadas en el cuerpo **se ignoran**.
- Si el cuerpo está vacío, la pieza no se publica y se reporta.

**Para un hilo de X:** una línea que contenga solamente `---` separa un tweet del siguiente.

> **Una trampa de Notion que conviene conocer.** Notion convierte en link automáticamente
> cualquier palabra que parezca un dominio: `archivo.md`, `github.com`, `ejemplo.io`. El texto
> deja de ser igual al que se publica. **Solución:** escribí esas palabras entre acentos graves
> (`` `así` ``), que Notion respeta.

---

## Las vistas que conviene tener

No son obligatorias —el sistema funciona igual sin ninguna— pero son lo que convierte la base en
algo usable todos los días.

1. **Un tablero por marca**, agrupado por estado. Es donde vivís: ves de un vistazo qué está en
   idea, qué en producción y qué aprobado.
2. **Un calendario**, por fecha de publicación. Es tu planificación real, sin límite de cuántas
   semanas hacia adelante.
3. **Un historial**, filtrado por `Publicado` y ordenado por fecha descendente. Es lo que
   efectivamente salió, con su link.

En todas: **ocultá las cinco propiedades de máquina**.

> **Por qué el calendario grande vive en Notion y no en Buffer.** Los planes gratuitos de Buffer
> admiten 10 posts programados por canal. Eso limita cuánto podés *planificar*, no cuánto podés
> *escribir*. En este sistema, todo lo aprobado espera en Notion sin límite de cantidad, y el
> programa va empujando a Buffer a medida que se libera lugar. Notion es el calendario grande;
> Buffer es una ventana de diez. No tenés que hacer nada para que eso pase.

---

## Un detalle que evita trabajo repetido

Si creás las piezas desde una vista ya filtrada (por marca, por tipo), Notion completa solas esas
propiedades en la fila nueva. Es preferible a acordarse de completarlas: lo correcto sale solo, que
es el criterio de todo este sistema.
