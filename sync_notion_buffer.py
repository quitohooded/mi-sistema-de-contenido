# sync_notion_buffer.py - La rutina del sync Notion -> Buffer, para las dos marcas.
#
# Implementa la seccion 11 del documento del mecanismo (COMO_FUNCIONA.md en el paquete
# distribuible, sync_notion_buffer.md en la instalacion de origen). Ese documento manda: si el
# codigo y el documento discrepan, el bug esta aca. Las "seccion N" de los comentarios son las
# de ese documento, y la numeracion es la misma en los dos.
#
# Uso:
#   python sync_notion_buffer.py                     # SECO: lee todo, no escribe nada, dice que haria
#   python sync_notion_buffer.py --apply             # ejecuta de verdad
#   python sync_notion_buffer.py --espacio "Mi marca"  # acotar a un espacio del config
#   python sync_notion_buffer.py --config otro.json    # usar otra configuracion
#
# Es idempotente: si corre dos veces seguidas, la segunda no cambia nada. El estado se lee de
# Notion y de Buffer en cada ejecucion; no guarda nada entre corridas.
#
# Configuracion: sync_config.json, al lado de este archivo. TODO lo propio de una instalacion
# vive ahi -espacios, canales, propiedades de Notion, zona horaria, slots-, asi que este motor
# no tiene adentro ningun dato de una persona o una marca. Otra maquina u otra persona cambian
# el config, no el codigo. Las credenciales NO estan en el config: el config dice donde estan,
# y estan siempre fuera de todo repo.
#
#   --config <ruta>   usar otro archivo de configuracion

import json, sys, hashlib, re, pathlib, time, urllib.request, urllib.error
from datetime import datetime, timedelta, timezone

import almacenamiento

TIMEOUT = 30
DIAS = {"lunes": 0, "martes": 1, "miercoles": 2, "miércoles": 2, "jueves": 3,
        "viernes": 4, "sabado": 5, "sábado": 5, "domingo": 6}


def ruta(p):
    """'~' se expande al home del usuario: es lo que hace que el mismo config funcione en otra
    maquina sin editar una linea. pathlib acepta '/' tambien en Windows."""
    return pathlib.Path(str(p)).expanduser()


def cargar_config(archivo=None):
    f = pathlib.Path(archivo) if archivo else pathlib.Path(__file__).parent / "sync_config.json"
    if not f.exists():
        raise RuntimeError(f"no se encontro la configuracion: {f}")
    c = json.loads(f.read_text(encoding="utf-8"))
    for req in ("zona_horaria", "cupo_por_canal", "notion", "espacios"):
        if req not in c:
            raise RuntimeError(f"{f.name}: falta la clave obligatoria '{req}'")
    if not c["espacios"]:
        raise RuntimeError(f"{f.name}: no hay ningun espacio declarado")
    return c


def zona(offset):
    """'-03:00' -> timezone. Nunca UTC pelado: una fecha sin hora interpretada como medianoche
    UTC publica a las 21 h del dia anterior."""
    m = re.fullmatch(r"([+-])(\d{2}):(\d{2})", offset.strip())
    if not m:
        raise RuntimeError(f"zona_horaria invalida: {offset!r}. Se espera algo como '-03:00'")
    signo = 1 if m.group(1) == "+" else -1
    return timezone(signo * timedelta(hours=int(m.group(2)), minutes=int(m.group(3))))


CFG = cargar_config(sys.argv[sys.argv.index("--config") + 1] if "--config" in sys.argv else None)
AR = zona(CFG["zona_horaria"])
CUPO = CFG["cupo_por_canal"]
LIMITE = CFG.get("limites_por_canal", {})
NOTION_DS = CFG["notion"]["data_source"]
NOTION_KEY = ruta(CFG["notion"]["credencial"])
P = CFG["notion"]["propiedades"]          # nombre real de cada propiedad en la base
EST = CFG["notion"]["estados"]            # 'aprobado' y 'publicado', los dos que gobiernan
ESPACIOS = CFG["espacios"]
ALM = CFG.get("almacenamiento") or {}     # opcional: sin esto el sync corre igual, sin placas
# Lo que NO puso este sync. Todo asset que no venga de aca lo puso el sync desde Notion, asi que
# si la fila ya no lo declara es que se lo sacaron. Vive en el config y no en el codigo porque
# es un dato de instalacion: otra persona con otro CDN no tiene por que editar el motor.
HOSTS_AJENOS = ALM.get("hosts_ajenos", ["buffer-media-uploads"])

# Hoy el unico backend es R2, y el campo `proveedor` existe para que el config declare lo que el
# codigo hace de verdad. Se valida aca en vez de ignorarlo: un campo que se ignora es un campo
# que miente, y un config que declarara otro proveedor correria contra R2 igual y EN SILENCIO.
# NO se implementan mas backends a proposito: es una decision vigente, no un pendiente.
# Si alguna vez hace falta otro, este diccionario es el unico punto que se toca.
PROVEEDORES = {"r2": almacenamiento.R2}
PROVEEDOR = (ALM.get("proveedor") or "r2").strip().lower()
if ALM and PROVEEDOR not in PROVEEDORES:
    raise RuntimeError(f"almacenamiento.proveedor desconocido: {ALM.get('proveedor')!r}. "
                       f"Disponibles: {', '.join(sorted(PROVEEDORES))}")

# El User-Agent no es cosmetico: el de urllib esta bloqueado por la proteccion anti-bot de
# Cloudflare y devuelve 403 sobre un objeto perfectamente subido. Va al config porque el valor
# verificado contra un CDN concreto es un dato de instalacion, no del motor.
if ALM.get("user_agent"):
    almacenamiento.UA = ALM["user_agent"]


# --------------------------------------------------------------------------- transporte

