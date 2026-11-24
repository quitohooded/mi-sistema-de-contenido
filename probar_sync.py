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
from datetime import datetime, timedelta

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
# Una fecha futura RELATIVA a hoy, en la zona del config. Estuvo escrita como literal
# ("2026-09-15T10:50:00-03:00") y el banco empezo a fallar solo el dia que esa fecha paso: la
# creacion rechaza una fecha vencida (seccion 11-e), asi que el caso 7 dejo de crear y media un
# `null`. Se genera con `m.AR` y no con un offset escrito a mano para que su isoformat() coincida
# con el que calcula el motor, y asi los hashes de los casos 5a y 8 se cumplan en cualquier zona.
FUT = (datetime.now(m.AR) + timedelta(days=60)).replace(
    hour=10, minute=50, second=0, microsecond=0).isoformat()
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


def correr(filas, posts, cuerpos, aplicar=True):
    """Corre la rutina real, interceptando toda escritura."""
    env = {"gql": [], "ops": [], "notion": [], "logs": [], "esp": [], "hue": []}
    # Tambien se reemplaza la lectura de la credencial: sin esto el banco no corre en una
    # instalacion recien bajada -que es justo donde mas importa que corra- y muere con un
    # traceback de archivo no encontrado, que se lee como "el paquete esta roto".
    m.leer_credencial = lambda *a, **k: "clave-de-prueba"
    m.posts_buffer = lambda k, o: posts
    m.filas_notion = lambda ma, c: filas
    m.cuerpo = lambda pid: cuerpos[pid]
    m.escribir = lambda pid, props, cover=None: env["notion"].append((pid, props))
    seq = [0]

    def gql(key, q, v=None):
        op = "delete" if "deletePost" in q else ("create" if "createPost" in q else "edit")
        env["gql"].append(v)
        env["ops"].append((op, v))
        seq[0] += 1
        exito = {"__typename": "PostActionSuccess", "post": {"id": f"nuevo-{seq[0]}"}}
        return {"editPost": exito, "createPost": exito,
                "deletePost": {"__typename": "DeletePostSuccess",
                               "id": (v or {}).get("input", {}).get("id", "x")}}

    m.buffer_gql = gql
    # `avisos` es la quinta lista desde el 2026-08-26: un aviso no es un error y no puede
    # cambiar el codigo de salida. Se desempaqueta explicito para que este banco falle si la
    # firma vuelve a cambiar, en vez de tragarselo con un *_.
    n, err, esp, hue, avi = m.correr(ESPACIO, aplicar, env["logs"].append)
    env["esp"] = esp
    env["hue"] = hue
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


def _fut_dia(dias, hh=10, mm=50):
    return (datetime.now(m.AR) + timedelta(days=dias)).replace(
        hour=hh, minute=mm, second=0, microsecond=0)


_slots = m.leer_slots(m.ESPACIOS[ESPACIO].get("slots"))
_canal_slot = "X" if "X" in _slots and "X" in _canales else next(iter(_slots))
_cid_slot = _canales[_canal_slot]
_, _slot_hh, _slot_mm = _slots[_canal_slot]

print("\n9. Fecha sin hora (YYYY-MM-DD) en (d) actualizacion aplica la hora del slot, no 00:00")
due_antes = _fut_dia(40, _slot_hh, _slot_mm).isoformat()
dia_nuevo = (_fut_dia(55, _slot_hh, _slot_mm)).strftime("%Y-%m-%d")
due_esperado = _fut_dia(55, _slot_hh, _slot_mm).isoformat()
env, n, err = correr(
    [fila("sinhora", EST["aprobado"], _canal_slot, bpid="p90",
          h=m.hashear("texto", due_antes, _cid_slot, ""), fecha=dia_nuevo)],
    {"p90": post("p90", _cid_slot, due_antes)},
    {"pg-sinhora": ("texto", ["texto"])},
)
inp9 = env["gql"][0]["input"] if env["gql"] else {}
props9 = env["notion"][0][1] if env["notion"] else {}
chequear("reprograma sin error", not err and len(env["ops"]) == 1 and env["ops"][0][0] == "edit",
         f"err={err} ops={env['ops']}")
