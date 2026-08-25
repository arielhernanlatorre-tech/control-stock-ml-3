import os
import json
import requests
from flask import Flask, request, jsonify
# Usamos el cliente oficial de Upstash Redis que no pierde la conexión en Flask
try:
    from upstash_redis import Redis
    kv = Redis.from_env() # Toma automáticamente las claves de tu pestaña Storage
except ImportError:
    kv = None

app = Flask(__name__)

def obtener_y_refrescar_token(cuenta_clave):
    if not kv:
        print("❌ Error: El cliente Redis de Upstash no está disponible.")
        return None

    # Obtenemos los tokens directamente desde la base de datos
    datos_token_str = kv.get(f"tokens:{cuenta_clave}")
    
    if not datos_token_str:
        print(f"❌ No se encontraron tokens en KV para {cuenta_clave}.")
        return None

    try:
        token_data = json.loads(datos_token_str) if isinstance(datos_token_str, str) else datos_token_str
    except Exception:
        token_data = datos_token_str
        
    access_token = token_data.get('access_token')
    refresh_token = token_data.get('refresh_token')

    url_test = "https://api.mercadolibre.com/users/me"
    headers_test = {"Authorization": f"Bearer {access_token}"}
    resp_test = requests.get(url_test, headers=headers_test)

    if resp_test.status_code == 200:
        return access_token

    print(f"🔄 Token vencido para [{cuenta_clave}]. Renovando en Mercado Libre...")
    url_oauth = "https://api.mercadolibre.com/oauth/token"
    payload = {
        "grant_type": "refresh_token",
        "client_id": os.environ.get("ML_CLIENT_ID"),
        "client_secret": os.environ.get("ML_CLIENT_SECRET"),
        "refresh_token": refresh_token
    }
    headers_oauth = {"accept": "application/json", "content-type": "application/x-www-form-urlencoded"}
    
    resp_oauth = requests.post(url_oauth, data=payload, headers=headers_oauth)
    if resp_oauth.status_code == 200:
        nuevos_datos = resp_oauth.json()
        nuevo_access = nuevos_datos.get("access_token")
        nuevo_refresh = nuevos_datos.get("refresh_token")
        
        estructura_guardado = {"access_token": nuevo_access, "refresh_token": nuevo_refresh}
        kv.set(f"tokens:{cuenta_clave}", json.dumps(estructura_guardado))
        print(f"✅ Tokens de [{cuenta_clave}] actualizados con éxito en Vercel KV.")
        return nuevo_access
    else:
        print(f"❌ Error crítico al renovar token: {resp_oauth.text}")
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
    r = requests.put(url, json=payload, headers=headers)
    print(f"   ↳ Sincronizando {item_id} a {nuevo_stock} unidades. Status API: {r.status_code}")

@app.route('/', defaults={'path': ''}, methods=['POST', 'GET'])
@app.route('/<path:path>', methods=['POST', 'GET'])
def catch_all(path):
    if request.method == 'GET':
        return jsonify({"status": "online", "mensaje": "Servidor activo. Monitoreando Webhooks con Upstash."}), 200

    try:
        notificacion = request.get_json(silent=True)
        if not notificacion:
            return jsonify({"error": "No se recibieron datos JSON válidos"}), 400
            
        print(f"📩 Webhook recibido: {json.dumps(notificacion)}")
        
        if notificacion.get("topic") == "items":
            recurso = notificacion.get("resource", "")
            item_id = recurso.split("/")[-1]
            
            if not kv:
                return jsonify({"error": "Base de datos KV no inicializada"}), 500

            mapa_productos_str = kv.get("mapa_productos")
            if not mapa_productos_str:
                print("⚠️ No hay equivalencias de productos cargadas.")
                return jsonify({"status": "no_product_map"}), 200
                
            try:
                mapa_productos = json.loads(mapa_productos_str) if isinstance(mapa_productos_str, str) else mapa_productos_str
            except Exception:
                mapa_productos = mapa_productos_str
            
            producto_encontrado = None
            for prod in mapa_productos:
                if item_id in [prod.get("id_a"), prod.get("id_b"), prod.get("id_c")]:
                    producto_encontrado = prod
                    break
            
            if producto_encontrado:
                id_a = producto_encontrado.get("id_a", "")
                id_b = producto_encontrado.get("id_b", "")
                id_c = producto_encontrado.get("id_c", "")
                
                mapeo_cuentas = {"cuenta_a": id_a, "cuenta_b": id_b, "cuenta_c": id_c}
                cuenta_origen = None
                for k, v in mapeo_cuentas.items():
                    if v == item_id:
                        cuenta_origen = k
                        break
                
                if cuenta_origen:
                    token_actual = obtener_y_refrescar_token(cuenta_origen)
                    if not token_actual:
                        return jsonify({"error": f"No se pudo validar el token de {cuenta_origen}"}), 400
                    
                    url_item = f"https://api.mercadolibre.com/items/{item_id}"
                    headers = {"Authorization": f"Bearer {token_actual}"}
                    resp_item = requests.get(url_item, headers=headers)
                    
                    if resp_item.status_code == 200:
                        stock_real = int(resp_item.json().get("available_quantity", 0))
                        
                        ultimo_stock_guardado = kv.get(f"stock_actual:{id_a}")
                        if ultimo_stock_guardado and int(ultimo_stock_guardado) == stock_real:
                            print(f"🛑 Webhook ignorado para {item_id}: Stock ya replicado ({stock_real} u.).")
                            return jsonify({"status": "ignored", "reason": "loop_prevention"}), 200
                            
                        kv.set(f"stock_actual:{id_a}", stock_real)
                        print(f"🚨 ¡Cambio detectado! Origen: {cuenta_origen}. Stock: {stock_real}")
                        
                        for cuenta_destino, id_destino in mapeo_cuentas.items():
                            if cuenta_destino != cuenta_origen and id_destino:
                                token_destino = obtener_y_refrescar_token(cuenta_destino)
                                if token_destino:
                                    try:
                                        actualizar_stock_ml(id_destino, stock_real, token_destino)
                                    except Exception as e:
                                        print(f"⚠️ Error al actualizar {cuenta_destino}: {e}")
                            
        return jsonify({"status": "ok"}), 200

    except Exception as e:
        print(f"❌ Error interno procesando el Webhook: {str(e)}")
        return jsonify({"error": str(e)}), 500
