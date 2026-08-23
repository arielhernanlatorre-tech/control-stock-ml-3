import csv
import json
import requests

def cargar_configuracion():
    with open("config.json", "r", encoding="utf-8") as archivo:
        return json.load(archivo)

def actualizar_stock_ml(id_publicacion, nuevo_stock, access_token):
    """Realiza la petición PUT a la API de Mercado Libre para modificar las cantidades."""
    if not id_publicacion or id_publicacion.upper() == "N/A":
        return "Saltado ⏩ (Sin ID en el CSV)"
        
    url = f"https://api.mercadolibre.com/items/{id_publicacion}"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
        "Accept": "application/json"
    }
    payload = {
        "available_quantity": int(nuevo_stock)
    }
    
    try:
        respuesta = requests.put(url, json=payload, headers=headers)
        if respuesta.status_code == 200:
            return "✅ ¡Stock actualizado con éxito!"
        else:
            msg_error = respuesta.json().get('message', 'Error desconocido')
            return f"❌ Error {respuesta.status_code}: {msg_error}"
    except Exception as e:
        return f"❌ Error de conexión: {e}"

def sincronizar_todo():
    config = cargar_configuracion()
    
    # Extraemos los tokens de acceso de las tres cuentas mapeadas en tu JSON
    tokens = {
        "cuenta_a": config.get("cuenta_a", {}).get("access_token"),
        "cuenta_b": config.get("cuenta_b", {}).get("access_token"),
        "cuenta_c": config.get("cuenta_c", {}).get("access_token")
    }
    
    print("🔄 Iniciando sincronización de stock multiplataforma...")
    print("--------------------------------------------------")
    
    with open("inventario.csv", mode="r", encoding="utf-8") as archivo_csv:
        lector = csv.DictReader(archivo_csv)
        
        for fila in lector:
            sku = fila.get("sku")
            stock = fila.get("stock")
            id_a = fila.get("id_cuenta_a")
            id_b = fila.get("id_cuenta_b")
            id_c = fila.get("id_cuenta_c")
            
            print(f"📦 SKU Detectado: {sku} | Cantidad objetivo: {stock}")
            
            # Sincronizar Cuenta A
            res_a = actualizar_stock_ml(id_a, stock, tokens["cuenta_a"])
            print(f"   🔹 Cuenta A ({id_a}): {res_a}")
            
            # Sincronizar Cuenta B
            res_b = actualizar_stock_ml(id_b, stock, tokens["cuenta_b"])
            print(f"   🔹 Cuenta B ({id_b}): {res_b}")
            
            # Sincronizar Cuenta C
            res_c = actualizar_stock_ml(id_c, stock, tokens["cuenta_c"])
            print(f"   🔹 Cuenta C ({id_c}): {res_c}")
            print("-" * 50)

if __name__ == "__main__":
    sincronizar_todo()
