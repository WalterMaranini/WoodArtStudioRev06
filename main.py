import os
import requests
from PIL import Image, ExifTags, UnidentifiedImageError
from io import BytesIO
from flask import Flask, render_template, request, jsonify
import threading
import time
from dotenv import load_dotenv
load_dotenv()
import logging
from flask import redirect, url_for
from werkzeug.utils import secure_filename
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
import json



# Configura il logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)

# -----------------------------------------------------
# PARAMETRI DI CONFIGURAZIONE
# -----------------------------------------------------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
template_path = os.path.join(BASE_DIR, 'templates')
base_directory = "static/Immagini"
github_repo_url = "https://api.github.com/repos/waltermaranini/WoodArtStudioImmagini/contents/images/"
GITHUB_TOKEN = os.getenv('GITHUB_TOKEN')
headers = {
    "Authorization": f"token {GITHUB_TOKEN}"
}

# Crea l'app Flask
app = Flask(__name__, template_folder=template_path)

app.secret_key = os.getenv('FLASK_SECRET_KEY', 'secret_key_da_cambiare')
login_manager = LoginManager()
login_manager.login_view = 'login'
login_manager.init_app(app)

# Percorso file utenti
utenti_file = os.path.join(BASE_DIR, 'utenti.json')

# Carica utenti da file
def carica_utenti():
    if os.path.exists(utenti_file):
        with open(utenti_file, 'r') as f:
            return json.load(f)
    else:
        return {}

# Salva utenti su file
def salva_utenti(utenti):
    with open(utenti_file, 'w') as f:
        json.dump(utenti, f)

# Inizializza
utenti = carica_utenti()

class User(UserMixin):
    def __init__(self, id_, username, password_hash):
        self.id = id_
        self.username = username
        self.password_hash = password_hash

    def get_id(self):
        return str(self.id)

@login_manager.user_loader
def load_user(user_id):
    user = utenti.get(user_id)
    if user:
        return User(user_id, user['username'], user['password_hash'])
    return None
@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        if any(u['username'] == username for u in utenti.values()):
            return "Username già esistente."
        user_id = str(len(utenti) + 1)
        password_hash = generate_password_hash(password)
        utenti[user_id] = {'username': username, 'password_hash': password_hash}
        salva_utenti(utenti)
        return redirect(url_for('login'))
    return render_template('register.html')
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        for id_, user in utenti.items():
            if user['username'] == username and check_password_hash(user['password_hash'], password):
                user_obj = User(id_, username, user['password_hash'])
                login_user(user_obj)
                return redirect(url_for('HomePage'))
        return "Login fallito. Username o password errati."
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('HomePage'))


# Crea la cartella base se non esiste
if not os.path.exists(base_directory):
    os.makedirs(base_directory)




def create_category_directories(category_name):
    category_path = os.path.join(base_directory, category_name)
    if not os.path.exists(category_path):
        os.makedirs(category_path)
        os.makedirs(os.path.join(category_path, "Ridotte"))
        os.makedirs(os.path.join(category_path, "Originali"))

def download_and_resize_image_from_bytes(content, save_path, scale=0.3):
    try:
        image = Image.open(BytesIO(content))

        # Prova a ottenere i metadati EXIF in formato bytes
        exif_bytes = image.info.get('exif', None)

        # Rotazione in base all'orientamento EXIF
        try:
            exif = image._getexif()
        except AttributeError:
            exif = None
        if exif is not None:
            orientation = exif.get(274)
            if orientation == 3:
                image = image.rotate(180, expand=True)
            elif orientation == 6:
                image = image.rotate(270, expand=True)
            elif orientation == 8:
                image = image.rotate(90, expand=True)

        # Ridimensionamento
        new_size = (int(image.width * scale), int(image.height * scale))
        resized_image = image.resize(new_size, Image.LANCZOS)

        # Salva immagine con metadati EXIF se presenti
        if exif_bytes:
            resized_image.save(save_path, exif=exif_bytes)
        else:
            resized_image.save(save_path)

    except UnidentifiedImageError:
        pass


def sync_with_github():
    while True:
        logging.info("Avvio sincronizzazione con GitHub...")
        response = requests.get(github_repo_url, headers=headers)
        if response.status_code == 200:
            contents = response.json()
            for item in contents:
                if item['type'] == 'dir':
                    category_name = item['name']
                    create_category_directories(category_name)
                    logging.info(f"Controllo categoria: {category_name}")
                    category_url = f"{github_repo_url}{category_name}"
                    category_response = requests.get(category_url, headers=headers)
                    if category_response.status_code == 200:
                        category_contents = category_response.json()
                        github_files = {
                            file_item['name']
                            for file_item in category_contents
                            if file_item['type'] == 'file'
                        }
                        local_original_path = os.path.join(base_directory, category_name, "Originali")
                        local_reduced_path = os.path.join(base_directory, category_name, "Ridotte")
                        local_files = set(os.listdir(local_original_path)) if os.path.exists(
                            local_original_path) else set()

                        # Elimina file locali non più presenti su GitHub
                        files_to_delete = local_files - github_files
                        for file_to_delete in files_to_delete:
                            logging.info(f"Elimino file obsoleto: {file_to_delete}")
                            original_file_path = os.path.join(local_original_path, file_to_delete)
                            reduced_file_path = os.path.join(local_reduced_path, file_to_delete)
                            if os.path.exists(original_file_path):
                                os.remove(original_file_path)
                            if os.path.exists(reduced_file_path):
                                os.remove(reduced_file_path)

                        # Scarica file mancanti
                        missing_files = github_files - local_files
                        for file_item in category_contents:
                            if file_item['type'] == 'file':
                                file_name = file_item['name']
                                file_url = file_item.get('download_url')
                                if not file_url:
                                    continue
                                local_original_file_path = os.path.join(local_original_path, file_name)
                                local_reduced_file_path = os.path.join(local_reduced_path, file_name)
                                if not os.path.exists(local_original_file_path):
                                    response = requests.get(file_url, headers=headers)
                                    if response.status_code == 200:
                                        content = response.content
                                        with open(local_original_file_path, 'wb') as f:
                                            f.write(content)
                                        logging.info(f"Scaricato file originale: {file_name}")
                                        download_and_resize_image_from_bytes(content, local_reduced_file_path)
                                        logging.info(f"Creata immagine ridotta: {file_name}")
                                    else:
                                        logging.error(f"Errore download {file_name}: {response.status_code}")
        else:
            logging.error(f"Errore accesso GitHub: {response.status_code}")

        logging.info("Fine sincronizzazione. Pausa di 60 secondi.\n")
        time.sleep(60)