def _abrir(req):
    """Todas las llamadas pasan por aca por dos razones, y las dos son de correr sin nadie
    mirando: sin `timeout` una conexion colgada cuelga el proceso entero (el Programador lo
    mata a los 15 min, pero muere sin linea de cierre en el log y sin codigo de salida
    propio, o sea un cuelgue mudo); y sin leer el cuerpo del HTTPError el mensaje queda en
    'HTTP Error 400: Bad Request', justo cuando el cuerpo es donde Notion dice QUE propiedad
    fallo. Desatendido, el log es lo unico que queda. Reintenta HTTP 429 (rate limit) respetando
    Retry-After hasta 5 veces."""
    for intento in range(6):
        try:
            return json.loads(urllib.request.urlopen(req, timeout=TIMEOUT).read())
        except urllib.error.HTTPError as e:
            detalle = ""
            try:
                detalle = e.read().decode("utf-8", "replace")[:400]
            except Exception:
                pass
            if e.code == 429 and intento < 5:
                espera = 1.5
                try:
                    ra = e.headers.get("Retry-After") if e.headers else None
                    if ra:
                        espera = min(max(float(ra), 0.5), 30.0)
                    else:
                        espera = min(2.0 * (intento + 1), 20.0)
                except Exception:
                    espera = 2.0 * (intento + 1)
                time.sleep(espera)
                continue
            raise RuntimeError(f"HTTP {e.code} en {req.full_url}: {detalle or e.reason}") from None
        except urllib.error.URLError as e:
            raise RuntimeError(f"sin conexion con {req.full_url}: {e.reason}") from None


def _post(url, payload, headers):
    return _abrir(urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"),
                                         headers=headers, method="POST"))


