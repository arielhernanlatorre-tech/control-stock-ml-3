import os
import json
import requests
import gspread
from flask import Flask, request, jsonify 
from google.oauth2.service_account import Credentials

app = Flask(__name__)

def inicializar_google_sheets():
    alcance = [
        'https://www.googleapis.com/auth/spreadsheets',
        'https://www.googleapis.com/auth/drive'
    ]
    
    if "CREDENTIALS_JSON" in os.environ:
        info_credenciales = json.loads(os.environ["CREDENTIALS_JSON"])
        credenciales = Credentials.from_service_account_info(info_credenciales, scopes=alcance)
    else:
        ruta_credenciales = os.path.join(os.getcwd(), 'credentials.json')
        credenciales = Credentials.from_service_account_file(ruta_credenciales, scopes=alcance)
        
    cliente = gspread.authorize(credenciales)
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
    url = f"https://api.mercadolibre.com/items/{item_id}"
    payload = {"available_quantity": int(nuevo_stock)}
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json"
    }
    requests.put(url, json=payload, headers=headers)

@app.route('/', defaults={'path': ''}, methods=['POST', 'GET'])
@app.route('/<path:path>', methods=['POST', 'GET'])
def catch_all(path):
    if request.method == 'GET':
        return jsonify({"status": "online", "mensaje": "Servidor activo. Usa POST para enviar webhooks."}), 200

    try:
        notificacion = request.get_json(silent=True)
        if not notificacion:
            return jsonify({"error": "No se recibieron datos JSON válidos"}), 400
            
        print(f"📩 Webhook recibido: {json.dumps(notificacion)}")
        
        if notificacion.get("topic") == "items":
            recurso = notificacion.get("resource", "")
            item_id = recurso.split("/")[-1]
            
            doc = inicializar_google_sheets()
            hoja_stock = doc.worksheet("Stock")
            hoja_tokens = doc.worksheet("Tokens")
            
            celda = hoja_stock.find(item_id)
            if celda:
                fila_num = celda.row
                fila_datos = hoja_stock.row_values(fila_num)
                
                # Asignación segura de columnas según tu estructura
                id_a = fila_datos[2] if len(fila_datos) > 2 else ""
                id_b = fila_datos[3] if len(fila_datos) > 3 else ""
                id_c = fila_datos[4] if len(fila_datos) > 4 else ""
                
                mapeo_cuentas = {"cuenta_a": id_a, "cuenta_b": id_b, "cuenta_c": id_c}
                cuenta_origen = None
                for k, v in mapeo_cuentas.items():
                    if v == item_id:
                        cuenta_origen = k
                        break
                
                if cuenta_origen:
                    tokens = obtener_tokens(hoja_tokens)
                    token_actual = tokens[cuenta_origen]['access_token']
                    
                    url_item = f"https://api.mercadolibre.com/items/{item_id}"
                    headers = {"Authorization": f"Bearer {token_actual}"}
                    resp_item = requests.get(url_item, headers=headers)
                    
                    if resp_item.status_code == 401:
                        nuevo_token = refrescar_token_cuenta(hoja_tokens, cuenta_origen, tokens[cuenta_origen]['refresh_token'])
                        if nuevo_token:
                            headers = {"Authorization": f"Bearer {nuevo_token}"}
                            resp_item = requests.get(url_item, headers=headers)
                    
                    if resp_item.status_code == 200:
                        stock_real = resp_item.json().get("available_quantity")
                        
                        # 1. Actualizamos el Google Sheets en tiempo real
                        hoja_stock.update_cell(fila_num, 2, stock_real)
                        
                        # 2. Intentamos refrescar los tokens espejos de forma segura
                        try:
                            tokens_actualizados = obtener_tokens(hoja_tokens)
                            for c_nombre in ["cuenta_a", "cuenta_b", "cuenta_c"]:
                                if c_nombre != cuenta_origen:
                                    refrescar_token_cuenta(hoja_tokens, c_nombre, tokens_actualizados[c_nombre]['refresh_token'])
                        except Exception as e:
                            print(f"⚠️ No se pudieron refrescar los tokens espejo: {e}")
                        
                        tokens_finales = obtener_tokens(hoja_tokens)
                        
                        # 3. Replicamos el stock de forma aislada (si una falla, las demás siguen)
                        if cuenta_origen != "cuenta_a":
                            try:
                                actualizar_stock_ml(id_a, stock_real, tokens_finales["cuenta_a"]['access_token'])
                            except Exception:
                                print("⚠️ Error al actualizar Cuenta A")
                                
                        if cuenta_origen != "cuenta_b":
                            try:
                                actualizar_stock_ml(id_b, stock_real, tokens_finales["cuenta_b"]['access_token'])
                            except Exception:
                                print("⚠️ Error al actualizar Cuenta B")
                                
                        if cuenta_origen != "cuenta_c":
                            try:
                                actualizar_stock_ml(id_c, stock_real, tokens_finales["cuenta_c"]['access_token'])
                            except Exception:
                                print("⚠️ Error al actualizar Cuenta C")
                            
        return jsonify({"status": "ok"}), 200

    except Exception as e:
        print(f"❌ Error interno: {str(e)}")
        return jsonify({"error": str(e)}), 500

