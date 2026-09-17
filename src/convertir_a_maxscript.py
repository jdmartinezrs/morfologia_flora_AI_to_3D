"""
==============================================================
CONVERSOR: coordenadas de silueta -> MAXScript (.ms)
==============================================================

Lee un archivo *_silueta.py generado por el extractor (o
cualquier archivo con una lista "puntos = [(x, y), ...]"),
simplifica el contorno con Douglas-Peucker, y genera un script
.ms para 3ds Max segun el --modo elegido:

  --modo extrusion   (comportamiento ORIGINAL de este script)
      Crea una Line (spline) cerrada y le aplica un modificador
      Extrude. Rapido, pero el volumen resultante es siempre
      plano/uniforme (sin relieve real).

  --modo domo | ondulado | venas | mapa_alturas   (NUEVO)
      Triangula el interior del contorno, calcula una altura por
      vertice segun el modo elegido, y construye una malla 3D
      CERRADA (superficie superior + inferior + pared lateral)
      con relieve real -- no una cascara extruida.

USO:
    # comportamiento de siempre (extrusion plana)
    python convertir_a_maxscript.py entrada_silueta.py salida.ms \
        --modo extrusion --tolerancia 0.8 --extrusion 15

    # relieve tipo domo
    python convertir_a_maxscript.py entrada_silueta.py salida.ms \
        --modo domo --altura-max 8 --subdivisiones 2

    # relieve ondulado (ondulaciones de margen + venacion simulada)
    python convertir_a_maxscript.py entrada.py salida.ms \
        --modo ondulado --altura-max 8 --amplitud-ondulacion 1.5

    # venas proceduales (nervio central + laterales)
    python convertir_a_maxscript.py entrada.py salida.ms \
        --modo venas --num-venas-laterales 7 --altura-vena 1.2

    # relieve a partir de una imagen de alturas real (ej. generada
    # con procesar_malla_capturada.py mapa-alturas)
    python convertir_a_maxscript.py entrada.py salida.ms \
        --modo mapa_alturas --imagen-alturas relieve.png --altura-max 8
==============================================================
"""

import re
import sys
import math
import argparse


# ==============================================================
# EXTRAER PUNTOS DEL ARCHIVO FUENTE (sin cambios)
# ==============================================================

def extraer_puntos(ruta_archivo):
    if ruta_archivo.endswith(".json"):
        import json
        with open(ruta_archivo, encoding="utf-8") as f:
            data = json.load(f)
        return [(float(x), float(y)) for x, y in data["puntos"]]

    with open(ruta_archivo, encoding="utf-8") as f:
        contenido = f.read()

    bloques = re.split(r"# Tipo:\s*(\w+)", contenido)

    if len(bloques) < 3:
        pares = re.findall(r"\(([-\d.]+),\s*([-\d.]+)\)", contenido)
        return [(float(x), float(y)) for x, y in pares]

    candidatos_exterior = []

    for i in range(1, len(bloques), 2):
        tipo = bloques[i]
        texto_bloque = bloques[i + 1]

        if tipo != "EXTERIOR":
            continue

        cierre = texto_bloque.find("]")
        texto_puntos = texto_bloque[:cierre] if cierre != -1 else texto_bloque

        pares = re.findall(r"\(([-\d.]+),\s*([-\d.]+)\)", texto_puntos)
        puntos = [(float(x), float(y)) for x, y in pares]

        if puntos:
            candidatos_exterior.append(puntos)

    if not candidatos_exterior:
        pares = re.findall(r"\(([-\d.]+),\s*([-\d.]+)\)", contenido)
        return [(float(x), float(y)) for x, y in pares]

    candidatos_exterior.sort(key=len, reverse=True)
    return candidatos_exterior[0]


# ==============================================================
# SIMPLIFICACION: DOUGLAS-PEUCKER (sin cambios)
# ==============================================================

def _distancia_punto_a_segmento(p, a, b):
    (px, py), (ax, ay), (bx, by) = p, a, b

    dx, dy = bx - ax, by - ay

    if dx == 0 and dy == 0:
        return ((px - ax) ** 2 + (py - ay) ** 2) ** 0.5

    t = ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)
    t = max(0.0, min(1.0, t))

    proy_x = ax + t * dx
    proy_y = ay + t * dy

    return ((px - proy_x) ** 2 + (py - proy_y) ** 2) ** 0.5


