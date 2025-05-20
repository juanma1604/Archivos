from flask import Flask, request, send_file, render_template_string, jsonify
import os
import pytesseract
from PIL import Image
import fitz  # PyMuPDF
import docx
import requests
import textwrap
import genanki
import tempfile
import re
from pathlib import Path
import logging
import time
from datetime import datetime

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

app = Flask(__name__)
UPLOAD_FOLDER = 'uploads'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
progress_data = {'current': 0, 'total': 0, 'status': 'idle', 'message': '', 'debug': ''}

# Simplified prompt
PROMPT = """Genera **solo** flashcards tipo Anki a partir del texto que recibirás.  
Usa siempre este formato y estilo:

1. Pregunta: ¿…?  
   Respuesta: <ul><li>…</li><li>…</li></ul>

No agregues nada más (ni títulos, ni explicaciones).  
No omitas ninguna idea. Cada idea completa del texto es una tarjeta.

**Ejemplo de cómo quieres la salida** (a partir de tu texto sobre obesidad):

1. Pregunta: ¿Cómo se clasifica la obesidad?  
   Respuesta:
   <ul>
     <li>Obesidad exógena o nutricional</li>
     <li>Obesidad endógena</li>
   </ul>

2. Pregunta: ¿Qué es obesidad exógena o nutricional?  
   Respuesta:
   <ul>
     <li>La mayoría de las personas obesas son por consumo exógeno y porque gastan pocas calorías.</li>
     <li>Supone el 95% de todos los casos de obesidad infantil.</li>
   </ul>

3. Pregunta: ¿Qué es obesidad endógena?  
   Respuesta:
   <ul>
     <li>Relacionada con otras condiciones que favorecen el acumulo de grasa en el organismo o que interfieren con la talla adecuada.</li>
   </ul>

Ahora, con ese mismo formato, genera las tarjetas para este texto:

"""

