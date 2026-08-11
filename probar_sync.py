# probar_sync.py - Banco de pruebas de sync_notion_buffer.py.
#
#   python probar_sync.py        # sale 0 si pasa todo, 1 si algo falla
#
# NO toca Buffer ni Notion: reemplaza las lecturas por datos sinteticos y captura los payloads
# que se MANDARIAN, corriendo la rutina real con aplicar=True.
#
# Por que existe: las rutas de imagen, hilo y canal NO se pueden ejercitar contra Buffer sin
# publicar de verdad, asi que las corridas de prueba en vivo no las tocan. Escrito el 2026-08-06,
# encontro dos defectos el mismo dia (el `post` sin definir tras un reordenamiento, y un chequeo
# nuevo que gritaba sobre 4 piezas sanas). Correrlo despues de tocar el sync.
#
# El caso 8 es un CONTROL NEGATIVO: si el hash coincide no puede pasar nada. Sin el, un banco
# que solo comprueba que no pasa nada malo pasaria igual con el sync entero comentado.
import sys, json, pathlib

sys.path.insert(0, str(pathlib.Path(__file__).parent))
import sync_notion_buffer as m

# Se toma el primer espacio del config y sus dos primeros canales: el banco no depende de una
# instalacion concreta, igual que el motor.
ESPACIO = next(iter(m.ESPACIOS))
_canales = m.ESPACIOS[ESPACIO]["canales"]
CID_X = _canales.get("X") or list(_canales.values())[0]
CID_LI = _canales.get("LinkedIn") or list(_canales.values())[-1]
# Si el config todavia tiene el mismo texto de relleno en dos canales, los ids son iguales y el
# caso 4 -que prueba que un cambio de canal se detecta- no puede distinguir nada. Se dice en vez
# de reportar tres FALLA sobre un motor sano.
DOS_CANALES = CID_X != CID_LI
P, EST = m.P, m.EST
FUT = "2026-09-15T10:50:00-03:00"
S3 = [{"type": "image", "source": "https://buffer-media-uploads.s3.amazonaws.com/x_linkedin"}]
PROPIA = [{"type": "image", "source": "https://cdn.ejemplo.com/placas/vieja.png"}]


def fila(nombre, estado, canal, bpid="", h="", fecha="", imagen=""):
    return {"id": "pg-" + nombre, "properties": {
        P["titulo"]:  {"type": "title", "title": [{"plain_text": nombre}]},
        P["estado"]:  {"type": "select", "select": {"name": estado}},
        P["canal"]:   {"type": "select", "select": {"name": canal}},
        P["post_id"]: {"type": "rich_text", "rich_text": [{"plain_text": bpid}] if bpid else []},
        P["hash"]:    {"type": "rich_text", "rich_text": [{"plain_text": h}] if h else []},
        P["fecha"]:   {"type": "date", "date": {"start": fecha} if fecha else None},
        P["imagen"]:  {"type": "url", "url": imagen or None}}}


def post(pid, cid, due, status="scheduled", sent=None, assets=None, thread=0):
    return {"id": pid, "status": status, "sentAt": sent, "dueAt": due, "channelId": cid,
            "text": "loquesea", "externalLink": None, "assets": assets or [],
            "metadata": {"threadCount": thread} if thread else None}


def correr(filas, posts, cuerpos):
    """Corre la rutina real con aplicar=True, interceptando toda escritura."""
    env = {"gql": [], "notion": []}
    # Tambien se reemplaza la lectura de la credencial: sin esto el banco no corre en una
    # instalacion recien bajada -que es justo donde mas importa que corra- y muere con un
    # traceback de archivo no encontrado, que se lee como "el paquete esta roto".
    m.leer_credencial = lambda *a, **k: "clave-de-prueba"
    m.posts_buffer = lambda k, o: posts
    m.filas_notion = lambda ma, c: filas
    m.cuerpo = lambda pid: cuerpos[pid]
    m.escribir = lambda pid, props: env["notion"].append((pid, props))

    def gql(key, q, v=None):
        env["gql"].append(v)
        exito = {"__typename": "PostActionSuccess", "post": {"id": "nuevo"}}
        return {"editPost": exito, "createPost": exito,
                "deletePost": {"__typename": "DeletePostSuccess", "id": "x"}}

    m.buffer_gql = gql
    n, err, esp, hue = m.correr(ESPACIO, True, lambda *a: None)
    return env, n, err


