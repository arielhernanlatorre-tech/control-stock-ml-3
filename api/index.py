import os
import json
import requests
import gspread
from flask import Flask, request, jsonify
from google.oauth2.service_account import Credentials

app = Flask(__name__)

# Configuración de Google Sheets desde las Variables de Entorno de Vercel
def conectar_google_sheets():
    credenciales_json = json.loads(os.environ.get("GOOGLE_CREDENTIALS"))
    spreadsheet_id = os.environ.get("GOOGLE_SPREADSHEET_ID")
    
    alcance = ["https://googleapis.com"]
    credenciales = Credentials.from_service_account_info(credenciales_json, scopes=alcance)
    cliente = gspread.authorize(credenciales)
    
    return cliente.open_by_key(spreadsheet_id)

def obtener_tokens_desde_sheets(nombre_cuenta):
    """Lee los tokens directamente desde la pestaña 'Tokens' de Google Sheets."""
    try:
        doc = conectar_google_sheets()
        hoja_tokens = doc.worksheet("Tokens")
        datos = hoja_tokens.get_all_records()
        
        for fila in datos:
            if str(fila.get("cuenta")).strip().lower() == nombre_cuenta.strip().lower():
                return {
                    "access_token": fila.get("access_token"),
                    "refresh_token": fila.get("refresh_token")
                }
        return None
    except Exception as e:
        print(f"❌ Error al leer tokens de Sheets: {e}")
        return None

def actualizar_tokens_en_sheets(nombre_cuenta, nuevo_access, nuevo_refresh):
    """Guarda los nuevos tokens en Google Sheets cuando Mercado Libre los renueva."""
    try:
        doc = conectar_google_sheets()
        hoja_tokens = doc.worksheet("Tokens")
        datos = hoja_tokens.get_all_records()
        
        for idx, fila in enumerate(datos, start=2): # fila 1 son encabezados
            if str(fila.get("cuenta")).strip().lower() == nombre_cuenta.strip().lower():
                hoja_tokens.update_cell(idx, 2, nuevo_access) # Columna B
                hoja_tokens.update_cell(idx, 3, nuevo_refresh) # Columna C
                print(f"💾 Tokens actualizados en Sheets para {nombre_cuenta}")
                return True
        return False
    except Exception as e:
        print(f"❌ Error al guardar tokens en Sheets: {e}")
        return False

def refrescar_token_ml(nombre_cuenta, refresh_token):
    """Pide un nuevo access_token a Mercado Libre usando el refresh_token."""
    url = "https://mercadolibre.com"
    payload = {
        "grant_type": "refresh_token",
        "client_id": os.environ.get("ML_CLIENT_ID"),
        "client_secret": os.environ.get("ML_CLIENT_SECRET"),
        "refresh_token": refresh_token
    }
    headers = {"content-type": "application/x-www-form-urlencoded"}
    
    respuesta = requests.post(url, data=payload, headers=headers)
    if respuesta.status_code == 200:
        datos = respuesta.json()
        nuevo_access = datos.get("access_token")
        nuevo_refresh = datos.get("refresh_token")
        # Los guardamos en el Excel para la próxima ejecución
        actualizar_tokens_en_sheets(nombre_cuenta, nuevo_access, nuevo_refresh)
        return nuevo_access
    else:
        print(f"❌ Error al refrescar token en ML: {respuesta.text}")
        return None

