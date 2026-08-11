# probar_placas.py - Banco de pruebas de la capa de placas (almacenamiento.py + el paso 0).
#
#   python probar_placas.py      # sale 0 si pasa todo, 1 si algo falla
#
# NO toca R2, ni Notion, ni Buffer: reemplaza la descarga del adjunto y el cliente del bucket
# por dobles, y captura lo que se SUBIRIA y lo que se ESCRIBIRIA.
#
# Por que existe: la ruta de imagen no se puede ejercitar contra Buffer sin publicar de verdad,
# y §14 de sync_notion_buffer.md ya tiene el precedente caro de dos rutas que estaban escritas,
# revisadas y mal, y que nadie noto porque ninguna pieza las habia tocado nunca.
#
# El caso 9 es un CONTROL NEGATIVO: si la placa ya esta materializada no puede pasar NADA, ni
# siquiera una consulta al bucket. Sin el, un banco que solo comprueba que no explota pasaria
# igual con el paso 0 entero comentado.
import sys, pathlib

sys.path.insert(0, str(pathlib.Path(__file__).parent))
import sync_notion_buffer as m
import almacenamiento as a

P = m.P
PNG = b"\x89PNG\r\n\x1a\n" + b"contenido de una placa"
JPG = b"\xff\xd8\xff" + b"otra placa"
CDN = "https://cdn.ejemplo.com"

ok = fallo = 0


def chequear(desc, cond):
    global ok, fallo
    if cond:
        ok += 1
        print(f"  OK    {desc}")
    else:
        fallo += 1
        print(f"  FALLA {desc}")


class ClienteFalso:
    """Doble del bucket. Cuenta las llamadas: es lo que permite probar que una corrida estable
    no toca R2 ni para preguntar."""
    def __init__(self, ya_existe=False):
        self.peso_max = 5 * 1024 * 1024
        self.subidos, self.consultas, self.ya_existe = [], 0, ya_existe

    def existe(self, key):
        self.consultas += 1
        return self.ya_existe

    def subir(self, key, contenido, ct, meta=None):
        self.subidos.append((key, len(contenido), ct, meta))


def fila(imagen="", adjunto=None):
    props = {P["imagen"]: {"type": "url", "url": imagen or None}}
    if adjunto is None:
        props[P["placa"]] = {"type": "files", "files": []}
    else:
        props[P["placa"]] = {"type": "files", "files": [adjunto]}
    return {"id": "pg-1", "properties": props}


def portadas(esc):
    """Las portadas que se mandarian: escribir() recibe cover como 3er argumento."""
    return [e[2] for e in esc if len(e) > 2 and e[2]]


def materializar(f, cliente, aplicar=True, imagen=None):
    """Corre el paso 0 real, interceptando la escritura a Notion.

    `imagen` sale de la propia fila, igual que en el motor: pasarla suelta hacia que los casos
    de 'sin adjunto' corrieran siempre con imagen vacia y uno de ellos pasara por la razon
    equivocada. Es el mismo modo de falla que la seccion 15 ya registra sobre otra prueba."""
    if imagen is None:
        imagen = m.prop_txt(f["properties"].get(P["imagen"]))
    escrituras, logs = [], []
    orig = m.escribir
    m.escribir = lambda pid, props, cover=None: escrituras.append((pid, props, cover))
    try:
        r = m.materializar(f, f["properties"], imagen, cliente, CDN, "EspacioX",
                           aplicar, logs.append, "pieza")
    finally:
        m.escribir = orig
    return r, escrituras, logs


print("1. Deteccion de tipo por los BYTES, no por la extension")
chequear("PNG", a.tipo_de(PNG) == ("png", "image/png"))
chequear("JPG", a.tipo_de(JPG) == ("jpg", "image/jpeg"))
chequear("GIF", a.tipo_de(b"GIF89a...")[0] == "gif")
chequear("WEBP (su firma no es un prefijo)",
         a.tipo_de(b"RIFF" + b"\x00\x00\x00\x00" + b"WEBP" + b"x")[0] == "webp")
try:
    a.tipo_de(b"esto no es una imagen")
    chequear("un archivo que no es imagen se rechaza", False)
except a.ErrorPlaca:
    chequear("un archivo que no es imagen se rechaza", True)
try:
    a.tipo_de(b"\x89PNG\r\n\x1a\n"[:4] + b"falso.png")
    chequear("un .png que no es PNG por dentro se rechaza", False)
except a.ErrorPlaca:
    chequear("un .png que no es PNG por dentro se rechaza", True)

