"""
==============================================================
MODELO DE FORMA POR ESPECIE (morfometria geometrica) - 2D + 3D
==============================================================

Toma varias muestras REALES de la misma especie (8-10+),
resuelve la correspondencia de puntos entre ellas, las alinea,
calcula la forma promedio y un modelo PCA de variacion natural.

Con eso, "dame una hoja de mango" deja de ser "repite una foto"
y pasa a ser "genera una silueta nueva, fiel a como varian las
hojas de mango reales que ya fotografiaste".

Esta version agrega el flujo 3D descrito en la investigacion de
"Captura de Relieve 3D en Morfologia Vegetal": en vez de modelar
solo el CONTORNO (x, y), se puede modelar el CONTORNO + una
GRILLA INTERIOR con altura h(x, y) (x, y, z), capturando
ondulaciones, venas y curvatura reales de cada especie.

------------------------------------------------------------
IDEA CLAVE DE LA EXTENSION A 3D
------------------------------------------------------------

Procrustes generalizado y PCA NO dependen de que los puntos sean
2D: son operaciones sobre vectores en R^D (centrar, rotar,
escalar, promediar, proyectar en componentes principales). Lo
unico realmente especifico de 2D en el codigo original era:

  1. calcular el eje mas largo de la hoja via un ANGULO
     (arctan2), en vez de un vector direccion generico
  2. re-muestrear la polilinea indexando columnas [:,0] y [:,1]
     a mano, en vez de por cada columna disponible
  3. reconstruir puntos con "// 2" fijo al cerrar el pipeline

Arreglando esos tres puntos, TODO el resto (Procrustes, deteccion
de atipicos, PCA, generacion de variantes) sirve sin cambios
tanto para (N, 2) como para (N, 3).

Lo que SI es nuevo para 3D es la CORRESPONDENCIA de landmarks de
superficie (no solo de contorno): para eso se agrega una grilla
de posiciones RELATIVAS (u, v) fija para toda la especie, y se
interpola la altura z de cada landmark desde la nube de puntos
3D real de cada hoja (ver Fase 1/2 del documento de
investigacion: fotogrametria / shape-from-shading -> nube de
puntos -> displacement).

------------------------------------------------------------
FLUJO 2D (silueta, sin cambios de comportamiento)
------------------------------------------------------------

1. extraer_puntos(archivo)              -> lee el contorno crudo
2. construir_landmarks(puntos, n_lado)  -> ancla apice/base y
                                            re-muestrea AMBOS
                                            lados por separado
3. analisis_procrustes_generalizado()   -> alinea todas las
                                            muestras y calcula
                                            la forma promedio
4. construir_modelo_pca()               -> modos de variacion
                                            natural de la especie
5. generar_variante()                   -> nueva hoja realista

------------------------------------------------------------
FLUJO 3D (silueta + relieve, nuevo)
------------------------------------------------------------

1. extraer_puntos_3d(archivo)              -> nube de puntos (x,y,z)
                                               reconstruida de UNA hoja
2. construir_landmarks_3d(puntos, ...)     -> contorno 2D (mismo
                                               algoritmo que en 2D)
                                               + grilla interior de
                                               posicion relativa fija
                                               + altura z interpolada
                                               (IDW) desde la nube
3. analisis_procrustes_generalizado()      -> EL MISMO codigo que en
                                               2D, ya funciona en R^3
4. construir_modelo_pca(..., dimension=3)  -> EL MISMO codigo, solo
                                               se le avisa la dimension
5. generar_variante() / generar_hoja_de_especie(..., sufijo_modelo="_3d")
                                            -> nueva hoja con relieve

------------------------------------------------------------
REQUISITOS DE LAS FOTOS / NUBES DE PUNTOS (importante)
------------------------------------------------------------

2D (sin cambios):
  - Una hoja por foto, extendida y plana (no doblada)
  - Fondo liso y contrastante
  - Si el peciolo quedo incluido en el recorte, cortalo antes

3D (nuevo):
  - La nube de puntos por hoja debe venir de una reconstruccion
    ya hecha (fotogrametria / COLMAP / shape-from-shading, ver
    Fase 1 del documento de investigacion). Este modulo NO
    reconstruye 3D desde fotos; solo modela estadisticamente una
    nube de puntos ya reconstruida.
  - Se asume que el eje z es "altura/relieve" y que x, y
    corresponden aproximadamente a la vista cenital (igual que
    el contorno 2D). Si la reconstruccion viene en otro sistema
    de coordenadas, reorientala antes de pasarla por aca.
  - La grilla interior usa posiciones RELATIVAS al bounding box
    de cada hoja, no un recorte exacto de su silueta irregular:
    en hojas muy lobuladas, algunos puntos de grilla pueden caer
    cerca del borde real en vez de estrictamente dentro. Esto es
    un compromiso deliberado para garantizar correspondencia
    (mismo numero de landmarks, mismo significado por indice) en
    todas las muestras, requisito de Procrustes/PCA.

==============================================================
"""

