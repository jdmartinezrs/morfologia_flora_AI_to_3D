import json
import os
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

import matplotlib
matplotlib.use("TkAgg")
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure

import convertir_a_maxscript
import extractor_siluetas
import generar
import entrenar_todo
import modelo_forma_especie


RAIZ = Path(__file__).resolve().parent.parent


class InterfazFlora(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Morfologia Flora | Pipeline 2D a 3D")
        self.geometry("1180x760")
        self.minsize(980, 650)
        self.configure(bg="#eef2f3")

        self.variables = {}
        self.vistas = {}
        self._crear_estilos()
        self._crear_cabecera()
        self._crear_contenido()
        self._crear_estado()
        self._refrescar_especies()

    def _crear_estilos(self):
        estilo = ttk.Style(self)
        estilo.theme_use("clam")
        estilo.configure("TFrame", background="#eef2f3")
        estilo.configure("Card.TFrame", background="#ffffff")
        estilo.configure("TLabel", background="#eef2f3", foreground="#243238")
        estilo.configure("Card.TLabel", background="#ffffff", foreground="#243238")
        estilo.configure("Title.TLabel", background="#eef2f3", foreground="#173f43", font=("Segoe UI", 22, "bold"))
        estilo.configure("Subtitle.TLabel", background="#eef2f3", foreground="#5b6b70", font=("Segoe UI", 10))
        estilo.configure("CardTitle.TLabel", background="#ffffff", foreground="#173f43", font=("Segoe UI", 13, "bold"))
        estilo.configure("TButton", padding=(10, 7))
        estilo.configure("Accent.TButton", background="#147d74", foreground="#ffffff", padding=(12, 8))
        estilo.map("Accent.TButton", background=[("active", "#0f655e")])
        estilo.configure("TNotebook", background="#eef2f3", borderwidth=0)
        estilo.configure("TNotebook.Tab", padding=(16, 9), background="#dce5e5")
        estilo.map("TNotebook.Tab", background=[("selected", "#ffffff")], foreground=[("selected", "#147d74")])

    def _crear_cabecera(self):
        cabecera = ttk.Frame(self, padding=(28, 22, 28, 10))
        cabecera.pack(fill="x")
        ttk.Label(cabecera, text="Morfologia Flora", style="Title.TLabel").pack(anchor="w")
        ttk.Label(cabecera, text="Convierte fotografias de hojas en modelos estadisticos y geometria para 3ds Max.", style="Subtitle.TLabel").pack(anchor="w", pady=(3, 0))

    def _crear_contenido(self):
        self.notebook = ttk.Notebook(self)
        self.notebook.pack(fill="both", expand=True, padx=28, pady=(0, 12))
        self._crear_pestana_extractor()
        self._crear_pestana_entrenamiento()
        self._crear_pestana_generador()
        self._crear_pestana_maxscript()

    def _crear_estado(self):
        pie = ttk.Frame(self, padding=(28, 0, 28, 18))
        pie.pack(fill="x")
        self.estado = tk.StringVar(value="Listo. Selecciona una operacion.")
        ttk.Label(pie, textvariable=self.estado, style="Subtitle.TLabel").pack(side="left")
        self.progreso = ttk.Progressbar(pie, mode="indeterminate", length=170)
        self.progreso.pack(side="right")

    def _nueva_pestana(self, titulo):
        frame = ttk.Frame(self.notebook, padding=18)
        self.notebook.add(frame, text=titulo)
        return frame

    def _campo(self, parent, etiqueta, clave, valor="", ancho=52, explorador=None):
        fila = ttk.Frame(parent, style="Card.TFrame")
        fila.pack(fill="x", pady=5)
        ttk.Label(fila, text=etiqueta, width=21, anchor="w", style="Card.TLabel").pack(side="left")
        variable = tk.StringVar(value=valor)
        self.variables[clave] = variable
        ttk.Entry(fila, textvariable=variable, width=ancho).pack(side="left", fill="x", expand=True)
        if explorador:
            ttk.Button(fila, text="Examinar", command=explorador).pack(side="left", padx=(8, 0))
        return variable

    def _panel_formulario(self, parent, titulo):
        panel = ttk.Frame(parent, style="Card.TFrame", padding=18)
        panel.pack(side="left", fill="both", expand=True, padx=(0, 10))
        ttk.Label(panel, text=titulo, style="CardTitle.TLabel").pack(anchor="w", pady=(0, 10))
        return panel

    def _panel_vista(self, parent, clave):
        panel = ttk.Frame(parent, style="Card.TFrame", padding=12)
        panel.pack(side="left", fill="both", expand=True)
        self.figura = Figure(figsize=(5, 5), dpi=100, facecolor="white")
        self.eje = self.figura.add_subplot(111)
        self.canvas = FigureCanvasTkAgg(self.figura, master=panel)
        self.canvas.get_tk_widget().pack(fill="both", expand=True)
        self.vistas[clave] = (self.eje, self.canvas)
        self._limpiar_vista(self.eje, self.canvas, "La vista previa aparecera aqui")
        return panel

    def _crear_pestana_extractor(self):
        pestana = self._nueva_pestana("1  Extraer silueta")
        formulario = self._panel_formulario(pestana, "Imagen a coordenadas")
        self._campo(formulario, "Imagen de entrada", "imagen", explorador=self._elegir_imagen)
        self._campo(formulario, "Especie", "especie", "mango")
        self._campo(formulario, "Carpeta de salida", "salida_extractor", str(RAIZ / "fotos_procesadas"), explorador=self._elegir_carpeta_extractor)
        ttk.Label(formulario, text="Se guardan el archivo *_silueta.py y sus coordenadas.", style="Card.TLabel", wraplength=380).pack(anchor="w", pady=(14, 10))
        ttk.Button(formulario, text="Extraer y guardar", style="Accent.TButton", command=self._extraer).pack(anchor="w", pady=8)
        self._panel_vista(pestana, "extractor")

    def _crear_pestana_entrenamiento(self):
        pestana = self._nueva_pestana("2  Entrenar modelos")
        formulario = self._panel_formulario(pestana, "Modelos por especie")
        self._campo(formulario, "Muestras", "carpeta_muestras", str(RAIZ / "fotos_procesadas"), explorador=self._elegir_carpeta_muestras)
        self._campo(formulario, "Guardar modelos", "carpeta_modelos", str(RAIZ / "modelos"), explorador=self._elegir_carpeta_modelos)
        self._campo(formulario, "Landmarks por lado", "landmarks", "100", ancho=12)
        ttk.Label(formulario, text="Cada especie necesita al menos 5 archivos *_silueta.py.", style="Card.TLabel", wraplength=380).pack(anchor="w", pady=(14, 10))
        ttk.Button(formulario, text="Entrenar todos", style="Accent.TButton", command=self._entrenar).pack(anchor="w", pady=8)
        self._panel_vista(pestana, "entrenamiento")

    def _crear_pestana_generador(self):
        pestana = self._nueva_pestana("3  Generar hojas")
        formulario = self._panel_formulario(pestana, "Variantes sinteticas")
        self._campo(formulario, "Modelos", "modelos_generador", str(RAIZ / "modelos"), explorador=self._elegir_carpeta_generador)
        fila = ttk.Frame(formulario, style="Card.TFrame")
        fila.pack(fill="x", pady=5)
        ttk.Label(fila, text="Especie", width=21, anchor="w", style="Card.TLabel").pack(side="left")
        self.especie_generador = tk.StringVar()
        self.combo_especies = ttk.Combobox(fila, textvariable=self.especie_generador, state="readonly")
        self.combo_especies.pack(side="left", fill="x", expand=True)
        ttk.Button(fila, text="Actualizar", command=self._refrescar_especies).pack(side="left", padx=(8, 0))
        self._campo(formulario, "Cantidad", "cantidad", "1", ancho=12)
        self._campo(formulario, "Intensidad", "intensidad", "1.0", ancho=12)
        self._campo(formulario, "Semilla (opcional)", "semilla", "", ancho=12)
        self._campo(formulario, "Guardar resultados", "salida_generador", str(RAIZ / "hojas_generadas"), explorador=self._elegir_carpeta_salida)
        ttk.Button(formulario, text="Generar hojas", style="Accent.TButton", command=self._generar).pack(anchor="w", pady=12)
        self._panel_vista(pestana, "generador")

    def _crear_pestana_maxscript(self):
        pestana = self._nueva_pestana("4  Exportar MAXScript")
        formulario = self._panel_formulario(pestana, "Geometria 3D")
        self._campo(formulario, "Silueta o JSON", "entrada_max", "", explorador=self._elegir_entrada_max)
        self._campo(formulario, "Archivo .ms", "salida_max", str(RAIZ / "hoja_3d.ms"), explorador=self._elegir_salida_max)
        self._campo(formulario, "Tolerancia", "tolerancia", "0.8", ancho=12)
        self._campo(formulario, "Extrusion", "extrusion", "15", ancho=12)
        self._campo(formulario, "Escala", "escala", "1.0", ancho=12)
        self._campo(formulario, "Nombre del objeto", "nombre_objeto", "Hoja_Silueta", ancho=24)
        ttk.Button(formulario, text="Crear MAXScript", style="Accent.TButton", command=self._convertir).pack(anchor="w", pady=12)
        self._panel_vista(pestana, "maxscript")

    def _elegir_imagen(self):
        ruta = filedialog.askopenfilename(filetypes=[("Imagenes", "*.png *.jpg *.jpeg *.bmp *.webp"), ("Todos", "*.*")])
        if ruta:
            self.variables["imagen"].set(ruta)

    def _elegir_archivo(self, clave, tipos):
        ruta = filedialog.askopenfilename(filetypes=tipos)
        if ruta:
            self.variables[clave].set(ruta)

    def _elegir_carpeta(self, clave):
        ruta = filedialog.askdirectory()
        if ruta:
            self.variables[clave].set(ruta)

    def _elegir_carpeta_extractor(self): self._elegir_carpeta("salida_extractor")
    def _elegir_carpeta_muestras(self): self._elegir_carpeta("carpeta_muestras")
    def _elegir_carpeta_modelos(self): self._elegir_carpeta("carpeta_modelos")
    def _elegir_carpeta_generador(self): self._elegir_carpeta("modelos_generador")
    def _elegir_carpeta_salida(self): self._elegir_carpeta("salida_generador")

    def _elegir_entrada_max(self):
        self._elegir_archivo("entrada_max", [("Siluetas y JSON", "*.py *.json"), ("Todos", "*.*")])

    def _elegir_salida_max(self):
        ruta = filedialog.asksaveasfilename(defaultextension=".ms", filetypes=[("MAXScript", "*.ms")])
        if ruta:
            self.variables["salida_max"].set(ruta)

    def _ejecutar(self, descripcion, funcion):
        self.estado.set(descripcion)
        self.progreso.start(10)

        def trabajo():
            try:
                resultado = funcion()
                self.after(0, lambda: self._terminar_trabajo(descripcion, resultado))
            except Exception as error:
                self.after(0, lambda: self._fallar_trabajo(str(error)))

        threading.Thread(target=trabajo, daemon=True).start()

    def _terminar_trabajo(self, descripcion, resultado):
        self.progreso.stop()
        self.estado.set(descripcion + " terminado")
        if resultado:
            messagebox.showinfo("Proceso terminado", resultado)

    def _fallar_trabajo(self, error):
        self.progreso.stop()
        self.estado.set("Se produjo un error")
        messagebox.showerror("No se pudo completar", error)

    def _extraer(self):
        imagen = self.variables["imagen"].get().strip()
        especie = self.variables["especie"].get().strip()
        carpeta = self.variables["salida_extractor"].get().strip()
        if not imagen or not especie or not os.path.isfile(imagen):
            messagebox.showwarning("Datos incompletos", "Selecciona una imagen existente y escribe la especie.")
            return

        def trabajo():
            gris = extractor_siluetas.cargar_imagen(imagen)
            alto, ancho = gris.shape
            mascara = extractor_siluetas.limpiar_mascara(extractor_siluetas.crear_mascara(gris))
            contornos, jerarquia = extractor_siluetas.encontrar_contornos(mascara)
            indice = extractor_siluetas.encontrar_contorno_principal(contornos, jerarquia)
            if indice is None:
                raise ValueError("No se encontro una silueta principal. Usa una imagen con fondo claro y hoja oscura.")
            indices = extractor_siluetas.obtener_descendientes(indice, contornos, jerarquia)
            coordenadas = extractor_siluetas.extraer_coordenadas(contornos, indices, jerarquia, ancho, alto)
            destino = Path(carpeta) / especie
            destino.mkdir(parents=True, exist_ok=True)
            nombre = Path(imagen).stem
            codigo = extractor_siluetas.generar_codigo_turtle(coordenadas, Path(imagen).name)
            archivo_py = destino / (nombre + "_silueta.py")
            archivo_txt = destino / (nombre + "_coordenadas.txt")
            archivo_py.write_text(codigo, encoding="utf-8")
            with archivo_txt.open("w", encoding="utf-8") as archivo:
                for numero, datos in enumerate(coordenadas, 1):
                    archivo.write(f"CONTORNO {numero}\nTIPO: {datos['tipo']}\nPROFUNDIDAD: {datos['profundidad']}\nPUNTOS: {len(datos['puntos'])}\n\n")
                    archivo.write("".join(f"{x}, {y}\n" for x, y in datos["puntos"]) + "\n")
            self.after(0, lambda: self._dibujar_coordenadas(coordenadas, "Silueta extraida"))
            return f"Guardado en:\n{archivo_py}"

        self._ejecutar("Extrayendo silueta", trabajo)

    def _entrenar(self):
        try:
            landmarks = int(self.variables["landmarks"].get())
        except ValueError:
            messagebox.showwarning("Dato invalido", "Landmarks por lado debe ser un numero entero.")
            return

        def trabajo():
            especies = entrenar_todo.encontrar_especies(self.variables["carpeta_muestras"].get())
            entrenadas = []
            for especie, archivos in especies.items():
                if len(archivos) < entrenar_todo.MINIMO_MUESTRAS:
                    continue
                modelo_forma_especie.entrenar_especie(especie, archivos, n_por_lado=landmarks, carpeta_modelos=self.variables["carpeta_modelos"].get())
                entrenadas.append(especie)
            if not entrenadas:
                raise ValueError("No hay especies con el minimo de 5 muestras.")
            self.after(0, self._refrescar_especies)
            return "Modelos entrenados:\n" + "\n".join(entrenadas)

        self._ejecutar("Entrenando modelos", trabajo)

    def _generar(self):
        especie = self.especie_generador.get()
        if not especie:
            messagebox.showwarning("Falta la especie", "Actualiza la lista y selecciona una especie.")
            return
        try:
            cantidad = int(self.variables["cantidad"].get())
            intensidad = float(self.variables["intensidad"].get())
            semilla = self.variables["semilla"].get().strip()
            semilla = int(semilla) if semilla else None
            if cantidad < 1 or intensidad < 0:
                raise ValueError
        except ValueError:
            messagebox.showwarning("Datos invalidos", "Cantidad e intensidad deben ser numeros validos.")
            return

        def trabajo():
            salida = Path(self.variables["salida_generador"].get())
            salida.mkdir(parents=True, exist_ok=True)
            for indice in range(cantidad):
                semilla_actual = semilla + indice if semilla is not None else None
                hoja = modelo_forma_especie.generar_hoja_de_especie(especie, carpeta_modelos=self.variables["modelos_generador"].get(), intensidad=intensidad, semilla=semilla_actual)
                ruta = salida / f"{especie}_generada_{indice + 1:03d}.json"
                ruta.write_text(json.dumps(hoja, ensure_ascii=False, indent=2), encoding="utf-8")
            self.after(0, lambda: self._dibujar_puntos(hoja["puntos"], f"{especie} generada"))
            return f"Generadas {cantidad} hoja(s) en:\n{salida}"

        self._ejecutar("Generando hojas", trabajo)

    def _convertir(self):
        entrada = self.variables["entrada_max"].get().strip()
        salida = self.variables["salida_max"].get().strip()
        if not entrada or not salida or not os.path.isfile(entrada):
            messagebox.showwarning("Datos incompletos", "Selecciona una entrada existente y un archivo .ms de salida.")
            return
        try:
            tolerancia = float(self.variables["tolerancia"].get())
            extrusion = float(self.variables["extrusion"].get())
            escala = float(self.variables["escala"].get())
            if tolerancia < 0 or extrusion < 0 or escala <= 0:
                raise ValueError
        except ValueError:
            messagebox.showwarning("Datos invalidos", "Tolerancia, extrusion y escala deben ser numeros validos.")
            return

        def trabajo():
            resultado = convertir_a_maxscript.convertir(entrada, salida, tolerancia, extrusion, escala, self.variables["nombre_objeto"].get().strip() or None)
            return f"MAXScript creado:\n{resultado['archivo_salida']}\n\nPuntos: {resultado['puntos_originales']} -> {resultado['puntos_simplificados']}"

        self._ejecutar("Creando MAXScript", trabajo)

    def _refrescar_especies(self):
        carpeta = self.variables.get("modelos_generador")
        ruta = carpeta.get() if carpeta else str(RAIZ / "modelos")
        especies = generar.listar_especies_disponibles(ruta)
        self.combo_especies["values"] = especies
        if especies and self.especie_generador.get() not in especies:
            self.especie_generador.set(especies[0])

    def _limpiar_vista(self, eje, canvas, mensaje):
        eje.clear()
        eje.text(0.5, 0.5, mensaje, ha="center", va="center", color="#7b8a8e", transform=eje.transAxes)
        eje.set_axis_off()
        canvas.draw_idle()

    def _dibujar_puntos(self, puntos, titulo):
        eje, canvas = self.vistas["generador"]
        self._dibujar_en_vista(eje, canvas, puntos, titulo)

    def _dibujar_en_vista(self, eje, canvas, puntos, titulo):
        eje.clear()
        cerrados = list(puntos) + [puntos[0]]
        eje.fill([p[0] for p in cerrados], [p[1] for p in cerrados], color="#68b6a9", alpha=0.55)
        eje.plot([p[0] for p in cerrados], [p[1] for p in cerrados], color="#147d74", linewidth=1.2)
        eje.set_title(titulo)
        eje.set_aspect("equal")
        eje.set_axis_off()
        canvas.draw_idle()

    def _dibujar_coordenadas(self, coordenadas, titulo):
        exteriores = [dato["puntos"] for dato in coordenadas if dato["tipo"] == "EXTERIOR"]
        if exteriores:
            eje, canvas = self.vistas["extractor"]
            self._dibujar_en_vista(eje, canvas, exteriores[0], titulo)


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    app = InterfazFlora()
    app.mainloop()