# estado_buffer.py - Mira SOLO el lado de Buffer. Nunca escribe nada, en ningun modo.
#
#   python estado_buffer.py                  # todos los espacios del config
#   python estado_buffer.py --espacio "Mi marca"
#   python estado_buffer.py --config otro.json
#
# Para que sirve: el sync te dice que HARIA. Esto te dice que HAY, contado del lado de Buffer y
# sin pasar por Notion ni por su credencial. Sirve para dos cosas concretas:
#
#   1. Confirmar un resultado del sync con una fuente independiente. Si el sync dice que programo
#      dos piezas, aca las tienen que aparecer. Un numero que sale del mismo programa que estas
#      verificando no verifica nada.
#   2. Ver cuanto lugar libre queda por canal antes de aprobar una tanda.
#
# Pagina hasta el final a proposito. La query `posts` de Buffer devuelve 10 por defecto y eso
# PARECE la cola completa, justo porque 10 coincide con el tope de posts programados por canal.
# Es un error que ya produjo un reporte falso ("10 agendados, 0 borradores" cuando eran 20 y 3).

import json, sys, pathlib, urllib.request, urllib.error
from datetime import datetime

sys.path.insert(0, str(pathlib.Path(__file__).parent))
import sync_notion_buffer as m           # se reusan config, zona horaria y transporte

URL = "https://api.buffer.com/graphql"

# Buffer nombra los servicios en ingles y con nombres viejos. Se traduce solo para mostrar.
SERVICIO = {"linkedin": "LinkedIn", "twitter": "X", "facebook": "Facebook",
            "instagram": "Instagram", "threads": "Threads", "mastodon": "Mastodon"}

Q_CANALES = '{ channels(input:{organizationId:"%s"}) { id service } }'
Q_POSTS = ('{ posts(input:{organizationId:"%s"}, first:50%s) '
           '{ edges { node { id status sentAt dueAt channelId text } } '
           'pageInfo { hasNextPage endCursor } } }')


def gql(key, q):
    req = urllib.request.Request(
        URL, data=json.dumps({"query": q}).encode("utf-8"),
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
    try:
        d = json.loads(urllib.request.urlopen(req, timeout=30).read())
    except urllib.error.HTTPError as e:
        raise SystemExit(f"Buffer respondio HTTP {e.code}: "
                         f"{e.read().decode('utf-8', 'replace')[:300]}")
    except urllib.error.URLError as e:
        raise SystemExit(f"sin conexion con Buffer: {e.reason}")
    if d.get("errors"):
        raise SystemExit("Buffer: " + json.dumps(d["errors"])[:300])
    return d["data"]


def main():
    solo = None
    if "--espacio" in sys.argv:
        solo = sys.argv[sys.argv.index("--espacio") + 1]
        if solo not in m.ESPACIOS:
            sys.stderr.write(f"espacio desconocido: {solo!r}. "
                             f"Declarados: {', '.join(m.ESPACIOS)}\n")
            return 2

    filas = []
    for espacio, cfg in m.ESPACIOS.items():
        if solo and espacio != solo:
            continue
        try:
            key = m.leer_credencial(m.ruta(cfg["credencial"]),
                                    f"Buffer para «{espacio}»", "paso 1")
        except RuntimeError as e:
            raise SystemExit(str(e))
        canales = {c["id"]: SERVICIO.get(c["service"], c["service"])
                   for c in gql(key, Q_CANALES % cfg["organizacion"])["channels"]}

        posts, after = [], None
        while True:
            arg = f', after:"{after}"' if after else ""
            d = gql(key, Q_POSTS % (cfg["organizacion"], arg))["posts"]
            posts += [e["node"] for e in d["edges"]]
            if not d["pageInfo"]["hasNextPage"]:
                break
            after = d["pageInfo"]["endCursor"]

        for cid, nombre in canales.items():
            delcanal = [p for p in posts if p["channelId"] == cid]
            agendados = [p for p in delcanal if p["status"] == "scheduled"]
            # Un borrador NO lo administra el sync: se muestra para que sepas que esta ahi.
            borradores = [p for p in delcanal if p["status"] in ("draft", "needs_approval")]
            print(f"{espacio:18} {nombre:10} agendados={len(agendados):2}/{m.CUPO}  "
                  f"borradores={len(borradores)}  libre={m.CUPO - len(agendados)}")
            for p in agendados + borradores:
                cuando = p.get("dueAt")
                filas.append({
                    "espacio": espacio, "canal": nombre, "id": p["id"], "status": p["status"],
                    "fecha": (datetime.fromisoformat(cuando.replace("Z", "+00:00"))
                              .astimezone(m.AR).isoformat()) if cuando else "",
                    "texto": (p.get("text") or "").strip()[:120]})

    salida = pathlib.Path(__file__).parent / "estado_buffer.json"
    salida.write_text(json.dumps(filas, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\nEn Buffer, sin publicar todavia: {len(filas)}")
    print(f"Detalle en {salida.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
