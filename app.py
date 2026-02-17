# -*- coding: utf-8 -*-
from pyngrok import ngrok, conf
import sqlite3, os, base64
import pandas as pd
import textwrap

from flask import Flask, request, send_file, render_template_string
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas as pdfcanvas
from reportlab.lib.utils import ImageReader
from io import BytesIO
from datetime import datetime, timedelta

# ---------------- NGROK ----------------
conf.get_default().auth_token = os.getenv("NGROK_AUTH_TOKEN")  # mejor por variable de entorno

# ---------------- APP ----------------
app = Flask(__name__)
DB_PATH = "firmas.db"

# 🔥 REINICIAR JORNADA CADA VEZ QUE SE EJECUTA
if os.path.exists(DB_PATH):
    os.remove(DB_PATH)
    print("🗑️ Jornada anterior borrada, iniciando en blanco")

# ---------------- BASE DE DATOS ----------------
conn = sqlite3.connect(DB_PATH)
cursor = conn.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS trabajadores (
    cedula TEXT PRIMARY KEY,
    nombre TEXT,
    cargo TEXT,
    firma TEXT,
    fecha_firma TEXT
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS facilitador (
    cedula TEXT PRIMARY KEY,
    nombre TEXT,
    tema TEXT,
    lugar TEXT,
    area_frente TEXT,
    duracion TEXT,
    firma TEXT
)
""")

df = pd.read_excel("trabajadores.xls")

# Normalizar columnas
df.columns = [c.strip().lower() for c in df.columns]

# Mapeo flexible (por si tu Excel dice Cédula, Documento, etc.)
mapa = {
    "cedula": ["cedula", "cédula", "documento", "id", "identificacion"],
    "nombre": ["nombre", "nombres", "nombre completo", "empleado"],
    "cargo":  ["cargo", "puesto", "rol", "area", "área"]
}

def buscar_col(opciones):
    for col in df.columns:
        if col in opciones:
            return col
    return None

col_cedula = buscar_col(mapa["cedula"])
col_nombre = buscar_col(mapa["nombre"])
col_cargo  = buscar_col(mapa["cargo"])

if not col_cedula or not col_nombre or not col_cargo:
    raise Exception(f"❌ Columnas no encontradas. Columnas reales: {list(df.columns)}")

df = df[[col_cedula, col_nombre, col_cargo]]
df.columns = ["cedula", "nombre", "cargo"]

# 🔥 LIMPIAR CÉDULAS
df["cedula"] = (
    df["cedula"]
    .astype(str)
    .str.replace(r"\.0$", "", regex=True)   # quita .0 de floats
    .str.replace(r"\D", "", regex=True)     # quita puntos, guiones, espacios
    .str.strip()
)

df.to_sql("trabajadores", conn, if_exists="append", index=False)
print("✅ Trabajadores cargados y cédulas normalizadas")



conn.commit()
conn.close()

# ---------------- PAGINAS HTML ----------------
pagina_login = """
<!doctype html>
<html>
<head>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
body{font-family:Arial;text-align:center;padding:20px;}
input,button{font-size:18px;padding:10px;width:90%;max-width:300px;}
button{background:#ff7a00;color:white;border:none;border-radius:5px;margin:6px;}
</style>
</head>
<body>
<img src="/logo" style="max-width:160px;"><br>
<h2>Registro de Asistencia</h2>
<form action="/buscar" method="post">
<input name="cedula" placeholder="Cédula del asistente" required>
<br><br>
<button type="submit">Firmar Asistencia</button>
</form>
<a href="/facilitador"><button type="button">Soy Facilitador</button></a>
<a href="/reporte_final" target="_blank"><button type="button">Generar PDF F-10</button></a>
</body>
</html>
"""

pagina_facilitador = """
<!doctype html>
<html>
<head>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
body{font-family:Arial;text-align:center;padding:20px;}
input,button{font-size:16px;padding:10px;width:90%;max-width:320px;margin:5px;}
canvas{border:1px solid black;width:350px;height:180px;}
button{background:#1f4fa3;color:white;border:none;border-radius:5px;}
</style>
</head>
<body>
<img src="/logo" style="max-width:120px;"><br>
<h2>Facilitador</h2>
<form action="/guardar_facilitador" method="post">
<input name="cedula" placeholder="Cédula" required>
<input name="nombre" placeholder="Nombre" required>
<input name="tema" placeholder="Tema" required>
<input name="lugar" placeholder="Lugar" required>
<input name="area_frente" placeholder="Área / Frente" required>
<input name="duracion" placeholder="Duración" required>
<h4>Firma</h4>
<canvas id="canvas"></canvas>
<input type="hidden" name="firma" id="firma">
<br><br>
<button type="button" onclick="guardarFirma()">Guardar Facilitador</button>
</form>
<script>
var c=document.getElementById("canvas"),x=c.getContext("2d"),d=false;
c.onmousedown=e=>{d=true;x.beginPath();x.moveTo(e.offsetX,e.offsetY);}
c.onmousemove=e=>{if(d){x.lineTo(e.offsetX,e.offsetY);x.stroke();}}
c.onmouseup=()=>d=false;
function guardarFirma(){
 document.getElementById("firma").value=c.toDataURL("image/png");
 document.forms[0].submit();
}
</script>
</body>
</html>
"""

firma_page = """
<!doctype html>
<html>
<head>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
body{font-family:Arial;text-align:center;padding:20px;}
canvas{border:1px solid black;width:350px;height:200px;}
button{background:#ff7a00;color:white;border:none;border-radius:5px;padding:10px 15px;margin:5px;}
</style>
</head>
<body>
<img src="/logo" style="max-width:120px;"><br>
<h2>Firmar Asistencia</h2>
<b>Nombre:</b> {{nombre}}<br>
<b>Cargo:</b> {{cargo}}<br><br>
<canvas id="canvas"></canvas>
<br><br>
<button onclick="guardar()">Guardar Firma</button>
<button onclick="limpiar()">Limpiar</button>
<script>
var canvas=document.getElementById("canvas");
var ctx=canvas.getContext("2d");
var dibujando=false;

function resizeCanvas(){
 var rect=canvas.getBoundingClientRect();
 canvas.width=rect.width;
 canvas.height=rect.height;
 ctx.lineWidth=2; ctx.lineCap="round";
}
resizeCanvas();

canvas.onmousedown=e=>{dibujando=true;ctx.beginPath();ctx.moveTo(e.offsetX,e.offsetY);}
canvas.onmousemove=e=>{if(dibujando){ctx.lineTo(e.offsetX,e.offsetY);ctx.stroke();}}
canvas.onmouseup=()=>dibujando=false;

function limpiar(){ctx.clearRect(0,0,canvas.width,canvas.height);}
function guardar(){
 var dataURL=canvas.toDataURL("image/png");
 fetch("/guardar_firma_asistente",{
   method:"POST",
   headers:{"Content-Type":"application/x-www-form-urlencoded"},
   body:"firma="+encodeURIComponent(dataURL)+"&cedula={{cedula}}"
 }).then(r=>r.text()).then(html=>{
   document.open();document.write(html);document.close();
 });
}
</script>
</body>
</html>
"""

pagina_gracias = """
<!doctype html>
<html>
<head>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
body{font-family:Arial;text-align:center;padding:30px;background:#f7f7f7;}
h2{color:#1f4fa3;}
button{background:#ff7a00;color:white;border:none;border-radius:5px;padding:12px 20px;font-size:16px;}
</style>
</head>
<body>
<h2>¡Gracias por registrar tu firma!</h2>
<p>Tu asistencia quedó guardada.</p>
<a href="/"><button>Finalizar</button></a>
</body>
</html>
"""

# ---------------- RUTAS ----------------
@app.route("/")
def inicio():
    return pagina_login

@app.route("/logo")
def logo():
    return send_file("/content/Registro-de-asistencia-ISMOCOL-SA/logoismocol.png", mimetype="image/png")

@app.route("/facilitador")
def facilitador():
    return pagina_facilitador

@app.route("/guardar_facilitador", methods=["POST"])
def guardar_facilitador():
    data = (
        request.form["cedula"],
        request.form["nombre"],
        request.form["tema"],
        request.form["lugar"],
        request.form["area_frente"],
        request.form["duracion"],
        request.form["firma"]
    )
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""INSERT OR REPLACE INTO facilitador
                   (cedula,nombre,tema,lugar,area_frente,duracion,firma)
                   VALUES (?,?,?,?,?,?,?)""", data)
    conn.commit()
    conn.close()
    return "<h3>Facilitador registrado correctamente</h3><a href='/'>Volver</a>"

@app.route("/buscar", methods=["POST"])
def buscar():
    import re
    cedula = re.sub(r"\D", "", request.form["cedula"].strip())

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    cur.execute("SELECT COUNT(*) FROM facilitador")
    if cur.fetchone()[0] == 0:
        conn.close()
        return "<h3>Debe registrar primero el Facilitador</h3><a href='/facilitador'>Registrar Facilitador</a>"

    cur.execute("SELECT nombre, cargo, firma FROM trabajadores WHERE cedula=?", (cedula,))
    data = cur.fetchone()
    conn.close()

    if not data:
        return "<h3>Cédula no encontrada</h3><a href='/'>Volver</a>"

    nombre, cargo, firma = data
    if firma:
        return "<h3>Esta cédula ya firmó.</h3><a href='/'>Volver</a>"

    html = firma_page.replace("{{cedula}}", cedula)\
                     .replace("{{nombre}}", nombre)\
                     .replace("{{cargo}}", cargo)
    return render_template_string(html)

@app.route("/guardar_firma_asistente", methods=["POST"])
def guardar_firma_asistente():
    cedula = request.form["cedula"]
    firma_base64 = request.form["firma"]
    fecha = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
        UPDATE trabajadores
        SET firma=?, fecha_firma=?
        WHERE cedula=?
    """, (firma_base64, fecha, cedula))
    conn.commit()
    conn.close()
    return pagina_gracias

@app.route("/reporte_final")
def reporte_final():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    cur.execute("SELECT nombre, tema, lugar, area_frente, duracion, firma FROM facilitador LIMIT 1")
    fac = cur.fetchone()

    cur.execute("""
        SELECT cedula, nombre, cargo, firma
        FROM trabajadores
        WHERE firma IS NOT NULL AND firma != ''
        ORDER BY fecha_firma ASC
    """)
    rows = cur.fetchall()
    conn.close()

    if not rows:
        return "<h3>No hay firmas registradas aún</h3><a href='/'>Volver</a>"

    os.makedirs("/content/pdfs", exist_ok=True)
    pdf_path = "/content/pdfs/reporte_firmas_final.pdf"

    c = pdfcanvas.Canvas(pdf_path, pagesize=A4)
    width, height = A4

    # ========== BLOQUE 1: ENCABEZADO COMPLETO (HOJA 1) ==========
    c.rect(30, height - 110, width - 60, 80)
    c.line(400, height - 110, 400, height - 30)
    c.line(400, height - 70, width - 30, height - 70)

    if os.path.exists("/content/Registro-de-asistencia-ISMOCOL-SA/logoismocol.png"):
        c.drawImage("/content/Registro-de-asistencia-ISMOCOL-SA/logoismocol.png", 40, height - 100, width=80, height=60)

    c.setFont("Helvetica-BoldOblique", 13)
    titulo = "REGISTRO DE ASISTENCIA"
    x_t, y_t = 160, height - 65
    c.drawString(x_t, y_t, titulo)
    c.line(x_t, y_t - 2, x_t + c.stringWidth(titulo, "Helvetica-BoldOblique", 13), y_t - 2)

    c.setFont("Helvetica-Bold", 10)
    c.drawString(420, height - 55, "IQH-GRAL-F-010")
    c.drawString(420, height - 85, "Revisión No. 5")

    # ---------- CASILLAS DE ACTIVIDAD ----------
    c.setFont("Helvetica", 8)
    actividades = ["INDUCCIÓN", "ENTRENAMIENTO", "CAPACITACIÓN", "CHARLA", "REUNIÓN", "LÚDICA"]
    x = 50
    y_cajas = height - 125
    for act in actividades:
        c.rect(x, y_cajas, 10, 10)
        c.drawString(x + 14, y_cajas + 1, act)
        x += 90

    # ---------- CAMPOS ----------
    fecha_colombia = (datetime.utcnow() - timedelta(hours=5)).strftime('%d/%m/%Y')
    nombre_f, tema, lugar, area_frente, duracion, firma_f = fac if fac else ("", "", "", "", "", "")

    campos = [
        ("ÁREA/FRENTE", area_frente),
        ("FECHA", fecha_colombia),
        ("LUGAR", lugar),
        ("DURACIÓN", duracion),
        ("FACILITADOR", nombre_f),
        ("FIRMA", ""),
    ]

    x1, x2 = 50, 300
    y_start = y_cajas - 30
    for i in range(0, len(campos), 2):
        y = y_start - (i // 2) * 22
        c.setFont("Helvetica-Bold", 10)
        c.drawString(x1, y, campos[i][0] + ":")
        c.drawString(x2, y, campos[i + 1][0] + ":")

        c.line(x1 + 95, y - 2, x1 + 230, y - 2)
        c.line(x2 + 95, y - 2, x2 + 230, y - 2)

        c.setFont("Helvetica", 9)
        if campos[i][1]:
            c.drawString(x1 + 100, y, campos[i][1])
        if campos[i + 1][1]:
            c.drawString(x2 + 100, y, campos[i + 1][1])

    # Firma del facilitador
    if firma_f:
        firma_bytes = base64.b64decode(firma_f.split(",")[1])
        img = ImageReader(BytesIO(firma_bytes))
        c.drawImage(img, x2 + 100, y_start - 44, 110, 30, mask="auto")

    # ---------- TEMAS (compactado) ----------
    y_temas = y_start - 70
    c.setFont("Helvetica-Bold", 10)
    c.drawString(50, y_temas, "TEMAS:")
    c.setFont("Helvetica", 10)
    c.drawString(100, y_temas, tema)
    for _ in range(4):  # antes 6
      y_temas -= 12   # antes 15
      c.line(100, y_temas, width - 50, y_temas)


    # ---------- TEXTO LEGAL ----------
    import textwrap
    texto_legal = (
        "Autorización de tratamiento de información personal: "
        "El firmante autoriza a Ismocol SA para que realice el tratamiento de su información personal "
        "de conformidad con el Manual de Políticas y Procedimientos para la Protección de Datos Personales ICA-GRAL-M-05. "
        "Ismocol SA realizará un tratamiento responsable y seguro de los datos suministrados conforme "
        "a las previsiones de la Ley 1581 de 2012 y las normas que la reglamentan.\n\n"
        "Manifiesto que he recibido y entendido en todo su alcance el tema tratado y me comprometo "
        "a cumplir con el procedimiento o contenido de los temas y responsabilidades a mi asignadas. "
        "En constancia firmo."
    )

    c.setFont("Helvetica", 8)
    textobject = c.beginText(40, y_temas - 10)
    textobject.setLeading(10)
    for parrafo in texto_legal.split("\n"):
        if parrafo.strip() == "":
            textobject.textLine("")
        else:
            for linea in textwrap.wrap(parrafo, 140):
                textobject.textLine(linea)
    c.drawText(textobject)

    # ---------- BLOQUE 2: MARCO GRANDE ----------
    y_tabla = textobject.getY() - 25
    c.rect(30, 60, width - 60, y_tabla - -284)

    # ---------- TABLA DE ASISTENTES ----------
    x_no, x_nombre, x_cargo, x_cedula, x_firma = 40, 80, 240, 380, 480
    alto_header, alto_fila = 22, 32

    def dibujar_header_tabla(yh):
        c.setFont("Helvetica-Bold", 11)
        c.rect(x_no, yh, width - 80, alto_header)
        c.drawString(x_no + 5, yh + 7, "No.")
        c.drawString(x_nombre, yh + 7, "NOMBRE")
        c.drawString(x_cargo, yh + 7, "CARGO")
        c.drawString(x_cedula, yh + 7, "CÉDULA")
        c.drawString(x_firma, yh + 7, "FIRMA")

    y = y_tabla - 1
    dibujar_header_tabla(y)
    y -= alto_header + 5

    def encabezado_simple():
        c.setFont("Helvetica-BoldOblique", 13)
        titulo2 = "REGISTRO DE ASISTENCIA"
        c.drawString(50, height - 50, titulo2)
        c.line(50, height - 52, 50 + c.stringWidth(titulo2, "Helvetica-BoldOblique", 13), height - 52)

        c.setFont("Helvetica", 8)
        t = c.beginText(40, height - 75)
        t.setLeading(11)
        for parrafo in texto_legal.split("\n"):
            if parrafo.strip() == "":
                t.textLine("")
            else:
                for linea in textwrap.wrap(parrafo, 140):
                    t.textLine(linea)
        c.drawText(t)
        return t.getY() - 20

    for i, (cedula, nombre, cargo, firma) in enumerate(rows, 1):
        if y < 90:
            c.showPage()
            y = encabezado_simple()
            dibujar_header_tabla(y)
            y -= alto_header + 5

        c.rect(x_no, y, width - 80, alto_fila)
        c.setFont("Helvetica", 11)
        c.drawString(x_no + 5, y + 10, str(i))
        c.drawString(x_nombre, y + 10, nombre[:30])
        c.drawString(x_cargo, y + 10, cargo[:30])
        c.drawString(x_cedula, y + 10, cedula)

        if firma:
            img = ImageReader(BytesIO(base64.b64decode(firma.split(",")[1])))
            c.drawImage(img, x_firma, y + 5, 90, 22, mask="auto")

        y -= alto_fila

    c.save()
    return send_file(pdf_path, mimetype="application/pdf", as_attachment=False)


# ---------------- INICIAR ----------------
public_url = ngrok.connect(5000)
print("📱 LINK PARA CELULAR:", public_url)
app.run(host="0.0.0.0", port=5000)
