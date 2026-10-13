from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
import requests
import sqlite3
import re
import json
import os
from datetime import datetime, date

# --- GARANTIA DE CAMINHO ABSOLUTO PARA O BANCO DE DADOS ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_NAME = os.path.join(BASE_DIR, "database.db")

app = Flask(__name__, static_folder='.', static_url_path='')
CORS(app)

TIMEOUT = 30

def get_db_connection():
    """Retorna uma conexão isolada e segura para o SQLite."""
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    """Inicializa as tabelas no banco SQLite local se não existirem."""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Tabela de licenças ativas por MAC
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS licenses (
            mac TEXT PRIMARY KEY,
            name TEXT,
            expiry_date TEXT,
            status TEXT
        )
    ''')
    
    # Tabela de cache da lista IPTV
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS playlist_cache (
            username TEXT PRIMARY KEY,
            dns TEXT,
            updated_at TEXT,
            data TEXT
        )
    ''')
    conn.commit()
    conn.close()

# Garante a criação do banco de dados na inicialização
init_db()

def check_mac_license(mac):
    """Valida o MAC Address no banco de dados SQLite."""
    if not mac:
        return False, "ID do dispositivo não fornecido."
    
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT expiry_date, status FROM licenses WHERE mac = ?", (mac,))
    row = cursor.fetchone()
    conn.close()

    if not row:
        return False, f"Dispositivo não licenciado. MAC: {mac}."
    
    expiry_str, status = row['expiry_date'], row['status']
    if status != 'active':
        return False, "Licença bloqueada ou inativa."
    
    try:
        expiry_date = datetime.strptime(expiry_str, "%Y-%m-%d")
        if datetime.now() > expiry_date:
            return False, "Sua licença expirou."
    except Exception:
        pass

    return True, "Licença Válida"

def parse_m3u_fast(m3u_text):
    """Processa o arquivo M3U de forma ultra-rápida."""
    channels = []
    current_name = "Sem Nome"
    current_logo = ""
    current_group = "Geral"
    current_type = "live"
    item_id = 1

    for line in m3u_text.splitlines():
        line = line.strip()
        if not line:
            continue
            
        if line.startswith('#EXTINF:'):
            nm = line.split(',')
            current_name = nm[-1].strip() if len(nm) > 1 else "Sem Nome"
            
            logo_m = re.search(r'tvg-logo="([^"]*)"', line, re.IGNORECASE)
            current_logo = logo_m.group(1) if logo_m else ""
            
            group_m = re.search(r'group-title="([^"]*)"', line, re.IGNORECASE)
            if group_m:
                current_group = group_m.group(1).strip() or 'Geral'
                g_lower = current_group.lower()
                if any(k in g_lower for k in ['filme', 'movie', 'vod']):
                    current_type = 'movie'
                elif any(k in g_lower for k in ['serie', 'série']):
                    current_type = 'series'
                else:
                    current_type = 'live'
            else:
                current_group = 'Geral'
                current_type = 'live'
                
        elif not line.startswith('#'):
            channels.append({
                'id': item_id,
                'name': current_name,
                'logo': current_logo,
                'group': current_group,
                'type': current_type,
                'url': line
            })
            item_id += 1
            
    return channels

# --- ROTAS DA APLICAÇÃO ---
app = Flask(__name__, static_folder='.', static_url_path='')
@app.route('/')
def index():
    """Entrega a interface principal (index.html)."""
    return send_from_directory('.', 'index.html')