import json
import os
import re

import numpy as np


# ==============================================================
# 1. EXTRAER PUNTOS DE UN ARCHIVO
# ==============================================================

def extraer_puntos(ruta_archivo):
    """
    Lee un archivo *_silueta.py y devuelve SOLO los puntos del
    contorno EXTERIOR (la silueta general de la hoja/planta).

    Importante: cuando la foto genera huecos interiores (comun en
    hojas con perforaciones, o en plantas como suculentas/cactus
    con texturas que el umbral confunde con huecos), el archivo
    trae VARIOS bloques de coordenadas (EXTERIOR + HUECO + DETALLE).
    Si se mezclan todos, la forma queda corrupta. Por eso se
    identifica cada bloque por su comentario "# Tipo: ..." y se
    usa unicamente el EXTERIOR mas grande.
    """
    with open(ruta_archivo, encoding="utf-8") as f:
        contenido = f.read()

    bloques = re.split(r"# Tipo:\s*(\w+)", contenido)

    if len(bloques) < 3:
        pares = re.findall(r"\(([-\d.]+),\s*([-\d.]+)\)", contenido)
        return np.array([[float(x), float(y)] for x, y in pares])

    candidatos_exterior = []

    for i in range(1, len(bloques), 2):
        tipo = bloques[i]
        texto_bloque = bloques[i + 1]

        if tipo != "EXTERIOR":
            continue

        cierre = texto_bloque.find("]")
        texto_puntos = texto_bloque[:cierre] if cierre != -1 else texto_bloque

        pares = re.findall(r"\(([-\d.]+),\s*([-\d.]+)\)", texto_puntos)
        puntos = np.array([[float(x), float(y)] for x, y in pares])

        if len(puntos) > 0:
            candidatos_exterior.append(puntos)

    if not candidatos_exterior:
        raise ValueError(
            f"No se encontro un contorno EXTERIOR valido en {ruta_archivo}"
        )

    candidatos_exterior.sort(key=len, reverse=True)
    return candidatos_exterior[0]


def extraer_puntos_3d(ruta_archivo):
    """
    Lee una nube de puntos / malla 3D reconstruida (fotogrametria,
    shape-from-shading, etc., ver Fase 1 del documento de
    investigacion) y devuelve un arreglo (N, 3) con columnas x, y, z.

    Formatos soportados:

      1) JSON con la forma {"puntos": [[x, y, z], ...]}
         (mismo esquema de salida que generar_hoja_de_especie, pero
         con 3 coordenadas por punto en vez de 2).

      2) Archivo *_relieve.py con bloques "# Tipo: SUPERFICIE"
         seguidos de tuplas (x, y, z), analogo a extraer_puntos()
         pero para nubes de puntos en vez de contornos 2D.
    """
    if ruta_archivo.endswith(".json"):
        with open(ruta_archivo, encoding="utf-8") as f:
            datos = json.load(f)
        puntos = np.array(datos["puntos"], dtype=float)
        if puntos.ndim != 2 or puntos.shape[1] != 3:
            raise ValueError(
                f"{ruta_archivo} no contiene puntos 3D validos "
                f"(se esperaban filas de 3 coordenadas)"
            )
        return puntos

    with open(ruta_archivo, encoding="utf-8") as f:
        contenido = f.read()

    bloques = re.split(r"# Tipo:\s*(\w+)", contenido)
    patron_triple = r"\(([-\d.]+),\s*([-\d.]+),\s*([-\d.]+)\)"

    if len(bloques) < 3:
        tripletas = re.findall(patron_triple, contenido)
        if not tripletas:
            raise ValueError(
                f"No se encontraron puntos 3D (x, y, z) en {ruta_archivo}"
            )
        return np.array([[float(x), float(y), float(z)] for x, y, z in tripletas])

    candidatos_superficie = []

    for i in range(1, len(bloques), 2):
        tipo = bloques[i]
        texto_bloque = bloques[i + 1]

        if tipo not in ("SUPERFICIE", "EXTERIOR"):
            continue

        cierre = texto_bloque.find("]")
        texto_puntos = texto_bloque[:cierre] if cierre != -1 else texto_bloque

        tripletas = re.findall(patron_triple, texto_puntos)
        puntos = np.array([[float(x), float(y), float(z)] for x, y, z in tripletas])

        if len(puntos) > 0:
            candidatos_superficie.append(puntos)

    if not candidatos_superficie:
        raise ValueError(
            f"No se encontro un bloque de superficie 3D valido en {ruta_archivo}"
        )

    candidatos_superficie.sort(key=len, reverse=True)
    return candidatos_superficie[0]


