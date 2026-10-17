import os
import json
import requests
import gspread
from flask import Flask, request, jsonify
from google.oauth2.service_account import Credentials
from upstash_redis import Redis

app = Flask(__name__)

# CONFIGURACIÓN AUTOMÁTICA NATIVA DE VERCEL KV
# Al usar .from_env(), la librería lee directamente KV_REST_API_URL y KV_REST_API_TOKEN de tu panel
try:
    redis = Redis.from_env()
    print("✅ Conexión con Vercel KV (Upstash) inicializada desde el entorno.")
except Exception as e:
    print(f"❌ Error crítico al conectar con Vercel KV: {e}")
    redis = None

def inicializar_google_sheets():
    """Conecta con Google Sheets usando la variable de entorno o un archivo local."""
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
    
    return gspread.authorize(credenciales).open_by_key(os.environ.get("GOOGLE_SPREADSHEET_ID"))

def obtener_tokens():
    """Lee de forma dinámica los access_tokens vigentes guardados en Vercel KV."""
    resultado_tokens = {}
    cuentas = ["cuenta_a", "cuenta_b", "cuenta_c"]
    
    for cuenta in cuentas:
        try:
            if not redis:
                raise Exception("Cliente Redis no disponible")
            
            datos_raw = redis.get(f"tokens:{cuenta}")
            if datos_raw:
                datos_json = json.loads(datos_raw) if isinstance(datos_raw, str) else datos_raw
                resultado_tokens[cuenta] = {
                    "access_token": datos_json.get("access_token", ""),
                    "refresh_token": datos_json.get("refresh_token", "")
                }
            else:
                print(f"⚠️ Advertencia: No se encontraron tokens en KV para {cuenta}.")
                resultado_tokens[cuenta] = {"access_token": "", "refresh_token": ""}
        except Exception as e:
            print(f"❌ Error al leer tokens de Redis para {cuenta}: {e}")
            resultado_tokens[cuenta] = {"access_token": "", "refresh_token": ""}
            
    return resultado_tokens

def actualizar_stock_ml(item_id, nuevo_stock, access_token, nombre_cuenta=""):
    """Envía la actualización de stock aplicando un bloqueo temporal en Redis para evitar bucles."""
    id_limpio = str(item_id).strip() if item_id else ""
    if not id_limpio or id_limpio.upper() == "N/A" or len(id_limpio) < 5 or not id_limpio.upper().startswith("MLA"):
        return

    if redis:
        # Colocamos un bloqueo (lock) de 45 segundos para indicarle a nuestra app 
        # que el cambio entrante fue provocado por nosotros mismos y no por una venta real.
        redis.set(f"lock:{id_limpio}", "true", ex=45)

    url_item = f"https://mercadolibre.com{id_limpio}"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json"
    }
    
    try:
        # Consultamos el ítem destino para verificar si posee variaciones
        resp_dest = requests.get(url_item, headers={"Authorization": f"Bearer {access_token}"})
        if resp_dest.status_code == 200:
            json_dest = resp_dest.json()
            variaciones = json_dest.get("variations", [])

            if variaciones:
                # Modificación para múltiples variaciones estándar
                lista_variaciones = [{"id": v.get("id"), "available_quantity": int(nuevo_stock)} for v in variaciones]
                payload = {"variations": lista_variaciones}
            else:
                # Modificación clásica para ítems individuales sin variación
                payload = {"available_quantity": int(nuevo_stock)}

            respuesta = requests.put(url_item, json=payload, headers=headers)
            if respuesta.status_code in:
                print(f"✅ ¡Éxito! Stock replicado en {nombre_cuenta} para el ítem {id_limpio}")
            else:
                print(f"⚠️ {nombre_cuenta} rechazó actualización ({id_limpio}). Status: {respuesta.status_code}")
        else:
            print(f"❌ No se pudo consultar el ítem destino {id_limpio} en {nombre_cuenta}.")
    except Exception as err:
        print(f"❌ Fallo de conexión con la API de Mercado Libre para {nombre_cuenta}: {err}")

