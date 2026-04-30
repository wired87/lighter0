import json
import sys
import uuid
from google import genai
import dotenv
from google.genai import types
import argparse

import requests
from io import BytesIO
from PIL import Image

import os
import vtracer
from svglib.svglib import svg2rlg
from reportlab.graphics import renderPS

dotenv.load_dotenv()



# ---------- 1. QUERY TRANSFORMATION ----------
def transform_query(full_prompt: str, gem_api_key) -> str:
    """
    Nimmt eine statische Instruktion und einen Basis-Text (Preprint),
    um über das Textmodell einen perfekten Bild-Prompt zu generieren.
    """
    print("[TRANSFORM] Optimiere den Prompt via Gemini...")
    try:
        client = genai.Client(api_key=gem_api_key or os.getenv("GEM_API_KEY"))
        response = client.models.generate_content(
            model='gemini-2.5-pro',
            contents=full_prompt,
            config=types.GenerateContentConfig(
                temperature=0.1
            )
        )

        optimized_prompt = response.text.strip()
        print(f"[TRANSFORM] ✅ Prompt erfolgreich erstellt:\n{optimized_prompt}\n")
        return f"{optimized_prompt}"

    except Exception as e:
        print(f"[ERR] Fehler bei der Textgenerierung: {e}")
        return ""



def list_available_models(gem_api_key):
    print("🔍 Frage verfügbare Modelle ab...\n")
    client = genai.Client(api_key=gem_api_key or os.getenv("GEM_API_KEY"))
    try:
        # client.models.list() gibt einen Iterator aller verfügbaren Modelle zurück
        models = client.models.list()

        print("--- ALLE VERFÜGBAREN MODELLE ---")
        for m in models:
            # Zeigt den Namen des Modells an (z.B. 'models/gemini-2.5-pro')
            print(f"Name: {m.name}")

            # Zeigt an, was das Modell kann (z.B. 'generateContent', 'generateImages')
            if m.supported_actions:
                print(f"  -> Aktionen: {', '.join(m.supported_actions)}")
            print("-" * 30)

    except Exception as e:
        print(f"[ERR] Fehler beim Abrufen der Modelle: {e}")

def get_prompt(images, theme, bg_texture, math_rule, product_name, typo_style, color_palette, tags):
    # --- Modular Variables ---
    """THEME_DESCRIPTION = "Mathematical and physical futuristic"
    BACKGROUND_TEXTURE = "sharp"
    GEOMETRIC_MATHEMATICAL_RULE = "golden ratio proportions"
    PRODUCT_NAME = ""
    TYPOGRAPHY_STYLE = "futuristic"
    COLOR_PALETTE = "black and white"
    TAGS = "A dark luxury cyberpunk lighter-cover with glowing orange neon elements and elegant typography."
    INPUT_DIR = "input"
    IMAGES = [
        Image.open(os.path.join(INPUT_DIR, file))
        for file in os.listdir(INPUT_DIR)
        if file.lower().endswith(('.jpg', '.jpeg', '.png'))
    ]"""

    def include_text():
        if len(product_name) > 0:
            return f"""
            The product name '{product_name}' is integrated into the layout using {typo_style}.
            """
        else:
            return "Do not include any title or text on the image!!!"

    static_prompt = f"""
    Generate a premium, flat graphic design for a square adhesive wrap (1:1 aspect ratio) based on the following strict parameters:

    * **Core Medium:** A flat, strictly 2D graphic design file. It is a full-bleed, edge-to-edge layout, strictly restricted to pure artwork.
    * **CRITICAL INSTRUCTION:** Do NOT draw any physical objects, hardware, or mockups. Draw ONLY the pure 2D print pattern itself.
    * **Perspective:** Orthographic, top-down view with absolutely no 3D perspective, no shadows, and no curved surfaces.
    * **Layout Exclusions:** No external text measurements, no dimension lines, no white borders, and no realistic product mockup backgrounds.
    * **Theme & Geometry:** The design theme features '{theme}' on a background texture of '{bg_texture}'. 
    Patterns and geometric structures are strictly derived from precise mathematical algorithms and physical forms, 
    specifically {math_rule}.
    * **Aesthetics:** High contrast lighting optimized for flat graphic print, with vector-style crispness.
    * **Colors:** The color palette is strictly: {color_palette}.
    * **Banned Effects:** No atmospheric smoke, bokeh, reflections, or out-of-focus areas.
    * **Typography:** {include_text()}
    * **Output Quality:** The final image is 8k resolution, perfectly square composition, suitable for immediate printing.
    * **Seamless Pattern, Tileable Texture
    * **Suited for digital print
    * **flat artwork cover designed for a size of 68x67mm (ensure the prompt implies a near-square 1:1 aspect ratio layout without drawing literal dimension lines)
    """

    full_prompt = f"""
    {static_prompt.strip()}

    --- PREPRINT TEXT ---
    {math_rule}

    --- PREPRINT IMAGES ---
    {images}
    """

    return full_prompt