@app.route('/api/login', methods=['GET'])
def api_login():
    """Autentica o dispositivo e serve a playlist (via Cache ou Download)."""
    mac = request.args.get('mac')
    dns = request.args.get('dns')
    user = request.args.get('username')
    password = request.args.get('password')

    # Validação de Licença
    is_valid, msg = check_mac_license(mac)
    if not is_valid:
        return jsonify({'status': 'error', 'message': msg}), 403

    if not dns or not user or not password:
        return jsonify({'status': 'error', 'message': 'Preencha todos os campos.'}), 400

    dns = dns.rstrip('/')
    if not (dns.startswith('http://') or dns.startswith('https://')):
        dns = f'http://{dns}'

    today_str = date.today().isoformat()
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # 1. Tenta carregar do Cache Local (Leitura Instantânea)
    cursor.execute("SELECT updated_at, data FROM playlist_cache WHERE username = ? AND dns = ?", (user, dns))
    row = cursor.fetchone()

    if row and row['updated_at'] == today_str:
        conn.close()
        try:
            data = json.loads(row['data'])
            stats = {
                'total': len(data),
                'live': sum(1 for i in data if i['type'] == 'live'),
                'movies': sum(1 for i in data if i['type'] == 'movie'),
                'series': sum(1 for i in data if i['type'] == 'series')
            }
            return jsonify({'status': 'success', 'stats': stats, 'items': data, 'cached': True})
        except Exception:
            pass # Se houver falha na leitura do JSON do cache, força novo download abaixo

    # 2. Se não houver cache para hoje, faz download do Provedor IPTV
    target_url = f"{dns}/get.php?username={user}&password={password}&type=m3u_plus"

    try:
        response = requests.get(target_url, timeout=TIMEOUT, stream=True)
        if response.status_code != 200:
            conn.close()
            return jsonify({'status': 'error', 'message': 'Credenciais incorretas ou servidor IPTV indisponível.'}), 401

        content = response.content.decode('utf-8', errors='ignore')
        data = parse_m3u_fast(content)
        data_json = json.dumps(data)

        # Atualiza o cache no banco SQLite
        cursor.execute('''
            INSERT OR REPLACE INTO playlist_cache (username, dns, updated_at, data)
            VALUES (?, ?, ?, ?)
        ''', (user, dns, today_str, data_json))
        conn.commit()
        conn.close()

        stats = {
            'total': len(data),
            'live': sum(1 for i in data if i['type'] == 'live'),
            'movies': sum(1 for i in data if i['type'] == 'movie'),
            'series': sum(1 for i in data if i['type'] == 'series')
        }

        return jsonify({'status': 'success', 'stats': stats, 'items': data, 'cached': False})

    except requests.exceptions.Timeout:
        conn.close()
        return jsonify({'status': 'error', 'message': 'O servidor IPTV demorou muito para responder (Timeout).'}), 504
    except Exception as e:
        conn.close()
        return jsonify({'status': 'error', 'message': f'Erro ao conectar: {str(e)}'}), 500

@app.route('/api/refresh_cache', methods=['GET'])
def refresh_cache():
    """Limpa o cache do usuário no banco SQLite para forçar atualização."""
    user = request.args.get('username')
    dns = request.args.get('dns')

    if not user or not dns:
        return jsonify({'status': 'error', 'message': 'Usuário e DNS são obrigatórios.'}), 400

    dns = dns.rstrip('/')
    if not (dns.startswith('http://') or dns.startswith('https://')):
        dns = f'http://{dns}'

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM playlist_cache WHERE username = ? AND dns = ?", (user, dns))
    conn.commit()
    conn.close()

    return jsonify({'status': 'success', 'message': 'Cache limpo com sucesso.'})

@app.route('/api/admin/add_license', methods=['POST'])
def add_license():
    """Endpoint de administração para cadastrar/renovar licenças MAC."""
    data = request.json or {}
    mac = data.get('mac')
    name = data.get('name', 'Cliente')
    expiry_date = data.get('expiry_date')

    if not mac or not expiry_date:
        return jsonify({'error': 'MAC e data de expiração (YYYY-MM-DD) são obrigatórios'}), 400

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        INSERT OR REPLACE INTO licenses (mac, name, expiry_date, status)
        VALUES (?, ?, ?, 'active')
    ''', (mac, name, expiry_date))
    conn.commit()
    conn.close()

    return jsonify({'status': 'success', 'message': f'Licença para o MAC {mac} ativada com sucesso.'})

# --- PONTO DE ENTRADA DO SERVIDOR ---
if __name__ == '__main__':
    # Captura a porta da variável de ambiente (Render/VPS) ou usa a 5000 por padrão
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)