chequear("dueAt enviado lleva la hora del slot (no 00:00)",
         inp9.get("dueAt") == due_esperado and inp9.get("mode") == "customScheduled",
         f"enviado={inp9.get('dueAt')} esperado={due_esperado}")
chequear("Notion guarda fecha resuelta y hash coherente con el slot",
         (props9.get(P["fecha"]) or {}).get("date", {}).get("start") == due_esperado
         and (props9.get(P["hash"]) or {}).get("rich_text", [{}])[0].get("text", {}).get("content")
             == m.hashear("texto", due_esperado, _cid_slot, ""),
         json.dumps(props9)[:200])

# Segunda corrida tras guardar: 0 cambios (idempotente)
env9b, n9b, err9b = correr(
    [fila("sinhora", EST["aprobado"], _canal_slot, bpid="p90",
          h=m.hashear("texto", due_esperado, _cid_slot, ""), fecha=due_esperado)],
    {"p90": post("p90", _cid_slot, due_esperado)},
    {"pg-sinhora": ("texto", ["texto"])},
)
chequear("segunda corrida con la fecha guardada no toca nada",
         not err9b and not env9b["gql"] and not env9b["notion"], str(env9b)[:150])

print("\n9b. CONTROL NEGATIVO: reprogramar en (d) a una fecha vencida se reporta y no edita")
dia_pasado = (datetime.now(m.AR) - timedelta(days=5)).strftime("%Y-%m-%d")
env9c, n9c, err9c = correr(
    [fila("vencida", EST["aprobado"], _canal_slot, bpid="p91",
          h=m.hashear("texto", due_antes, _cid_slot, ""), fecha=dia_pasado)],
    {"p91": post("p91", _cid_slot, due_antes)},
    {"pg-vencida": ("texto", ["texto"])},
)
chequear("reporta fecha vencida", any("vencida" in e for e in err9c), str(err9c))
chequear("no llama a editPost ni escribe en Notion",
         not env9c["gql"] and not env9c["notion"], str(env9c)[:150])


def _cola_llena(canal, cid, dias_lista, prefijo="q"):
    """Arma `len(dias_lista)` filas Aprobado ya sincronizadas con sus posts scheduled."""
    filas_q, posts_q, cuerpos_q = [], {}, {}
    for i, d in enumerate(dias_lista, 1):
        nom = f"{prefijo}{i}"
        pid = f"p-{nom}"
        txt = f"texto {nom}"
        due = _fut_dia(d, _slot_hh, _slot_mm).isoformat()
        h = m.hashear(txt, due, cid, "")
        filas_q.append(fila(nom, EST["aprobado"], canal, bpid=pid, h=h, fecha=due))
        posts_q[pid] = post(pid, cid, due)
        cuerpos_q[f"pg-{nom}"] = (txt, [txt])
    return filas_q, posts_q, cuerpos_q


print("\n10. Cancelacion con fecha lejana libera cupo en la MISMA corrida para pieza cercana")
dias_base = [10 + 2 * i for i in range(m.CUPO - 1)]
f10, p10, c10 = _cola_llena(_canal_slot, _cid_slot, dias_base, prefijo="s")
# Pieza cancelada (salio de Aprobado) con fecha MUY lejana (despues de la pieza nueva)
due_cancel = _fut_dia(150, _slot_hh, _slot_mm).isoformat()
f10.append(fila("cancelada-lejana", "En producción", _canal_slot, bpid="p-canc",
                h="viejo", fecha=due_cancel))