def generate_cover_image(image_prompt: str, gem_api_key=None):
    """
    Nimmt den transformierten Prompt und generiert ein Bild über die API.
    """
    print("[GENERATE] Generiere Bild via API...")

    try:
        client = genai.Client(api_key=gem_api_key or os.getenv("GEM_API_KEY"))
        # Wir rufen das Bildmodell auf (Googles Imagen-3 ist das Standardmodell hierfür)
        result = client.models.generate_images(
            model='imagen-4.0-ultra-generate-001',
            prompt=image_prompt,
            config=types.GenerateImagesConfig(
                number_of_images=1,
                output_mime_type="image/jpeg",
                aspect_ratio="1:1"  # 1:1 ist fast genau dein gewünschtes Format von 68x69mm
            )
        )
        return result
    except Exception as e:
        print(f"[ERR] Fehler bei der Bildgenerierung: {e}")




# ---------- 1. DIE NÄCHSTE FUNKTION (Pipeline) ----------
def run_generation_pipeline(
        images,
        theme,
        bg_texture,
        math_rule,
        product_name,
        typo_style,
        color_palette,
        tags,
        output_dir,
        args,
        gem_api_key,
        height=600,
        width=600,
):
    """
    Diese Funktion nimmt alle geöffneten Bilder und Argumente entgegen und
    könnte nun deinen Prompt bauen und an die Google GenAI API schicken.
    """
    print("\n🚀 --- PIPELINE GESTARTET ---")
    print(f"📦 Geladene Bilder:   {len(images)}")
    print(f"🎨 Theme:             {theme}")
    print(f"🖼️ Background:        {bg_texture}")
    print(f"📐 Math Rule:         {math_rule}")
    print(f"🏷️ Product Name:      '{product_name}'")
    print(f"🔤 Typography:        {typo_style}")
    print(f"🎨 Colors:            {color_palette}")
    print(f"🔖 Tags:              {tags}")
    print("----------------------------\n")


    ### VALIDATE
    if os.getenv("SHOW_AVAILABLE_MODELS", None) is not None:
        list_available_models()

    if output_dir is None:
        base_dir = os.path.dirname(os.path.abspath(__file__))

        # 2. Hängt "output" an (macht automatisch \ unter Windows und / unter Linux)
        output_dir = os.path.join(base_dir, "output")
        print("no output dir given -> fall back on defualt", output_dir)
    ###

    prompt = get_prompt(images, theme, bg_texture, math_rule, product_name, typo_style, color_palette, tags)
    # GENERATE
    gen_id = uuid.uuid4()

    # 1. Erstelle den spezifischen Unterordner für DIESEN Durchlauf
    run_dir = os.path.join(output_dir, str(gen_id))
    os.makedirs(run_dir, exist_ok=True)

    # 2. Definiere die finalen Speicherpfade
    image_save_path = os.path.join(run_dir, "img.jpg")
    json_save_path = os.path.join(run_dir, "args.json")
    vec_save_path = os.path.join(run_dir, "vec.eps")

    # 3. Bild generieren
    result = generate_cover_image(prompt, gem_api_key)

    # --- SAVE IMAGE ---
    for generated_image in result.generated_images:
        image_bytes = generated_image.image.image_bytes
        image = Image.open(BytesIO(image_bytes))
        img = img.resize((height or 600, width or 600))  # z.B. 68mm * 69mm bei 10px/mm

        image.save(image_save_path)
        print(f"[GENERATE] ✅ Bild erfolgreich gespeichert unter: {image_save_path}")

    try:
        args_dict = vars(args)

        # Speichere das Dictionary als schön formatierte JSON-Datei
        with open(json_save_path, "w", encoding="utf-8") as f:
            json.dump(args_dict, f, indent=4, ensure_ascii=False)

        # save vector image
        convert_to_vector_eps(
            input_path=image_save_path,
            output_eps_path=vec_save_path,
        )

        print(f"[SAVE] ✅ Setup-Parameter gespeichert unter: {json_save_path}")
    except Exception as e:
        print(f"[ERR] ❌ Konnte JSON nicht speichern: {e}")