print("\n2. La clave no significa nada y es determinista")
k1, k2 = a.clave_de(PNG, "png"), a.clave_de(PNG, "png")
chequear("el mismo contenido da la misma clave", k1 == k2)
chequear("contenido distinto da clave distinta", a.clave_de(JPG, "jpg") != k1)
chequear("no revela marca, fecha ni pieza",
         not any(x in k1 for x in ("EspacioX", "2026", "pg-")))
chequear("es hash + extension", len(k1) == 32 + 4 and k1.endswith(".png"))

print("\n3. Peso maximo: una placa gigante se rechaza, no se sube")
c = ClienteFalso()
c.peso_max = 10
a._bytes = lambda url: PNG
try:
    a.analizar(c, "http://x", CDN)
    chequear("supera el maximo -> ErrorPlaca", False)
except a.ErrorPlaca as e:
    chequear("supera el maximo -> ErrorPlaca", "maximo" in str(e))
chequear("y no subio nada", not c.subidos)

print("\n4. Adjunto vacio")
a._bytes = lambda url: b""
c = ClienteFalso()
try:
    a.analizar(c, "http://x", CDN)
    chequear("adjunto vacio -> ErrorPlaca", False)
except a.ErrorPlaca:
    chequear("adjunto vacio -> ErrorPlaca", True)

a._bytes = lambda url: PNG   # de aca en adelante, el adjunto es un PNG valido

print("\n5. Placa nueva: se sube y se escribe la URL en Notion")
c = ClienteFalso()
f = fila(adjunto={"type": "file", "file": {"url": "https://notion-firmada/x.png"}})
url, esc, logs = materializar(f, c)
chequear("devuelve la URL del CDN del espacio", url.startswith(CDN + "/"))
chequear("subio exactamente una vez", len(c.subidos) == 1)
chequear("con el content-type correcto", c.subidos[0][2] == "image/png")
chequear("y con metadatos de espacio y pieza",
         c.subidos[0][3] == {"espacio": "EspacioX", "pieza": "pg-1"})
chequear("escribio la URL en la propiedad imagen",
         len(esc) == 1 and esc[0][1][P["imagen"]]["url"] == url)
chequear("lo reporto en el log", any("placa" in x for x in logs))

print("\n6. La misma placa ya en el bucket: no se re-sube")
c = ClienteFalso(ya_existe=True)
url2, esc, _ = materializar(f, c)
chequear("misma clave que antes", url2 == url)
chequear("consulto si existia", c.consultas == 1)
chequear("y NO subio", not c.subidos)

print("\n7. Adjunto externo (enlazado, no subido a Notion)")
c = ClienteFalso()
fe = fila(adjunto={"type": "external", "external": {"url": "https://otro-lado/x.png"}})
url3, esc, _ = materializar(fe, c)
chequear("tambien se materializa al bucket propio", url3.startswith(CDN + "/"))

print("\n8. En SECO no escribe nada, pero dice que haria")
c = ClienteFalso()
url4, esc, logs = materializar(f, c, aplicar=False)
chequear("devuelve la URL que tendria", url4 == url)
chequear("no consulto ni subio a R2", c.consultas == 0 and not c.subidos)
chequear("no escribio en Notion", not esc)
chequear("pero lo reporto", any("placa" in x for x in logs))

print("\n9. CONTROL NEGATIVO: ya materializada -> no puede pasar NADA")
c = ClienteFalso()
ya = fila(imagen=url, adjunto={"type": "file", "file": {"url": "https://notion-firmada/x.png"}})
url5, esc, logs = materializar(ya, c)
chequear("devuelve la misma URL", url5 == url)
chequear("cero consultas a R2", c.consultas == 0)
chequear("cero subidas", not c.subidos)
chequear("cero escrituras en Notion", not esc)

print("\n10. Sin adjunto: distingue 'se la sacaron' de 'la cargo una persona a mano'")
c = ClienteFalso()
url6, esc, logs = materializar(fila(imagen=CDN + "/vieja.png"), c)
chequear("placa del CDN propio sin adjunto -> se limpia", url6 == "")
chequear("y limpia la propiedad en Notion",
         len(esc) == 1 and esc[0][1][P["imagen"]]["url"] is None)

c = ClienteFalso()
manual = "https://buffer-media-uploads.s3.amazonaws.com/x"
url7, esc, _ = materializar(fila(imagen=manual), c)
chequear("URL ajena sin adjunto -> se respeta", url7 == manual)
chequear("y no se toca Notion", not esc)

