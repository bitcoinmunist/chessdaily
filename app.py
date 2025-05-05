import os
from flask import Flask, redirect, url_for, session, request, render_template_string, send_from_directory, render_template, jsonify
from authlib.integrations.flask_client import OAuth
from dotenv import load_dotenv
import json
from datetime import datetime, timedelta

load_dotenv()

print('GOOGLE_CLIENT_ID:', os.environ.get('GOOGLE_CLIENT_ID'))
print('GOOGLE_CLIENT_SECRET:', os.environ.get('GOOGLE_CLIENT_SECRET'))
print('FLASK_SECRET_KEY:', os.environ.get('FLASK_SECRET_KEY'))

app = Flask(__name__)
app.secret_key = os.environ.get('FLASK_SECRET_KEY', 'supersecret')

# Configuração do OAuth
oauth = OAuth(app)
google = oauth.register(
    name='google',
    client_id=os.environ['GOOGLE_CLIENT_ID'],
    client_secret=os.environ['GOOGLE_CLIENT_SECRET'],
    server_metadata_url='https://accounts.google.com/.well-known/openid-configuration',
    client_kwargs={
        'scope': 'openid email profile'
    }
)

# Armazenamento em memória
user_scores = {}

# Configuração do arquivo de scores
SCORES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data')
SCORES_FILE = os.path.join(SCORES_DIR, 'user_scores.json')

# Garantir que o diretório existe
os.makedirs(SCORES_DIR, exist_ok=True)

def load_scores():
    global user_scores
    # Primeiro tenta carregar da memória
    if user_scores:
        return user_scores
    
    # Se não estiver na memória, tenta carregar do arquivo
    if os.path.exists(SCORES_FILE):
        try:
            with open(SCORES_FILE, 'r') as f:
                user_scores = json.load(f)
                return user_scores
        except json.JSONDecodeError:
            pass
    
    # Se não conseguir carregar do arquivo, retorna um dicionário vazio
    return {}

def save_scores(scores):
    global user_scores
    user_scores = scores
    try:
        with open(SCORES_FILE, 'w') as f:
            json.dump(scores, f, indent=4)
    except Exception as e:
        print(f"Erro ao salvar scores: {e}")

# Carregar scores ao iniciar o servidor
load_scores()

@app.route('/')
def index():
    return render_template('login.html')

@app.route('/login')
def login():
    return render_template('login.html')

@app.route('/login/google')
def login_google():
    redirect_uri = os.environ.get('GOOGLE_REDIRECT_URI', url_for('authorize', _external=True))
    return google.authorize_redirect(redirect_uri)

@app.route('/authorize')
def authorize():
    token = google.authorize_access_token()
    user_info = token.get('userinfo')
    if not user_info:
        user_info = token
    session['user'] = user_info
    return redirect('/chess')

@app.route('/chess')
def chess():
    user = dict(session).get('user', None)
    if not user:
        return redirect('/')
    return render_template('chess.html')

@app.route('/logout')
def logout():
    session.pop('user', None)
    return redirect('/')

@app.route('/api/user_status')
def user_status():
    user = dict(session).get('user', None)
    if not user:
        return {'error': 'not_logged_in'}, 401
    email = user.get('email')
    scores = load_scores()
    user_data = scores.get(email, {'score': 0, 'last_move': None})
    now = datetime.utcnow()
    last_move = user_data.get('last_move')
    if last_move:
        last_move_dt = datetime.strptime(last_move, '%Y-%m-%dT%H:%M:%S')
        delta = now - last_move_dt
        seconds_left = max(0, 24*3600 - int(delta.total_seconds()))
    else:
        seconds_left = 0
    return {
        'score': user_data.get('score', 0),
        'seconds_left': seconds_left
    }

@app.route('/api/register_move', methods=['POST'])
def register_move():
    user = dict(session).get('user', None)
    if not user:
        return {'error': 'not_logged_in'}, 401
    email = user.get('email')
    scores = load_scores()
    user_data = scores.get(email, {'score': 0, 'last_move': None, 'position': None})
    now = datetime.utcnow()
    last_move = user_data.get('last_move')
    if last_move:
        last_move_dt = datetime.strptime(last_move, '%Y-%m-%dT%H:%M:%S')
        if (now - last_move_dt).total_seconds() < 24*3600:
            return {'error': 'wait'}, 403
    # Permite a jogada
    user_data['score'] = user_data.get('score', 0) + 1
    user_data['last_move'] = now.strftime('%Y-%m-%dT%H:%M:%S')
    scores[email] = user_data
    save_scores(scores)
    return {'ok': True, 'score': user_data['score']}

@app.route('/api/reset_test', methods=['POST'])
def reset_test():
    user = dict(session).get('user', None)
    if not user:
        return jsonify({'error': 'Not logged in'})
    email = user.get('email')
    scores = load_scores()
    user_data = scores.get(email, {'score': 0, 'last_move': None})
    user_data['last_move'] = None  # Reseta o tempo da última jogada
    scores[email] = user_data
    save_scores(scores)
    return jsonify({'ok': True})

@app.route('/api/register_victory', methods=['POST'])
def register_victory():
    user = dict(session).get('user', None)
    if not user:
        return {'error': 'not_logged_in'}, 401
    email = user.get('email')
    scores = load_scores()
    user_data = scores.get(email, {'score': 0, 'last_move': None})
    user_data['score'] = user_data.get('score', 0) + 1000
    scores[email] = user_data
    save_scores(scores)
    return {'ok': True, 'score': user_data['score']}

@app.route('/api/save_position', methods=['POST'])
def save_position():
    user = dict(session).get('user', None)
    if not user:
        return {'error': 'not_logged_in'}, 401
    data = request.get_json()
    position = data.get('position')
    email = user.get('email')
    scores = load_scores()
    user_data = scores.get(email, {'score': 0, 'last_move': None, 'position': None})
    user_data['position'] = position
    scores[email] = user_data
    save_scores(scores)
    return {'ok': True}

@app.route('/api/get_position')
def get_position():
    user = dict(session).get('user', None)
    if not user:
        return {'error': 'not_logged_in'}, 401
    email = user.get('email')
    scores = load_scores()
    user_data = scores.get(email, {'position': None})
    return {'position': user_data.get('position')}

if __name__ == '__main__':
    app.run(debug=True) 