ok = fallo = 0


def chequear(titulo, cond, detalle=""):
    global ok, fallo
    print(("  OK   " if cond else "  FALLA") + f" {titulo}" + (f"  <- {detalle}" if not cond else ""))
    if cond:
        ok += 1
    else:
        fallo += 1


print("\n1. Hilo de X actualizado (mandaba el hilo entero como un solo tweet)")
tramos = ["tramo uno", "tramo dos", "tramo tres"]
env, *_ = correr([fila("hilo", EST["aprobado"], "X", bpid="p1", h="viejo", fecha=FUT)],
                 {"p1": post("p1", CID_X, FUT, thread=3)},
                 {"pg-hilo": ("\n\n".join(tramos), tramos)})
inp = env["gql"][0]["input"] if env["gql"] else {}
chequear("manda el thread como objetos {text, assets}",
         inp.get("metadata", {}).get("twitter", {}).get("thread") ==
         [{"text": t, "assets": []} for t in tramos], json.dumps(inp)[:200])
chequear("el text exterior es el primer tramo, no el hilo concatenado",
         inp.get("text") == tramos[0], repr(inp.get("text"))[:120])

print("\n2. Un hilo que deja de ser hilo se colapsa (omitir metadata preserva los tramos viejos)")
env, *_ = correr([fila("colapso", EST["aprobado"], "X", bpid="p1", h="viejo", fecha=FUT)],
                 {"p1": post("p1", CID_X, FUT, thread=3)}, {"pg-colapso": ("uno solo", ["uno solo"])})
inp = env["gql"][0]["input"] if env["gql"] else {}
chequear("manda thread de un tramo",
         inp.get("metadata", {}).get("twitter", {}).get("thread") == [{"text": "uno solo", "assets": []}],
         json.dumps(inp)[:200])

print("\n3. Imagen cambiada: se aplica, y con el altText donde va")
env, *_ = correr([fila("img", EST["aprobado"], "LinkedIn", bpid="p2", h="viejo", fecha=FUT,
                       imagen="https://cdn.ejemplo.com/placas/x.png")],
                 {"p2": post("p2", CID_LI, FUT, assets=[{"type": "image"}])},
                 {"pg-img": ("texto", ["texto"])})
inp = env["gql"][0]["input"] if env["gql"] else {}
img = inp.get("assets", [{}])[0].get("image", {})
chequear("manda assets con la URL nueva", img.get("url") == "https://cdn.ejemplo.com/placas/x.png",
         json.dumps(inp)[:200])
chequear("altText DENTRO de metadata (plano es InvalidInputError)",
         "altText" in img.get("metadata", {}), json.dumps(img)[:200])

print("\n4. Canal cambiado: se reporta y NO se finge sincronizado")
if not DOS_CANALES:
    print("  (se saltea: tu config declara el mismo id en dos canales, asi que no hay cambio de")
    print("   canal posible que probar. Corregi los ids con `python ids_buffer.py`.)")
else:
    env, n, err = correr([fila("canal", EST["aprobado"], "X", bpid="p3", h="viejo", fecha=FUT)],
                         {"p3": post("p3", CID_LI, FUT)}, {"pg-canal": ("t", ["t"])})
    chequear("reporta el error", any("canal" in e for e in err), str(err))
    chequear("no manda ninguna edicion", not env["gql"], str(env["gql"])[:150])
    chequear("NO guarda el hash (si lo guardara, no volveria a avisar)", not env["notion"],
             str(env["notion"])[:150])

print("\n5a. REGRESION: placa cargada a mano y fila sincronizada -> silencio absoluto")
txt5 = "texto sincronizado"
env, n, err = correr([fila("s3sync", EST["aprobado"], "LinkedIn", bpid="p4",
                           h=m.hashear(txt5, FUT, CID_LI, ""), fecha=FUT)],
                     {"p4": post("p4", CID_LI, FUT, assets=S3)}, {"pg-s3sync": (txt5, [txt5])})