# HTML template with debug section
HTML_TEMPLATE = '''
<!DOCTYPE html>
<html lang="es">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>📚 Generador de Flashcards Anki</title>
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.2/css/all.min.css">
    <link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700&display=swap">
    <style>
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body {
            font-family: 'Inter', sans-serif;
            max-width: 1000px;
            margin: 0 auto;
            padding: 20px;
            background: #f4f7fa;
            color: #333;
            transition: all 0.3s ease;
        }
        .dark-mode {
            background: #1e1e1e;
            color: #e0e0e0;
        }
        .container {
            background: white;
            padding: 30px;
            border-radius: 12px;
            box-shadow: 0 4px 20px rgba(0,0,0,0.1);
            margin-bottom: 20px;
        }
        .dark-mode .container {
            background: #2c2c2c;
            box-shadow: 0 4px 20px rgba(0,0,0,0.3);
        }
        h1 {
            font-size: 2rem;
            margin-bottom: 20px;
            display: flex;
            align-items: center;
            gap: 10px;
        }
        .upload-area {
            border: 3px dashed #ccc;
            padding: 30px;
            text-align: center;
            border-radius: 10px;
            cursor: pointer;
            transition: border-color 0.3s, background 0.3s;
            margin-bottom: 20px;
        }
        .upload-area:hover, .upload-area.dragover {
            border-color: #4caf50;
            background: #e8f5e9;
        }
        .dark-mode .upload-area {
            border-color: #555;
        }
        .dark-mode .upload-area:hover, .dark-mode .upload-area.dragover {
            border-color: #4caf50;
            background: #2a3d2a;
        }
        .progress-container {
            width: 100%;
            background: #eee;
            height: 30px;
            border-radius: 15px;
            overflow: hidden;
            margin: 20px 0;
            display: none;
        }
        .dark-mode .progress-container {
            background: #444;
        }
        .progress-bar {
            height: 100%;
            background: linear-gradient(90deg, #4caf50, #81c784);
            width: 0;
            transition: width 0.5s ease;
        }
        .flashcard {
            background: #fff;
            border-radius: 8px;
            padding: 15px;
            margin: 10px 0;
            box-shadow: 0 2px 5px rgba(0,0,0,0.1);
            cursor: pointer;
            transition: transform 0.3s;
        }
        .dark-mode .flashcard {
            background: #3a3a3a;
            box-shadow: 0 2px 5px rgba(0,0,0,0.3);
        }
        .flashcard:hover {
            transform: translateY(-3px);
        }
        .flashcard .answer {
            display: none;
            margin-top: 10px;
        }
        .flashcard.active .answer {
            display: block;
        }
        .button {
            display: inline-block;
            padding: 10px 20px;
            background: #4caf50;
            color: white;
            text-decoration: none;
            border-radius: 5px;
            transition: background 0.3s;
            border: none;
            cursor: pointer;
        }
        .button:hover {
            background: #45a049;
        }
        .error {
            color: #d32f2f;
            background: #ffebee;
            padding: 10px;
            border-radius: 5px;
            margin-bottom: 20px;
        }
        .dark-mode .error {
            background: #5c2a2a;
        }
        .debug {
            background: #e3f2fd;
            padding: 10px;
            border-radius: 5px;
            margin-bottom: 20px;
            font-size: 0.9rem;
            color: #1565c0;
            white-space: pre-wrap;
        }
        .dark-mode .debug {
            background: #1a3c5c;
            color: #90caf9;
        }
        .theme-toggle {
            position: fixed;
            top: 20px;
            right: 20px;
            cursor: pointer;
            font-size: 1.5rem;
        }
    </style>
</head>
<body>
    <i class="fas fa-moon theme-toggle" onclick="toggleTheme()"></i>
    <div class="container">
        <h1><i class="fas fa-book"></i> Generador de Flashcards Anki</h1>
        {% if error %}
        <div class="error">{{ error }}</div>
        {% endif %}
        <form id="upload-form" action="/" method="post" enctype="multipart/form-data">
            <div class="upload-area" id="upload-area">
                <p><i class="fas fa-upload"></i> Arrastra y suelta tu archivo aquí o haz clic para seleccionar</p>
                <input type="file" name="file" id="file-input" accept=".pdf,.docx,.txt,.png,.jpg,.jpeg" required style="display: none;">
            </div>
                {% if uploaded_filename %}
                <p style="margin-top:10px;"><strong>Archivo seleccionado:</strong> {{ uploaded_filename }}</p>
            {% endif %}

            <button type="submit" class="button"><i class="fas fa-cogs"></i> Generar Mazos</button>
        </form>

        <div class="progress-container" id="progress-container">
            <div class="progress-bar" id="progress-bar"></div>
        </div>
        <p id="progress-label"></p>
        <div class="debug" id="debug-label"></div>

        {% if flashcards_by_deck %}
        <h2><i class="fas fa-layer-group"></i> Tarjetas Generadas</h2>
        {% for deck, cards in flashcards_by_deck.items() %}
            <h3>{{ deck }} ({{ cards|length }} tarjetas)</h3>
            <div class="deck">
                {% for q, a in cards %}
                <div class="flashcard" onclick="this.classList.toggle('active')">
                    <strong>{{ q }}</strong>
                    <div class="answer">{{ a|safe }}</div>
                </div>
                {% endfor %}
            </div>
        {% endfor %}
        <a href="{{ download_url }}" class="button"><i class="fas fa-download"></i> Descargar .apkg</a>
        {% endif %}
    </div>

    <script>
        function toggleTheme() {
            document.body.classList.toggle('dark-mode');
            const icon = document.querySelector('.theme-toggle');
            icon.classList.toggle('fa-moon');
            icon.classList.toggle('fa-sun');
        }

        const uploadArea = document.getElementById('upload-area');
        const fileInput = document.getElementById('file-input');
        uploadArea.addEventListener('click', () => fileInput.click());
        uploadArea.addEventListener('dragover', (e) => {
            e.preventDefault();
            uploadArea.classList.add('dragover');
        });
        uploadArea.addEventListener('dragleave', () => {
            uploadArea.classList.remove('dragover');
        });
        uploadArea.addEventListener('drop', (e) => {
            e.preventDefault();
            uploadArea.classList.remove('dragover');
            fileInput.files = e.dataTransfer.files;
            document.getElementById('upload-form').submit();
        });

        function updateProgress() {
            fetch('/progress').then(response => response.json()).then(data => {
                const bar = document.getElementById('progress-bar');
                const label = document.getElementById('progress-label');
                const debugLabel = document.getElementById('debug-label');
                const container = document.getElementById('progress-container');
                if (data.total > 0) {
                    container.style.display = 'block';
                    const percent = Math.floor((data.current / data.total) * 100);
                    bar.style.width = percent + '%';
                    label.innerText = data.status === 'processing' ? `Procesando: ${percent}%` : data.message || '¡Completado!';
                    debugLabel.innerText = data.debug || 'Esperando acción...';
                }
                if (data.status === 'processing') {
                    setTimeout(updateProgress, 1000);
                } else if (data.status === 'error') {
                    label.innerText = data.message;
                    debugLabel.innerText = data.debug;
                    container.style.display = 'none';
                }
            }).catch(err => {
                console.error('Error fetching progress:', err);
                document.getElementById('progress-label').innerText = 'Error al actualizar el progreso';
                document.getElementById('debug-label').innerText = 'Error de conexión con el servidor';
            });
        }

        document.getElementById('upload-form').addEventListener('submit', () => {
            document.getElementById('progress-label').innerText = 'Iniciando procesamiento...';
            document.getElementById('debug-label').innerText = 'Preparando archivo...';
            setTimeout(updateProgress, 500);
        });
    </script>
</body>
</html>
'''