def simplificar_douglas_peucker(puntos, tolerancia):
    if len(puntos) < 3:
        return puntos[:]

    conservar = [False] * len(puntos)
    conservar[0] = True
    conservar[-1] = True

    pila = [(0, len(puntos) - 1)]

    while pila:
        inicio, fin = pila.pop()

        if fin - inicio < 2:
            continue

        a, b = puntos[inicio], puntos[fin]

        max_dist = -1.0
        max_idx = -1

        for i in range(inicio + 1, fin):
            d = _distancia_punto_a_segmento(puntos[i], a, b)
            if d > max_dist:
                max_dist = d
                max_idx = i

        if max_dist > tolerancia:
            conservar[max_idx] = True
            pila.append((inicio, max_idx))
            pila.append((max_idx, fin))

    return [p for p, k in zip(puntos, conservar) if k]


def _asegurar_poligono_simple(puntos, eps=1e-9):
    """Quita puntos duplicados consecutivos y el cierre duplicado
    (primer punto == ultimo punto), que rompe el ear clipping."""
    limpio = []
    for p in puntos:
        if not limpio or (abs(p[0] - limpio[-1][0]) > eps or abs(p[1] - limpio[-1][1]) > eps):
            limpio.append(p)
    if len(limpio) > 1 and abs(limpio[0][0] - limpio[-1][0]) < eps and abs(limpio[0][1] - limpio[-1][1]) < eps:
        limpio.pop()
    return limpio


# ==============================================================
# MODO "extrusion": GENERAR MAXSCRIPT CON SPLINE + EXTRUDE
# (identico al comportamiento original del script que enviaste)
# ==============================================================

def generar_maxscript_extrusion(
    puntos,
    nombre_objeto="Hoja_Silueta",
    altura_extrusion=15.0,
    escala=1.0,
    segmentos_extrusion=1,
    convertir_a_poly=True,
):
    # Centrar en el origen (bounding box), y voltear Y
    # (en la imagen Y crece hacia abajo; en Max normalmente
    # queremos Y "normal" en el plano XY)
    xs = [p[0] for p in puntos]
    ys = [p[1] for p in puntos]

    centro_x = (min(xs) + max(xs)) / 2
    centro_y = (min(ys) + max(ys)) / 2

    lineas = []

    lineas.append("-- ==========================================================")
    lineas.append("-- SILUETA 3D GENERADA AUTOMATICAMENTE (modo: extrusion)")
    lineas.append("-- Puntos en el contorno: {}".format(len(puntos)))
    lineas.append("-- ==========================================================")
    lineas.append("")
    lineas.append("delete objects")
    lineas.append("")
    lineas.append("shp = splineShape pos:[0,0,0] name:\"{}\"".format(nombre_objeto))
    lineas.append("addNewSpline shp")
    lineas.append("")

    for x, y in puntos:
        px = (x - centro_x) * escala
        py = -(y - centro_y) * escala

        lineas.append(
            "addKnot shp 1 #corner #line [{:.3f}, {:.3f}, 0]".format(px, py)
        )

    lineas.append("")
    lineas.append("close shp 1")
    lineas.append("updateShape shp")
    lineas.append("")
    lineas.append("-- Extrusion: le da volumen 3D uniforme a la silueta")
    lineas.append(
        "addModifier shp (Extrude amount:{} segments:{} capStart:on capEnd:on)".format(
            altura_extrusion, segmentos_extrusion
        )
    )
    lineas.append("")

    if convertir_a_poly:
        lineas.append("-- Convertir a Editable Poly para facilitar edicion posterior")
        lineas.append("convertToPoly shp")
        lineas.append("")

    lineas.append("max zoomext sel all")
    lineas.append("")
    lineas.append(
        'print ("Silueta 3D creada: " + shp.name + " (" + {} as string + " puntos)")'.format(
            len(puntos)
        )
    )

    return "\n".join(lineas)


# ==============================================================
# MODOS DE RELIEVE ("domo", "ondulado", "venas", "mapa_alturas")
# ==============================================================

# --- Triangulacion del interior: ear clipping -------------------

def _area_poligono(pts):
    a = 0.0
    n = len(pts)
    for i in range(n):
        x1, y1 = pts[i]
        x2, y2 = pts[(i + 1) % n]
        a += x1 * y2 - x2 * y1
    return a / 2.0


def _es_ccw(pts):
    return _area_poligono(pts) > 0


def _cruz(o, a, b):
    return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])