p10["p-canc"] = post("p-canc", _cid_slot, due_cancel)
# Pieza nueva Aprobado con fecha cercana (antes que todo)
due_cerca = _fut_dia(2, _slot_hh, _slot_mm).isoformat()
f10.append(fila("nueva-cercana", EST["aprobado"], _canal_slot, fecha=due_cerca))
c10["pg-nueva-cercana"] = ("texto cercano", ["texto cercano"])

env10, n10, err10 = correr(f10, p10, c10)
chequear("sin errores y sin piezas esperando cupo",
         not err10 and not env10["esp"], f"err={err10} esp={env10['esp']}")
chequear("1 cancelada, 1 programada y 0 desalojadas en la misma corrida",
         n10["canceladas"] == 1 and n10["programadas"] == 1 and n10["desalojadas"] == 0, str(n10))
chequear("borra la cancelada ANTES de crear la cercana",
         [op for op, _ in env10["ops"]] == ["delete", "create"]
         and env10["ops"][0][1]["input"]["id"] == "p-canc"
         and env10["ops"][1][1]["input"]["dueAt"] == due_cerca,
         str(env10["ops"])[:200])

print("\n11. Desalojo por prioridad con cupo lleno (10/10): entra la cercana, sale la mas lejana")
dias_10 = [10 + 2 * i for i in range(m.CUPO)]
f11, p11, c11 = _cola_llena(_canal_slot, _cid_slot, dias_10, prefijo="m")
nom_lejana = f"m{m.CUPO}"
pid_lejana = f"p-{nom_lejana}"
due_lejana = _fut_dia(dias_10[-1], _slot_hh, _slot_mm).isoformat()
due_urgente = _fut_dia(3, _slot_hh, _slot_mm).isoformat()
f11.append(fila("urgente", EST["aprobado"], _canal_slot, fecha=due_urgente))
c11["pg-urgente"] = ("texto urgente", ["texto urgente"])

# 11a. Modo SECO: simula desalojo sin escribir nada y mantiene el cupo exacto
env11s, n11s, err11s = correr(f11, p11, c11, aplicar=False)
chequear("en seco no llama a Buffer ni escribe en Notion",
         not err11s and not env11s["gql"] and not env11s["notion"], str(env11s)[:150])
chequear("en seco simula 1 desalojada, 1 programada y 0 canceladas",
         n11s["desalojadas"] == 1 and n11s["programadas"] == 1 and n11s["canceladas"] == 0,
         str(n11s))
chequear("en seco loguea el desalojo y deja el cupo en 10/10",
         any("desalojada" in l and nom_lejana in l and "entra mas cercana" in l
             for l in env11s["logs"])
         and any(f"{_canal_slot} {m.CUPO}/{m.CUPO}" in l for l in env11s["logs"])
         and any(nom_lejana in e for e in env11s["esp"]),
         f"logs={env11s['logs']} esp={env11s['esp']}")

# 11b. Modo REAL: borra la mas lejana en Buffer, limpia sus campos en Notion y crea la urgente
env11, n11, err11 = correr(f11, p11, c11, aplicar=True)
chequear("sin errores: 1 desalojada, 1 programada, 0 canceladas",
         not err11 and n11["desalojadas"] == 1 and n11["programadas"] == 1
         and n11["canceladas"] == 0, f"err={err11} n={n11}")
chequear("borra la mas lejana ANTES de crear la urgente",
         [op for op, _ in env11["ops"]] == ["delete", "create"]
         and env11["ops"][0][1]["input"]["id"] == pid_lejana
         and env11["ops"][1][1]["input"]["dueAt"] == due_urgente,
         str(env11["ops"])[:200])
esc_lejana = [pr for pg, pr in env11["notion"] if pg == f"pg-{nom_lejana}"]
esc_urgente = [pr for pg, pr in env11["notion"] if pg == "pg-urgente"]
chequear("limpia Buffer Post ID y Buffer Hash de la desalojada en Notion",
         len(esc_lejana) == 1
         and esc_lejana[0][P["post_id"]] == {"rich_text": []}
         and esc_lejana[0][P["hash"]] == {"rich_text": []}
         and P["last_sync"] in esc_lejana[0],
         str(esc_lejana)[:200])
