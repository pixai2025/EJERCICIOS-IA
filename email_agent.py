import os
import base64
import sqlite3
from datetime import datetime, timedelta
import json
import re
from typing import List, Dict, Any

# APIs
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from openai import OpenAI
import requests
import schedule
import time

# Configuración
from dotenv import load_dotenv
load_dotenv()

class EmailIntelligenceAgent:
    def __init__(self):
        # Configuración de APIs
        self.openai_client = OpenAI(api_key=os.getenv('OPENAI_API_KEY'))
        self.whatsapp_token = os.getenv('WHATSAPP_TOKEN')
        self.phone_number = os.getenv('MY_PHONE_NUMBER')
        
        # Gmail API scopes
        self.SCOPES = ['https://www.googleapis.com/auth/gmail.readonly']
        
        # Base de datos
        self.init_database()
        
        # Configuraciones personalizadas
        self.vip_senders = [
            'cliente@importante.com',
            'jefe@empresa.com',
            'contrato@proveedor.com'
        ]
        
        self.critical_keywords = [
            'urgente', 'crítico', 'problema', 'error', 'fallo',
            'presupuesto', 'contrato', 'factura', 'pago',
            'reunión', 'deadline', 'entrega', 'proyecto'
        ]
    
    def init_database(self):
        """Inicializa la base de datos para tracking"""
        conn = sqlite3.connect('email_tracking.db')
        cursor = conn.cursor()
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS processed_emails (
                id TEXT PRIMARY KEY,
                processed_date TIMESTAMP,
                subject TEXT,
                sender TEXT,
                importance_level TEXT,
                summary TEXT
            )
        ''')
        
        conn.commit()
        conn.close()
    
    def authenticate_gmail(self):
        """Autenticación con Gmail API"""
        creds = None
        
        if os.path.exists('token.json'):
            creds = Credentials.from_authorized_user_file('token.json', self.SCOPES)
        
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                flow = InstalledAppFlow.from_client_secrets_file(
                    'credentials.json', self.SCOPES)
                creds = flow.run_local_server(port=0)
            
            with open('token.json', 'w') as token:
                token.write(creds.to_json())
        
        return build('gmail', 'v1', credentials=creds)
    
    def get_new_emails(self) -> List[Dict]:
        """Obtiene correos nuevos desde ayer"""
        service = self.authenticate_gmail()
        
        # Fecha de ayer
        yesterday = (datetime.now() - timedelta(days=1)).strftime('%Y/%m/%d')
        
        # Buscar correos desde ayer
        query = f'after:{yesterday} in:inbox'
        
        try:
            result = service.users().messages().list(
                userId='me', 
                q=query,
                maxResults=50
            ).execute()
            
            messages = result.get('messages', [])
            emails = []
            
            for message in messages:
                # Verificar si ya fue procesado
                if self.is_already_processed(message['id']):
                    continue
                
                # Obtener detalles del correo
                msg = service.users().messages().get(
                    userId='me', 
                    id=message['id']
                ).execute()
                
                email_data = self.parse_email(msg)
                if email_data:
                    emails.append(email_data)
            
            return emails
            
        except Exception as error:
            print(f'Error al obtener correos: {error}')
            return []
    
    def parse_email(self, message: Dict) -> Dict:
        """Extrae información del correo"""
        payload = message['payload']
        headers = payload.get('headers', [])
        
        # Extraer headers importantes
        subject = next((h['value'] for h in headers if h['name'] == 'Subject'), '')
        sender = next((h['value'] for h in headers if h['name'] == 'From'), '')
        date = next((h['value'] for h in headers if h['name'] == 'Date'), '')
        
        # Extraer el cuerpo del correo
        body = self.extract_email_body(payload)
        
        return {
            'id': message['id'],
            'subject': subject,
            'sender': sender,
            'date': date,
            'body': body[:1000],  # Limitar a 1000 caracteres
            'snippet': message.get('snippet', '')
        }
    
    def extract_email_body(self, payload: Dict) -> str:
        """Extrae el contenido del correo"""
        body = ""
        
        if 'parts' in payload:
            for part in payload['parts']:
                if part['mimeType'] == 'text/plain':
                    if 'data' in part['body']:
                        body = base64.urlsafe_b64decode(part['body']['data']).decode('utf-8')
                        break
        elif payload['mimeType'] == 'text/plain':
            if 'data' in payload['body']:
                body = base64.urlsafe_b64decode(payload['body']['data']).decode('utf-8')
        
        return body
    
    def analyze_email_with_ai(self, email: Dict) -> Dict:
        """Analiza el correo con IA para determinar importancia y generar resumen"""
        
        prompt = f"""
        Analiza este correo electrónico y proporciona la siguiente información en formato JSON:

        CORREO:
        Remitente: {email['sender']}
        Asunto: {email['subject']}
        Contenido: {email['body']}

        PROPORCIONA:
        {{
            "importancia": "ALTA|MEDIA|BAJA",
            "categoria": "TRABAJO|PERSONAL|CLIENTE|PROVEEDOR|MARKETING|SPAM",
            "emocion": "POSITIVO|NEUTRAL|NEGATIVO|ENFADADO",
            "requiere_accion": true/false,
            "es_urgente": true/false,
            "resumen": "Resumen en máximo 2 líneas",
            "acciones_sugeridas": ["acción1", "acción2"],
            "palabras_clave": ["palabra1", "palabra2"]
        }}

        Contexto: Soy publicista y copywriter. Prioriza correos de clientes, proyectos y oportunidades de negocio.
        """
        
        try:
            response = self.openai_client.chat.completions.create(
                model="gpt-4",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3
            )
            
            analysis = json.loads(response.choices[0].message.content)
            return analysis
            
        except Exception as error:
            print(f'Error en análisis IA: {error}')
            return self.get_default_analysis()
    
    def get_default_analysis(self) -> Dict:
        """Análisis por defecto si falla la IA"""
        return {
            "importancia": "MEDIA",
            "categoria": "TRABAJO",
            "emocion": "NEUTRAL",
            "requiere_accion": False,
            "es_urgente": False,
            "resumen": "Correo pendiente de análisis",
            "acciones_sugeridas": ["Revisar manualmente"],
            "palabras_clave": []
        }
    
    def is_vip_email(self, email: Dict) -> bool:
        """Detecta si es un correo VIP"""
        sender_email = email['sender'].lower()
        
        # Verificar remitentes VIP
        for vip in self.vip_senders:
            if vip.lower() in sender_email:
                return True
        
        # Verificar palabras clave críticas
        text = f"{email['subject']} {email['body']}".lower()
        for keyword in self.critical_keywords:
            if keyword in text:
                return True
        
        return False
    
    def generate_summary_message(self, emails: List[Dict], analyses: List[Dict]) -> str:
        """Genera el mensaje resumen para WhatsApp"""
        
        if not emails:
            return "🌅 *Buenos días!* No tienes correos nuevos importantes hoy."
        
        # Contar por importancia
        alta = sum(1 for a in analyses if a['importancia'] == 'ALTA')
        media = sum(1 for a in analyses if a['importancia'] == 'MEDIA') 
        
        # Mensaje principal
        message = f"🌅 *Buenos días, Capo!*\n"
        message += f"📧 Tienes *{len(emails)}* correos nuevos:\n"
        message += f"🔴 {alta} alta prioridad\n"
        message += f"🟡 {media} prioridad media\n\n"
        
        # Correos importantes
        message += "🚨 *REQUIEREN ATENCIÓN:*\n\n"
        
        urgent_count = 0
        for email, analysis in zip(emails, analyses):
            if analysis['importancia'] == 'ALTA' or analysis['es_urgente']:
                urgent_count += 1
                if urgent_count <= 5:  # Máximo 5 correos urgentes
                    sender_clean = email['sender'].split('<')[0].strip().strip('"')
                    message += f"📌 *{sender_clean}*\n"
                    message += f"   _{analysis['resumen']}_\n"
                    if analysis['requiere_accion']:
                        message += f"   ⚡ Requiere acción\n"
                    message += "\n"
        
        if urgent_count == 0:
            message += "✅ No hay correos urgentes\n\n"
        elif urgent_count > 5:
            message += f"... y {urgent_count - 5} más urgentes\n\n"
        
        # Estadísticas por categoría
        categories = {}
        for analysis in analyses:
            cat = analysis['categoria']
            categories[cat] = categories.get(cat, 0) + 1
        
        if categories:
            message += "📊 *POR CATEGORÍA:*\n"
            for cat, count in categories.items():
                emoji = self.get_category_emoji(cat)
                message += f"{emoji} {cat}: {count}\n"
        
        message += f"\n🕐 Revisión: {datetime.now().strftime('%H:%M')}"
        
        return message
    
    def get_category_emoji(self, category: str) -> str:
        """Devuelve emoji por categoría"""
        emojis = {
            'TRABAJO': '💼',
            'CLIENTE': '👤', 
            'PERSONAL': '🏠',
            'PROVEEDOR': '🏢',
            'MARKETING': '📢',
            'SPAM': '🗑️'
        }
        return emojis.get(category, '📝')
    
    def send_whatsapp_message(self, message: str):
        """Envía mensaje por WhatsApp usando API"""
        
        # Opción 1: WhatsApp Business API (Recomendado para producción)
        if self.whatsapp_token:
            self.send_via_whatsapp_api(message)
        else:
            # Opción 2: PyWhatKit (Para desarrollo/testing)
            self.send_via_pywhatkit(message)
    
    def send_via_whatsapp_api(self, message: str):
        """Envía via WhatsApp Business API"""
        url = "https://graph.facebook.com/v18.0/{your-phone-number-id}/messages"
        
        headers = {
            "Authorization": f"Bearer {self.whatsapp_token}",
            "Content-Type": "application/json"
        }
        
        data = {
            "messaging_product": "whatsapp",
            "to": self.phone_number,
            "type": "text",
            "text": {
                "body": message
            }
        }
        
        try:
            response = requests.post(url, headers=headers, json=data)
            if response.status_code == 200:
                print("✅ Mensaje enviado por WhatsApp")
            else:
                print(f"❌ Error enviando WhatsApp: {response.text}")
        except Exception as error:
            print(f"❌ Error en WhatsApp API: {error}")
    
    def send_via_pywhatkit(self, message: str):
        """Envía via PyWhatKit (alternativa para testing)"""
        try:
            import pywhatkit as pwk
            
            now = datetime.now()
            send_time = now + timedelta(minutes=1)
            
            pwk.sendwhatmsg(
                self.phone_number, 
                message, 
                send_time.hour, 
                send_time.minute,
                wait_time=10,
                tab_close=True
            )
            print("✅ Mensaje programado en WhatsApp")
            
        except Exception as error:
            print(f"❌ Error con PyWhatKit: {error}")
    
    def mark_as_processed(self, email: Dict, analysis: Dict):
        """Marca correo como procesado en la base de datos"""
        conn = sqlite3.connect('email_tracking.db')
        cursor = conn.cursor()
        
        cursor.execute('''
            INSERT OR REPLACE INTO processed_emails 
            (id, processed_date, subject, sender, importance_level, summary)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (
            email['id'],
            datetime.now(),
            email['subject'],
            email['sender'],
            analysis['importancia'],
            analysis['resumen']
        ))
        
        conn.commit()
        conn.close()
    
    def is_already_processed(self, email_id: str) -> bool:
        """Verifica si el correo ya fue procesado"""
        conn = sqlite3.connect('email_tracking.db')
        cursor = conn.cursor()
        
        cursor.execute('SELECT id FROM processed_emails WHERE id = ?', (email_id,))
        result = cursor.fetchone()
        
        conn.close()
        return result is not None
    
    def run_daily_analysis(self):
        """Función principal que se ejecuta diariamente"""
        print(f"🚀 Iniciando análisis matutino - {datetime.now()}")
        
        try:
            # 1. Obtener correos nuevos
            emails = self.get_new_emails()
            print(f"📧 Encontrados {len(emails)} correos nuevos")
            
            if not emails:
                self.send_whatsapp_message("🌅 *Buenos días!* No tienes correos nuevos hoy. ¡Perfecto para enfocarte en tus proyectos! 💪")
                return
            
            # 2. Analizar cada correo con IA
            analyses = []
            for email in emails:
                analysis = self.analyze_email_with_ai(email)
                analyses.append(analysis)
                
                # Marcar como procesado
                self.mark_as_processed(email, analysis)
            
            # 3. Generar y enviar resumen
            summary_message = self.generate_summary_message(emails, analyses)
            self.send_whatsapp_message(summary_message)
            
            print("✅ Análisis completado y mensaje enviado")
            
        except Exception as error:
            print(f"❌ Error en análisis diario: {error}")
            self.send_whatsapp_message(f"🚨 Error en agente de correo: {str(error)}")

# Función para programar la ejecución
def schedule_agent():
    """Programa el agente para ejecutarse diariamente"""
    agent = EmailIntelligenceAgent()
    
    # Programar para las 8:00 AM todos los días
    schedule.every().day.at("08:00").do(agent.run_daily_analysis)
    
    # También puedes programar para días específicos:
    # schedule.every().monday.at("08:00").do(agent.run_daily_analysis)
    # schedule.every().friday.at("17:00").do(agent.run_weekly_summary)
    
    print("📅 Agente programado para las 8:00 AM diarias")
    
    # Ejecutar inmediatamente para probar
    print("🧪 Ejecutando prueba inmediata...")
    agent.run_daily_analysis()
    
    # Mantener el script corriendo
    while True:
        schedule.run_pending()
        time.sleep(60)  # Verificar cada minuto

if __name__ == "__main__":
    schedule_agent()