def extract_text(file_path):
    """Extrae texto de diferentes tipos de archivos."""
    logger.info(f"Extrayendo texto de: {file_path}")
    progress_data['debug'] = f"Extrayendo texto del archivo: {os.path.basename(file_path)}"
    try:
        ext = Path(file_path).suffix.lower()
        if ext == '.pdf':
            text = ""
            doc = fitz.open(file_path)
            for page in doc:
                text += page.get_text()
            doc.close()
            logger.info("Texto extraído de PDF")
            return text
        elif ext == '.docx':
            doc = docx.Document(file_path)
            text = "\n".join([para.text for para in doc.paragraphs])
            logger.info("Texto extraído de DOCX")
            return text
        elif ext in ('.png', '.jpg', '.jpeg'):
            text = pytesseract.image_to_string(Image.open(file_path))
            logger.info("Texto extraído de imagen")
            return text
        elif ext == '.txt':
            with open(file_path, 'r', encoding='utf-8') as f:
                text = f.read()
            logger.info("Texto extraído de TXT")
            return text
        logger.warning(f"Formato de archivo no soportado: {ext}")
        return ""
    except Exception as e:
        logger.error(f"Error al extraer texto: {e}")
        progress_data['debug'] = f"Error al extraer texto: {e}"
        raise

def call_phi3(prompt, retries=5, initial_delay=1):
    """Llama a la API de Phi3 con reintentos."""
    logger.info(f"Enviando prompt a la API de Phi3 (longitud: {len(prompt)} caracteres)")
    prompt_summary = prompt[:100] + ("..." if len(prompt) > 100 else "")
    progress_data['debug'] = f"Enviando prompt al modelo Phi3 ({len(prompt)} caracteres)\nResumen: {prompt_summary}"
    
    # Save prompt to prompts_log.txt
    with open('prompts_log.txt', 'a', encoding='utf-8') as f:
        f.write(f"[{datetime.now()}] Prompt enviado ({len(prompt)} caracteres):\n{prompt}\n\n")
    
    for attempt in range(retries):
        try:
            response = requests.post(
                "http://localhost:11434/api/generate",
        json={
          "model": "mixtral:8x22b",    # cambia aquí
          "prompt": prompt,
          "stream": False
        },
                timeout=240
            )
            response.raise_for_status()
            logger.info("Respuesta exitosa de la API de Phi3")
            progress_data['debug'] = "Respuesta recibida del modelo Phi3"
            return response.json()['response']
        except requests.RequestException as e:
            logger.error(f"Intento {attempt + 1}/{retries} fallido: {e}")
            progress_data['debug'] = f"Error en intento {attempt + 1}/{retries}: {e}"
            if attempt < retries - 1:
                delay = initial_delay * (2 ** attempt)
                logger.info(f"Reintentando en {delay} segundos...")
                time.sleep(delay)
            else:
                logger.error(f"Fallo después de {retries} intentos")
                raise Exception(f"Error al conectar con la API de Phi3 después de {retries} intentos: {e}")