def _punto_en_triangulo(p, a, b, c):
    d1 = _cruz(a, b, p)
    d2 = _cruz(b, c, p)
    d3 = _cruz(c, a, p)
    tiene_neg = (d1 < 0) or (d2 < 0) or (d3 < 0)
    tiene_pos = (d1 > 0) or (d2 > 0) or (d3 > 0)
    return not (tiene_neg and tiene_pos)


def triangular_ear_clipping(puntos):
    """Triangula un poligono simple (sin auto-interseccion).
    Devuelve una lista de triangulos como indices (i, j, k)
    referidos a la lista `puntos` original."""
    pts = puntos[:]
    if not _es_ccw(pts):
        pts = pts[::-1]
        indices = list(range(len(puntos) - 1, -1, -1))
    else:
        indices = list(range(len(puntos)))

    anillo = list(zip(indices, pts))
    triangulos = []

    intentos_sin_avance = 0
    while len(anillo) > 3 and intentos_sin_avance < len(anillo) * 2 + 10:
        n = len(anillo)
        oreja_encontrada = False
        for i in range(n):
            i_prev = (i - 1) % n
            i_next = (i + 1) % n
            idx_a, a = anillo[i_prev]
            idx_b, b = anillo[i]
            idx_c, c = anillo[i_next]

            if _cruz(a, b, c) <= 1e-12:
                continue  # reflejo (concavo), no puede ser oreja

            hay_punto_dentro = False
            for j in range(n):
                if j in (i_prev, i, i_next):
                    continue
                _, p = anillo[j]
                if _punto_en_triangulo(p, a, b, c):
                    hay_punto_dentro = True
                    break

            if hay_punto_dentro:
                continue

            triangulos.append((idx_a, idx_b, idx_c))
            del anillo[i]
            oreja_encontrada = True
            intentos_sin_avance = 0
            break

        if not oreja_encontrada:
            intentos_sin_avance += 1
            if len(anillo) > 3:
                del anillo[0]

    if len(anillo) == 3:
        (ia, _), (ib, _), (ic, _) = anillo
        triangulos.append((ia, ib, ic))

    return triangulos


# --- Subdivision 1-a-4 con cache de puntos medios ----------------

def subdividir_malla(vertices, triangulos, veces):
    verts = list(vertices)
    tris = list(triangulos)

    for _ in range(veces):
        cache_medios = {}

        def punto_medio(i, j):
            clave = (i, j) if i < j else (j, i)
            if clave in cache_medios:
                return cache_medios[clave]
            xi, yi = verts[i]
            xj, yj = verts[j]
            nuevo = ((xi + xj) / 2.0, (yi + yj) / 2.0)
            verts.append(nuevo)
            nuevo_idx = len(verts) - 1
            cache_medios[clave] = nuevo_idx
            return nuevo_idx

        nuevos_tris = []
        for (a, b, c) in tris:
            mab = punto_medio(a, b)
            mbc = punto_medio(b, c)
            mca = punto_medio(c, a)
            nuevos_tris.append((a, mab, mca))
            nuevos_tris.append((b, mbc, mab))
            nuevos_tris.append((c, mca, mbc))
            nuevos_tris.append((mab, mbc, mca))
        tris = nuevos_tris

    return verts, tris


# --- Funciones de altura (relieve) -------------------------------

def _distancia_a_borde(p, contorno):
    mejor = float("inf")
    n = len(contorno)
    for i in range(n):
        a = contorno[i]
        b = contorno[(i + 1) % n]
        d = _distancia_punto_a_segmento(p, a, b)
        if d < mejor:
            mejor = d
    return mejor


def _eje_principal(contorno):
    n = len(contorno)
    cx = sum(p[0] for p in contorno) / n
    cy = sum(p[1] for p in contorno) / n

    sxx = sum((p[0] - cx) ** 2 for p in contorno) / n
    syy = sum((p[1] - cy) ** 2 for p in contorno) / n
    sxy = sum((p[0] - cx) * (p[1] - cy) for p in contorno) / n

    traza = sxx + syy
    det = sxx * syy - sxy * sxy
    disc = max(traza * traza / 4 - det, 0.0)
    raiz = disc ** 0.5
    lam1 = traza / 2 + raiz

    if abs(sxy) > 1e-9:
        vx, vy = lam1 - syy, sxy
    else:
        vx, vy = (1.0, 0.0) if sxx >= syy else (0.0, 1.0)
    norma = (vx * vx + vy * vy) ** 0.5 or 1.0
    vx, vy = vx / norma, vy / norma

    wx, wy = -vy, vx
    return (cx, cy), (vx, vy), (wx, wy)


