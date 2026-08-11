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

import json, sys, hashlib, re, pathlib, urllib.request, urllib.error
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
    fallo. Desatendido, el log es lo unico que queda."""
    try:
        return json.loads(urllib.request.urlopen(req, timeout=TIMEOUT).read())
    except urllib.error.HTTPError as e:
        detalle = ""
        try:
            detalle = e.read().decode("utf-8", "replace")[:400]
        except Exception:
            pass
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


def prop_placa(p):
    """URL de descarga del primer adjunto de una propiedad de tipo `files`.

    Notion devuelve dos formas: 'file' es un archivo subido a Notion, y su URL esta FIRMADA y
    expira en el orden de una hora -por eso hay que bajarla ahora y no guardarla-; 'external' es
    un archivo enlazado desde afuera."""
    if not p or p.get("type") != "files":
        return ""
    for f in p["files"] or []:
        if f.get("type") == "file":
            return (f.get("file") or {}).get("url", "")
        if f.get("type") == "external":
            return (f.get("external") or {}).get("url", "")
    return ""


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

def materializar(fila, pr, imagen, cliente, cdn, espacio, aplicar, log, nombre):
    """Paso 0 de la seccion 9: la placa que se arrastro a Notion se sube al bucket y su URL
    publica queda escrita en `imagen`.

    El reparto es: `placa` (adjunto) es la superficie humana y la unica que se toca a mano; el
    bucket es donde Buffer puede leerla el dia que publica; `imagen` es el puente y la escribe
    la maquina. Devuelve la imagen que corresponde usar en esta corrida, para que el hash de la
    seccion 8 y el payload la vean ya resuelta.
    """
    origen = prop_placa(pr.get(P["placa"]))

    if not origen:
        # No hay adjunto. Si `imagen` apunta al CDN propio, la placa estuvo y se la sacaron: se
        # limpia para que la regla (d) pueda avisar que una edicion no puede dejar un post sin
        # placa. Si es una URL cargada a mano, se respeta y no se toca: es el caso de las piezas
        # cuya placa se subio por la app web.
        if imagen and imagen.startswith(cdn):
            log(f"  placa quitada  {nombre}")
            if aplicar:
                escribir(fila["id"], {P["imagen"]: p_url("")})
            return ""
        return imagen

    # La placa apunta a un host que no es de este sync: lo tipico es una URL del S3 de Buffer,
    # que la app web usa para las placas que se suben desde ahi. NO se materializa, y no es una
    # preferencia: `[CONFIRMADO]` 2026-08-07 esas URLs son PRIVADAS (S3 responde AccessDenied),
    # asi que no se pueden descargar para subirlas ni sirven adjuntadas en Notion. Intentarlo
    # daria un error por fila en cada corrida. Se devuelve `imagen` intacta para no mover el hash.
    if any(h in origen for h in HOSTS_AJENOS):
        return imagen

    # Ya apunta al CDN propio: es la URL final, no hay nada que descargar ni subir. Pasa cuando
    # la placa se adjunto como archivo externo, y ahorra una descarga por fila en cada corrida.
    if origen.startswith(cdn):
        if origen != imagen:
            log(f"  placa       {nombre}  (ya en el CDN)")
            if aplicar:
                escribir(fila["id"], {P["imagen"]: p_url(origen)}, cover=portada(fila, origen, cdn))
        return origen

    url, key, contenido, ct, peso = almacenamiento.analizar(cliente, origen, cdn)
    if url == imagen:
        return imagen                       # ya materializada: no se toca R2 ni para preguntar

    # Aviso, no bloqueo. El sync NO comprime a proposito: la clave es el hash del contenido, asi
    # que si comprimiera, la clave dependeria del resultado de la compresion y el dia que cambiara
    # la libreria o un parametro se re-subirian TODAS las placas y se editarian TODOS los posts.
    # Optimizar es del lado del diseno, donde se ve el resultado.
    gordo = peso > ALM.get("aviso_peso_mb", 1) * 1024 * 1024
    log(f"  placa       {nombre}  ({peso // 1024} KB)" + ("  conviene optimizarla" if gordo else ""))
    if aplicar:
        if not cliente.existe(key):         # la misma placa nunca se sube dos veces
            cliente.subir(key, contenido, ct, {"espacio": espacio, "pieza": fila["id"]})
        escribir(fila["id"], {P["imagen"]: p_url(url)}, cover=portada(fila, url, cdn))
    return url


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
    """Forma verificada por introspeccion (2026-08-06): ImageAssetInput es {url, thumbnailUrl,
    metadata}, y `altText` vive DENTRO de ImageMetadataInput, no al lado de `url`. Mandarlo
    plano es un InvalidInputError."""
    if not imagen:
        return []
    return [{"image": {"url": imagen, "metadata": {"altText": texto[:100]}}}]


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

    n = dict(programadas=0, actualizadas=0, publicadas=0, canceladas=0)
    errores, esperando, huerfanos = [], [], []

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

    # ---- paso 3: procesar cada fila, primer caso que coincide
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
                    buffer_gql(key, M_DELETE, {"input": {"id": bpid}})
                    escribir(f["id"], {P["post_id"]: p_text(""), P["hash"]: p_text(""),
                                       P["last_sync"]: p_date(ahora.isoformat())})
                # el lugar queda libre EN ESTA corrida: sin esto, una pieza que espera cupo
                # se reporta como esperando aunque el hueco acabe de abrirse
                agendados[canal] -= 1
                if post.get("dueAt"):
                    ocupados[canal].discard(
                        datetime.fromisoformat(post["dueAt"].replace("Z", "+00:00")).astimezone(AR))
                n["canceladas"] += 1
                continue

            if estado != EST["aprobado"]:
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
                imagen = materializar(f, pr, imagen, cliente, cdn, espacio, aplicar, log, nombre)

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
            if post:
                if not post.get("dueAt"):
                    errores.append(f"{nombre}: su post esta {post['status']} y sin fecha en Buffer")
                    continue

                due = datetime.fromisoformat(post["dueAt"].replace("Z", "+00:00")).astimezone(AR)
                due_notion = (datetime.fromisoformat(fecha.replace("Z", "+00:00")).astimezone(AR)
                              if fecha else due)
                h = hashear(texto, due_notion.isoformat(), cid, imagen)
                if h == prop_txt(pr.get(P["hash"])):
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
                                      and not any(h in (a.get("source") or "")
                                                  for h in HOSTS_AJENOS)
                                      for a in (post.get("assets") or [])):
                    errores.append(f"{nombre}: la fila ya no declara `Imagen` pero el post tiene "
                                   f"la placa puesta por el sync, y una edicion no puede quitarla. "
                                   f"Cancelala y volve a aprobarla.")
                    continue

                cambio_fecha = due_notion != due
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
                    escribir(f["id"], {P["hash"]: p_text(h),
                                       P["last_sync"]: p_date(ahora.isoformat())})
                n["actualizadas"] += 1
                continue

            # (e) creacion
            if agendados[canal] >= CUPO:
                esperando.append(f"{canal} · {nombre}")
                continue
            if fecha:
                due_notion = datetime.fromisoformat(fecha.replace("Z", "+00:00")).astimezone(AR)
                if len(fecha) == 10:                    # dia sin hora: se aplica la hora del slot
                    _, hh, mm = slots[canal]
                    due_notion = due_notion.replace(hour=hh, minute=mm)
            else:
                due_notion = proximo_hueco(slots, canal, ocupados[canal], ahora)
            if due_notion <= ahora:
                errores.append(f"{nombre}: fecha {due_notion:%Y-%m-%d %H:%M} ya paso, vencida")
                continue

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
    return n, errores, esperando, huerfanos


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
    total = dict(programadas=0, actualizadas=0, publicadas=0, canceladas=0)
    errores, esperando, huerfanos = [], [], []
    cortadas = 0

    for espacio in ESPACIOS:
        if solo and espacio != solo:
            continue
        print(f"\n{espacio}")
        try:
            n, e, w, h = correr(espacio, aplicar, print)
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

    print(f"\nSync {datetime.now(AR):%d/%m %H:%M} - {total['programadas']} programadas, "
          f"{total['actualizadas']} actualizadas, {total['publicadas']} publicadas, "
          f"{total['canceladas']} canceladas. "
          + ("Sin errores." if not errores else f"{len(errores)} error(es)."))
    for x in errores:   print(f"  error:    {x}")
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