c = ClienteFalso()
url8, esc, _ = materializar(fila(), c)
chequear("sin adjunto y sin imagen -> no hace nada", url8 == "" and not esc)

print("\n10b. Placa de un host ajeno: se ve en Notion pero NO se materializa")
c = ClienteFalso()
ajena = "https://buffer-media-uploads.s3.amazonaws.com/abc_linkedin"
fa = fila(adjunto={"type": "external", "name": "buffer.png", "external": {"url": ajena}})
urlA, esc, logs = materializar(fa, c)
chequear("no la sube al CDN propio", not c.subidos)
chequear("ni consulta el bucket", c.consultas == 0)
chequear("no escribe en Notion", not esc)
chequear("y deja la imagen como estaba, para no mover el hash", urlA == "")

print("\n10c. Placa que YA apunta al CDN propio: no se descarga ni se re-sube")
c = ClienteFalso()
directa = CDN + "/abc123.png"
fd = fila(adjunto={"type": "external", "external": {"url": directa}})
descargas = []
_orig_bytes = a._bytes
a._bytes = lambda url: descargas.append(url) or PNG
urlD, esc, logs = materializar(fd, c)
a._bytes = _orig_bytes
chequear("devuelve esa misma URL", urlD == directa)
chequear("NO descargo nada", not descargas)
chequear("ni subio ni consulto", not c.subidos and c.consultas == 0)
chequear("y escribe la URL en imagen", len(esc) == 1 and esc[0][1][P["imagen"]]["url"] == directa)

c = ClienteFalso()
fd2 = fila(imagen=directa, adjunto={"type": "external", "external": {"url": directa}})
urlD2, esc2, _ = materializar(fd2, c)
chequear("si ya estaba escrita, no reescribe", urlD2 == directa and not esc2)

print("\n10e. Placa pesada: avisa, pero NO bloquea ni comprime")
c = ClienteFalso()
GORDA = b"\x89PNG\r\n\x1a\n" + b"x" * (2 * 1024 * 1024)
a._bytes = lambda url: GORDA
urlG, esc, logs = materializar(f, c)
chequear("la sube igual (avisar no es bloquear)", len(c.subidos) == 1)
chequear("y avisa en el log", any("optimizar" in x for x in logs))
chequear("sube el archivo TAL CUAL, sin comprimir", c.subidos[0][1] == len(GORDA))

a._bytes = lambda url: PNG                      # control: una chica no dispara el aviso
c = ClienteFalso()
_, _, logs = materializar(f, c)
chequear("una placa chica NO dispara el aviso", not any("optimizar" in x for x in logs))

print("\n10d. La placa se pone de portada de la pagina (asi se ve grande al abrirla)")
c = ClienteFalso()
_, esc, _ = materializar(f, c)
chequear("manda la portada al materializar", portadas(esc) == [url])

c = ClienteFalso()
conport = fila(adjunto={"type": "file", "file": {"url": "https://notion-firmada/x.png"}})
conport["cover"] = {"type": "external", "external": {"url": "https://otra-cosa/foto.jpg"}}
_, esc, _ = materializar(conport, c)
chequear("NO pisa una portada puesta a mano", not portadas(esc))
chequear("pero igual escribe la imagen", len(esc) == 1)

c = ClienteFalso()
mia = fila(adjunto={"type": "file", "file": {"url": "https://notion-firmada/x.png"}})
mia["cover"] = {"type": "external", "external": {"url": CDN + "/vieja.png"}}
_, esc, _ = materializar(mia, c)
chequear("si la portada la puso el sync, la actualiza", portadas(esc) == [url])

print("\n11. La URL entra al hash, que es lo que dispara la actualizacion en Buffer")
h_sin = m.hashear("texto", "2026-09-01T10:00:00-03:00", "cid", "")
h_con = m.hashear("texto", "2026-09-01T10:00:00-03:00", "cid", CDN + "/a.png")
h_otra = m.hashear("texto", "2026-09-01T10:00:00-03:00", "cid", CDN + "/b.png")
chequear("agregar una placa cambia el hash", h_sin != h_con)
chequear("cambiar la placa cambia el hash", h_con != h_otra)
chequear("la misma placa da el mismo hash",
         h_con == m.hashear("texto", "2026-09-01T10:00:00-03:00", "cid", CDN + "/a.png"))

print(f"\n{ok} OK, {fallo} FALLA")
sys.exit(1 if fallo else 0)
