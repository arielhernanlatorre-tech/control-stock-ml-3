# VERCEL DEPLOYMENT BYPASS: SOLUCIÓN COMPLETA PARA ENTORNO Y VARIACIONES
import os
import json
import requests
import gspread
from flask import Flask, request, jsonify 
from google.oauth2.service_account import Credentials
from upstash_redis import Redis

app = Flask(__name__)

# CONFIGURACIÓN FORZADA: Forzamos tus datos reales anulando las variables internas de Vercel
UPSTASH_REDIS_REST_URL = "https://united-basilisk-148242.upstash.io"
UPSTASH_REDIS_REST_TOKEN = "gQAAAAAAAkMSAAIgcDE5ZGUxYTkzMzAwNzY0NDllYTk3YTNmMmI1NTc1MjMyYw"

# Inicializamos el cliente de Redis de forma directa
redis = Redis(url=UPSTASH_REDIS_REST_URL, token=UPSTASH_REDIS_REST_TOKEN)

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

def obtener_tokens():
    """Lee los tokens directamente desde Vercel KV en tiempo real."""
    resultado_tokens = {}
    cuentas = ["cuenta_a", "cuenta_b", "cuenta_c"]
    
    for cuenta in cuentas:
        try:
            datos_raw = redis.get(f"tokens:{cuenta}")
            
            if datos_raw:
                if isinstance(datos_raw, str):
                    datos_json = json.loads(datos_raw)
                else:
                    datos_json = datos_raw
                
                resultado_tokens[cuenta] = {
                    "access_token": datos_json.get("access_token", ""),
                    "refresh_token": datos_json.get("refresh_token", "")
                }
            else:
                print(f"⚠️ Advertencia: No se encontraron tokens en KV para {cuenta}. Usando vacíos.")
                resultado_tokens[cuenta] = {"access_token": "", "refresh_token": ""}
                
        except Exception as e:
            print(f"❌ Error al leer tokens de Redis para {cuenta}: {e}")
            resultado_tokens[cuenta] = {"access_token": "", "refresh_token": ""}
            
    return resultado_tokens

def actualizar_stock_ml(item_id, nuevo_stock, access_token, nombre_cuenta=""):
    """Envía la actualización de stock controlando de forma inteligente las variaciones."""
    id_limpio = str(item_id).strip() if item_id else ""
    if not id_limpio or id_limpio.upper() == "N/A" or len(id_limpio) < 5 or not id_limpio.upper().startswith("MLA"):
        print(f"⏩ Saltando réplica para {nombre_cuenta}: ID inválido o vacío ('{item_id}')")
        return

    url_item = f"https://api.mercadolibre.com/items/{id_limpio}"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json"
    }
    
    try:
        # Consultamos primero el ítem de destino para verificar variaciones físicas
        resp_dest = requests.get(url_item, headers={"Authorization": f"Bearer {access_token}"})
        
        if resp_dest.status_code == 200:
            json_dest = resp_dest.json()
            variaciones = json_dest.get("variations", [])
            
            # Si el producto tiene variaciones, inyectamos la cantidad en cada una de ellas
            if variaciones and len(variaciones) > 0:
                lista_variaciones = []
                for v in variaciones:
                    lista_variaciones.append({
                        "id": v.get("id"),
                        "available_quantity": int(nuevo_stock)
                    })
                payload = {"variations": lista_variaciones}
            else:
                # Formato clásico para productos estándar
                payload = {"available_quantity": int(nuevo_stock)}
                
            respuesta = requests.put(url_item, json=payload, headers=headers)
            if respuesta.status_code == 200 or respuesta.status_code == 201:
                print(f"✅ ¡Éxito! Stock replicado en {nombre_cuenta} para el ítem {id_limpio}")
            else:
                print(f"⚠️ {nombre_cuenta} rechazó actualización ({id_limpio}). Status: {respuesta.status_code}")
        else:
            print(f"❌ No se pudo consultar el ítem destino {id_limpio} en {nombre_cuenta}.")
            
    except Exception as err:
        print(f"❌ Fallo al conectar con la API para {nombre_cuenta}: {err}")

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
                
                # Extracción segura de columnas
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
                    
                    if not token_actual:
                        print(f"❌ No hay token disponible para la cuenta origen: {cuenta_origen}")
                        return jsonify({"status": "error_token_origen"}), 200
                        
                    url_item = f"https://api.mercadolibre.com/items/{item_id}"
                    headers = {"Authorization": f"Bearer {token_actual}"}
                    resp_item = requests.get(url_item, headers=headers)
                    
                    if resp_item.status_code == 200:
                        stock_real = resp_item.json().get("available_quantity")
                        
                        hoja_stock.update_cell(fila_num, 2, stock_real)
                        
                        try:
                            redis.set(f"stock_actual:{item_id}", stock_real)
                        except Exception as redis_err:
                            print(f"⚠️ Error al guardar en Redis: {redis_err}")
                        
                        if cuenta_origen != "cuenta_a":
                            actualizar_stock_ml(id_a, stock_real, tokens_finales["cuenta_a"]['access_token'], "Cuenta A")
                                
                        if cuenta_origen != "cuenta_b":
                            actualizar_stock_ml(id_b, stock_real, tokens_finales["cuenta_b"]['access_token'], "Cuenta B")
                                
                        if cuenta_origen != "cuenta_c":
                            actualizar_stock_ml(id_c, stock_real, tokens_finales["cuenta_c"]['access_token'], "Cuenta C")
                            
        return jsonify({"status": "ok"}), 200

    except Exception as e:
        print(f"❌ Error crítico interno controlado: {str(e)}")
        return jsonify({"status": "error_interno_controlado", "detalle": str(e)}), 200

# EXPORTACIONES REQUERIDAS POR VERCEL PARA EVITAR ERRORES TOP-LEVEL
application = app
handler = app
