# almacenamiento.py - La capa de archivos del sync. Sube una placa a un bucket y devuelve su
# URL publica estable.
#
# Es una capa INDEPENDIENTE a proposito: no sabe nada de Notion, de Buffer ni de marcas. Recibe
# bytes y devuelve una clave. Eso es lo que permite cambiar de proveedor tocando el config y no
# el motor, que es lo que va a necesitar cualquier instalacion distinta de la original.
#
# Por que existe, en una linea: Buffer NO re-hospeda la imagen al crear el post (verificado, ver
# la seccion 14 del documento del mecanismo), asi que el post queda apuntando a la URL de origen hasta el
# dia que sale. Una URL firmada de Notion expira en ~1 hora y daria una placa rota una semana
# despues, en un post ya publicado. De ahi que la placa tenga que vivir en una URL publica y
# estable, y de ahi este modulo.
#
# Se firma SigV4 a mano, con la libreria estandar. El sync no tiene dependencias externas y
# conviene que siga asi: corre desatendido, y una instalacion nueva no deberia tener que
# instalar nada para publicar una imagen.

import hashlib, hmac, json, pathlib, urllib.request, urllib.error
from datetime import datetime, timezone

TIMEOUT = 30
REGION, SERVICE = "auto", "s3"

# Se manda un User-Agent propio porque el de urllib esta bloqueado.
# `[CONFIRMADO]` 2026-08-07: la proteccion anti-bot de Cloudflare responde 403 a
# `Python-urllib/3.11` sobre el dominio del CDN, y 200 a curl, a python-requests y a los
# crawlers de las redes (LinkedInBot, facebookexternalhit, Twitterbot). O sea que NO afecta a la
# publicacion, pero si a cualquier verificacion hecha desde Python: un GET de control devolvia
# 403 sobre un objeto que estaba perfectamente subido. Es un falso negativo que cuesta caro,
# porque se lee como 'la subida fallo' y manda a arreglar lo que no esta roto.
# El valor se puede cambiar desde el config (`almacenamiento.user_agent`): cual UA quedo
# verificado contra un CDN concreto es un dato de instalacion, no del motor.
UA = "sync-contenido/1.0"

# Firma de los formatos que aceptan las redes. Se mira el contenido y no la extension: el nombre
# de un archivo lo pone una persona y puede mentir; los primeros bytes no.
FIRMAS = [
    (b"\x89PNG\r\n\x1a\n", "png", "image/png"),
    (b"\xff\xd8\xff",      "jpg", "image/jpeg"),
    (b"GIF87a",            "gif", "image/gif"),
    (b"GIF89a",            "gif", "image/gif"),
]


class ErrorPlaca(Exception):
    """Un problema con una placa concreta. No frena el sync: la fila se reporta y se sigue."""


def _bytes(url):
    """Descarga binaria. Se usa para traer el adjunto de Notion mientras su URL firmada todavia
    esta viva, que es el unico momento en que se puede."""
    try:
        r = urllib.request.urlopen(
            urllib.request.Request(url, headers={"User-Agent": UA}), timeout=TIMEOUT)
        return r.read()
    except urllib.error.HTTPError as e:
        raise ErrorPlaca(f"no se pudo descargar el adjunto (HTTP {e.code})") from None
    except urllib.error.URLError as e:
        raise ErrorPlaca(f"no se pudo descargar el adjunto ({e.reason})") from None


def tipo_de(contenido):
    """(ext, content_type) segun los bytes reales. WEBP se detecta aparte porque su firma no es
    un prefijo: es 'RIFF' + 4 bytes de tamano + 'WEBP'."""
    for firma, ext, ct in FIRMAS:
        if contenido.startswith(firma):
            return ext, ct
    if contenido[:4] == b"RIFF" and contenido[8:12] == b"WEBP":
        return "webp", "image/webp"
    raise ErrorPlaca("el archivo no es una imagen PNG, JPG, GIF ni WEBP")