# ---------- 2. BILDER LADEN (Web, Datei, Ordner) ----------
def load_image_source(source_path: str):
    """
    Erkennt automatisch, ob der Pfad eine URL, ein lokaler Ordner oder eine Datei ist,
    öffnet die Bilder und gibt eine Liste von PIL-Image-Objekten zurück.
    """
    loaded_images = []

    # Fall A: Es ist eine Web-URL
    if source_path.startswith("http://") or source_path.startswith("https://"):
        print(f"[LOAD] Lade Bild aus dem Web: {source_path}")
        try:
            response = requests.get(source_path)
            response.raise_for_status()  # Wirft Fehler bei 404 etc.
            img = Image.open(BytesIO(response.content))
            loaded_images.append(img)
        except Exception as e:
            print(f"[ERR] Fehler beim Web-Download: {e}")

    # Fall B: Es ist ein lokaler Ordner
    elif os.path.isdir(source_path):
        print(f"[LOAD] Lade Bilder aus Ordner: {source_path}")
        for file in os.listdir(source_path):
            path = os.path.join(source_path, file)
            # Nur echte Dateien öffnen, die Endungen von Bildern haben
            if os.path.isfile(path) and file.lower().endswith(('.png', '.jpg', '.jpeg', '.webp')):
                try:
                    loaded_images.append(Image.open(path))
                except Exception as e:
                    print(f"[ERR] Fehler bei {file}: {e}")

    # Fall C: Es ist eine einzelne lokale Datei
    elif os.path.isfile(source_path):
        print(f"[LOAD] Lade lokale Datei: {source_path}")
        try:
            loaded_images.append(Image.open(source_path))
        except Exception as e:
            print(f"[ERR] Fehler bei lokaler Datei: {e}")

    else:
        print(f"[WARN] Input '{source_path}' nicht gefunden. Gehe ohne Bilder weiter.")


    return loaded_images

def print_welcome_screen():
    # ANSI Farb-Codes für das Terminal
    CYAN = '\033[96m'
    MAGENTA = '\033[95m'
    YELLOW = '\033[93m'
    RESET = '\033[0m'
    BOLD = '\033[1m'

    # ASCII Art Generator (Schriftart: "Slant")
    logo = f"""
{CYAN}   _____                 __               {MAGENTA}  ___         __ 
{CYAN}  / ___/___  ____ _____/ /__  ___________{MAGENTA} /   |  _____/ /_
{CYAN}  \__ \/ _ \/ __ `/ __  / _ \/ ___/ ___/{MAGENTA} / /| | / ___/ __/
{YELLOW} ___/ /  __/ /_/ / /_/ /  __(__  |__  ) {YELLOW}/ ___ |/ /  / /_  
{YELLOW}/____/\___/\__,_/\__,_/\___/____/____/ {YELLOW}/_/  |_/_/   \__/  
{RESET}
    """
    print(logo)
    print(f"{BOLD} Seamless Cover-Art Generator CLI v1.0{RESET}")
    print(f" Powered by AI | {MAGENTA}Ready to create...{RESET}")
    print("-" * 55 + "\n")