def _dos_puntos_mas_lejanos(contorno):
    mejor_d = -1.0
    mejor_par = (0, 1)
    n = len(contorno)
    for i in range(n):
        for j in range(i + 1, n):
            d = (contorno[i][0] - contorno[j][0]) ** 2 + (contorno[i][1] - contorno[j][1]) ** 2
            if d > mejor_d:
                mejor_d = d
                mejor_par = (i, j)
    return contorno[mejor_par[0]], contorno[mejor_par[1]]


def _generar_venas_procedurales(contorno, num_laterales, angulo_grados=35.0):
    p_a, p_b = _dos_puntos_mas_lejanos(contorno)
    midrib = (p_a, p_b)
    mx, my = midrib[1][0] - midrib[0][0], midrib[1][1] - midrib[0][1]
    largo = (mx * mx + my * my) ** 0.5 or 1.0
    dx, dy = mx / largo, my / largo
    nx, ny = -dy, dx

    venas = [midrib]
    ang = math.radians(angulo_grados)

    if num_laterales > 0:
        paso = largo / (num_laterales + 1)
        for i in range(1, num_laterales + 1):
            t = i * paso
            base_x = midrib[0][0] + dx * t
            base_y = midrib[0][1] + dy * t
            longitud_lateral = largo * 0.4
            for signo in (1, -1):
                dir_x = dx * math.cos(ang) + signo * nx * math.sin(ang)
                dir_y = dy * math.cos(ang) + signo * ny * math.sin(ang)
                punta_x = base_x + dir_x * longitud_lateral
                punta_y = base_y + dir_y * longitud_lateral
                venas.append(((base_x, base_y), (punta_x, punta_y)))

    return venas


def calcular_alturas(
    vertices,
    contorno_original,
    modo,
    altura_max,
    exponente,
    amplitud_ondulacion,
    frecuencia_ondulacion,
    num_venas_laterales,
    ancho_vena,
    altura_vena,
    imagen_alturas,
):
    dist_max = max(_distancia_a_borde(p, contorno_original) for p in vertices) or 1.0

    if modo == "mapa_alturas":
        return _alturas_desde_imagen(vertices, contorno_original, imagen_alturas, altura_max)

    alturas = []

    venas = None
    if modo == "venas":
        venas = _generar_venas_procedurales(contorno_original, num_venas_laterales)

    centro, eje_mayor, eje_menor = None, None, None
    if modo == "ondulado":
        centro, eje_mayor, eje_menor = _eje_principal(contorno_original)

    for p in vertices:
        d_borde = _distancia_a_borde(p, contorno_original)
        base = altura_max * (d_borde / dist_max) ** exponente

        if modo == "domo":
            h = base

        elif modo == "ondulado":
            cx, cy = centro
            rel_x = (p[0] - cx) * eje_mayor[0] + (p[1] - cy) * eje_mayor[1]
            rel_y = (p[0] - cx) * eje_menor[0] + (p[1] - cy) * eje_menor[1]
            onda_margen = amplitud_ondulacion * math.sin(frecuencia_ondulacion * rel_y * 0.3)
            onda_venas = (amplitud_ondulacion * 0.4) * math.sin(frecuencia_ondulacion * 2.2 * rel_x * 0.05)
            h = base + onda_margen * (d_borde / dist_max) + onda_venas

        elif modo == "venas":
            d_vena_min = min(_distancia_punto_a_segmento(p, seg[0], seg[1]) for seg in venas)
            cresta = altura_vena * math.exp(-(d_vena_min / max(ancho_vena, 1e-6)) ** 2)
            h = base + cresta

        else:
            raise ValueError("Modo de relieve desconocido: {}".format(modo))

        alturas.append(h)

    return alturas