# ==============================================================
# 2. CORRESPONDENCIA: ANCLAR APICE/BASE Y RE-MUESTREAR POR LADO
#    (generalizado: funciona con puntos de 2 O 3 columnas)
# ==============================================================

def _direccion_principal(puntos):
    """
    Devuelve el autovector unitario de mayor varianza de 'puntos'.
    Generaliza el antiguo calculo por angulo (valido solo en 2D)
    a cualquier numero de columnas: 2 (x,y) o 3 (x,y,z).
    """
    centrado = puntos - puntos.mean(axis=0)
    cov = np.cov(centrado.T)
    valores, vectores = np.linalg.eigh(cov)
    direccion = vectores[:, np.argmax(valores)]
    return direccion


def _eje_principal(puntos):
    """
    (Solo 2D) Angulo en radianes del eje mas largo de la hoja.
    Se conserva por compatibilidad con codigo existente; por
    dentro usa _direccion_principal, que es la version generica.
    """
    direccion = _direccion_principal(puntos)
    return np.arctan2(direccion[1], direccion[0])


def _encontrar_apice_base(puntos):
    """
    Proyecta todos los puntos sobre el eje de mayor varianza y
    toma los extremos como apice/base. Funciona igual para
    puntos (N, 2) o (N, 3): la proyeccion se hace sobre todas las
    columnas disponibles.

    Nota 3D: en hojas con mucha curvatura longitudinal, proyectar
    sobre x,y,z en vez de solo x,y puede desplazar ligeramente el
    apice/base detectado respecto al modelo 2D puro. Si eso pesa
    para tu especie, pasa puntos[:, :2] en vez de puntos[:, :3].

    Retorna los INDICES (en el arreglo original) del apice y base.
    """
    direccion = _direccion_principal(puntos)
    centro = puntos.mean(axis=0)
    proyeccion = (puntos - centro) @ direccion

    idx_apice = int(np.argmax(proyeccion))
    idx_base = int(np.argmin(proyeccion))

    return idx_apice, idx_base


def _resamplear_polilinea(polilinea, n_puntos):
    """
    Re-muestrea una polilinea abierta a n_puntos equidistantes
    por longitud de arco (incluye siempre el primer y ultimo
    punto). Funciona para polilineas de cualquier numero de
    columnas (2D: x,y — 3D: x,y,z): la longitud de arco usa la
    norma euclidiana completa, y cada columna se interpola por
    separado sobre esa misma longitud de arco.
    """
    polilinea = np.asarray(polilinea)

    if len(polilinea) < 2:
        return np.repeat(polilinea, n_puntos, axis=0)

    segmentos = np.linalg.norm(np.diff(polilinea, axis=0), axis=1)
    longitud_acumulada = np.concatenate([[0], np.cumsum(segmentos)])
    longitud_total = longitud_acumulada[-1]

    if longitud_total == 0:
        return np.repeat(polilinea[:1], n_puntos, axis=0)

    objetivos = np.linspace(0, longitud_total, n_puntos)

    columnas_interp = [
        np.interp(objetivos, longitud_acumulada, polilinea[:, col])
        for col in range(polilinea.shape[1])
    ]

    return np.column_stack(columnas_interp)