# Wichtig: Dieser Import muss oben im Skript stehen
from prompt_toolkit import prompt


def ask_user(frage: str, default_wert: str) -> str:
    print(f"❓ {frage}")

    # Wandle None in einen leeren String um, damit es keine TypeErrors gibt
    safe_default = "" if default_wert is None else str(default_wert)

    try:
        response = prompt("   > ", default=safe_default).strip()

    except Exception as e:
        #print(f"Cant open prompt toolkit. Falling back to default input... (Err, {e})")
        try:
            response = input(f"   [Default: {safe_default}]: ").strip()
            if not response:
                response = safe_default
        except Exception as e_fallback:
            print(f"   [!] Eingabe nicht möglich ({e_fallback}). Nutze Standardwert.", safe_default)
            response = safe_default

    if response == "exit":
        main()
    else:
        return response



def convert_to_vector_eps(
        input_path: str,
        output_eps_path: str,
):
    """
    1. Vektorisiert ein JPG/PNG zu echten Pfaden.
    2. Konvertiert die Pfade in ein druckfertiges, professionelles .eps Format.
    """
    if not os.path.exists(input_path):
        print(f"❌ Fehler: '{input_path}' nicht gefunden.")
        return

    temp_svg_path = "temp_vector.svg"

    try:
        print(f"⏳ Schritt 1: Analysiere Bild und berechne Vektoren...")
        vtracer.convert_image_to_svg_py(
            input_path,
            temp_svg_path,
            colormode='color',
            hierarchical='stacked',
            mode='spline',
            filter_speckle=4,
            color_precision=6
        )

        print(f"⏳ Schritt 2: Konvertiere Vektoren in professionelles EPS-Format...")
        # Lade das SVG ein
        drawing = svg2rlg(temp_svg_path)

        # Schreibe es als echte EPS-Datei auf die Festplatte
        renderPS.drawToFile(drawing, output_eps_path)

        print(f"✅ FERTIG! Echte Vektor-Datei erstellt: {output_eps_path}")

    except Exception as e:
        print(f"❌ Fehler bei der Konvertierung: {e}")

    finally:
        # Räume die temporäre SVG-Datei auf, damit alles sauber bleibt
        if os.path.exists(temp_svg_path):
            os.remove(temp_svg_path)