def create_anki_apkg(flashcards_by_deck, output_path):
    """Crea un archivo .apkg para Anki."""
    logger.info(f"Creando archivo .apkg en: {output_path}")
    progress_data['debug'] = "Creando archivo Anki (.apkg)"
    try:
        my_package = genanki.Package([])
        for deck_name, cards in flashcards_by_deck.items():
            model = genanki.Model(
                model_id=abs(hash(deck_name)) % (10 ** 10),
                name='FlashcardModel',
                fields=[{'name': 'Question'}, {'name': 'Answer'}],
                templates=[{
                    'name': 'Card 1',
                    'qfmt': '{{Question}}',
                    'afmt': '{{FrontSide}}<hr id="answer">{{Answer}}',
                }],
                css=".card { font-family: arial; font-size: 16px; text-align: left; }"
            )
            deck = genanki.Deck(
                deck_id=abs(hash(deck_name)) % (10 ** 10),
                name=deck_name,
            )
            for question, answer in cards:
                deck.add_note(genanki.Note(model=model, fields=[question, answer]))
            my_package.decks.append(deck)
        my_package.write_to_file(output_path)
        logger.info("Archivo .apkg creado exitosamente")
        progress_data['debug'] = "Archivo .apkg creado"
    except Exception as e:
        logger.error(f"Error al crear .apkg: {e}")
        progress_data['debug'] = f"Error al crear .apkg: {e}"
        raise

def parse_phi3_output(output):
    """Parsea la salida de Phi3 para extraer flashcards."""
    logger.info("Parseando salida de Phi3")
    progress_data['debug'] = "Parseando respuesta del modelo"
    try:
        flashcards = {}
        current_deck = None
        lines = output.strip().split('\n')
        question = ""
        answer = ""
        for line in lines:
            line = line.strip()
            if line.startswith('---'):
                continue
            if not line:
                continue
            if not question and line.startswith('Pregunta:'):
                question = line.replace('Pregunta:', '').strip()
            elif question and line.startswith('Respuesta:'):
                answer = line.replace('Respuesta:', '').strip()
            elif question and answer:
                if current_deck:
                    flashcards.setdefault(current_deck, []).append((question, answer))
                question, answer = "", ""
            elif not question and not answer:
                current_deck = line
        logger.info(f"Flashcards parseadas: {len(flashcards)} mazos")
        progress_data['debug'] = f"Flashcards parseadas: {len(flashcards)} mazos"
        return flashcards
    except Exception as e:
        logger.error(f"Error al parsear salida de Phi3: {e}")
        progress_data['debug'] = f"Error al parsear respuesta: {e}"
        raise

def dividir_texto(texto, max_chars=3000):
    """Divide el texto en fragmentos sin omitir ideas, intentando no romper párrafos ni perder contenido."""
    logger.info(f"Dividiendo texto de {len(texto)} caracteres en fragmentos de máximo {max_chars}")
    progress_data['debug'] = f"Dividiendo texto en fragmentos de máximo {max_chars} caracteres"
    try:
        chunks = []
        current_chunk = ""

        paragraphs = texto.split('\n\n')

        for para in paragraphs:
            para = para.strip()
            if not para:
                continue
            if len(para) > max_chars:
                # Si el párrafo es demasiado largo, lo dividimos por oraciones o saltos de línea
                subparts = textwrap.wrap(para, width=max_chars, break_long_words=False, break_on_hyphens=False)
                for sub in subparts:
                    chunks.append(sub.strip())
            elif len(current_chunk) + len(para) + 2 < max_chars:
                current_chunk += para + "\n\n"
            else:
                chunks.append(current_chunk.strip())
                current_chunk = para + "\n\n"

        if current_chunk.strip():
            chunks.append(current_chunk.strip())

        logger.info(f"Texto dividido en {len(chunks)} fragmentos")
        progress_data['debug'] = f"Texto dividido en {len(chunks)} fragmentos"
        return chunks

    except Exception as e:
        logger.error(f"Error al dividir texto: {e}")
        progress_data['debug'] = f"Error al dividir texto: {e}"
        raise