def buffer_gql(key, query, variables=None):
    d = _post("https://api.buffer.com/graphql",
              {"query": query, "variables": variables or {}},
              {"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
    if d.get("errors"):
        raise RuntimeError("Buffer: " + json.dumps(d["errors"])[:400])
    return d["data"]


def leer_credencial(p, que, donde):
    """Un archivo de credencial que falta es el error mas comun de una instalacion nueva, y el
    mensaje crudo del sistema ('[Errno 2] No such file or directory') no dice ni que archivo
    hace falta ni de donde se saca. Desatendido, el log es lo unico que queda: que diga algo."""
    if not p.exists():
        raise RuntimeError(f"falta la credencial de {que}: no existe {p}. "
                           f"Crea ese archivo con el token adentro (ver INSTALACION.md, {donde}), "
                           f"o corregi la ruta en el config.")
    tok = p.read_text(encoding="utf-8").strip()
    if not tok:
        raise RuntimeError(f"la credencial de {que} esta vacia: {p}")
    return tok


def notion(path, payload=None, method=None):
    tok = leer_credencial(NOTION_KEY, "Notion", "paso 2")
    h = {"Authorization": f"Bearer {tok}", "Notion-Version": "2025-09-03",
         "Content-Type": "application/json"}
    url = f"https://api.notion.com/v1/{path}"
    if payload is None and method is None:
        return _abrir(urllib.request.Request(url, headers=h))
    return _abrir(urllib.request.Request(url, data=json.dumps(payload or {}).encode("utf-8"),
                                         headers=h, method=method or "POST"))


# --------------------------------------------------------------------------- slots

def leer_slots(cfg_slots):
    """Dos modos, declarados en el config:

    'documento' - se parsean de una tabla '### Slots' en un markdown. Sirve cuando la cadencia es
                  criterio editorial y vive escrita en el documento de esa marca o proyecto, asi
                  que cambiarla es cambiar esa tabla y nada mas (seccion 2).
    'inline'    - se declaran en el propio config. Es el modo util para cualquier instalacion
                  que no tenga un markdown con ese formato, que es casi cualquiera.

    Si no se pueden leer, es error duro: adivinar un horario es peor que no publicar."""
    fuente = (cfg_slots or {}).get("fuente", "documento")

    if fuente == "inline":
        slots = {}
        for canal, d in (cfg_slots.get("canales") or {}).items():
            idx = sorted(DIAS[x.strip().lower()] for x in d["dias"] if x.strip().lower() in DIAS)
            hh, mm = str(d["hora"]).split(":")
            if not idx:
                raise RuntimeError(f"el canal {canal} no declara ningun dia valido")
            slots[canal] = (idx, int(hh), int(mm))
        if not slots:
            raise RuntimeError("los slots inline no declaran ningun canal")
        return slots

    if fuente != "documento":
        raise RuntimeError(f"fuente de slots desconocida: {fuente!r} (se espera 'documento' o 'inline')")

    doc = ruta(cfg_slots["ruta"])
    if not doc.exists():
        raise RuntimeError(f"no existe el documento de slots: {doc}")
    txt = doc.read_text(encoding="utf-8")
    m = re.search(r"###\s+Slots\s*(.*?)(?=\n##\s|\Z)", txt, re.S)
    if not m:
        raise RuntimeError(f"{doc.name}: no se encontro la seccion '### Slots'")
    slots = {}
    for fila in re.finditer(r"^\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|\s*(\d{1,2}):(\d{2})\s*\|",
                            m.group(1), re.M):
        canal, dias, hh, mm = fila.groups()
        if canal.strip().lower() in ("canal", "---"):
            continue
        idx = [DIAS[d.strip().lower()] for d in dias.split("·") if d.strip().lower() in DIAS]
        if idx:
            slots[canal.strip()] = (sorted(idx), int(hh), int(mm))
    if not slots:
        raise RuntimeError(f"{doc.name}: la tabla de slots no se pudo parsear")
    return slots


def proximo_hueco(slots, canal, ocupados, desde):
    """Primer slot del canal posterior a `desde` que no este ya ocupado."""
    if canal not in slots:
        raise RuntimeError(f"el canal {canal} no tiene slot declarado")
    dias, hh, mm = slots[canal]
    d = desde.astimezone(AR)
    for salto in range(0, 400):
        cand = (d + timedelta(days=salto)).replace(hour=hh, minute=mm, second=0, microsecond=0)
        if cand.weekday() in dias and cand > d and cand not in ocupados:
            return cand
    raise RuntimeError(f"no hay hueco libre para {canal} en un ano")


def parsear_fecha(fecha, canal, slots):
    """Parsea una fecha ISO de Notion a la zona horaria del config (`AR`).
    Si viene solo el dia ('YYYY-MM-DD', 10 caracteres) y el canal esta en `slots`,
    aplica la hora y el minuto del slot en zona `AR` (sin depender del huso local del SO)."""
    s = fecha.strip()
    d = datetime.fromisoformat(s.replace("Z", "+00:00"))
    if d.tzinfo is None:
        d = d.replace(tzinfo=AR)
    else:
        d = d.astimezone(AR)
    if len(s) == 10 and canal in slots:
        _, hh, mm = slots[canal]
        d = d.replace(hour=hh, minute=mm, second=0, microsecond=0)
    return d


def _orden_creacion(f, slots):
    """Clave de orden cronologico para (e) creacion: filas con fecha primero (por datetime
    resuelto, incluyendo hora del slot si vino solo el dia) y filas sin fecha al final."""
    pr = f["properties"]
    fecha = prop_txt(pr.get(P["fecha"]))
    canal = prop_txt(pr.get(P["canal"]))
    if not fecha:
        return (1, datetime.max.replace(tzinfo=AR))
    try:
        return (0, parsear_fecha(fecha, canal, slots))
    except Exception:
        return (0, datetime.max.replace(tzinfo=AR))


# --------------------------------------------------------------------------- Notion

def prop_txt(p):
    if not p:
        return ""
    t = p.get("type")
    if t in ("rich_text", "title"):
        return "".join(x["plain_text"] for x in p[t]).strip()
    if t == "select":
        return (p["select"] or {}).get("name", "")
    if t == "url":
        return p["url"] or ""
    if t == "checkbox":
        return p["checkbox"]
    if t == "date":
        return (p["date"] or {}).get("start", "")
    return ""


def prop_placas(p):
    """URLs de descarga de TODOS los adjuntos de una propiedad de tipo `files`, EN ORDEN.

    Notion devuelve dos formas: 'file' es un archivo subido a Notion, y su URL esta FIRMADA y
    expira en el orden de una hora -por eso hay que bajarla ahora y no guardarla-; 'external' es
    un archivo enlazado desde afuera.

    El orden del array es el que se ve en Notion, y es el que Esteban controla arrastrando los
    archivos dentro de la propiedad. Ese orden ES el orden de publicacion (seccion 9)."""
    if not p or p.get("type") != "files":
        return []
    out = []
    for f in p["files"] or []:
        if f.get("type") == "file":
            u = (f.get("file") or {}).get("url", "")
        elif f.get("type") == "external":
            u = (f.get("external") or {}).get("url", "")
        else:
            u = ""
        if u:
            out.append(u)
    return out


def urls(s):
    """`imagen` guarda N URLs separadas por espacios, en orden. Es un campo de tipo `url` en
    Notion, y `[CONFIRMADO]` 2026-08-26 Notion acepta y devuelve ese string intacto: no valida
    el formato. Se eligio asi para NO tener que cambiar el tipo de la propiedad, que es
    estructura de la base y la toca Esteban, no el sync."""
    return (s or "").split()


def junta(lista):
    return " ".join(lista)


def filas_notion(espacio, canales):
    """Todas las filas del espacio cuyo canal mapea a Buffer. Pagina hasta el final."""
    out, cursor = [], None
    while True:
        payload = {"page_size": 100, "filter": {"and": [
            {"property": P["espacio"], "select": {"equals": espacio}},
            {"property": P["archivado"], "checkbox": {"equals": False}},
            {"or": [{"property": P["canal"], "select": {"equals": c}} for c in canales]},
        ]}}
        if cursor:
            payload["start_cursor"] = cursor
        d = notion(f"data_sources/{NOTION_DS}/query", payload)
        out += d["results"]
        if not d.get("has_more"):
            break
        cursor = d["next_cursor"]
    return out


def cuerpo(page_id):
    """El cuerpo de la pagina ES el texto que se publica (seccion 6). Devuelve (texto, tramos).
    `tramos` parte el texto en un divisor `---`, que es como se escribe un hilo de X."""
    bloques, cursor = [], None
    while True:
        q = f"blocks/{page_id}/children?page_size=100" + (f"&start_cursor={cursor}" if cursor else "")
        d = notion(q)
        bloques += d["results"]
        if not d.get("has_more"):
            break
        cursor = d["next_cursor"]

    tramos, actual = [], []
    for b in bloques:
        t = b["type"]
        if t == "divider":
            tramos.append(actual); actual = []
            continue
        if t not in ("paragraph", "bulleted_list_item", "numbered_list_item"):
            continue  # toggle, callout, quote, codigo, tablas e imagenes se ignoran
        txt = "".join(x["plain_text"] for x in b[t]["rich_text"])
        if t == "bulleted_list_item":
            txt = "— " + txt
        elif t == "numbered_list_item":
            txt = "1. " + txt
        if txt.strip() == "---":
            tramos.append(actual); actual = []
            continue
        actual.append(txt)
    tramos.append(actual)

    partes = ["\n\n".join(x for x in tr).strip() for tr in tramos]
    partes = [p for p in partes if p]
    return "\n\n".join(partes), partes


def escribir(page_id, props, cover=None):
    payload = {"properties": props}
    if cover:
        payload["cover"] = {"type": "external", "external": {"url": cover}}
    return notion(f"pages/{page_id}", payload, method="PATCH")


def cover_propio(fila, cdn):
    """El cover actual, si lo puso este sync. Sirve para no pisar uno puesto a mano:
    solo se reemplaza el que apunta al CDN propio."""
    c = (fila.get("cover") or {})
    return (c.get("external") or {}).get("url", "").startswith(cdn) if c else False


def p_text(v):   return {"rich_text": [{"text": {"content": v}}] if v else []}
def p_sel(v):    return {"select": {"name": v}}
def p_url(v):    return {"url": v or None}
def p_date(v):   return {"date": {"start": v} if v else None}


# --------------------------------------------------------------------------- placas

def materializar(fila, pr, imagen, cliente, cdn, espacio, aplicar, log, nombre, canal, avisos):
    """Paso 0 de la seccion 9: las placas que se arrastraron a Notion se suben al bucket y sus
    URLs publicas quedan escritas en `imagen`, separadas por espacio y EN EL MISMO ORDEN.

    El reparto es: `placa` (adjuntos) es la superficie humana y la unica que se toca a mano; el
    bucket es donde Buffer puede leerlas el dia que publica; `imagen` es el puente y la escribe
    la maquina. Devuelve la imagen que corresponde usar en esta corrida, para que el hash de la
    seccion 8 y el payload la vean ya resuelta.

    Varias imagenes por pieza `[CONFIRMADO]` 2026-08-26: la propiedad `Placa` siempre admitio
    varios archivos y el sync subia solo el primero, en silencio. Como el string entero entra al
    hash, agregar, quitar o REORDENAR archivos dispara sola la actualizacion en Buffer.
    """
    origenes = prop_placas(pr.get(P["placa"]))

    if not origenes:
        # No hay adjuntos. Si `imagen` apunta al CDN propio, la placa estuvo y se la sacaron: se
        # limpia para que la regla (d) pueda avisar que una edicion no puede dejar un post sin
        # placa. Si es una URL cargada a mano, se respeta y no se toca: es el caso de las piezas
        # cuya placa se subio por la app web.
        if imagen and imagen.startswith(cdn):
            log(f"  placa quitada  {nombre}")
            if aplicar:
                escribir(fila["id"], {P["imagen"]: p_url("")})
            return ""
        return imagen

    # Alguna placa apunta a un host que no es de este sync: lo tipico es una URL del S3 de Buffer,
    # que la app web usa para las placas que se suben desde ahi. NO se materializa, y no es una
    # preferencia: `[CONFIRMADO]` 2026-08-07 esas URLs son PRIVADAS (S3 responde AccessDenied),
    # asi que no se pueden descargar para subirlas ni sirven adjuntadas en Notion. Intentarlo
    # daria un error por fila en cada corrida. Se devuelve `imagen` intacta para no mover el hash.
    #
    # Basta UNA ajena para no tocar la fila entera: materializar solo las demas cambiaria `imagen`
    # y dispararia una edicion que dejaria el post con menos placas de las que tiene. Conservador
    # a proposito, y es la misma semantica que tenia con una sola.
    if any(any(h in o for h in HOSTS_AJENOS) for o in origenes):
        return imagen

    # Se resuelve cada adjunto por separado, conservando el orden. Los que ya apuntan al CDN
    # propio son su propia URL final: no hay nada que descargar ni subir, y ahorra una descarga
    # por archivo en cada corrida.
    finales, pendientes, peso_total, vistas = [], [], 0, set()
    for o in origenes:
        if o.startswith(cdn):
            finales.append(o)
            continue
        url, key, contenido, ct, peso = almacenamiento.analizar(cliente, o, cdn)
        finales.append(url)
        # Dedup DENTRO de la fila: dos adjuntos con el mismo contenido dan la misma clave, y sin
        # esto se subian dos veces, porque cada uno consulta el bucket por separado y la primera
        # subida todavia no se ve. El post igual las lleva las dos veces si asi se cargaron: lo
        # que se deduplica es la subida, no lo que se publica.
        if key in vistas:
            continue
        vistas.add(key)
        peso_total += peso
        pendientes.append((key, contenido, ct, peso))

    nueva = junta(finales)
    if nueva == imagen:
        return imagen                       # ya materializada: no se toca R2 ni para preguntar

    # Aviso, no bloqueo, y por dos motivos distintos:
    #
    # Peso: el sync NO comprime a proposito. La clave es el hash del contenido, asi que si
    # comprimiera, la clave dependeria del resultado de la compresion y el dia que cambiara la
    # libreria o un parametro se re-subirian TODAS las placas y se editarian TODOS los posts.
    # Optimizar es del lado del diseno, donde se ve el resultado.
    #
    # Cantidad: cada red tiene su tope de imagenes por post y NO estan verificados contra la API
    # desde aca, asi que el sync avisa y deja decidir a Buffer. Si Buffer rechaza, la fila se
    # reporta y NO se guarda su hash (seccion 11-d), que es el comportamiento correcto: se
    # reintenta sola en la corrida siguiente. Inventar un limite duro seria peor que este aviso.
    tope = (CFG.get("imagenes_por_canal") or {}).get(canal)
    if tope and len(finales) > tope:
        avisos.append(f"{nombre}: {len(finales)} imagenes y {canal} suele aceptar {tope}. "
                      f"Se manda igual; si Buffer la rechaza, la fila se reporta y se reintenta.")

    gordo = peso_total > ALM.get("aviso_peso_mb", 1) * 1024 * 1024
    cuantas = f"{len(finales)} imagen" + ("es" if len(finales) != 1 else "")
    log(f"  placa       {nombre}  ({cuantas}, {peso_total // 1024} KB)"
        + ("  conviene optimizarlas" if gordo else ""))
    if aplicar:
        for key, contenido, ct, peso in pendientes:
            if not cliente.existe(key):     # la misma placa nunca se sube dos veces
                cliente.subir(key, contenido, ct, {"espacio": espacio, "pieza": fila["id"]})
        # Una sola escritura a Notion por fila, con las N URLs ya resueltas.
        escribir(fila["id"], {P["imagen"]: p_url(nueva)}, cover=portada(fila, finales[0], cdn))
    return nueva


def portada(fila, url, cdn):
    """La placa tambien se pone de portada de la pagina, y por eso se ve grande al abrirla y en
    las vistas de galeria. Va como portada y NO como bloque en el cuerpo a proposito: la seccion 6
    manda que en el cuerpo no vaya nada que no se publique, y la portada es metadato de la pagina,
    asi que el texto publicable sigue siendo exactamente el cuerpo.

    No se pisa una portada puesta a mano: solo se reemplaza la que ya apunta al CDN propio."""
    return url if (not fila.get("cover") or cover_propio(fila, cdn)) else None


# --------------------------------------------------------------------------- hash

def hashear(texto, due_iso, channel_id, imagen):
    """Seccion 8. Se calcula SIEMPRE con los datos de Notion, nunca con los de Buffer, y todo
    salto de linea se colapsa a UNO: Notion no distingue corte de parrafo de salto suave, asi
    que sin esto el mismo texto da hashes distintos de los dos lados."""
    plano = re.sub(r"\n+", "\n", texto).strip()
    crudo = f"{plano}|{due_iso}|{channel_id}|{imagen or ''}"
    return hashlib.sha256(crudo.encode("utf-8")).hexdigest()


# --------------------------------------------------------------------------- Buffer

Q_POSTS = """query($org:OrganizationId!,$after:String){
  posts(input:{organizationId:$org}, first:50, after:$after){
    edges{ node{ id status sentAt dueAt channelId text externalLink
      assets{ type source }
      metadata{ __typename ... on TwitterPostMetadata { threadCount } } } }
    pageInfo{ hasNextPage endCursor } } }"""

M_CREATE = """mutation($input:CreatePostInput!){ createPost(input:$input){
  __typename ... on PostActionSuccess { post { id } }
  ... on InvalidInputError { message } ... on LimitReachedError { message }
  ... on UnauthorizedError { message } ... on NotFoundError { message }
  ... on RestProxyError { message } ... on UnexpectedError { message } } }"""

M_EDIT = """mutation($input:EditPostInput!){ editPost(input:$input){
  __typename ... on PostActionSuccess { post { id } }
  ... on InvalidInputError { message } ... on LimitReachedError { message }
  ... on UnauthorizedError { message } ... on NotFoundError { message }
  ... on RestProxyError { message } ... on UnexpectedError { message } } }"""

M_DELETE = """mutation($input:DeletePostInput!){ deletePost(input:$input){
  __typename ... on DeletePostSuccess { id } ... on VoidMutationError { message } } }"""


def posts_buffer(key, org):
    """Pagina hasta hasNextPage:false. Sin esto devuelve 10 y PARECE la cola completa, justo
    porque 10 coincide con el tope por canal. Ya produjo un reporte falso el 2026-07-28."""
    out, after = [], None
    while True:
        d = buffer_gql(key, Q_POSTS, {"org": org, "after": after})["posts"]
        out += [e["node"] for e in d["edges"]]
        if not d["pageInfo"]["hasNextPage"]:
            break
        after = d["pageInfo"]["endCursor"]
    return {p["id"]: p for p in out}


def assets_img(imagen, texto):
    """Un asset por imagen, EN ORDEN. `imagen` trae N URLs separadas por espacio.

    Forma verificada por introspeccion (2026-08-06): ImageAssetInput es {url, thumbnailUrl,
    metadata}, y `altText` vive DENTRO de ImageMetadataInput, no al lado de `url`. Mandarlo
    plano es un InvalidInputError.

    Que Buffer acepte varios y RESPETE EL ORDEN esta `[CONFIRMADO]` 2026-08-26 contra la API,
    con un borrador real de 3 imagenes que se creo, se releyo y se borro. El schema ya declaraba
    `assets` como lista, pero una ruta que nunca se ejecuto no esta verificada."""
    lista = urls(imagen)
    if not lista:
        return []
    n = len(lista)
    alt = texto[:100]
    return [{"image": {"url": u, "metadata": {
                "altText": alt if n == 1 else f"{alt} ({i} de {n})"}}}
            for i, u in enumerate(lista, 1)]


def thread_x(tramos):
    """`thread` es una lista de ThreadedPostInput {text, assets}, NO una lista de strings, y
    `assets` es obligatorio en cada tramo. Verificado por introspeccion (2026-08-06)."""
    return [{"text": t, "assets": []} for t in tramos]


def payload_crear(canal, cid, texto, tramos, due_iso, imagen):
    inp = {"channelId": cid, "text": texto, "mode": "customScheduled",
           "dueAt": due_iso, "schedulingType": "automatic", "needsApproval": False,
           "assets": assets_img(imagen, texto)}
    if canal == "Facebook":
        inp["metadata"] = {"facebook": {"type": "post"}}          # sin esto rechaza todo
    if canal == "X" and len(tramos) > 1:
        inp["text"] = tramos[0]                                    # el text exterior = primer tramo
        inp["metadata"] = {"twitter": {"thread": thread_x(tramos)}}
    return inp


# --------------------------------------------------------------------------- rutina

def correr(espacio, aplicar, log):
    cfg = ESPACIOS[espacio]
    key = leer_credencial(ruta(cfg["credencial"]), f"Buffer para «{espacio}»", "paso 1")
    canales, slots = cfg["canales"], leer_slots(cfg.get("slots"))
    # El almacenamiento es opcional: sin `almacenamiento` en el config o sin `cdn` en el espacio,
    # el sync corre exactamente como antes y la propiedad `Imagen` sigue siendo manual.
    cdn = cfg.get("cdn")
    cliente = PROVEEDORES[PROVEEDOR](ALM) if (ALM and cdn) else None
    inv = {v: k for k, v in canales.items()}
    ahora = datetime.now(AR)

    # ---- paso 1: leer los dos lados
    posts = posts_buffer(key, cfg["organizacion"])
    mios = {i: p for i, p in posts.items() if p["channelId"] in inv}
    filas = filas_notion(espacio, canales)

    n = dict(programadas=0, actualizadas=0, publicadas=0, canceladas=0, desalojadas=0)
    errores, esperando, huerfanos = [], [], []
    # Un aviso NO es un error: la fila se procesa igual y el codigo de salida sigue siendo 0.
    # Van separados porque mezclarlos haria que la rutina programada muestre en rojo una corrida
    # que salio bien, y una alarma que suena sin motivo es la que hace que nadie mire el log.
    avisos = []

    # ---- paso 2: reconciliacion. Un post sin fila NO se borra: se reporta y se deja.
    conocidos = {prop_txt(f["properties"].get(P["post_id"])) for f in filas}
    for i, p in mios.items():
        if p["status"] == "scheduled" and i not in conocidos:
            huerfanos.append(f'{inv[p["channelId"]]} {p.get("dueAt","")} {(p.get("text") or "")[:60]}')

    agendados = {c: sum(1 for p in mios.values()
                        if p["channelId"] == cid and p["status"] == "scheduled")
                 for c, cid in canales.items()}
    ocupados = {c: set() for c in canales}
    for p in mios.values():
        if p["status"] == "scheduled" and p.get("dueAt"):
            ocupados[inv[p["channelId"]]].add(
                datetime.fromisoformat(p["dueAt"].replace("Z", "+00:00")).astimezone(AR))

    # Posts scheduled gestionados (tienen fila Aprobado sana en Notion y siguen scheduled tras
    # el pase 1). Sirven para desalojar el mas lejano en (e) cuando el cupo esta lleno y entra
    # una pieza con fecha estrictamente anterior. NUNCA incluye huerfanos ni publicados.
    gestionados = {c: {} for c in canales}   # canal -> {bpid: (due_actual, fila, nombre)}
    por_crear = []

    # ---- paso 3a: procesar primero todas las filas con post existente o terminales (a, b, c, d),
    # para que cancelaciones y reprogramaciones actualicen cupo, huecos ocupados y fechas reales
    # ANTES de procesar (e) creacion (sin depender de si la cancelada tenia fecha mas lejana).
    for f in sorted(filas, key=lambda f: prop_txt(f["properties"].get(P["fecha"])) or "9"):
        pr = f["properties"]
        nombre = prop_txt(pr.get(P["titulo"]))[:50]
        estado = prop_txt(pr.get(P["estado"]))
        canal = prop_txt(pr.get(P["canal"]))
        bpid = prop_txt(pr.get(P["post_id"]))
        cid = canales.get(canal)
        try:
            post = mios.get(bpid) if bpid else None

            # (a) terminal: una fila Publicado no se toca nunca. Si ademas apunta a un post que
            #     Buffer no da por enviado, es una inconsistencia: se reporta y NO se actua.
            if estado == EST["publicado"]:
                if post is not None and not post.get("sentAt"):
                    errores.append(f"{nombre}: esta en {EST['publicado']} pero su post sigue "
                                   f"{post['status']} en Buffer")
                continue

            if bpid and post is None:
                errores.append(f"{nombre}: Buffer Post ID {bpid} no existe en Buffer")
                continue

            # (b) ya salio. Va antes que cancelacion y actualizacion: un post publicado
            #     es intocable pase lo que pase con el dropdown.
            if post and post.get("sentAt"):
                log(f"  publicada   {canal:9} {nombre}")
                if aplicar:
                    escribir(f["id"], {P["estado"]: p_sel(EST["publicado"]),
                                       P["url"]: p_url(post.get("externalLink")),
                                       P["fecha"]: p_date(post["sentAt"]),
                                       P["last_sync"]: p_date(ahora.isoformat())})
                n["publicadas"] += 1
                continue

            # (c) cancelacion. La condicion 'scheduled' no es un detalle: sin ella
            #     esta regla borra borradores, que por definicion no estan aprobados.
            if post and estado != EST["aprobado"] and post["status"] == "scheduled":
                log(f"  cancelada   {canal:9} {nombre}")
                if aplicar:
                    rd = buffer_gql(key, M_DELETE, {"input": {"id": bpid}})["deletePost"]
                    if rd["__typename"] != "DeletePostSuccess":
                        raise RuntimeError(rd.get("message", rd["__typename"]))
                    escribir(f["id"], {P["post_id"]: p_text(""), P["hash"]: p_text(""),
                                       P["last_sync"]: p_date(ahora.isoformat())})
                # el lugar queda libre EN ESTA corrida y antes de (e), sin depender del orden
                # de fechas entre la cancelada y las piezas nuevas
                canal_post = inv[post["channelId"]]
                agendados[canal_post] -= 1
                if post.get("dueAt"):
                    ocupados[canal_post].discard(
                        datetime.fromisoformat(post["dueAt"].replace("Z", "+00:00")).astimezone(AR))
                n["canceladas"] += 1
                continue

            if estado != EST["aprobado"]:
                continue

            # Sin post existente: queda para el paso 3b ((e) creacion).
            if not post:
                por_crear.append(f)
                continue

            texto, tramos = cuerpo(f["id"])
            if not texto:
                errores.append(f"{nombre}: el cuerpo esta vacio, no se publica")
                continue
            imagen = prop_txt(pr.get(P["imagen"]))
            fecha = prop_txt(pr.get(P["fecha"]))

            # paso 0 (seccion 9): resolver la placa ANTES de hashear. La URL entra al hash, asi
            # que una placa nueva o cambiada dispara sola la actualizacion en Buffer.
            if cliente:
                imagen = materializar(f, pr, imagen, cliente, cdn, espacio, aplicar, log,
                                      nombre, canal, avisos)

            # longitud: nunca cortar, resumir ni reescribir
            if canal == "X" and len(tramos) > 1:
                largo = [t for t in tramos if len(t) > LIMITE.get("X", 10**9)]
                if largo:
                    errores.append(f"{nombre}: {len(largo)} tramo(s) de X pasan "
                                   f"{LIMITE.get('X')}")
                    continue
            elif len(texto) > LIMITE.get(canal, 10**9):
                errores.append(f"{nombre}: {len(texto)} caracteres, pasa el limite de {canal}")
                continue

            # (d) actualizacion.
            #
            # El hash vigila CUATRO cosas (texto, fecha, canal, imagen) y una edicion no puede
            # aplicarlas todas. Lo que no se pueda aplicar se reporta y NO se guarda el hash:
            # guardarlo dejaria la fila marcada como sincronizada mintiendo, y eso no vuelve a
            # avisar nunca mas.
            if not post.get("dueAt"):
                errores.append(f"{nombre}: su post esta {post['status']} y sin fecha en Buffer")
                continue

            due = datetime.fromisoformat(post["dueAt"].replace("Z", "+00:00")).astimezone(AR)
            due_notion = parsear_fecha(fecha, canal, slots) if fecha else due
            h = hashear(texto, due_notion.isoformat(), cid, imagen)

            # Un post solo puede ser desalojado en (e) si esta scheduled en el mismo canal,
            # sigue sano y no depende de una placa privada cargada a mano en Buffer S3.
            asset_ajeno_sin_notion = (
                not imagen and any(
                    a.get("type") == "image"
                    and any(hj in (a.get("source") or "") for hj in HOSTS_AJENOS)
                    for a in (post.get("assets") or [])
                )
            )
            elegible_desalojo = (
                post["status"] == "scheduled"
                and post["channelId"] == cid
                and not asset_ajeno_sin_notion
            )

            if h == prop_txt(pr.get(P["hash"])):
                if elegible_desalojo:
                    gestionados[canal][bpid] = (due, f, nombre)
                continue

            # De aca en adelante hay algo que aplicar, y recien aca corresponde preguntarse
            # si se puede. Estos chequeos van DESPUES de comparar el hash a proposito: antes,
            # le gritaban todos los dias a 4 piezas que estaban perfectamente sincronizadas,
            # y una alarma que suena siempre es peor que no tener alarma.
            if post["channelId"] != cid:
                errores.append(f"{nombre}: la fila dice {canal} y el post esta en otro canal. "
                               f"Buffer no puede mover un post de canal: sacala de "
                               f"{EST['aprobado']} para que se cancele, y volve a aprobarla.")
                continue
            # Notion no declara imagen pero el post tiene una. Si la subio una persona por la
            # app web vive en buffer-media-uploads y hay que preservarla (omitir `assets` lo hace);
            # si apunta a un dominio propio la puso este sync desde Notion, asi que la sacaron
            # de la fila y esta edicion no puede borrarla. Solo ese caso se reporta.
            if not imagen and any(a.get("type") == "image"
                                  and not any(hj in (a.get("source") or "")
                                              for hj in HOSTS_AJENOS)
                                  for a in (post.get("assets") or [])):
                errores.append(f"{nombre}: la fila ya no declara `Imagen` pero el post tiene "
                               f"la placa puesta por el sync, y una edicion no puede quitarla. "
                               f"Cancelala y volve a aprobarla.")
                continue

            cambio_fecha = due_notion != due
            if cambio_fecha and due_notion <= ahora:
                errores.append(f"{nombre}: fecha {due_notion:%Y-%m-%d %H:%M} ya paso, vencida")
                continue

            log(f"  actualizada {canal:9} {nombre}" + ("  (+reprograma)" if cambio_fecha else ""))
            if aplicar:
                inp = {"id": bpid, "text": texto}   # el text va SIEMPRE: si se omite, falla
                if cambio_fecha:                    # mandar mode reprograma aunque no cambie
                    inp["mode"] = "customScheduled"
                    inp["dueAt"] = due_notion.isoformat()
                if imagen:
                    # solo cuando Notion la declara: omitir `assets` preserva la que haya
                    # (verificado, seccion 14), asi que mandarlo vacio la borraria
                    inp["assets"] = assets_img(imagen, texto)
                if canal == "Facebook":
                    # Facebook exige `type` tambien AL EDITAR, no solo al crear.
                    # `[CONFIRMADO]` 2026-08-07: sin esto la edicion vuelve con
                    # "Invalid post: Facebook posts require a type (post, story, or reel)".
                    # No se habia ejercitado nunca porque las pruebas de edicion del
                    # 2026-08-06 fueron todas sobre X.
                    inp["metadata"] = {"facebook": {"type": "post"}}
                era_hilo = ((post.get("metadata") or {}).get("threadCount") or 0) > 1
                if canal == "X" and (len(tramos) > 1 or era_hilo):
                    # el text exterior es el primer tramo, igual que al crear. Y si dejo de
                    # ser hilo hay que mandar el thread igual, de un solo tramo: omitir
                    # metadata PRESERVA los tramos viejos en vez de borrarlos.
                    inp["text"] = tramos[0]
                    inp["metadata"] = {"twitter": {"thread": thread_x(tramos)}}
                r = buffer_gql(key, M_EDIT, {"input": inp})["editPost"]
                if r["__typename"] != "PostActionSuccess":
                    raise RuntimeError(r.get("message", r["__typename"]))
                upd = {P["hash"]: p_text(h), P["last_sync"]: p_date(ahora.isoformat())}
                if fecha and len(fecha.strip()) == 10:
                    # Si la fecha vino sin hora, guardamos el timestamp resuelto para que Notion
                    # muestre la hora real y un cambio futuro de slots no reprograme lo agendado.
                    upd[P["fecha"]] = p_date(due_notion.isoformat())
                escribir(f["id"], upd)
            if cambio_fecha and post["status"] == "scheduled":
                ocupados[canal].discard(due)
                ocupados[canal].add(due_notion)
            if elegible_desalojo:
                gestionados[canal][bpid] = (due_notion if cambio_fecha else due, f, nombre)
            n["actualizadas"] += 1

        except Exception as e:                          # un error no frena el sync entero
            errores.append(f"{nombre}: {e}")

    # ---- paso 3b: (e) creacion, por fecha ascendente.
    # Si el cupo esta lleno (agendados == CUPO) pero la pieza nueva tiene fecha estrictamente
    # anterior al post scheduled gestionado mas lejano del mismo canal, se desaloja ese post
    # (vuelve a esperar cupo en Notion) para que entre la pieza mas cercana.
    for f in sorted(por_crear, key=lambda f: _orden_creacion(f, slots)):
        pr = f["properties"]
        nombre = prop_txt(pr.get(P["titulo"]))[:50]
        canal = prop_txt(pr.get(P["canal"]))
        cid = canales.get(canal)
        try:
            fecha = prop_txt(pr.get(P["fecha"]))
            if fecha:
                due_notion = parsear_fecha(fecha, canal, slots)
            else:
                due_notion = proximo_hueco(slots, canal, ocupados[canal], ahora)
            if due_notion <= ahora:
                errores.append(f"{nombre}: fecha {due_notion:%Y-%m-%d %H:%M} ya paso, vencida")
                continue

            # Chequear cupo ANTES de leer el cuerpo o materializar placas: con 200+ piezas
            # aprobadas en cola futura, leer blocks/children para piezas que no pueden entrar hoy
            # dispara HTTP 429 en Notion y sube placas meses antes de tiempo.
            desalojable = None
            if agendados[canal] >= CUPO:
                if agendados[canal] == CUPO and gestionados[canal]:
                    v_bpid, (v_due, v_fila, v_nombre) = max(
                        gestionados[canal].items(), key=lambda kv: kv[1][0]
                    )
                    if due_notion < v_due:
                        desalojable = (v_bpid, v_due, v_fila, v_nombre)
                if not desalojable:
                    esperando.append(f"{canal} · {nombre}")
                    continue

            texto, tramos = cuerpo(f["id"])
            if not texto:
                errores.append(f"{nombre}: el cuerpo esta vacio, no se publica")
                continue
            imagen = prop_txt(pr.get(P["imagen"]))

            # paso 0 (seccion 9): resolver la placa ANTES de hashear.
            if cliente:
                imagen = materializar(f, pr, imagen, cliente, cdn, espacio, aplicar, log,
                                      nombre, canal, avisos)

            # longitud: nunca cortar, resumir ni reescribir
            if canal == "X" and len(tramos) > 1:
                largo = [t for t in tramos if len(t) > LIMITE.get("X", 10**9)]
                if largo:
                    errores.append(f"{nombre}: {len(largo)} tramo(s) de X pasan "
                                   f"{LIMITE.get('X')}")
                    continue
            elif len(texto) > LIMITE.get(canal, 10**9):
                errores.append(f"{nombre}: {len(texto)} caracteres, pasa el limite de {canal}")
                continue

            if desalojable:
                v_bpid, v_due, v_fila, v_nombre = desalojable
                log(f"  desalojada  {canal:9} {v_nombre} (entra mas cercana)")
                if aplicar:
                    rd = buffer_gql(key, M_DELETE, {"input": {"id": v_bpid}})["deletePost"]
                    if rd["__typename"] != "DeletePostSuccess":
                        raise RuntimeError(rd.get("message", rd["__typename"]))
                    upd_v = {P["post_id"]: p_text(""), P["hash"]: p_text(""),
                             P["last_sync"]: p_date(ahora.isoformat())}
                    if not prop_txt(v_fila["properties"].get(P["fecha"])):
                        upd_v[P["fecha"]] = p_date(v_due.isoformat())
                    escribir(v_fila["id"], upd_v)
                agendados[canal] -= 1
                ocupados[canal].discard(v_due)
                del gestionados[canal][v_bpid]
                esperando.append(f"{canal} · {v_nombre}")
                n["desalojadas"] += 1

            log(f"  programada  {canal:9} {due_notion:%d/%m %H:%M}  {nombre}")
            if aplicar:
                inp = payload_crear(canal, cid, texto, tramos, due_notion.isoformat(), imagen)
                r = buffer_gql(key, M_CREATE, {"input": inp})["createPost"]
                if r["__typename"] != "PostActionSuccess":
                    raise RuntimeError(r.get("message", r["__typename"]))
                nuevo = r["post"]["id"]
                escribir(f["id"], {
                    P["post_id"]: p_text(nuevo),
                    P["hash"]: p_text(hashear(texto, due_notion.isoformat(), cid, imagen)),
                    P["fecha"]: p_date(due_notion.isoformat()),
                    P["last_sync"]: p_date(ahora.isoformat())})
            agendados[canal] += 1
            ocupados[canal].add(due_notion)
            n["programadas"] += 1

        except Exception as e:                          # un error no frena el sync entero
            errores.append(f"{nombre}: {e}")

    log("  cupo: " + " · ".join(f"{c} {agendados[c]}/{CUPO}" for c in canales))
    return n, errores, esperando, huerfanos, avisos


# Corriendo desatendido el log es lo unico que queda de una corrida, asi que su ruta es un dato
# de instalacion y va al config. El default no lleva el nombre de ninguna marca adentro.
LOG = ruta(CFG.get("log", "~/.sync_notion_buffer/sync.log"))


def main():
    aplicar = "--apply" in sys.argv
    solo = None
    for bandera in ("--espacio", "--marca"):            # --marca se mantiene por compatibilidad
        if bandera in sys.argv:
            solo = sys.argv[sys.argv.index(bandera) + 1]
            break
    if solo and solo not in ESPACIOS:
        sys.stderr.write(f"espacio desconocido: {solo!r}. Declarados: {', '.join(ESPACIOS)}\n")
        return 2

    # Corriendo sin nadie mirando, lo unico que queda de una corrida es el log. Se escribe
    # siempre, tambien en seco, y el codigo de salida es lo que hace que el programador de
    # tareas muestre la corrida en rojo en vez de en verde con errores adentro.
    LOG.parent.mkdir(parents=True, exist_ok=True)
    lineas = []

    def print(*a):                                      # noqa: A001 - deliberado
        t = " ".join(str(x) for x in a)
        lineas.append(t)
        sys.stdout.write(t + "\n")

    print(f"Sync {datetime.now(AR):%d/%m %H:%M} - modo {'REAL' if aplicar else 'SECO (no escribe nada)'}")
    total = dict(programadas=0, actualizadas=0, publicadas=0, canceladas=0, desalojadas=0)
    errores, esperando, huerfanos, avisos = [], [], [], []
    cortadas = 0

    for espacio in ESPACIOS:
        if solo and espacio != solo:
            continue
        print(f"\n{espacio}")
        try:
            n, e, w, h, av = correr(espacio, aplicar, print)
        except Exception as exc:                        # no se puede conectar: cortar sin tocar nada
            print(f"  CORTADO: {exc}")
            errores.append(f"{espacio}: {exc}")
            cortadas += 1
            continue
        for k in total:
            total[k] += n[k]
        errores += [f"{espacio} · {x}" for x in e]
        esperando += [f"{espacio} · {x}" for x in w]
        huerfanos += [f"{espacio} · {x}" for x in h]
        avisos += [f"{espacio} · {x}" for x in av]

    extra_des = f", {total['desalojadas']} desalojadas" if total["desalojadas"] else ""
    print(f"\nSync {datetime.now(AR):%d/%m %H:%M} - {total['programadas']} programadas, "
          f"{total['actualizadas']} actualizadas, {total['publicadas']} publicadas, "
          f"{total['canceladas']} canceladas{extra_des}. "
          + ("Sin errores." if not errores else f"{len(errores)} error(es)."))
    for x in errores:   print(f"  error:    {x}")
    for x in avisos:    print(f"  aviso:    {x}")
    for x in esperando: print(f"  esperando cupo: {x}")
    for x in huerfanos: print(f"  huerfano (no se toca): {x}")

    with LOG.open("a", encoding="utf-8") as fh:
        fh.write("\n".join(lineas) + "\n" + "-" * 70 + "\n")

    # 0 = todo bien · 1 = corrio pero algo pide un humano · 2 = un espacio no pudo correr
    if cortadas:
        return 2
    return 1 if (errores or huerfanos) else 0


if __name__ == "__main__":
    sys.exit(main())
