import os
import json
from http.server import BaseHTTPRequestHandler
import requests
import gspread
from flask import Flask, request, jsonify 
app = Flask(__name__)
from google.oauth2.service_account import Credentials

def inicializar_google_sheets():
    # CORREGIDO: URLs completas y correctas para la API de Google (Línea 11)
    alcance = [
        'https://www.googleapis.com/auth/spreadsheets',
        'https://www.googleapis.com/auth/drive'
    ]
    
    # Si la variable de entorno está en Vercel, procesamos el JSON directamente desde texto
    if "CREDENTIALS_JSON" in os.environ:
        info_credenciales = json.loads(os.environ["CREDENTIALS_JSON"])
        credenciales = Credentials.from_service_account_info(info_credenciales, scopes=alcance)
    else:
        # En tu computadora local seguirá buscando el archivo físico tradicional
        ruta_credenciales = os.path.join(os.getcwd(), 'credentials.json')
        credenciales = Credentials.from_service_account_file(ruta_credenciales, scopes=alcance)
        
    cliente = gspread.authorize(credenciales)
    # Abre la planilla usando la variable de entorno configurada en Vercel
    return cliente.open_by_key(os.environ.get("GOOGLE_SPREADSHEET_ID"))

def obtener_tokens(hoja_tokens):
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
    # CORREGIDO: Ruta oficial para renovar credenciales en Mercado Libre
    url = "https://api.mercadolibre.com/oauth/token"
    payload = {
        "grant_type": "refresh_token",
        "client_id": os.environ.get("ML_CLIENT_ID"),
        "client_secret": os.environ.get("ML_CLIENT_SECRET"),
        "refresh_token": refresh_token
    }
    headers = {"accept": "application/json", "content-type": "application/x-www-form-urlencoded"}
    
    resp = requests.post(url, data=payload, headers=headers)
    if resp.status_code == 200:
        datos = resp.json()
        nuevo_access = datos.get("access_token")
        nuevo_refresh = datos.get("refresh_token")
        guardar_tokens_en_sheet(hoja_tokens, cuenta, nuevo_access, nuevo_refresh)
        return nuevo_access
    return None

def actualizar_stock_ml(item_id, nuevo_stock, access_token):
    if not item_id or str(item_id).strip().upper() == "N/A" or not str(item_id).startswith("MLA"):
        return
    # CORREGIDO: Endpoint correcto de la API para actualizar items
    url = f"https://api.mercadolibre.com/items/{item_id}"
    payload = {"available_quantity": int(nuevo_stock)}
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json"
    }
    requests.put(url, json=payload, headers=headers)

class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        longitud_contenido = int(self.headers['Content-Length'])
        datos_post = self.rfile.read(longitud_contenido)
        
        try:
            notificacion = json.loads(datos_post.decode('utf-8'))
            # Verificamos que sea una notificación sobre un artículo/item
            if notificacion.get("topic") == "items":
                recurso = notificacion.get("resource", "")
                item_id = recurso.split("/")[-1] # Extrae el MLAXXXXXXXXX
                
                doc = inicializar_google_sheets()
                hoja_stock = doc.worksheet("Stock")
                hoja_tokens = doc.worksheet("Tokens")
                
                # Buscamos el item en las columnas de las 3 cuentas
                celda = hoja_stock.find(item_id)
                if celda:
                    fila_num = celda.row
                    fila_datos = hoja_stock.row_values(fila_num)
                    
                    # Estructura: sku=col1, stock=col2, id_a=col3, id_b=col4, id_c=col5
                    sku = fila_datos[0]
                    id_a = fila_datos[2] if len(fila_datos) > 2 else ""
                    id_b = fila_datos[3] if len(fila_datos) > 3 else ""
                    id_c = fila_datos[4] if len(fila_datos) > 4 else ""
                    
                    # Mapeo para identificar en qué cuenta se vendió
                    mapeo_cuentas = {"cuenta_a": id_a, "cuenta_b": id_b, "cuenta_c": id_c}
                    cuenta_origen = None
                    for k, v in mapeo_cuentas.items():
                        if v == item_id:
                            cuenta_origen = k
                            break
                    
                    if cuenta_origen:
                        tokens = obtener_tokens(hoja_tokens)
                        token_actual = tokens[cuenta_origen]['access_token']
                        
                        # CORREGIDO: Endpoint correcto para obtener el detalle del item
                        url_item = f"https://api.mercadolibre.com/items/{item_id}"
                        headers = {"Authorization": f"Bearer {token_actual}"}
                        resp_item = requests.get(url_item, headers=headers)
                        
                        # Si el token expiró, lo renovamos e intentamos de nuevo
                        if resp_item.status_code == 401:
                            nuevo_token = refrescar_token_cuenta(hoja_tokens, cuenta_origen, tokens[cuenta_origen]['refresh_token'])
                            if nuevo_token:
                                headers = {"Authorization": f"Bearer {nuevo_token}"}
                                resp_item = requests.get(url_item, headers=headers)
                        
                        if resp_item.status_code == 200:
                            stock_real = resp_item.json().get("available_quantity")
                            
                            # 1. Actualizamos la celda de la hoja Stock en Google Sheets
                            hoja_stock.update_cell(fila_num, 2, stock_real)
                            
                            # 2. Refrescamos tokens de las OTRAS cuentas por seguridad antes de sincronizar
                            tokens_actualizados = obtener_tokens(hoja_tokens)
                            for c_nombre in ["cuenta_a", "cuenta_b", "cuenta_c"]:
                                if c_nombre != cuenta_origen:
                                    refrescar_token_cuenta(hoja_tokens, c_nombre, tokens_actualizados[c_nombre]['refresh_token'])
                            
                            # Volvemos a leer tokens frescos post-renovación
                            tokens_finales = obtener_tokens(hoja_tokens)
                            
                            # 3. Replicamos el stock en las cuentas restantes
                            if cuenta_origen != "cuenta_a":
                                actualizar_stock_ml(id_a, stock_real, tokens_finales["cuenta_a"]['access_token'])
                            if cuenta_origen != "cuenta_b":
                                actualizar_stock_ml(id_b, stock_real, tokens_finales["cuenta_b"]['access_token'])
                            if cuenta_origen != "cuenta_c":
                                actualizar_stock_ml(id_c, stock_real, tokens_finales["cuenta_c"]['access_token'])
            
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({"status": "ok"}).encode('utf-8'))
        except Exception as e:
            self.send_response(500)
            self.end_headers()
            self.wfile.write(str(e).encode('utf-8'))