def construir_landmarks(puntos, n_por_lado=100):
    """
    Convierte un contorno crudo (miles de puntos irregulares) en
    un vector de landmarks CON CORRESPONDENCIA: mismo numero de
    puntos, empezando siempre en la base, pasando por un lado
    hasta el apice, y volviendo por el otro lado.

    Ya generaliza a 3D si 'puntos' trae columna z (no hace falta
    tocar esta funcion): se usa internamente para la parte de
    CONTORNO del flujo 3D, ver construir_landmarks_3d().

    Retorna un arreglo (2*n_por_lado - 2, D).
    """
    idx_apice, idx_base = _encontrar_apice_base(puntos)

    if idx_base <= idx_apice:
        lado_a = puntos[idx_base:idx_apice + 1]
    else:
        lado_a = np.vstack([puntos[idx_base:], puntos[:idx_apice + 1]])

    if idx_apice <= idx_base:
        lado_b = puntos[idx_apice:idx_base + 1]
    else:
        lado_b = np.vstack([puntos[idx_apice:], puntos[:idx_base + 1]])

    lado_a_rs = _resamplear_polilinea(lado_a, n_por_lado)
    lado_b_rs = _resamplear_polilinea(lado_b, n_por_lado)

    landmarks = np.vstack([lado_a_rs, lado_b_rs[1:-1]])

    return landmarks


# ==============================================================
# 2b. GRILLA INTERIOR DE SUPERFICIE (solo necesaria para 3D)
# ==============================================================

def _grilla_relativa(n_u=6, n_v=10):
    """
    Grilla de coordenadas RELATIVAS (u, v) en [0,1] x [0,1], con un
    numero FIJO de puntos (n_u * n_v) igual para todas las hojas de
    la especie. Esta es la correspondencia de los landmarks de
    superficie: el punto de indice k siempre representa "la misma
    posicion relativa" dentro de la hoja (p. ej. 30% del ancho,
    60% del largo), sin importar el tamano exacto de cada muestra.

    Los margenes (0.08-0.92 en u, 0.05-0.95 en v) evitan poner
    landmarks pegados al contorno, donde la altura interpolada es
    mas sensible a errores de la reconstruccion 3D.
    """
    us = np.linspace(0.08, 0.92, n_u)
    vs = np.linspace(0.05, 0.95, n_v)
    return np.array([[u, v] for v in vs for u in us])


def _grilla_interior_leaf(contorno_xy, grilla_relativa):
    """
    Ubica la grilla relativa (u, v) dentro del bounding box del
    contorno de ESTA hoja. Mismo numero de puntos que
    'grilla_relativa' para cualquier hoja; solo cambia su posicion
    real (x, y) segun el tamano/forma de la muestra.
    """
    minimo = contorno_xy.min(axis=0)
    maximo = contorno_xy.max(axis=0)
    rango = maximo - minimo
    return minimo + grilla_relativa * rango


def _interpolar_altura_idw(nube_xyz, xy_objetivo, k=8, potencia=2.0):
    """
    Estima la altura z en cada posicion de 'xy_objetivo' por
    interpolacion IDW (inverse distance weighting) a partir de la
    nube de puntos 3D reconstruida de una hoja. Se evita depender
    de scipy: alcanza con numpy.

    nube_xyz: (M, 3) nube de puntos reconstruida de UNA hoja.
    xy_objetivo: (K, 2) posiciones donde se necesita la altura
                 (landmarks de contorno + grilla interior, ya con
                 correspondencia resuelta entre hojas).
    k: cuantos vecinos mas cercanos (en x,y) se promedian.
    """
    xy_nube = nube_xyz[:, :2]
    z_nube = nube_xyz[:, 2]
    k = min(k, len(nube_xyz))

    alturas = np.empty(len(xy_objetivo))

    for i, punto in enumerate(xy_objetivo):
        distancias = np.linalg.norm(xy_nube - punto, axis=1)
        idx_cercanos = np.argsort(distancias)[:k]
        d = distancias[idx_cercanos]

        if d[0] < 1e-9:
            alturas[i] = z_nube[idx_cercanos[0]]
            continue

        pesos = 1.0 / (d ** potencia)
        alturas[i] = np.sum(pesos * z_nube[idx_cercanos]) / np.sum(pesos)

    return alturas