def _alturas_desde_imagen(vertices, contorno_original, ruta_imagen, altura_max):
    try:
        from PIL import Image
    except ImportError:
        raise SystemExit(
            "El modo 'mapa_alturas' necesita la libreria Pillow. "
            "Instalala con: pip install Pillow --break-system-packages"
        )

    img = Image.open(ruta_imagen).convert("L")
    ancho_img, alto_img = img.size
    pixeles = img.load()

    xs = [p[0] for p in contorno_original]
    ys = [p[1] for p in contorno_original]
    x_min, x_max = min(xs), max(xs)
    y_min, y_max = min(ys), max(ys)
    rango_x = (x_max - x_min) or 1.0
    rango_y = (y_max - y_min) or 1.0

    alturas = []
    for (px, py) in vertices:
        u = (px - x_min) / rango_x
        v = (py - y_min) / rango_y
        ix = min(max(int(u * (ancho_img - 1)), 0), ancho_img - 1)
        iy = min(max(int((1 - v) * (alto_img - 1)), 0), alto_img - 1)
        gris = pixeles[ix, iy] / 255.0
        alturas.append(gris * altura_max)

    return alturas


# --- Construccion de la malla 3D cerrada (top + bottom + pared) -

def construir_malla_solida(vertices_2d, triangulos, alturas, grosor, simetria):
    n = len(vertices_2d)

    if simetria:
        z_top = [h / 2.0 for h in alturas]
        z_bottom = [-h / 2.0 for h in alturas]
    else:
        z_top = [h for h in alturas]
        z_bottom = [-grosor for _ in alturas]

    verts_3d = []
    for i in range(n):
        x, y = vertices_2d[i]
        verts_3d.append((x, y, z_top[i]))
    offset_bottom = len(verts_3d)
    for i in range(n):
        x, y = vertices_2d[i]
        verts_3d.append((x, y, z_bottom[i]))

    caras = []
    for (a, b, c) in triangulos:
        caras.append((a, b, c))
    for (a, b, c) in triangulos:
        caras.append((c + offset_bottom, b + offset_bottom, a + offset_bottom))

    conteo_aristas = {}
    for (a, b, c) in triangulos:
        for u, v in ((a, b), (b, c), (c, a)):
            clave = (u, v) if u < v else (v, u)
            conteo_aristas[clave] = conteo_aristas.get(clave, 0) + 1

    aristas_borde = [ar for ar, cnt in conteo_aristas.items() if cnt == 1]

    adyacencia = {}
    for (u, v) in aristas_borde:
        adyacencia.setdefault(u, []).append(v)
        adyacencia.setdefault(v, []).append(u)

    anillo = []
    if adyacencia:
        inicio = next(iter(adyacencia))
        actual = inicio
        anterior = None
        visitados = set()
        while True:
            anillo.append(actual)
            visitados.add(actual)
            vecinos = [x for x in adyacencia.get(actual, []) if x != anterior]
            siguiente = None
            for v in vecinos:
                if v == inicio and len(anillo) > 2:
                    siguiente = v
                    break
                if v not in visitados:
                    siguiente = v
                    break
            if siguiente is None or siguiente == inicio:
                break
            anterior, actual = actual, siguiente

    for k in range(len(anillo)):
        i0 = anillo[k]
        i1 = anillo[(k + 1) % len(anillo)]
        top0, top1 = i0, i1
        bot0, bot1 = i0 + offset_bottom, i1 + offset_bottom
        caras.append((top0, top1, bot1))
        caras.append((top0, bot1, bot0))

    return verts_3d, caras


# --- Exportar la malla con relieve a MAXScript -------------------

def generar_maxscript_malla(
    vertices_3d,
    caras,
    nombre_objeto="Hoja_3D",
    escala=1.0,
    suavizar=True,
    iteraciones_suavizado=1,
    convertir_a_poly=True,
):
    xs = [v[0] for v in vertices_3d]
    ys = [v[1] for v in vertices_3d]
    centro_x = (min(xs) + max(xs)) / 2
    centro_y = (min(ys) + max(ys)) / 2

    lineas = []
    lineas.append("-- ==========================================================")
    lineas.append("-- MALLA 3D CON RELIEVE GENERADA AUTOMATICAMENTE")
    lineas.append("-- Vertices: {}  |  Caras: {}".format(len(vertices_3d), len(caras)))
    lineas.append("-- ==========================================================")
    lineas.append("")
    lineas.append("delete objects")
    lineas.append("")
    lineas.append("vertsArr = #()")

    for (x, y, z) in vertices_3d:
        px = (x - centro_x) * escala
        py = -(y - centro_y) * escala
        pz = z * escala
        lineas.append("append vertsArr [{:.4f}, {:.4f}, {:.4f}]".format(px, py, pz))

    lineas.append("")
    lineas.append("carasArr = #()")
    for (a, b, c) in caras:
        lineas.append("append carasArr [{}, {}, {}]".format(a + 1, b + 1, c + 1))

    lineas.append("")
    lineas.append('obj3d = mesh vertices:vertsArr faces:carasArr name:"{}"'.format(nombre_objeto))
    lineas.append("update obj3d")
    lineas.append("")

    if suavizar:
        lineas.append("-- Suavizado: relaja la malla para que el relieve luzca organico")
        lineas.append(
            "addModifier obj3d (MeshSmooth iterations:{} strength:0.5)".format(iteraciones_suavizado)
        )
        lineas.append("")

    if convertir_a_poly:
        lineas.append("-- Convertir a Editable Poly para edicion posterior")
        lineas.append("convertToPoly obj3d")
        lineas.append("polyop.autoSmooth obj3d degrees:60")
        lineas.append("")

    lineas.append("max zoomext sel all")
    lineas.append("")
    lineas.append(
        'print ("Malla 3D creada: " + obj3d.name + " (" + {} as string + " verts, " + {} as string + " caras)")'.format(
            len(vertices_3d), len(caras)
        )
    )

    return "\n".join(lineas)


