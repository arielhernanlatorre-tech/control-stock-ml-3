import os
import json
import requests
import gspread
from flask import Flask, request, jsonify 
from google.oauth2.service_account import Credentials

app = Flask(__name__)

def inicializar_google_sheets():
    alcance = [
        'https://googleapis.com',
        'https://googleapis.com'
    ]
    
    if "CREDENTIALS_JSON" in os.environ:
        info_credenciales = json.loads(os.environ["CREDENTIALS_JSON"])
        credenciales = Credentials.from_service_account_info(info_credenciales, scopes=alcance)
    else:
        ruta_credenciales = os.path.join(os.getcwd(), 'credentials.json')
        credenciales = Credentials.from_service_account_file(ruta_credenciales, scopes=alcance)
        
    cliente = gspread.authorize(credenciales)
    return cliente.open_by_key(os.environ.get("GOOGLE_SPREADSHEET_ID"))

def obtener_tokens(hoja_tokens=None):
    """Lee los tokens directamente desde las Variables de Entorno de Vercel."""
    return {
        "cuenta_a": {
            "access_token": os.environ.get("TOKEN_CUENTA_A", ""),
            "refresh_token": os.environ.get("REFRESH_CUENTA_A", "")
        },
        "cuenta_b": {
            "access_token": os.environ.get("TOKEN_CUENTA_B", ""),
            "refresh_token": os.environ.get("REFRESH_CUENTA_B", "")
        },
        "cuenta_c": {
            "access_token": os.environ.get("TOKEN_CUENTA_C", ""),
            "refresh_token": os.environ.get("REFRESH_CUENTA_C", "")
        }
    }

def actualizar_stock_ml(item_id, nuevo_stock, access_token):
    if not item_id or str(item_id).strip().upper() == "N/A" or not str(item_id).startswith("MLA"):
        return
    url = f"https://mercadolibre.com{item_id}"
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
                    tokens_finales = obtener_tokens()
                    token_actual = tokens_finales[cuenta_origen]['access_token']
                    
                    url_item = f"https://mercadolibre.com{item_id}"
                    headers = {"Authorization": f"Bearer {token_actual}"}
                    resp_item = requests.get(url_item, headers=headers)
                    
                    if resp_item.status_code == 200:
                        stock_real = resp_item.json().get("available_quantity")
                        
                        # 1. Actualizamos el Google Sheets en tiempo real (Pestaña Stock)
                        hoja_stock.update_cell(fila_num, 2, stock_real)
                        
                        # 2. Replicamos el stock de forma aislada a las cuentas espejo usando Vercel
                        if cuenta_origen != "cuenta_a":
                            try:
                                actualizar_stock_ml(id_a, stock_real, tokens_finales["cuenta_a"]['access_token'])
                            except Exception as e:
                                print(f"⚠️ Error al actualizar Cuenta A: {e}")
                                
                        if cuenta_origen != "cuenta_b":
                            try:
                                actualizar_stock_ml(id_b, stock_real, tokens_finales["cuenta_b"]['access_token'])
                            except Exception as e:
                                print(f"⚠️ Error al actualizar Cuenta B: {e}")
                                
                        if cuenta_origen != "cuenta_c":
                            try:
                                actualizar_stock_ml(id_c, stock_real, tokens_finales["cuenta_c"]['access_token'])
                            except Exception as e:
                                print(f"⚠️ Error al actualizar Cuenta C: {e}")
                            
        return jsonify({"status": "ok"}), 200

    except Exception as e:
        print(f"❌ Error interno: {str(e)}")
        return jsonify({"error": str(e)}), 500
