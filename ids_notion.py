# ids_notion.py - Te da el id que va en `notion.data_source` del config, y de paso te dice si la
# base esta bien compartida y si le faltan propiedades. Solo lee.
#
#   python ids_notion.py https://www.notion.so/tu-workspace/1234abcd...?v=...
#   python ids_notion.py 1234abcd5678...            # tambien acepta el id pelado
#
# Por que hace falta un programa para esto: el id que pide el config NO es el que ves en la URL.
# Notion muestra el id de la BASE, y la API moderna organiza cada base en una o mas "fuentes de
# datos" (data sources), que es lo que hay que consultar. El id de la fuente no aparece en ninguna
# pantalla de Notion: sale de preguntarle a la API.
#
# Y hay una trampa que cuesta una hora si no se sabe: pidiendo con una version vieja de la API
# (`2022-06-28`) la consulta devuelve 404. El 404 se lee como "falta compartir la base con la
# integracion" -que es lo que la propia documentacion sugiere- y te manda a arreglar algo que no
# esta roto. Este programa pide con la version correcta.

import json, re, sys, pathlib, urllib.request, urllib.error

VERSION = "2025-09-03"          # con una anterior, esta consulta devuelve 404

# Los nombres que el sync espera por defecto. Si en tu base los llamaste distinto, no es un
# problema: se declara la traduccion en `notion.propiedades` del config.
ESPERADAS = ["Name", "Estado", "Canal", "Marca", "Fecha de publicación", "Archivo", "URL",
             "Buffer Post ID", "Buffer Hash", "Buffer Last Sync", "Imagen", "Placa"]


def pedir(tok, path):
    req = urllib.request.Request(
        f"https://api.notion.com/v1/{path}",
        headers={"Authorization": f"Bearer {tok}", "Notion-Version": VERSION})
    try:
        return json.loads(urllib.request.urlopen(req, timeout=30).read())
    except urllib.error.HTTPError as e:
        cuerpo = e.read().decode("utf-8", "replace")[:400]
        if e.code == 404:
            raise SystemExit(
                "Notion responde 404. Las dos causas posibles, en orden de probabilidad:\n"
                "  1. La base no esta compartida con tu integracion. En Notion: abri la base,\n"
                "     menu '...' arriba a la derecha, Conexiones, y agrega la tuya.\n"
                "  2. El id que pasaste no es el de una base de datos.\n"
                f"\nRespuesta cruda: {cuerpo}")
        if e.code == 401:
            raise SystemExit(f"Notion responde 401: el token no sirve o esta mal copiado.\n{cuerpo}")
        raise SystemExit(f"Notion responde HTTP {e.code}:\n{cuerpo}")
    except urllib.error.URLError as e:
        raise SystemExit(f"sin conexion con Notion: {e.reason}")


def id_de(texto):
    """Saca el id de una URL de Notion, o acepta el id pelado. Notion lo escribe de las dos
    formas -con guiones y sin- y la API acepta las dos."""
    crudo = texto.split("?")[0].rstrip("/").split("/")[-1]
    m = re.findall(r"[0-9a-fA-F]{32}|[0-9a-fA-F-]{36}", crudo)
    if not m:
        raise SystemExit(f"no encuentro un id de Notion en: {texto}")
    return m[-1]


def ruta_credencial():
    cfg = pathlib.Path(__file__).parent / "sync_config.json"
    if cfg.exists():
        c = json.loads(cfg.read_text(encoding="utf-8"))
        r = (c.get("notion") or {}).get("credencial")
        if r:
            return pathlib.Path(str(r)).expanduser()
    return pathlib.Path("~/.notion/api_key").expanduser()


def main():
    if len(sys.argv) < 2:
        raise SystemExit("Uso:  python ids_notion.py <URL de tu base de Notion>\n"
                         "Copiala del navegador con la base abierta.")

    p = ruta_credencial()
    if not p.exists():
        raise SystemExit(f"no existe el archivo de credencial: {p}\n"
                         "Crealo con el token de tu integracion adentro "
                         "(https://www.notion.so/my-integrations).")
    tok = p.read_text(encoding="utf-8").strip()
    if not tok:
        raise SystemExit(f"el archivo de credencial esta vacio: {p}")

    db = pedir(tok, f"databases/{id_de(sys.argv[1])}")
    titulo = "".join(t.get("plain_text", "") for t in db.get("title") or []) or "(sin titulo)"
    fuentes = db.get("data_sources") or []
    if not fuentes:
        raise SystemExit("esa base no declara ninguna fuente de datos. Revisa que sea una base "
                         "de datos y no una pagina comun.")

    print(f'Base: {titulo}\n')
    for f in fuentes:
        print(f'  "data_source": "{f["id"]}"')
    if len(fuentes) > 1:
        print("\n  (tu base tiene varias fuentes: elegi la que contenga las piezas)")

    # Las propiedades se leen de la fuente, no de la base.
    d = pedir(tok, f"data_sources/{fuentes[0]['id']}")
    tiene = set((d.get("properties") or {}).keys())
    faltan = [x for x in ESPERADAS if x not in tiene]

    print("\nPropiedades encontradas:")
    for n in sorted(tiene):
        print(f"  · {n}")
    if faltan:
        print("\nCon los nombres por defecto faltarian estas:")
        for n in faltan:
            print(f"  X {n}")
        print("\nNo necesariamente es un error: si las llamaste distinto, declara la equivalencia")
        print("en `notion.propiedades` del config. Si directamente no existen, crealas siguiendo")
        print("NOTION.md.")
    else:
        print("\nEstan todas las que el sync espera por defecto.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