# ==============================================================
# MAIN: un unico punto de entrada que decide segun --modo
# ==============================================================

def convertir(
    ruta_entrada,
    ruta_salida,
    modo="extrusion",
    tolerancia=0.8,
    nombre_objeto=None,
    escala=1.0,
    # parametros de extrusion (comportamiento original)
    altura_extrusion=15.0,
    # parametros de relieve (nuevos modos)
    subdivisiones=2,
    altura_max=8.0,
    exponente=1.5,
    amplitud_ondulacion=1.0,
    frecuencia_ondulacion=3.0,
    num_venas_laterales=6,
    ancho_vena=1.5,
    altura_vena=1.0,
    grosor=0.8,
    simetria=False,
    imagen_alturas=None,
    suavizar=True,
):
    puntos = extraer_puntos(ruta_entrada)

    if not puntos:
        raise ValueError("No se encontraron coordenadas en el archivo.")

    puntos_simplificados = simplificar_douglas_peucker(puntos, tolerancia)

    if nombre_objeto is None:
        nombre_objeto = "Silueta_3D" if modo == "extrusion" else "Hoja_3D"

    # -------- MODO ORIGINAL: spline + extrude ---------------------
    if modo == "extrusion":
        codigo = generar_maxscript_extrusion(
            puntos_simplificados,
            nombre_objeto=nombre_objeto,
            altura_extrusion=altura_extrusion,
            escala=escala,
        )
        with open(ruta_salida, "w", encoding="utf-8") as f:
            f.write(codigo)
        return {
            "modo": modo,
            "puntos_originales": len(puntos),
            "puntos_simplificados": len(puntos_simplificados),
            "reduccion_pct": round(100 * (1 - len(puntos_simplificados) / len(puntos)), 1),
            "archivo_salida": ruta_salida,
        }

    # -------- MODOS NUEVOS: malla 3D con relieve real -------------
    contorno = _asegurar_poligono_simple(puntos_simplificados)
    if len(contorno) < 3:
        raise ValueError("El contorno simplificado quedo con menos de 3 puntos; baja --tolerancia.")

    triangulos_base = triangular_ear_clipping(contorno)
    if not triangulos_base:
        raise ValueError(
            "No se pudo triangular el contorno (posible auto-interseccion). "
            "Proba con --tolerancia mas bajo."
        )

    n_tri_final_estimado = len(triangulos_base) * (4 ** subdivisiones)
    if n_tri_final_estimado > 150000:
        raise ValueError(
            "La combinacion de puntos de contorno ({}) y --subdivisiones ({}) "
            "generaria ~{} triangulos, demasiados para un .ms manejable. "
            "Baja --subdivisiones o sube --tolerancia.".format(
                len(triangulos_base), subdivisiones, n_tri_final_estimado
            )
        )

    vertices_2d, triangulos = subdividir_malla(contorno, triangulos_base, subdivisiones)

    alturas = calcular_alturas(
        vertices_2d,
        contorno,
        modo=modo,
        altura_max=altura_max,
        exponente=exponente,
        amplitud_ondulacion=amplitud_ondulacion,
        frecuencia_ondulacion=frecuencia_ondulacion,
        num_venas_laterales=num_venas_laterales,
        ancho_vena=ancho_vena,
        altura_vena=altura_vena,
        imagen_alturas=imagen_alturas,
    )

    vertices_3d, caras = construir_malla_solida(
        vertices_2d, triangulos, alturas, grosor=grosor, simetria=simetria
    )

    codigo = generar_maxscript_malla(
        vertices_3d, caras, nombre_objeto=nombre_objeto, escala=escala, suavizar=suavizar
    )

    with open(ruta_salida, "w", encoding="utf-8") as f:
        f.write(codigo)

    return {
        "modo": modo,
        "puntos_contorno": len(contorno),
        "triangulos_base": len(triangulos_base),
        "vertices_totales": len(vertices_3d),
        "caras_totales": len(caras),
        "archivo_salida": ruta_salida,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Convierte coordenadas de silueta a MAXScript: extrusion plana (original) o malla 3D con relieve (nuevo)"
    )
    parser.add_argument("entrada", help="Archivo .py/.json con la lista de puntos")
    parser.add_argument("salida", help="Archivo .ms de salida")
    parser.add_argument(
        "--modo",
        choices=["extrusion", "domo", "ondulado", "venas", "mapa_alturas"],
        default="extrusion",
        help="'extrusion' = comportamiento original (spline+extrude, plano). "
             "Los demas generan una malla 3D con relieve real.",
    )
    parser.add_argument("--tolerancia", type=float, default=0.8,
                         help="Tolerancia de simplificacion Douglas-Peucker")
    parser.add_argument("--escala", type=float, default=1.0)
    parser.add_argument("--nombre", type=str, default=None)

    # -- parametros del modo "extrusion" (originales) --
    parser.add_argument("--extrusion", type=float, default=15.0,
                         help="[modo extrusion] Altura de la extrusion 3D")

    # -- parametros de los modos de relieve (nuevos) --
    parser.add_argument("--subdivisiones", type=int, default=2,
                         help="[modos de relieve] Detalle interior de la malla (x4 triangulos por nivel)")
    parser.add_argument("--altura-max", type=float, default=8.0)
    parser.add_argument("--exponente", type=float, default=1.5,
                         help="Forma del domo base: 1=conico, >1 mas plano al centro")
    parser.add_argument("--amplitud-ondulacion", type=float, default=1.0)
    parser.add_argument("--frecuencia-ondulacion", type=float, default=3.0)
    parser.add_argument("--num-venas-laterales", type=int, default=6)
    parser.add_argument("--ancho-vena", type=float, default=1.5)
    parser.add_argument("--altura-vena", type=float, default=1.0)
    parser.add_argument("--grosor", type=float, default=0.8,
                         help="Grosor de la hoja cuando --simetria no esta activo")
    parser.add_argument("--simetria", action="store_true")
    parser.add_argument("--imagen-alturas", type=str, default=None,
                         help="[modo mapa_alturas] Imagen en escala de grises con el relieve")
    parser.add_argument("--sin-suavizado", action="store_true")

    args = parser.parse_args()

    if args.modo == "mapa_alturas" and not args.imagen_alturas:
        parser.error("--modo mapa_alturas requiere --imagen-alturas")

    resultado = convertir(
        args.entrada,
        args.salida,
        modo=args.modo,
        tolerancia=args.tolerancia,
        nombre_objeto=args.nombre,
        escala=args.escala,
        altura_extrusion=args.extrusion,
        subdivisiones=args.subdivisiones,
        altura_max=args.altura_max,
        exponente=args.exponente,
        amplitud_ondulacion=args.amplitud_ondulacion,
        frecuencia_ondulacion=args.frecuencia_ondulacion,
        num_venas_laterales=args.num_venas_laterales,
        ancho_vena=args.ancho_vena,
        altura_vena=args.altura_vena,
        grosor=args.grosor,
        simetria=args.simetria,
        imagen_alturas=args.imagen_alturas,
        suavizar=not args.sin_suavizado,
    )

    print("Modo:", resultado["modo"])
    if resultado["modo"] == "extrusion":
        print("Puntos originales:", resultado["puntos_originales"])
        print("Puntos simplificados:", resultado["puntos_simplificados"])
        print("Reduccion:", resultado["reduccion_pct"], "%")
    else:
        print("Puntos de contorno:", resultado["puntos_contorno"])
        print("Triangulos base:", resultado["triangulos_base"])
        print("Vertices totales:", resultado["vertices_totales"])
        print("Caras totales:", resultado["caras_totales"])
    print("Archivo generado:", resultado["archivo_salida"])