@app.route('/', defaults={'path': ''}, methods=['POST', 'GET'])
@app.route('/<path:path>', methods=['POST', 'GET'])
def catch_all(path):
    if request.method == 'GET':
        return jsonify({"status": "online", "mensaje": "Servidor activo con Vercel KV nativo."}), 200

    try:
        notificacion = request.get_json(silent=True)
        if not notificacion:
            return jsonify({"error": "No se recibieron datos JSON válidos"}), 400

        print(f"📩 Webhook recibido: {json.dumps(notificacion)}")

        if notificacion.get("topic") == "items":
            recurso = notificacion.get("resource", "")
            item_id = recurso.split("/")[-1]

            # CONTROL ANTI-BUCLE (LOOP PROTECTION):
            # Si existe un lock activo para este item_id, significa que el cambio de stock lo hicimos nosotros.
            # Consumimos el bloqueo, lo borramos y salimos de inmediato sin replicar infinitamente.
            if redis and redis.get(f"lock:{item_id}"):
                print(f"⏩ Webhook ignorado para {item_id} (Modificación interna detectada de forma segura).")
                redis.delete(f"lock:{item_id}")
                return jsonify({"status": "ignored_loop_protection"}), 200

            doc = inicializar_google_sheets()
            hoja_stock = doc.worksheet("Stock")
            celda = hoja_stock.find(item_id)
            
            if celda:
                fila_num = celda.row
                fila_datos = hoja_stock.row_values(fila_num)
                
                # Extracción defensiva controlando el largo real de las columnas leídas de Sheets
                id_a = fila_datos[2] if len(fila_datos) > 2 else ""
                id_b = fila_datos[3] if len(fila_datos) > 3 else ""
                id_c = fila_datos[4] if len(fila_datos) > 4 else ""

                mapeo_cuentas = {"cuenta_a": id_a, "cuenta_b": id_b, "cuenta_c": id_c}
                cuenta_origen = next((k for k, v in mapeo_cuentas.items() if v == item_id), None)

                if cuenta_origen:
                    tokens_finales = obtener_tokens()
                    token_actual = tokens_finales[cuenta_origen]['access_token']
                    
                    if not token_actual:
                        print(f"❌ No hay token disponible para la cuenta origen: {cuenta_origen}")
                        return jsonify({"status": "error_token_origen"}), 200

                    # Consultamos el stock real actual de la cuenta que vendió
                    url_item = f"https://mercadolibre.com{item_id}"
                    resp_item = requests.get(url_item, headers={"Authorization": f"Bearer {token_actual}"})
                    
                    if resp_item.status_code == 200:
                        stock_real = resp_item.json().get("available_quantity")
                        
                        # Actualizamos la hoja de cálculo en la columna 2 (B)
                        hoja_stock.update_cell(fila_num, 2, stock_real)
                        
                        try:
                            if redis:
                                redis.set(f"stock_actual:{item_id}", stock_real)
                        except Exception as redis_err:
                            print(f"⚠️ Error al registrar stock actual en Redis: {redis_err}")

                        # Replicamos de forma cruzada a las cuentas restantes (solo si el id existe en el Sheet)
                        if cuenta_origen != "cuenta_a" and id_a:
                            actualizar_stock_ml(id_a, stock_real, tokens_finales["cuenta_a"]['access_token'], "Cuenta A")
                        if cuenta_origen != "cuenta_b" and id_b:
                            actualizar_stock_ml(id_b, stock_real, tokens_finales["cuenta_b"]['access_token'], "Cuenta B")
                        if cuenta_origen != "cuenta_c" and id_c:
                            actualizar_stock_ml(id_c, stock_real, tokens_finales["cuenta_c"]['access_token'], "Cuenta C")

            return jsonify({"status": "ok"}), 200
            
    except Exception as e:
        print(f"❌ Error crítico interno controlado: {str(e)}")
        return jsonify({"status": "error_interno_controlado", "detalle": str(e)}), 200

# Exportaciones que requiere Vercel Serverless
application = app
handler = app