def construir_landmarks_3d(puntos_3d, n_por_lado=100, n_u=6, n_v=10):
    """
    Version 3D de construir_landmarks(): en vez de devolver solo el
    contorno re-muestreado, devuelve CONTORNO + GRILLA INTERIOR, los
    dos con altura z interpolada desde la nube de puntos reconstruida
    de esa hoja.

    Esto es lo que permite pasar de "silueta plana extruida" a
    "malla con relieve" (Fase 2 del documento de investigacion): el
    contorno fija la forma en planta (igual que el modelo 2D) y la
    grilla interior aporta la altura h(x,y) que captura ondulaciones,
    venas y curvatura propias de cada especie.

    Retorna un arreglo (n_landmarks, 3), con
    n_landmarks = (2*n_por_lado - 2) + (n_u * n_v),
    mismo tamano y mismo orden para toda hoja de la especie
    (condicion necesaria para Procrustes/PCA).
    """
    puntos_xy = puntos_3d[:, :2]

    contorno_xy = construir_landmarks(puntos_xy, n_por_lado=n_por_lado)

    grilla_rel = _grilla_relativa(n_u=n_u, n_v=n_v)
    grilla_xy = _grilla_interior_leaf(contorno_xy, grilla_rel)

    xy_todos = np.vstack([contorno_xy, grilla_xy])
    alturas = _interpolar_altura_idw(puntos_3d, xy_todos)

    return np.column_stack([xy_todos, alturas])


# ==============================================================
# 3. ANALISIS DE PROCRUSTES GENERALIZADO
#    (sin cambios: ya es generico en la dimension D)
# ==============================================================

def _procrustes_2_formas(forma, referencia):
    """
    Alinea 'forma' contra 'referencia' (misma cantidad de puntos)
    usando traslacion + rotacion + escala uniforme (sin reflejo).
    Kabsch en R^D: sirve igual para D=2 (contorno) o D=3
    (contorno + relieve) sin ningun cambio, porque centrar, SVD y
    el chequeo de determinante no asumen una dimension particular.
    """
    centro_forma = forma.mean(axis=0)
    centro_ref = referencia.mean(axis=0)

    f = forma - centro_forma
    r = referencia - centro_ref

    escala_f = np.sqrt((f ** 2).sum())
    escala_r = np.sqrt((r ** 2).sum())

    f_norm = f / escala_f
    r_norm = r / escala_r

    matriz_h = f_norm.T @ r_norm
    u, _, vt = np.linalg.svd(matriz_h)
    rotacion = u @ vt

    if np.linalg.det(rotacion) < 0:
        u[:, -1] *= -1
        rotacion = u @ vt

    alineada = (f_norm @ rotacion) * escala_r + centro_ref

    return alineada


def analisis_procrustes_generalizado(lista_landmarks, iteraciones=5):
    """
    Alinea un conjunto de hojas (todas con la misma cantidad de
    landmarks, gracias a construir_landmarks / construir_landmarks_3d)
    entre si, e itera para converger a una forma promedio estable.

    Se usa TAL CUAL para 2D y para 3D: no depende de la dimension.

    Retorna (formas_alineadas, forma_promedio).
    """
    formas = [f.copy() for f in lista_landmarks]

    promedio = formas[0].copy()

    for _ in range(iteraciones):
        alineadas = [_procrustes_2_formas(f, promedio) for f in formas]
        nuevo_promedio = np.mean(alineadas, axis=0)
        promedio = nuevo_promedio
        formas = alineadas

    return formas, promedio


# ==============================================================
# 4. MODELO PCA DE VARIACION DE FORMA
#    (generalizado con parametro 'dimension')
# ==============================================================

def detectar_valores_atipicos(formas_alineadas, promedio, nombres=None, factor_std=2.0):
    """
    Compara cada forma alineada contra el promedio y calcula que
    tan lejos esta (distancia RMS punto a punto). Sirve igual para
    2D y 3D: la formula no depende del numero de columnas.

    Retorna una lista de dicts ordenada de mas a menos sospechosa:
        [{"nombre": ..., "distancia": ..., "atipico": True/False}, ...]
    """
    if nombres is None:
        nombres = [f"muestra_{i}" for i in range(len(formas_alineadas))]

    distancias = [
        float(np.sqrt(np.mean((f - promedio) ** 2)))
        for f in formas_alineadas
    ]

    media = np.mean(distancias)
    desviacion = np.std(distancias)
    umbral = media + factor_std * desviacion

    resultado = [
        {
            "nombre": nombre,
            "distancia": round(dist, 2),
            "atipico": bool(dist > umbral),
        }
        for nombre, dist in zip(nombres, distancias)
    ]

    resultado.sort(key=lambda r: r["distancia"], reverse=True)

    return resultado