class R2:
    def __init__(self, cfg_alm):
        cred = pathlib.Path(str(cfg_alm["credencial"])).expanduser()
        if not cred.exists():
            raise RuntimeError(f"no se encontro la credencial de almacenamiento: {cred}")
        c = json.loads(cred.read_text(encoding="utf-8"))
        for k in ("endpoint", "access_key_id", "secret_access_key", "bucket"):
            if not c.get(k):
                raise RuntimeError(f"{cred.name}: falta '{k}'")
        self.c = c
        self.peso_max = int(cfg_alm.get("peso_maximo_mb", 5)) * 1024 * 1024

    # -------------------------------------------------------------- firma
    def _pedido(self, metodo, key, cuerpo=b"", content_type=None, meta=None):
        host = self.c["endpoint"].removeprefix("https://")
        ruta = f"/{self.c['bucket']}/{key}"
        ahora = datetime.now(timezone.utc)
        amzdate, datestamp = ahora.strftime("%Y%m%dT%H%M%SZ"), ahora.strftime("%Y%m%d")
        payload_hash = hashlib.sha256(cuerpo).hexdigest()

        h = {"host": host, "x-amz-content-sha256": payload_hash, "x-amz-date": amzdate}
        if content_type:
            h["content-type"] = content_type
        for k, v in (meta or {}).items():
            h[f"x-amz-meta-{k}"] = v

        firmados = sorted(h)
        canon = (f"{metodo}\n{ruta}\n\n"
                 + "".join(f"{k}:{h[k].strip()}\n" for k in firmados) + "\n"
                 + ";".join(firmados) + "\n" + payload_hash)

        scope = f"{datestamp}/{REGION}/{SERVICE}/aws4_request"
        to_sign = (f"AWS4-HMAC-SHA256\n{amzdate}\n{scope}\n"
                   + hashlib.sha256(canon.encode()).hexdigest())

        k = ("AWS4" + self.c["secret_access_key"]).encode()
        for parte in (datestamp, REGION, SERVICE, "aws4_request"):
            k = hmac.new(k, parte.encode(), hashlib.sha256).digest()
        sig = hmac.new(k, to_sign.encode(), hashlib.sha256).hexdigest()

        h["Authorization"] = (f"AWS4-HMAC-SHA256 Credential={self.c['access_key_id']}/{scope}, "
                              f"SignedHeaders={';'.join(firmados)}, Signature={sig}")
        h["User-Agent"] = UA        # fuera de la firma a proposito: no esta en SignedHeaders
        return urllib.request.Request(self.c["endpoint"] + ruta,
                                      data=cuerpo if metodo == "PUT" else None,
                                      headers=h, method=metodo)

    # -------------------------------------------------------------- operaciones
    def existe(self, key):
        """HEAD antes de subir. Ahorra la escritura y hace la corrida idempotente: la placa que
        ya esta no se vuelve a subir nunca."""
        try:
            urllib.request.urlopen(self._pedido("HEAD", key), timeout=TIMEOUT)
            return True
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return False
            raise ErrorPlaca(f"R2 respondio {e.code} al consultar {key}") from None
        except urllib.error.URLError as e:
            raise ErrorPlaca(f"sin conexion con R2 ({e.reason})") from None

    def subir(self, key, contenido, content_type, meta=None):
        try:
            urllib.request.urlopen(
                self._pedido("PUT", key, contenido, content_type, meta), timeout=TIMEOUT)
        except urllib.error.HTTPError as e:
            cuerpo = e.read().decode("utf-8", "replace")[:300]
            raise ErrorPlaca(f"R2 rechazo la subida (HTTP {e.code}): {cuerpo}") from None
        except urllib.error.URLError as e:
            raise ErrorPlaca(f"sin conexion con R2 ({e.reason})") from None


def clave_de(contenido, ext):
    """La clave NO significa nada, y es deliberado.

    No lleva marca, ni fecha, ni id de pieza, asi que la URL publica no cuenta nada del sistema
    ni se puede enumerar. Al ser el hash del CONTENIDO se ganan tres cosas de arriba:
      - idempotencia: el mismo archivo da la misma clave y no se vuelve a subir;
      - version nueva = clave nueva, que es lo que hace que el hash de la seccion 8 dispare la
        actualizacion en Buffer sin que nadie coordine nada;
      - deduplicacion: la misma placa en dos piezas es un solo objeto.
    Y no hay que guardarla en ningun lado: se recalcula. Por eso el sistema no necesita una base
    de datos de archivos, que seria un segundo lugar donde el estado puede discrepar de Notion.
    """
    return f"{hashlib.sha256(contenido).hexdigest()[:32]}.{ext}"


def analizar(cliente, url_origen, cdn):
    """Descarga el adjunto, lo valida y calcula su URL publica. NO sube nada.

    Se separa del subir a proposito: si la fila ya declara esa misma URL, no hay que tocar R2 ni
    para preguntar. Una corrida diaria estable no hace una sola llamada al bucket. Y en seco se
    puede reportar igual que esa fila cambiaria, sin escribir nada."""
    contenido = _bytes(url_origen)
    if not contenido:
        raise ErrorPlaca("el adjunto vino vacio")
    if len(contenido) > cliente.peso_max:
        raise ErrorPlaca(f"la placa pesa {len(contenido)/1024/1024:.1f} MB y el maximo es "
                         f"{cliente.peso_max/1024/1024:.0f} MB")
    ext, content_type = tipo_de(contenido)
    key = clave_de(contenido, ext)
    return f"{cdn.rstrip('/')}/{key}", key, contenido, content_type, len(contenido)