# ---------- 3. CLI SETUP ----------
def main():
    # PRINT WELCOME
    print_welcome_screen()
    print("[SYSTEM] Initialisiere Pipeline...")

    # ArgumentParser generiert automatisch das -h / --help Menü
    parser = argparse.ArgumentParser(
        description="Generiere Seamless Cover-Artworks aus Bildern und Text-Parametern.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter  # Zeigt die Defaults im Help-Text an
    )

    # Input Path (Kann URL, Ordner oder Datei sein)
    parser.add_argument("-i", "--input", default="input",
                        help="Pfad zum lokalen Ordner, zur Datei oder eine direkte Web-Bild-URL (z.B. https://example.com/img.jpg)")

    # Design Parameter
    parser.add_argument("--theme", default="Mathematical and physical futuristic",
                        help="Das Design-Thema (z.B. 'Cyberpunk neon city')")
    parser.add_argument("--bg_texture", default="sharp",
                        help="Hintergrundtextur (z.B. 'matte dark metal')")
    parser.add_argument("--math", default="golden ratio proportions",
                        help="Mathematische Geometrie-Regel (z.B. 'Fibonacci spirals')")
    parser.add_argument("--name", default="",
                        help="Der Produktname (Leer lassen für kein Text)")
    parser.add_argument("--typo", default="futuristic",
                        help="Der Typografie-Stil (z.B. 'bold angular modern')")
    parser.add_argument("--colors", default="black and white",
                        help="Farbpalette (z.B. 'neon orange and deep black')")
    parser.add_argument("--tags",
                        default="A colorful luxury cyberpunk lighter-cover with glowing orange neon elements and elegant typography.",
                        help="Zusätzliche Tags als Basis für das Design")
    parser.add_argument("--output_dir",
                        default="output",
                        help="Folder/Dir to save the genrated content to")

    # Liest die Argumente aus der Kommandozeile
    args = parser.parse_args()

    # len(sys.argv) == 1 bedeutet: Der User hat "python main.py" ohne --parameter getippt
    if len(sys.argv) == 1:
        gem_api_key = input("❓ GE  MINI_API_KEY (required): ").strip()
        if gem_api_key is None or len(gem_api_key) == 0:
            gem_api_key = os.getenv("GEM_API_KEY")
        if gem_api_key is None or len(gem_api_key) == 0:
            print("GEM KEY IS NOT ALLOWED TO BE EMPTY -> exit")
            main()
        json_input = input("❓ Optional: Pfad zu einer cfg.json Datei zum prefill der argumente - kann angepasst werden. (Leer lassen zum Überspringen): ").strip()

        # Bereinigt den Pfad (entfernt versehentliche Anführungszeichen beim Copy-Paste und löst "~" auf)
        json_path = os.path.expanduser(json_input.strip('"').strip("'"))

        if json_path:
            if os.path.isfile(json_path) and json_path.lower().endswith('.json'):
                try:
                    with open(json_path, 'r', encoding='utf-8') as f:
                        config_data = json.load(f)

                    print(f"✅ JSON erfolgreich geladen: {json_path}")

                    # Mappe JSON-Keys auf args (nur wenn das Argument im Parser existiert)
                    args_dict = vars(args)
                    for key, value in config_data.items():
                        if key in args_dict:
                            setattr(args, key, value)
                            print(f"   -> Übernehme '{key}': {value}")

                except Exception as e:
                    print(f"❌ Fehler beim Lesen der JSON-Datei: {e}")
            else:
                print(f"⚠️ Datei nicht gefunden oder ungültig: '{json_path}'. Nutze Standardwerte.")

        print("\n--- Parameter-Setup ---")

        print("\n⚙️ Interaktiver Modus gestartet! (Drücke einfach ENTER für die Standardwerte)\n")
        args.input = ask_user("Wo liegen die Bilder? (Ordner, Datei oder URL)", args.input)
        args.tags = ask_user("Welche Tags beschreiben das Cover?", args.tags)
        args.theme = ask_user("Was ist das grundlegende Thema?", args.theme)
        args.bg_texture = ask_user("Wie soll die Hintergrundtextur sein?", args.bg_texture)
        args.math = ask_user("Gibt es eine geometrische Regel?", args.math)
        args.name = ask_user("Wie lautet der Produktname? (Leer für keinen Text)", args.name)
        args.typo = ask_user("Welcher Typografie-Stil soll genutzt werden?", args.typo)
        args.colors = ask_user("Wie lautet die Farbpalette?", args.colors)
        args.tags = ask_user("Zusätzliche Freitext-Beschreibung?", args.tags)
        args.tags = ask_user("In welcher Dir soll das resultet gespeichert werden?", args.output_dir)
        print("\n" + "=" * 40 + "\n")

    # 1. Bilder laden
    images = load_image_source(args.input)

    # 2. Alles an die nächste Funktion übergeben
    run_generation_pipeline(
        images=images,
        theme=args.theme,
        bg_texture=args.bg_texture,
        math_rule=args.math,
        product_name=args.name,
        typo_style=args.typo,
        color_palette=args.colors,
        tags=args.tags,
        output_dir=args.output_dir,
        args=args,
        gem_api_key=gem_api_key,
        height=args.height,
        width=args.width,
    )


# ---------- MAIN ENTRY ----------
if __name__ == "__main__":
    # build pyinstaller --onefile --console gem.py
    main()