def construir_modelo_pca(formas_alineadas, n_componentes=6, dimension=2):
    """
    Convierte cada forma alineada (N, dimension) en un vector
    (N*dimension,), y calcula PCA sobre el conjunto.

    dimension=2 para modelos de silueta (compatibilidad con el
    comportamiento original); dimension=3 para modelos de
    contorno+relieve entrenados con entrenar_especie_3d().

    Retorna un dict con: promedio, componentes, varianzas,
    n_puntos, dimension.
    """
    matriz = np.array([f.flatten() for f in formas_alineadas])

    promedio = matriz.mean(axis=0)
    centrado = matriz - promedio

    u, s, vt = np.linalg.svd(centrado, full_matrices=False)

    n_disponibles = min(n_componentes, vt.shape[0])
    componentes = vt[:n_disponibles]
    varianzas = (s[:n_disponibles] ** 2) / (matriz.shape[0] - 1)

    return {
        "promedio": promedio.tolist(),
        "componentes": componentes.tolist(),
        "varianzas": varianzas.tolist(),
        "n_puntos": matriz.shape[1] // dimension,
        "n_muestras": matriz.shape[0],
        "dimension": dimension,
    }


def generar_variante(modelo, intensidad=1.0, semilla=None):
    """
    Genera una silueta (2D) o superficie (3D) nueva a partir del
    modelo de la especie: forma promedio + combinacion aleatoria
    de los modos de variacion (PCA), acotada por la varianza real
    observada.

    Lee modelo["dimension"] para saber si debe reconstruir puntos
    (x,y) o (x,y,z); los modelos generados por versiones anteriores
    del script (sin esa clave) se asumen 2D, por compatibilidad.

    intensidad: 1.0 = variacion tipica observada en las fotos.
                > 1.0 = variantes mas extremas (menos realistas).
                < 1.0 = variantes mas conservadoras (mas parecidas
                        al promedio).
    """
    rng = np.random.default_rng(semilla)

    promedio = np.array(modelo["promedio"])
    componentes = np.array(modelo["componentes"])
    varianzas = np.array(modelo["varianzas"])
    dimension = modelo.get("dimension", 2)

    coeficientes = rng.normal(0, 1, size=len(varianzas))
    coeficientes = np.clip(coeficientes, -2, 2) * intensidad

    desplazamiento = coeficientes @ (componentes * np.sqrt(varianzas)[:, None])

    vector_final = promedio + desplazamiento

    n_puntos = modelo["n_puntos"]
    return vector_final.reshape(n_puntos, dimension)


# ==============================================================
# 5. FLUJO COMPLETO POR ESPECIE — 2D (silueta)
# ==============================================================

def entrenar_especie(nombre_especie, archivos_silueta, n_por_lado=100,
                      n_componentes=6, carpeta_modelos="modelos"):
    """
    Toma una lista de archivos *_silueta.py de la MISMA especie,
    construye landmarks, alinea, y guarda el modelo PCA en disco.
    """
    landmarks_todas = []

    for archivo in archivos_silueta:
        puntos = extraer_puntos(archivo)
        landmarks = construir_landmarks(puntos, n_por_lado=n_por_lado)
        landmarks_todas.append(landmarks)

    formas_alineadas, promedio = analisis_procrustes_generalizado(
        landmarks_todas
    )

    nombres_archivos = [os.path.basename(a) for a in archivos_silueta]
    reporte_atipicos = detectar_valores_atipicos(
        formas_alineadas, promedio, nombres=nombres_archivos
    )

    modelo = construir_modelo_pca(
        formas_alineadas, n_componentes=n_componentes, dimension=2
    )
    modelo["especie"] = nombre_especie
    modelo["n_muestras_entrenamiento"] = len(archivos_silueta)
    modelo["reporte_calidad"] = reporte_atipicos

    os.makedirs(carpeta_modelos, exist_ok=True)
    ruta_modelo = os.path.join(carpeta_modelos, f"{nombre_especie}.json")

    with open(ruta_modelo, "w", encoding="utf-8") as f:
        json.dump(modelo, f, ensure_ascii=False, indent=2)

    return modelo, ruta_modelo, reporte_atipicos


