# ids_buffer.py - Te imprime los ids de Buffer que el config necesita. Solo lee.
#
#   python ids_buffer.py                 # usa la credencial que dice el config
#   python ids_buffer.py ~/.buffer/api_key   # o le pasas la ruta directamente
#
# Existe porque es el unico dato del setup que no se puede copiar de la pantalla de Buffer: ni el
# id de la organizacion ni el de cada canal se ven en la web. Salen de la API, y pedirtelos "a
# mano" seria mandarte a escribir una consulta GraphQL para completar un formulario.
#
# NO escribe nada en Buffer ni en ningun lado. Lo peor que puede pasar es que te diga que la
# credencial esta mal.

import json, sys, pathlib, urllib.request, urllib.error

URL = "https://api.buffer.com/graphql"
# Van en dos pasos y no en uno solo a proposito. Pedir los canales anidados dentro de la cuenta
# (`account { organizations { channels } }`) devuelve FORBIDDEN en cuanto tu cuenta ve mas de una
# organizacion: la credencial autoriza una sola, y el error tumba la consulta entera en vez de
# saltear la que no corresponde. Verificado contra la API real el 2026-08-11.
Q_ORGS = "{ account { organizations { id name } } }"
Q_CANALES = ('{ channels(input:{organizationId:"%s"}) '
             '{ id service name displayName isDisconnected } }')


def pedir(key, query, tolerar=False):
    req = urllib.request.Request(
        URL, data=json.dumps({"query": query}).encode("utf-8"),
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
    try:
        d = json.loads(urllib.request.urlopen(req, timeout=30).read())
    except urllib.error.HTTPError as e:
        cuerpo = e.read().decode("utf-8", "replace")[:300]
        raise SystemExit(f"Buffer respondio HTTP {e.code}. Suele ser una credencial vencida o de "
                         f"otra cuenta.\n{cuerpo}")
    except urllib.error.URLError as e:
        raise SystemExit(f"sin conexion con Buffer: {e.reason}")
    if d.get("errors"):
        if tolerar:
            return None
        raise SystemExit("Buffer: " + json.dumps(d["errors"])[:300])
    return d["data"]


def ruta_credencial():
    """Del argumento si lo pasaste; si no, del config; si no hay config, la ruta de costumbre."""
    if len(sys.argv) > 1 and not sys.argv[1].startswith("-"):
        return pathlib.Path(sys.argv[1]).expanduser()
    cfg = pathlib.Path(__file__).parent / "sync_config.json"
    if cfg.exists():
        c = json.loads(cfg.read_text(encoding="utf-8"))
        for esp in (c.get("espacios") or {}).values():
            if esp.get("credencial"):
                return pathlib.Path(str(esp["credencial"])).expanduser()
    return pathlib.Path("~/.buffer/api_key").expanduser()


def main():
    p = ruta_credencial()
    if not p.exists():
        raise SystemExit(f"no existe el archivo de credencial: {p}\n"
                         f"Crealo con tu clave de Buffer adentro "
                         f"(https://publish.buffer.com/settings/api), o pasame la ruta:\n"
                         f"  python ids_buffer.py ruta/al/archivo")
    key = p.read_text(encoding="utf-8").strip()
    if not key:
        raise SystemExit(f"el archivo de credencial esta vacio: {p}")

    orgs = pedir(key, Q_ORGS)["account"]["organizations"]
    if not orgs:
        raise SystemExit("esa credencial no ve ninguna organizacion.")

    print(f"Credencial leida de: {p}\n")
    vistas = 0
    for o in orgs:
        d = pedir(key, Q_CANALES % o["id"], tolerar=True)
        if d is None:
            # Normal si tenes varias organizaciones: cada credencial ve una sola. Se saltea en
            # vez de cortar, porque la que te interesa puede ser la siguiente de la lista.
            print(f'  (organizacion "{o["name"]}": esta credencial no la autoriza)\n')
            continue
        vistas += 1
        print(f'  "organizacion": "{o["id"]}"        <- {o["name"]}')
        print('  "canales": {')
        for c in d["channels"] or []:
            # El nombre que usa Buffer por dentro no siempre es el que ves: twitter es X. Y las
            # mayusculas importan, porque este texto tiene que coincidir con el de Notion.
            visible = {"twitter": "X", "linkedin": "LinkedIn", "facebook": "Facebook",
                       "instagram": "Instagram", "threads": "Threads",
                       "mastodon": "Mastodon"}.get(c["service"], c["service"].capitalize())
            quien = c.get("displayName") or c.get("name") or ""
            roto = "  (DESCONECTADO en Buffer)" if c.get("isDisconnected") else ""
            print(f'    "{visible}": "{c["id"]}"'.ljust(46)
                  + f'<- {c["service"]}' + (f' · {quien}' if quien else "") + roto)
        print("  }\n")

    if not vistas:
        raise SystemExit("esta credencial no autoriza ninguna de tus organizaciones. Si tenes "
                         "varias cuentas de Buffer, cada una necesita su propia clave.")

    print("Copia esos valores a sync_config.json, en el espacio que corresponda.")
    print("Ojo: el nombre de la izquierda ('LinkedIn', 'X', 'Facebook') tiene que ser IGUAL al")
    print("valor que uses en la propiedad Canal de Notion. Si en Notion escribis 'Twitter',")
    print("aca tiene que decir 'Twitter'.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
