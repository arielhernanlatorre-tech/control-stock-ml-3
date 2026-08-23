import json
import csv
import requests

def cargar_configuracion():
    with open("config.json", "r", encoding="utf-8") as archivo:
        return json.load(archivo)

def guardar_configuracion(config):
    with open("config.json", "w", encoding="utf-8") as archivo:
        json.dump(config, archivo, indent=4, ensure_ascii=False)

def refrescar_token_cuenta(id_cuenta_json):
    """
    Renueva el access_token de una cuenta específica (cuenta_a, cuenta_b o cuenta_c)
    usando su respectivo refresh_token guardado en config.json.
    """
    config = cargar_configuracion()
    client_id = config.get("client_id")
    client_secret = config.get("client_secret")
    
    cuenta = config.get(id_cuenta_json, {})
    refresh_token = cuenta.get("refresh_token")
    nombre_cuenta = cuenta.get("nombre", id_cuenta_json)
    
    if not refresh_token:
        # Si la cuenta no tiene token aún (como la B y C ahora), salta sin dar error
        return False
    config = cargar_configuracion()
    client_id = config.get("client_id")
    client_secret = config.get("client_secret")
    url = "https://api.mercadolibre.com/oauth/token"
    payload = {
        "grant_type": "refresh_token",
        "client_id": client_id,
        "client_secret": client_secret,
        "refresh_token": refresh_token
    }
    headers = {
        "accept": "application/json",
        "content-type": "application/x-www-form-urlencoded"
    }
    
    try:
        respuesta = requests.post(url, data=payload, headers=headers)
        if respuesta.status_code == 200:
            datos = respuesta.json()
            config[id_cuenta_json]["access_token"] = datos.get("access_token")
            config[id_cuenta_json]["refresh_token"] = datos.get("refresh_token")
            guardar_configuracion(config)
            print(f"✅ Tokens de [{nombre_cuenta}] renovados automáticamente.")
            return True
        else:
            print(f"❌ Error al renovar token de [{nombre_cuenta}] (Código {respuesta.status_code})")
            return False
    except Exception as e:
        print(f"❌ Error de conexión al renovar token de [{nombre_cuenta}]: {e}")
        return False

def actualizar_stock_ml(item_id, nuevo_stock, access_token, nombre_cuenta):
    url = f"https://api.mercadolibre.com/items/{item_id}"
    payload = {
        "available_quantity": int(nuevo_stock)
    }
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
        "Accept": "application/json"
    }
    
    respuesta = requests.put(url, json=payload, headers=headers)
    if respuesta.status_code == 200:
        print(f"  ✅ [{nombre_cuenta}] Publicación {item_id} sincronizada a {nuevo_stock} unidades.")
    else:
        print(f"  ❌ [{nombre_cuenta}] Error en {item_id}: Código {respuesta.status_code} - {respuesta.text}")

def procesar_inventario():
    # 1. Renovación automática de tokens para cada cuenta por separado
    print("🔄 Iniciando control y renovación de tokens...")
    cuentas_a_procesar = ["cuenta_a", "cuenta_b", "cuenta_c"]
    for cuenta in cuentas_a_procesar:
        refrescar_token_cuenta(cuenta)
    
    # 2. Volvemos a cargar la configuración ya actualizada
    config = cargar_configuracion()
    
    print("\n📋 Leyendo archivo inventario.csv e iniciando sincronización...")
    try:
        with open("inventario.csv", mode="r", encoding="utf-8") as archivo_csv:
            lector = csv.DictReader(archivo_csv, delimiter=',')
            
            for fila in lector:
                sku = fila.get("sku")
                nuevo_stock = fila.get("stock")
                
                print(f"\n📦 SKU: {sku} ➡️ Stock Único Central: {nuevo_stock}")
                
                # Relación entre columnas del CSV y bloques del config.json
                mapeo = [
                    ("id_cuenta_a", "cuenta_a"),
                    ("id_cuenta_b", "cuenta_b"),
                    ("id_cuenta_c", "cuenta_c")
                ]
                
                for columna_csv, clave_json in mapeo:
                    item_id = fila.get(columna_csv)
                    
                    if item_id and str(item_id).strip().upper().startswith("MLA"):
                        datos_cuenta = config.get(clave_json, {})
                        token = datos_cuenta.get("access_token")
                        nombre_vis = datos_cuenta.get("nombre", clave_json)
                        
                        if not token:
                            print(f"  ⚠️ Saltando {nombre_vis}: No tiene un access_token activo.")
                            continue
                            
                        actualizar_stock_ml(item_id.strip(), nuevo_stock, token, nombre_vis)
                        
    except FileNotFoundError:
        print("❌ Error: No se encontró el archivo inventario.csv.")

if __name__ == "__main__":
    procesar_inventario()
