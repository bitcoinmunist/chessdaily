import os
from flask import Flask, redirect, url_for, session, request, render_template_string, send_from_directory, render_template, jsonify
from authlib.integrations.flask_client import OAuth
from dotenv import load_dotenv
import json
from datetime import datetime, timedelta
import sqlite3
from contextlib import closing

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

# Configuração do banco de dados
DATABASE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data')
DATABASE_FILE = os.path.join(DATABASE_DIR, 'chess.db')

# Garantir que o diretório existe
os.makedirs(DATABASE_DIR, exist_ok=True)

def get_db():
    db = sqlite3.connect(DATABASE_FILE)
    db.row_factory = sqlite3.Row
    return db

def init_db():
    with closing(get_db()) as db:
        with app.open_resource('schema.sql', mode='r') as f:
            db.cursor().executescript(f.read())
        db.commit()

def init_app():
    with app.app_context():
        init_db()

# Criar o arquivo schema.sql
schema_sql = """
CREATE TABLE IF NOT EXISTS user_scores (
    email TEXT PRIMARY KEY,
    score INTEGER DEFAULT 0,
    last_move TEXT,
    position TEXT
);
"""

with open('schema.sql', 'w') as f:
    f.write(schema_sql)

# Inicializar o banco de dados
init_app()

def get_user_data(email):
    with closing(get_db()) as db:
        cursor = db.execute('SELECT * FROM user_scores WHERE email = ?', (email,))
        row = cursor.fetchone()
        if row:
            return dict(row)
        return {'email': email, 'score': 0, 'last_move': None, 'position': None}

def save_user_data(email, data):
    with closing(get_db()) as db:
        db.execute('''
            INSERT OR REPLACE INTO user_scores (email, score, last_move, position)
            VALUES (?, ?, ?, ?)
        ''', (email, data.get('score', 0), data.get('last_move'), data.get('position')))
        db.commit()

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
    user_data = get_user_data(email)
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
    user_data = get_user_data(email)
    now = datetime.utcnow()
    last_move = user_data.get('last_move')
    if last_move:
        last_move_dt = datetime.strptime(last_move, '%Y-%m-%dT%H:%M:%S')
        if (now - last_move_dt).total_seconds() < 24*3600:
            return {'error': 'wait'}, 403
    # Permite a jogada
    user_data['score'] = user_data.get('score', 0) + 1
    user_data['last_move'] = now.strftime('%Y-%m-%dT%H:%M:%S')
    save_user_data(email, user_data)
    return {'ok': True, 'score': user_data['score']}

@app.route('/api/reset_test', methods=['POST'])
def reset_test():
    user = dict(session).get('user', None)
    if not user:
        return jsonify({'error': 'Not logged in'})
    email = user.get('email')
    user_data = get_user_data(email)
    user_data['last_move'] = None
    save_user_data(email, user_data)
    return jsonify({'ok': True})

@app.route('/api/register_victory', methods=['POST'])
def register_victory():
    user = dict(session).get('user', None)
    if not user:
        return {'error': 'not_logged_in'}, 401
    email = user.get('email')
    user_data = get_user_data(email)
    user_data['score'] = user_data.get('score', 0) + 1000
    save_user_data(email, user_data)
    return {'ok': True, 'score': user_data['score']}

@app.route('/api/save_position', methods=['POST'])
def save_position():
    user = dict(session).get('user', None)
    if not user:
        return {'error': 'not_logged_in'}, 401
    data = request.get_json()
    position = data.get('position')
    email = user.get('email')
    user_data = get_user_data(email)
    user_data['position'] = position
    save_user_data(email, user_data)
    return {'ok': True}

@app.route('/api/get_position')
def get_position():
    user = dict(session).get('user', None)
    if not user:
        return {'error': 'not_logged_in'}, 401
    email = user.get('email')
    user_data = get_user_data(email)
    return {'position': user_data.get('position')}

if __name__ == '__main__':
    app.run(debug=True) 