@app.route("/", methods=["GET", "POST"])
def index():
    """Ruta principal para la interfaz y procesamiento de archivos."""
    flashcards_by_deck = {}
    download_url = None
    error = None

    if request.method == "POST":
        file = request.files.get('file')
        if not file:
            error = "No se seleccionó ningún archivo."
            logger.error(error)
            progress_data['status'] = 'error'
            progress_data['message'] = error
            progress_data['debug'] = error
        else:
            filename = os.path.splitext(file.filename)[0]
            file_path = os.path.join(UPLOAD_FOLDER, file.filename)
            file.save(file_path)
            logger.info(f"Archivo guardado: {file_path}")
            progress_data['debug'] = f"Archivo guardado: {os.path.basename(file_path)}"

            try:
                content = extract_text(file_path)
                if not content.strip():
                    error = "No se pudo extraer texto del archivo."
                    logger.error(error)
                    progress_data['status'] = 'error'
                    progress_data['message'] = error
                    progress_data['debug'] = error
                else:
                    chunks = dividir_texto(content)
                    progress_data['total'] = len(chunks)
                    progress_data['current'] = 0
                    progress_data['status'] = 'processing'
                    progress_data['message'] = 'Procesando archivo...'
                    logger.info(f"Procesando {len(chunks)} fragmentos de texto")

                    for i, chunk in enumerate(chunks):
                        logger.info(f"Enviando fragmento {i+1}/{len(chunks)} a la API")
                        progress_data['debug'] = f"Enviando fragmento {i+1}/{len(chunks)} al modelo"
                        full_prompt = PROMPT + "\n\n" + chunk
                        try:
                            ai_output = call_phi3(full_prompt)
                            partial_cards = parse_phi3_output(ai_output)
                            for deck, cards in partial_cards.items():
                                flashcards_by_deck.setdefault(deck, []).extend(cards)
                            progress_data['current'] = i + 1
                            logger.info(f"Fragmento {i+1} procesado exitosamente")
                        except Exception as e:
                            logger.error(f"Error procesando fragmento {i+1}: {e}")
                            progress_data['debug'] = f"Error procesando fragmento {i+1}: {e}"
                            raise

                    progress_data['status'] = 'completed'
                    progress_data['message'] = '¡Tarjetas generadas!'
                    progress_data['debug'] = 'Generación de tarjetas completada'
                    logger.info(f"Tarjetas generadas: {sum(len(cards) for cards in flashcards_by_deck.values())} en total")

                    out_path = os.path.join(tempfile.gettempdir(), f"{filename}.apkg")
                    create_anki_apkg(flashcards_by_deck, out_path)
                    download_url = f"/download/{os.path.basename(out_path)}"
                    logger.info(f"Archivo .apkg disponible para descargar: {out_path}")
                    progress_data['debug'] = f"Archivo .apkg creado: {os.path.basename(out_path)}"

            except Exception as e:
                error = f"Error al procesar el archivo: {str(e)}"
                progress_data['status'] = 'error'
                progress_data['message'] = error
                progress_data['debug'] = error
                logger.error(error)

            finally:
                if os.path.exists(file_path):
                    os.remove(file_path)
                    logger.info(f"Archivo temporal eliminado: {file_path}")
                    progress_data['debug'] = "Archivo temporal eliminado"

    return render_template_string(
        HTML_TEMPLATE,
        download_url=download_url,
        flashcards_by_deck=flashcards_by_deck,
        error=error,
        uploaded_filename=(file.filename if request.method=="POST" and file else None)
    )

@app.route("/progress")
def progress():
    """Devuelve el estado del progreso."""
    logger.debug(f"Estado del progreso: {progress_data}")
    return jsonify(progress_data)

@app.route("/download/<filename>")
def download_file(filename):
    """Permite descargar el archivo .apkg."""
    path = os.path.join(tempfile.gettempdir(), filename)
    logger.info(f"Descargando archivo: {path}")
    progress_data['debug'] = f"Descargando archivo: {filename}"
    try:
        return send_file(path, as_attachment=True)
    except Exception as e:
        logger.error(f"Error al descargar archivo: {e}")
        progress_data['debug'] = f"Error al descargar: {e}"
        raise

if __name__ == "__main__":
    logger.info("Iniciando la aplicación Flask en http://localhost:5000")
    app.run(debug=True, port=5000)