@app.route('/')
def HomePage():
    return render_template('HomePage.html')

@app.route('/Galleria')
def galleria_immagini():
    categories = {}
    for category_name in sorted(os.listdir(base_directory)):
        category_path = os.path.join(base_directory, category_name, "Ridotte")
        if os.path.isdir(category_path):
            try:
                immagini_ridotte = sorted(os.listdir(category_path))
            except FileNotFoundError:
                immagini_ridotte = []
            images = [
                {
                    "ridotta": f"/{category_path}/{img}",
                    "originale": f"/{base_directory}/{category_name}/Originali/{img}"
                }
                for img in immagini_ridotte
                if os.path.isfile(os.path.join(category_path, img))
            ]
            categories[category_name] = images
    return render_template('Gallery.html', categories=categories)

@app.route('/Ricerca')
def pagina_ricerca():
    return render_template('Ricerca.html')

@app.route('/api/ricerca_immagini')
def ricerca():
    colore_query = request.args.get('colore', '').lower()
    dimensione_query = request.args.get('dimensione', '').lower()

    risultati = []

    for category_name in os.listdir(base_directory):
        reduced_path = os.path.join(base_directory, category_name, "Ridotte")
        if os.path.isdir(reduced_path):
            for nome_file in os.listdir(reduced_path):
                percorso_file = os.path.join(reduced_path, nome_file)
                if not os.path.isfile(percorso_file):
                    continue
                dati = estrai_attributi_immagine(percorso_file)
                if dati:
                    if (not colore_query or colore_query in dati['colore']) and \
                            (not dimensione_query or dimensione_query in dati['dimensione']):
                        dati["ridotta"] = f"/static/Immagini/{category_name}/Ridotte/{dati['filename']}"
                        risultati.append(dati)

    return jsonify(risultati)

@app.route('/Configurazione')
@login_required
def pagina_configurazione():
    immagini = []
    for category_name in sorted(os.listdir(base_directory)):
        originali_path = os.path.join(base_directory, category_name, "Originali")
        if os.path.isdir(originali_path):
            for nome_file in os.listdir(originali_path):
                immagini.append({
                    "categoria": category_name,
                    "filename": nome_file,
                    "path": f"/static/Immagini/{category_name}/Originali/{nome_file}"
                })
    return render_template('Configurazione.html', immagini=immagini)
def estrai_attributi_immagine(percorso_file):
    try:
        image = Image.open(percorso_file)
        exif_data = image.getexif()
        colore = exif_data.get(270, '').strip().lower()
        dimensione = exif_data.get(40092, '').strip().lower()
        return {
            "filename": os.path.basename(percorso_file),
            "colore": colore,
            "dimensione": dimensione
        }
    except Exception as e:
        return None


@app.route('/upload_immagine', methods=['POST'])
def upload_immagine():
    categoria = request.form['categoria']
    immagine = request.files['immagine']

    if immagine and categoria:
        category_path = os.path.join(base_directory, categoria, "Originali")
        if not os.path.exists(category_path):
            create_category_directories(categoria)

        filename = secure_filename(immagine.filename)
        save_path = os.path.join(category_path, filename)
        immagine.save(save_path)
        logging.info(f"Immagine caricata: {filename} nella categoria {categoria}")

    return redirect(url_for('pagina_configurazione'))


@app.route('/elimina_immagine', methods=['POST'])
def elimina_immagine():
    categoria = request.form['categoria']
    filename = request.form['filename']
    original_path = os.path.join(base_directory, categoria, "Originali", filename)
    reduced_path = os.path.join(base_directory, categoria, "Ridotte", filename)

    if os.path.exists(original_path):
        os.remove(original_path)
        logging.info(f"Immagine originale eliminata: {filename}")
    if os.path.exists(reduced_path):
        os.remove(reduced_path)
        logging.info(f"Immagine ridotta eliminata: {filename}")

    return redirect(url_for('pagina_configurazione'))


if __name__ == '__main__':
    print(os.path.exists("templates/HomePage.html"))
    print("Cartella corrente:", os.getcwd())
    print("Template esiste?", os.path.exists("templates/HomePage.html"))
    print("Current working directory:", os.getcwd())
    print("Cartella template usata da Flask:", app.template_folder)
    sync_thread = threading.Thread(target=sync_with_github, daemon=True)
    sync_thread.start()
    #app.run(debug=True) # Questo richiamo va omesso per essere eseguito su PythonAnyWhere