def procesar_cambio_stock(resource_url):
    """Identifica el producto vendido, calcula el nuevo stock y lo impacta en las 3 cuentas."""
    try:
        # Extraemos el ID de item de la URL (ej: /items/MLA3726719130 -> MLA3726719130)
        item_id = resource_url.split("/")[-1]
        
        doc = conectar_google_sheets()
        hoja_stock = doc.worksheet("Stock")
        productos = hoja_stock.get_all_records()
        
        fila_producto = None
        nro_fila_excel = None
        cuenta_origen = None
        
        # 1. Buscamos a qué fila del Excel pertenece el MLA vendido
        for idx, prod in enumerate(productos, start=2):
            if str(prod.get("id_cuenta_a")) == item_id:
                fila_producto = prod
                nro_fila_excel = idx
                cuenta_origen = "cuenta_a"
                break
            elif str(prod.get("id_cuenta_b")) == item_id:
                fila_producto = prod
                nro_fila_excel = idx
                cuenta_origen = "cuenta_b"
                break
            elif str(prod.get("id_cuenta_c")) == item_id:
                fila_producto = prod
                nro_fila_excel = idx
                cuenta_origen = "cuenta_c"
                break
                
        if not fila_producto:
            print(f"⚠️ El item {item_id} no está registrado en la pestaña Stock.")
            return
            
        # 2. Obtenemos el stock actual de Mercado Libre de la cuenta que vendió
        tokens_origen = obtener_tokens_desde_sheets(cuenta_origen)
        if not tokens_origen: return
        
        url_ml = f"https://mercadolibre.com{item_id}"
        headers = {"Authorization": f"Bearer {tokens_origen['access_token']}"}
        res_item = requests.get(url_ml, headers=headers)
        
        # Si el token expiró (401), lo refrescamos e intentamos de nuevo
        if res_item.status_code == 401:
            nuevo_access = refrescar_token_ml(cuenta_origen, tokens_origen["refresh_token"])
            if nuevo_access:
                headers = {"Authorization": f"Bearer {nuevo_access}"}
                res_item = requests.get(url_ml, headers=headers)
                
        if res_item.status_code != 200:
            print("❌ Error al consultar stock en Mercado Libre.")
            return
            
        nuevo_stock_real = res_item.json().get("available_quantity", 0)
        print(f"📉 Venta detectada. Nuevo stock real en Mercado Libre: {nuevo_stock_real}")
        
        # 3. Actualizamos la celda de Stock en Google Sheets (Columna B)
        hoja_stock.update_cell(nro_fila_excel, 2, nuevo_stock_real)
        
        # 4. Sincronizamos el nuevo stock en las otras dos cuentas socias
        cuentas_destino = ["cuenta_a", "cuenta_b", "cuenta_c"]
        cuentas_destino.remove(cuenta_origen)
        
        for cuenta in cuentas_destino:
            mla_destino = fila_producto.get(f"id_{cuenta}")
            if mla_destino and str(mla_destino).strip():
                tokens_dest = obtener_tokens_desde_sheets(cuenta)
                if tokens_dest:
                    url_update = f"https://mercadolibre.com{mla_destino}"
                    headers_dest = {"Authorization": f"Bearer {tokens_dest['access_token']}"}
                    payload_dest = {"available_quantity": nuevo_stock_real}
                    
                    res_up = requests.put(url_update, json=payload_dest, headers=headers_dest)
                    if res_up.status_code == 401: # Si expiró, se refresca
                        act_access = refrescar_token_ml(cuenta, tokens_dest["refresh_token"])
                        if act_access:
                            headers_dest = {"Authorization": f"Bearer {act_access}"}
                            res_up = requests.put(url_update, json=payload_dest, headers=headers_dest)
                            
                    if res_up.status_code == 200:
                        print(f"✅ Stock sincronizado en {cuenta} para el item {mla_destino}")
                    else:
                        print(f"❌ Falló sincronización en {cuenta}: {res_up.text}")
                        
    except Exception as e:
        print(f"❌ Error en la lógica de actualización: {e}")

# Webhook receptor de Vercel
@app.route('/', defaults={'path': ''}, methods=['POST', 'GET'])
@app.route('/<path:path>', methods=['POST', 'GET'])
def catch_all(path):
    try:
        data = request.get_json(silent=True)
        if not data:
            return jsonify({"status": "ok", "message": "Servidor en línea (Esperando Webhook)"}), 200
            
        resource = data.get("resource")
        if resource:
            print(f"🚀 Notificación recibida para el recurso: {resource}")
            # Ejecutamos la sincronización en segundo plano usando los datos en la nube
            procesar_cambio_stock(resource)
            return jsonify({"status": "success", "message": "Sincronización procesada"}), 200
            
        return jsonify({"status": "ok", "message": "JSON recibido sin recurso válido"}), 200
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500
