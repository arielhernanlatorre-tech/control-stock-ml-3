import os

# Lista de archivos a buscar
archivos_proyecto = [
    "config.json",
    "actualizar_stock.py",
    "sincronizador.py",
    "obtener_token.py",
    "inventario.csv"
]

archivo_salida = "proyecto_completo.txt"

with open(archivo_salida, "w", encoding="utf-8") as salida:
    for nombre_archivo in archivos_proyecto:
        if os.path.exists(nombre_archivo):
            salida.write(f"=== INICIO ARCHIVO: {nombre_archivo} ===\n")
            try:
                with open(nombre_archivo, "r", encoding="utf-8") as f:
                    salida.write(f.read())
            except Exception as e:
                salida.write(f"[Error al leer el archivo: {e}]\n")
            salida.write(f"\n=== FIN ARCHIVO: {nombre_archivo} ===\n\n")
        else:
            salida.write(f"=== ARCHIVO NO ENCONTRADO: {nombre_archivo} ===\n\n")

print("¡Listo! Archivo actualizado correctamente.")