chequear("la desalojada pasa a esperando cupo y la urgente queda programada",
         len(esc_urgente) == 1 and any(nom_lejana in e for e in env11["esp"])
         and not any("urgente" in e for e in env11["esp"]),
         f"esp={env11['esp']}")

# 11c. Segunda corrida tras el desalojo: 100% idempotente (0 cambios)
f11_post, p11_post, c11_post = _cola_llena(_canal_slot, _cid_slot, dias_10[:-1], prefijo="m")
# La desalojada sigue Aprobado en Notion con su fecha lejana, pero sin Buffer Post ID ni Hash
f11_post.append(fila(nom_lejana, EST["aprobado"], _canal_slot, fecha=due_lejana))
c11_post[f"pg-{nom_lejana}"] = (f"texto {nom_lejana}", [f"texto {nom_lejana}"])
# La urgente ahora esta en Buffer y Notion sincronizada
h_urg = m.hashear("texto urgente", due_urgente, _cid_slot, "")
f11_post.append(fila("urgente", EST["aprobado"], _canal_slot, bpid="p-urg",
                     h=h_urg, fecha=due_urgente))
p11_post["p-urg"] = post("p-urg", _cid_slot, due_urgente)
c11_post["pg-urgente"] = ("texto urgente", ["texto urgente"])

env11_2, n11_2, err11_2 = correr(f11_post, p11_post, c11_post, aplicar=True)
chequear("segunda corrida es 100% idempotente (0 llamadas, 0 escrituras)",
         not err11_2 and not env11_2["gql"] and not env11_2["notion"]
         and n11_2["programadas"] == 0 and n11_2["desalojadas"] == 0
         and any(nom_lejana in e for e in env11_2["esp"]),
         f"n={n11_2} ops={env11_2['ops']} esp={env11_2['esp']}")

# 11d. Reprogramacion en (d) actualiza el candidato mas lejano antes del desalojo en (e)
f11d, p11d, c11d = _cola_llena(_canal_slot, _cid_slot, dias_10, prefijo="r")
due_movida = _fut_dia(120, _slot_hh, _slot_mm).isoformat()
# r1 originalmente era la mas cercana (D+10), pero en Notion se movio a D+120 (pasa a ser la mas lejana)
f11d[0]["properties"][P["fecha"]]["date"]["start"] = due_movida
f11d.append(fila("urgente-d", EST["aprobado"], _canal_slot, fecha=due_urgente))
c11d["pg-urgente-d"] = ("urgente d", ["urgente d"])
env11d, n11d, err11d = correr(f11d, p11d, c11d, aplicar=True)
chequear("si (d) movio una pieza a fecha mas lejana, (e) desaloja ESA (no la vieja mas lejana)",
         not err11d and n11d["actualizadas"] == 1 and n11d["desalojadas"] == 1
         and n11d["programadas"] == 1
         and [op for op, _ in env11d["ops"]] == ["edit", "delete", "create"]
         and env11d["ops"][1][1]["input"]["id"] == "p-r1",
         f"err={err11d} n={n11d} ops={env11d['ops']}")

print("\n12. CONTROL NEGATIVO: NUNCA desaloja un post huerfano aunque tenga fecha mas lejana")
# Caso A: 9 gestionados cercanos + 1 huerfano muy lejano (D+200); nueva pieza en D+50
f12, p12, c12 = _cola_llena(_canal_slot, _cid_slot, [10 + 2 * i for i in range(m.CUPO - 1)],
                            prefijo="g")
p12["p-huerfano"] = post("p-huerfano", _cid_slot, _fut_dia(200, _slot_hh, _slot_mm).isoformat())
f12.append(fila("intermedia", EST["aprobado"], _canal_slot,
                fecha=_fut_dia(50, _slot_hh, _slot_mm).isoformat()))