chequear("no reporta nada (le gritaba a 4 piezas reales todos los dias)",
         not err and not env["gql"] and not env["notion"], str(err))

print("\n5b. Placa cargada a mano y texto editado -> se edita y la placa se preserva")
env, n, err = correr([fila("s3edit", EST["aprobado"], "LinkedIn", bpid="p4", h="viejo", fecha=FUT)],
                     {"p4": post("p4", CID_LI, FUT, assets=S3)}, {"pg-s3edit": ("nuevo", ["nuevo"])})
inp = env["gql"][0]["input"] if env["gql"] else {}
chequear("edita sin error", not err and env["gql"], str(err))
chequear("NO manda assets (omitirlo es lo que preserva la placa)", "assets" not in inp,
         json.dumps(inp)[:200])

print("\n5c. Placa puesta por el sync y la fila ya no la declara -> eso si se reporta")
env, n, err = correr([fila("propia", EST["aprobado"], "LinkedIn", bpid="p4", h="viejo", fecha=FUT)],
                     {"p4": post("p4", CID_LI, FUT, assets=PROPIA)}, {"pg-propia": ("t", ["t"])})
chequear("reporta y no toca nada", bool(err) and not env["gql"] and not env["notion"],
         str(err) + str(env["gql"])[:100])

print("\n5d. REGRESION: editar un post de Facebook necesita `metadata.type`")
# Encontrado en produccion el 2026-08-07: Facebook exige `type` tambien al EDITAR, no solo al
# crear, y Buffer rechazaba la edicion entera. No se habia visto nunca porque todas las pruebas
# de edicion en vivo del 2026-08-06 fueron sobre X.
CID_FB = _canales.get("Facebook")
if CID_FB:
    env, n, err = correr([fila("fbedit", EST["aprobado"], "Facebook", bpid="p9", h="viejo",
                               fecha=FUT)],
                         {"p9": post("p9", CID_FB, FUT)}, {"pg-fbedit": ("nuevo", ["nuevo"])})
    inp = env["gql"][0]["input"] if env["gql"] else {}
    chequear("edita sin error", not err and env["gql"], str(err))
    chequear("manda metadata.facebook.type",
             (inp.get("metadata") or {}).get("facebook", {}).get("type") == "post",
             json.dumps(inp)[:200])
else:
    print("  (esta instalacion no declara Facebook: se saltea)")

print("\n6. Publicado cuyo post sigue scheduled: el 11-a lo pedia y era mudo")
env, n, err = correr([fila("inconsis", EST["publicado"], "X", bpid="p5", h="h", fecha=FUT)],
                     {"p5": post("p5", CID_X, FUT)}, {"pg-inconsis": ("t", ["t"])})
chequear("lo reporta", any(EST["publicado"] in e for e in err), str(err))
chequear("y sigue sin tocar la fila", not env["gql"] and not env["notion"], str(env["notion"])[:150])

print("\n7. Creacion con imagen (nunca se ejercito: mandaba altText plano)")
env, *_ = correr([fila("nueva", EST["aprobado"], "LinkedIn", fecha=FUT, imagen="https://cdn.ejemplo.com/p.png")],
                 {}, {"pg-nueva": ("texto nuevo", ["texto nuevo"])})
inp = env["gql"][0]["input"] if env["gql"] else {}
chequear("altText dentro de metadata",
         inp.get("assets", [{}])[0].get("image", {}).get("metadata", {}).get("altText") == "texto nuevo",
         json.dumps(inp.get("assets"))[:200])

print("\n8. CONTROL NEGATIVO: si el hash coincide, no puede pasar nada")
t8 = "texto igual"
env, n, err = correr([fila("igual", EST["aprobado"], "LinkedIn", bpid="p6",
                           h=m.hashear(t8, FUT, CID_LI, ""), fecha=FUT)],
                     {"p6": post("p6", CID_LI, FUT)}, {"pg-igual": (t8, [t8])})
chequear("cero llamadas y cero escrituras", not env["gql"] and not env["notion"] and not err,
         str(env)[:150])

print(f"\n{ok} OK, {fallo} FALLA")
sys.exit(1 if fallo else 0)