# ==============================================================
# 5b. FLUJO COMPLETO POR ESPECIE — 3D (contorno + relieve)
# ==============================================================

def entrenar_especie_3d(nombre_especie, archivos_relieve, n_por_lado=100,
                         n_u=6, n_v=10, n_componentes=6,
                         carpeta_modelos="modelos"):
    """
    Version 3D de entrenar_especie(): toma nubes de puntos / mallas
    ya reconstruidas (una por hoja, ver extraer_puntos_3d) en vez de
    contornos 2D, y entrena un modelo de forma+relieve.

    El resto del pipeline (Procrustes generalizado, deteccion de
    atipicos, PCA) es literalmente el mismo codigo que en 2D: ambas
    funciones trabajan con arreglos (N, D) genericos.
    """
    landmarks_todas = []

    for archivo in archivos_relieve:
        puntos_3d = extraer_puntos_3d(archivo)
        landmarks = construir_landmarks_3d(
            puntos_3d, n_por_lado=n_por_lado, n_u=n_u, n_v=n_v
        )
        landmarks_todas.append(landmarks)

    formas_alineadas, promedio = analisis_procrustes_generalizado(
        landmarks_todas
    )

    nombres_archivos = [os.path.basename(a) for a in archivos_relieve]
    reporte_atipicos = detectar_valores_atipicos(
        formas_alineadas, promedio, nombres=nombres_archivos
    )

    modelo = construir_modelo_pca(
        formas_alineadas, n_componentes=n_componentes, dimension=3
    )
    modelo["especie"] = nombre_especie
    modelo["n_muestras_entrenamiento"] = len(archivos_relieve)
    modelo["reporte_calidad"] = reporte_atipicos
    modelo["n_landmarks_contorno"] = 2 * n_por_lado - 2
    modelo["n_landmarks_grilla"] = n_u * n_v
    modelo["grilla_relativa"] = _grilla_relativa(n_u=n_u, n_v=n_v).tolist()

    os.makedirs(carpeta_modelos, exist_ok=True)
    ruta_modelo = os.path.join(carpeta_modelos, f"{nombre_especie}_3d.json")

    with open(ruta_modelo, "w", encoding="utf-8") as f:
        json.dump(modelo, f, ensure_ascii=False, indent=2)

    return modelo, ruta_modelo, reporte_atipicos


def generar_hoja_de_especie(nombre_especie, carpeta_modelos="modelos",
                             intensidad=1.0, semilla=None, sufijo_modelo=""):
    """
    Carga el modelo entrenado de una especie y genera una hoja nueva.
    Esta es la funcion que responde a "dame una hoja de mango".

    sufijo_modelo:
        ""     -> carga "<especie>.json" (modelo 2D de silueta)
        "_3d"  -> carga "<especie>_3d.json" (modelo de contorno+relieve,
                  entrenado con entrenar_especie_3d())
    """
    ruta_modelo = os.path.join(
        carpeta_modelos, f"{nombre_especie}{sufijo_modelo}.json"
    )

    with open(ruta_modelo, encoding="utf-8") as f:
        modelo = json.load(f)

    puntos = generar_variante(modelo, intensidad=intensidad, semilla=semilla)

    resultado = {
        "especie": nombre_especie,
        "fuente": "generada_desde_modelo_real",
        "dimension": modelo.get("dimension", 2),
        "n_muestras_entrenamiento": modelo["n_muestras_entrenamiento"],
        "puntos": [[round(float(c), 2) for c in punto] for punto in puntos],
    }

    if modelo.get("dimension") == 3:
        resultado["n_landmarks_contorno"] = modelo.get("n_landmarks_contorno")
        resultado["n_landmarks_grilla"] = modelo.get("n_landmarks_grilla")

    return resultado


if __name__ == "__main__":
    print("Este modulo se usa importado, ver ejemplo_uso.py")