c12["pg-intermedia"] = ("texto intermedio", ["texto intermedio"])

env12, n12, err12 = correr(f12, p12, c12, aplicar=True)
chequear("no borra el huerfano ni crea la nueva pieza",
         not err12 and not env12["gql"] and not env12["notion"]
         and n12["desalojadas"] == 0 and n12["programadas"] == 0,
         f"ops={env12['ops']} n={n12}")
chequear("reporta el huerfano y deja la nueva pieza esperando cupo",
         len(env12["hue"]) == 1 and any("intermedia" in e for e in env12["esp"]),
         f"hue={env12['hue']} esp={env12['esp']}")

# Caso B: todos los posts del cupo son huerfanos lejanos y llega una pieza muy cercana (D+2)
p12b = {f"p-h{i}": post(f"p-h{i}", _cid_slot, _fut_dia(80 + i, _slot_hh, _slot_mm).isoformat())
        for i in range(m.CUPO)}
f12b = [fila("muy-cercana", EST["aprobado"], _canal_slot,
             fecha=_fut_dia(2, _slot_hh, _slot_mm).isoformat())]
env12b, n12b, err12b = correr(f12b, p12b, {"pg-muy-cercana": ("cerca", ["cerca"])}, aplicar=True)
chequear("con cupo lleno de huerfanos tampoco borra ninguno",
         not err12b and not env12b["gql"] and not env12b["notion"]
         and len(env12b["hue"]) == m.CUPO and any("muy-cercana" in e for e in env12b["esp"]),
         f"ops={env12b['ops']} hue={len(env12b['hue'])} esp={env12b['esp']}")

print("\n13. CONTROL NEGATIVO: NO desaloja si la pieza nueva tiene fecha igual o posterior")
f13, p13, c13 = _cola_llena(_canal_slot, _cid_slot, dias_10, prefijo="c")
due_max = _fut_dia(dias_10[-1], _slot_hh, _slot_mm).isoformat()
due_despues = _fut_dia(dias_10[-1] + 5, _slot_hh, _slot_mm).isoformat()
f13.append(fila("igual-fecha", EST["aprobado"], _canal_slot, fecha=due_max))
f13.append(fila("posterior", EST["aprobado"], _canal_slot, fecha=due_despues))
c13["pg-igual-fecha"] = ("igual", ["igual"])
c13["pg-posterior"] = ("despues", ["despues"])

env13, n13, err13 = correr(f13, p13, c13, aplicar=True)
chequear("cero llamadas y cero desalojos ante fecha igual o posterior",
         not err13 and not env13["gql"] and not env13["notion"]
         and n13["desalojadas"] == 0 and n13["programadas"] == 0,
         f"ops={env13['ops']} n={n13}")
chequear("ambas piezas quedan esperando cupo",
         any("igual-fecha" in e for e in env13["esp"])
         and any("posterior" in e for e in env13["esp"]),
         f"esp={env13['esp']}")

print("\n13b. CONTROL NEGATIVO: pieza nueva vencida con cupo lleno reporta error y NO desaloja")
f13b, p13b, c13b = _cola_llena(_canal_slot, _cid_slot, dias_10, prefijo="v")
f13b.append(fila("nueva-vencida", EST["aprobado"], _canal_slot, fecha=dia_pasado))
c13b["pg-nueva-vencida"] = ("vencida", ["vencida"])
env13b, n13b, err13b = correr(f13b, p13b, c13b, aplicar=True)
chequear("reporta vencida y no borra ni crea nada",
         any("vencida" in e for e in err13b) and not env13b["gql"] and not env13b["notion"]
         and n13b["desalojadas"] == 0 and n13b["programadas"] == 0,
         f"err={err13b} ops={env13b['ops']}")

print(f"\n{ok} OK, {fallo} FALLA")
sys.exit(1 if fallo else 0)
