import json
import requests

def cargar_configuracion():
    """Lee el archivo de configuración con las credenciales."""
    with open("config.json", "r", encoding="utf-8") as archivo:
        return json.load(archivo)

def guardar_tokens_en_cuenta(datos_respuesta, cuenta):
    """Guarda el access y refresh token en el bloque correspondiente del config.json."""
    config = cargar_configuracion()
    
    if cuenta in config:
        config[cuenta]["access_token"] = datos_respuesta.get("access_token")
        config[cuenta]["refresh_token"] = datos_respuesta.get("refresh_token")
        
        with open("config.json", "w", encoding="utf-8") as archivo:
            json.dump(config, archivo, indent=4, ensure_ascii=False)
        print(f"💾 Tokens guardados correctamente en la sección '{cuenta}' de config.json.")
    else:
        print(f"❌ Error: La cuenta '{cuenta}' no está definida en el archivo de configuración.")

def intercambiar_codigo():
    config = cargar_configuracion()
    
    print("📋 Configuración detectada. Por favor ingresa los siguientes datos:")
    cuenta_destino = input("Indica la cuenta a vincular (ejemplo: cuenta_b o cuenta_c): ").strip().lower()
    
    print("\nVe al navegador, autoriza la app y copia el código que aparece en la URL de Google (?code=TG-...)")
    code = input("Pega el código de autorización aquí: ").strip()
    
    if not code:
        print("❌ Error: El código de autorización no puede estar vacío.")
        return

    url = "https://api.mercadolibre.com/oauth/token"
    
    payload = {
        "grant_type": "authorization_code",
        "client_id": config.get("client_id"),
        "client_secret": config.get("client_secret"),
        "code": code,
        "redirect_uri": "https://google.com"
    }
    
    headers = {
        "accept": "application/json",
        "content-type": "application/x-www-form-urlencoded"
    }
    
    print(f"\n⏳ Solicitando Access Token para '{cuenta_destino}' a Mercado Libre...")
    
    try:
        respuesta = requests.post(url, data=payload, headers=headers)
        
        if respuesta.status_code == 200:
            print("✅ Token obtenido con éxito de la API.")
            guardar_tokens_en_cuenta(respuesta.json(), cuenta_destino)
        else:
            print(f"❌ Error al obtener el token. Status: {respuesta.status_code}")
            print(f"Detalle del error: {respuesta.text}")
            
    except requests.exceptions.RequestException as e:
        print(f"❌ Ocurrió un error en la conexión de red: {e}")

if __name__ == "__main__":
    intercambiar_codigo()
