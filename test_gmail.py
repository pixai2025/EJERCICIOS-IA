import os
import pickle
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

# Scopes necesarios para Gmail
SCOPES = ['https://www.googleapis.com/auth/gmail.readonly']

def authenticate_gmail():
    """Autenticación inicial con Gmail"""
    creds = None
    
    # El archivo token.json almacena los tokens de acceso del usuario
    if os.path.exists('token.json'):
        creds = Credentials.from_authorized_user_file('token.json', SCOPES)
    
    # Si no hay credenciales válidas disponibles, permite al usuario autorizarse
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(
                'credentials.json', SCOPES)
            # Esto abrirá tu navegador para autorizarte
            creds = flow.run_local_server(port=0)
        
        # Guarda las credenciales para la próxima ejecución
        with open('token.json', 'w') as token:
            token.write(creds.to_json())
    
    return build('gmail', 'v1', credentials=creds)

def test_gmail_connection():
    """Prueba la conexión y obtiene información básica"""
    print("🚀 Iniciando prueba de conexión con Gmail...")
    
    try:
        service = authenticate_gmail()
        
        # Obtener información del perfil
        profile = service.users().getProfile(userId='me').execute()
        print(f"✅ Conectado exitosamente!")
        print(f"📧 Email: {profile['emailAddress']}")
        print(f"📊 Total de mensajes: {profile['messagesTotal']}")
        
        # Obtener los últimos 5 correos
        print("\n📬 Últimos 5 correos:")
        results = service.users().messages().list(
            userId='me', 
            maxResults=5
        ).execute()
        
        messages = results.get('messages', [])
        
        for i, message in enumerate(messages, 1):
            msg = service.users().messages().get(
                userId='me', 
                id=message['id']
            ).execute()
            
            headers = msg['payload'].get('headers', [])
            subject = next((h['value'] for h in headers if h['name'] == 'Subject'), 'Sin asunto')
            sender = next((h['value'] for h in headers if h['name'] == 'From'), 'Sin remitente')
            
            print(f"{i}. {subject[:50]}...")
            print(f"   De: {sender[:50]}...")
            print()
        
        print("🎉 ¡Perfecto! Tu conexión con Gmail está funcionando.")
        return True
        
    except Exception as error:
        print(f"❌ Error: {error}")
        print("\n🔧 Posibles soluciones:")
        print("1. Verifica que credentials.json esté en la carpeta correcta")
        print("2. Asegúrate de que Gmail API esté habilitada")
        print("3. Revisa que hayas configurado la pantalla de consentimiento")
        return False

if __name__ == "__main__":
    test_gmail_connection()
