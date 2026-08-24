import json
import csv
import requests
import os
import gspread
from google.oauth2.service_account import Credentials

def inicializar_google_sheets():
    alcance = [
        'https://www.googleapis.com/auth/spreadsheets',
        'https://www.googleapis.com/auth/drive'
    ]
    ruta_credenciales = os.path.join(os.getcwd(), 'credentials.json')
    credenciales = Credentials.from_service_account_file(ruta_credenciales, scopes=alcance)
    cliente = gspread.authorize(credenciales)
    # Reemplaza aquí con tu ID real si usas uno fijo en entorno local
    return cliente.open_by_key("1Y_RziiD0CHJ-qlKzTwChj5a1XGX8yZPiQqXvylXjL8M")

def obtener_tokens_desde_sheet(hoja_tokens):
    datos = hoja_tokens.get_all_records()
    tokens = {}
    for fila in datos:
        tokens[fila['cuenta']] = {
            'access_token': fila['access_token'],
            'refresh_token': fila['refresh_token']
        }
    return tokens

def guardar_tokens_en_sheet(hoja_tokens, cuenta, access, refresh):
    celda_cuenta = hoja_tokens.find(cuenta)
    if celda_cuenta:
        fila = celda_cuenta.row
        hoja_tokens.update_cell(fila, 2, access)
        hoja_tokens.update_cell(fila, 3, refresh)

def refrescar_token_cuenta(hoja_tokens, cuenta, refresh_token):
    # Cargamos credenciales base del config local
    with open("config.json", "r", encoding="utf-8") as archivo:
        config = json.load(archivo)
        
    url = "https://api.mercadolibre.com/oauth/token"
    payload = {
        "grant_type": "refresh_token",
        "client_id": config.get("client_id"),
        "client_secret": config.get("client_secret"),
        "refresh_token": refresh_token
    }
    headers = {"accept": "application/json", "content-type": "application/x-www-form-urlencoded"}
    
    resp = requests.post(url, data=payload, headers=headers)
    if resp.status_code == 200:
        datos = resp.json()
        nuevo_access = datos.get("access_token")
        nuevo_refresh = datos.get("refresh_token")
        # Guarda directo en la nube (Google Sheets)
        guardar_tokens_en_sheet(hoja_tokens, cuenta, nuevo_access, nuevo_refresh)
        print(f"✅ Tokens de [{cuenta}] renovados y guardados en Google Sheets.")
        return nuevo_access
    else:
        print(f"❌ Error al renovar token de [{cuenta}] en la API.")
        return None

def actualizar_stock_ml(item_id, nuevo_stock, access_token, nombre_cuenta):
    url = f"https://api.mercadolibre.com/items/{item_id}"
    payload = {"available_quantity": int(nuevo_stock)}
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
        "Accept": "application/json"
    }
    respuesta = requests.put(url, json=payload, headers=headers)
    if respuesta.status_code == 200:
        print(f"  ✅ [{nombre_cuenta}] Publicación {item_id} sincronizada a {nuevo_stock} unidades.")
    else:
        print(f"  ❌ [{nombre_cuenta}] Error en {item_id}: Código {respuesta.status_code}")

def procesar_inventario():
    print("🔄 Conectando con Google Sheets para validar tokens...")
    try:
        doc = inicializar_google_sheets()
        hoja_tokens = doc.worksheet("Tokens")
    except Exception as e:
        print(f"❌ Error al conectar con Google Sheets: {e}")
        return

    tokens_actuales = obtener_tokens_desde_sheet(hoja_tokens)
    
    # Intentamos refrescar todos antes de arrancar la carga pesada
    for cuenta in ["cuenta_a", "cuenta_b", "cuenta_c"]:
        if cuenta in tokens_actuales and tokens_actuales[cuenta]['refresh_token']:
            nuevo_access = refrescar_token_cuenta(hoja_tokens, cuenta, tokens_actuales[cuenta]['refresh_token'])
            if nuevo_access:
                tokens_actuales[cuenta]['access_token'] = nuevo_access

    print("\n📋 Leyendo archivo inventario.csv e iniciando sincronización...")
    try:
        with open("inventario.csv", mode="r", encoding="utf-8") as archivo_csv:
            lector = csv.DictReader(archivo_csv, delimiter=',')
            
            for fila in lector:
                sku = fila.get("sku")
                nuevo_stock = fila.get("stock")
                
                print(f"\n📦 SKU: {sku} ➡️ Stock Único Central: {nuevo_stock}")
                
                mapeo = [
                    ("id_cuenta_a", "cuenta_a"),
                    ("id_cuenta_b", "cuenta_b"),
                    ("id_cuenta_c", "cuenta_c")
                ]
                
                for columna_csv, clave_json in mapeo:
                    item_id = fila.get(columna_csv)
                    if item_id and str(item_id).strip().upper().startswith("MLA"):
                        token = tokens_actuales.get(clave_json, {}).get("access_token")
                        if not token:
                            print(f"  ⚠️ Saltando {clave_json}: Sin token activo en Sheets.")
                            continue
                        actualizar_stock_ml(item_id.strip(), nuevo_stock, token, clave_json)
                        
    except FileNotFoundError:
        print("❌ Error: No se encontró el archivo inventario.csv.")

if __name__ == "__main__":
    procesar_inventario()
