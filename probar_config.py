# probar_config.py - Banco de pruebas de la capa de configuracion del sync.
#
#   python probar_config.py      # sale 0 si pasa todo, 1 si algo falla
#
# NO toca Buffer ni Notion para escribir: corre el sync en seco con configuraciones sinteticas.
#
# Por que existe: el 2026-08-06 se saco toda la configuracion del motor a sync_config.json, para
# que el mismo codigo sirva en otra maquina o para otra persona. Eso agrego caminos que una
# instalacion concreta NO ejercita nunca -el modo de slots 'inline', un config invalido, un
# espacio inexistente-, y una ruta que nunca se ejecuta no esta verificada por mas que este
# escrita: es exactamente como convivieron altText y el thread mal formados durante dias.
#
# El caso 2 es un CONTROL NEGATIVO del caso 1: si un slot distinto NO diera distinto, la
# comparacion del caso 1 no probaria nada.
import sys, json, pathlib, tempfile, subprocess, copy

AQUI = pathlib.Path(__file__).parent
sys.path.insert(0, str(AQUI))
import sync_notion_buffer as m

ok = fallo = 0


def chequear(t, cond, det=""):
    global ok, fallo
    # El detalle se sanea porque sale de la salida real del sync, que trae acentos: en una consola
    # cp1252 un `print` crudo lanza UnicodeEncodeError y el banco MUERE justo al reportar el unico
    # fallo que tenia que mostrar. Encontrado el 2026-08-07, con un fallo real adentro.
    det = str(det).encode("ascii", "replace").decode("ascii")
    print(("  OK   " if cond else "  FALLA") + f" {t}" + (f"  <- {det}" if not cond else ""))
    if cond:
        ok += 1
    else:
        fallo += 1


BASE = json.loads((AQUI / "sync_config.json").read_text(encoding="utf-8"))
ESPACIO = next(iter(BASE["espacios"]))

# Los casos que lanzan el sync de verdad necesitan credenciales validas. En una instalacion recien
# bajada todavia no existen, y sin este chequeo el banco reportaria FALLA sobre un paquete sano:
# el usuario nuevo lee "2 FALLA" y concluye que lo que le dieron esta roto. Se saltean diciendo
# por que, que no es lo mismo que pasar en silencio.
def _hay_credencial(ruta_str):
    return pathlib.Path(str(ruta_str)).expanduser().exists()


CREDENCIALES = (_hay_credencial(BASE["notion"]["credencial"])
                and _hay_credencial(BASE["espacios"][ESPACIO]["credencial"]))
SLOTS = BASE["espacios"][ESPACIO].get("slots", {})
tmp = pathlib.Path(tempfile.mkdtemp())


def escribir(cfg, nombre="c.json"):
    f = tmp / nombre
    f.write_text(json.dumps(cfg, ensure_ascii=False), encoding="utf-8")
    return f


def correr_cli(args):
    r = subprocess.run([sys.executable, "sync_notion_buffer.py"] + args, cwd=str(AQUI),
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    return r.returncode, (r.stdout or "") + (r.stderr or "")


print("\n1. Los dos modos de slots son equivalentes")
if SLOTS.get("fuente") != "documento":
    print("  (se saltea: el espacio de referencia no usa el modo documento)")
else:
    doc = m.leer_slots(SLOTS)
    canales_inline = {c: {"dias": [d for d, i in m.DIAS.items() if i in v[0] and len(d) == len(d.encode())],
                          "hora": f"{v[1]:02d}:{v[2]:02d}"} for c, v in doc.items()}
    inline = m.leer_slots({"fuente": "inline", "canales": canales_inline})
    chequear("documento e inline producen los mismos slots", doc == inline, f"{doc} vs {inline}")

    print("\n2. CONTROL NEGATIVO: un slot distinto tiene que diferir")
    otro = copy.deepcopy(canales_inline)
    primero = next(iter(otro))
    hh, mm = otro[primero]["hora"].split(":")
    otro[primero]["hora"] = f"{hh}:{(int(mm) + 1) % 60:02d}"
    chequear("un minuto de diferencia se detecta", doc != m.leer_slots({"fuente": "inline", "canales": otro}))

print("\n3. Un config con slots inline corre de punta a punta, sin tocar el hash")
if not CREDENCIALES:
    print("  (se saltea: necesita credenciales reales de Notion y Buffer, y todavia no hay)")
else:
    cfg = copy.deepcopy(BASE)
    cfg["espacios"] = {ESPACIO: copy.deepcopy(BASE["espacios"][ESPACIO])}
    cfg["espacios"][ESPACIO]["slots"] = {"fuente": "inline", "canales": {
        c: {"dias": ["jueves"], "hora": "09:30"} for c in BASE["espacios"][ESPACIO]["canales"]}}
    code, out = correr_cli(["--config", str(escribir(cfg, "inline.json"))])
    chequear("corre en seco y sale 0", code == 0, f"code={code} {out[-300:]}")
    chequear("0 actualizadas: el hash no se movio", "0 actualizadas" in out, out[-300:])
    chequear("solo corre el espacio declarado en ese config",
             all(e not in out for e in BASE["espacios"] if e != ESPACIO), out[:200])

print("\n4. Modos de falla: tiene que fallar FUERTE, nunca seguir a ciegas")
code, _ = correr_cli(["--config", str(tmp / "no-existe.json")])
chequear("config inexistente: sale distinto de 0", code != 0, f"code={code}")

for nombre, mutar in [
    ("zona horaria invalida", lambda c: c.update({"zona_horaria": "menos tres"})),
    ("falta 'espacios'",      lambda c: c.pop("espacios")),
    ("espacios vacio",        lambda c: c.update({"espacios": {}})),
    ("fuente de slots rara",  lambda c: c["espacios"][ESPACIO].update({"slots": {"fuente": "telepatia"}})),
    ("documento inexistente", lambda c: c["espacios"][ESPACIO].update(
        {"slots": {"fuente": "documento", "ruta": "C:/no/existe.md"}})),
    # Hasta el 2026-08-11 este campo se ignoraba: declarar otro proveedor no cambiaba nada y el
    # sync seguia usando R2 en silencio. Un campo que se ignora es un campo que miente.
    ("proveedor desconocido",  lambda c: c["almacenamiento"].update({"proveedor": "s3"})),
]:
    c = copy.deepcopy(BASE)
    try:
        mutar(c)
    except Exception:
        pass
    code, out = correr_cli(["--config", str(escribir(c, "malo.json"))])
    chequear(f"{nombre}: falla fuerte", code != 0, f"code={code} {out[-200:]}")

print("\n5. Seleccion de espacio por linea de comandos")
code, out = correr_cli(["--espacio", "Espacio Que No Existe"])
chequear("espacio inexistente: sale 2 y lo dice", code == 2 and "desconocido" in out.lower(),
         f"code={code} {out[:200]}")
if not CREDENCIALES:
    print("  (el caso siguiente se saltea: necesita credenciales reales)")
    print(f"\n{ok} OK, {fallo} FALLA")
    sys.exit(1 if fallo else 0)
code, out = correr_cli(["--espacio", ESPACIO])
chequear("espacio valido: corre y sale 0", code == 0, f"code={code}")

print(f"\n{ok} OK, {fallo} FALLA")
sys.exit(1 if fallo else 0)
