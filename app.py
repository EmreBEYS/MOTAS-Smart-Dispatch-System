from flask import Flask, render_template, redirect, url_for, request, send_file, session, flash
from urllib.parse import urlparse
from functools import wraps
from werkzeug.utils import secure_filename


import os
import psycopg2
import psycopg2.extras
import pandas as pd

from dotenv import load_dotenv
from openai import OpenAI

from config import Config



# --------------------------------------------------
# ENV + APP CONFIG
# --------------------------------------------------

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ENV_PATH = os.path.join(BASE_DIR, "ai.env")

load_dotenv(ENV_PATH)

app = Flask(__name__)
app.config.from_object(Config)
app.secret_key = Config.SECRET_KEY

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

if OPENAI_API_KEY:
    print("OPENAI_API_KEY başarıyla okundu.")
else:
    print("UYARI: OPENAI_API_KEY ai.env dosyasından okunamadı.")

client = OpenAI(api_key=OPENAI_API_KEY)

EXPORT_DIR = os.path.join(BASE_DIR, "exports")
os.makedirs(EXPORT_DIR, exist_ok=True)

DUYURU_UPLOAD_FOLDER = os.path.join(BASE_DIR, "static", "image", "duyurular")
os.makedirs(DUYURU_UPLOAD_FOLDER, exist_ok=True)

#-----------------------------------
# AI CEVAP 
#--------------------------------

def db_ai_ulasim_verisi_getir():
    conn = None
    cur = None

    try:
        conn = get_db_connection()
        cur = conn.cursor()

        cur.execute("""
            SELECT hat_kodu, hat_adi
            FROM hatlar
            WHERE aktif = TRUE
            ORDER BY hat_kodu ASC
        """)
        hat_rows = cur.fetchall()

        hat_bilgileri = [
            f"{row[0]} - {row[1]}"
            for row in hat_rows
        ]

        cur.execute("""
            SELECT durak_kodu, durak_adi
            FROM duraklar
            WHERE aktif = TRUE
            ORDER BY durak_adi ASC
            LIMIT 300
        """)
        durak_rows = cur.fetchall()

        durak_bilgileri = [
            f"{row[0]} - {row[1]}"
            for row in durak_rows
        ]

        cur.execute("""
            SELECT h.hat_kodu, h.hat_adi, s.gun_tipi, s.yon, s.saat
            FROM seferler s
            JOIN hatlar h ON h.hat_id = s.hat_id
            WHERE h.aktif = TRUE
            ORDER BY h.hat_kodu, s.gun_tipi, s.yon, s.saat
            LIMIT 600
        """)
        sefer_rows = cur.fetchall()

        sefer_bilgileri = [
            f"{row[0]} - {row[1]} | {row[2]} | {row[3]} | {row[4]}"
            for row in sefer_rows
        ]

        return {
            "hatlar": "\n".join(hat_bilgileri),
            "duraklar": "\n".join(durak_bilgileri),
            "seferler": "\n".join(sefer_bilgileri)
        }

    except Exception as e:
        print("AI için veritabanı bilgileri çekilemedi:", e)

        return {
            "hatlar": "",
            "duraklar": "",
            "seferler": ""
        }

    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()

# --------------------------------------------------
# DB CONNECTION
# --------------------------------------------------

def get_db_connection():
    db_uri = Config.SQLALCHEMY_DATABASE_URI

    if not db_uri:
        raise Exception("SQLALCHEMY_DATABASE_URI tanımlı değil.")

    db_url = urlparse(db_uri)

    conn = psycopg2.connect(
        host=db_url.hostname,
        database=db_url.path[1:],
        user=db_url.username,
        password=db_url.password,
        port=db_url.port
    )

    return conn

def get_dict_cursor():
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    return conn, cur

# --------------------------------------------------
# OPENAI ULAŞIM CEVABI
# --------------------------------------------------
def duraktan_gecen_hatlari_getir(durak_adi):
    conn = None
    cur = None

    try:
        conn = get_db_connection()
        cur = conn.cursor()

        cur.execute("""
            SELECT DISTINCT h.hat_id, h.hat_kodu, h.hat_adi
            FROM hat_durak hd
            JOIN duraklar d ON d.durak_id = hd.durak_id
            JOIN hatlar h ON h.hat_id = hd.hat_id
            WHERE h.aktif = TRUE
              AND d.aktif = TRUE
              AND LOWER(d.durak_adi) LIKE LOWER(%s)
            ORDER BY h.hat_kodu ASC
        """, (f"%{durak_adi}%",))

        return cur.fetchall()

    except Exception as e:
        print("Duraktan geçen hatlar alınamadı:", e)
        return []

    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


def ortak_hat_bul(nereden, nereye):
    nereden_hatlar = duraktan_gecen_hatlari_getir(nereden)
    nereye_hatlar = duraktan_gecen_hatlari_getir(nereye)

    ortak_hatlar = []

    for h1 in nereden_hatlar:
        for h2 in nereye_hatlar:
            if h1[0] == h2[0]:
                ortak_hatlar.append({
                    "hat_id": h1[0],
                    "hat_kodu": h1[1],
                    "hat_adi": h1[2]
                })

    return ortak_hatlar


def hat_saatlerini_getir(hat_id):
    conn = None
    cur = None

    try:
        conn = get_db_connection()
        cur = conn.cursor()

        cur.execute("""
            SELECT gun_tipi, yon, saat
            FROM seferler
            WHERE hat_id = %s
            ORDER BY 
                CASE 
                    WHEN gun_tipi = 'Hafta İçi' THEN 1
                    WHEN gun_tipi = 'Hafta Sonu' THEN 2
                    ELSE 3
                END,
                yon,
                saat
            LIMIT 20
        """, (hat_id,))

        return cur.fetchall()

    except Exception as e:
        print("Hat saatleri alınamadı:", e)
        return []

    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


def openai_ulasim_cevabi_al(nereden, nereye):
    nereden = nereden.strip()
    nereye = nereye.strip()

    ortak_hatlar = ortak_hat_bul(nereden, nereye)

    if ortak_hatlar:
        ilk_hat = ortak_hatlar[0]
        saatler = hat_saatlerini_getir(ilk_hat["hat_id"])

        saat_metni = ""

        if saatler:
            saat_metni = "\n\nYaklaşık bazı sefer saatleri:\n"

            for gun_tipi, yon, saat in saatler[:10]:
                saat_metni += f"- {gun_tipi} | {yon} | {saat}\n"

        return f"""
Önerilen Hat: {ilk_hat["hat_kodu"]} ({ilk_hat["hat_adi"]})
Aktarma Durumu: Direkt
Yol Tarifi: {nereden} durağından {ilk_hat["hat_kodu"]} hattına binerek {nereye} noktasına direkt ulaşabilirsiniz.
{ saat_metni }
Not: Güncel hat ve saat bilgisi için MOTAŞ hareket saatleri sayfasını kontrol ediniz.
"""

    if not OPENAI_API_KEY or client is None:
        return "OpenAI API anahtarı bulunamadı. Lütfen ai.env dosyasındaki OPENAI_API_KEY değerini kontrol edin."

    db_verisi = db_ai_ulasim_verisi_getir()

    hatlar = db_verisi["hatlar"]
    duraklar = db_verisi["duraklar"]
    seferler = db_verisi["seferler"]

    prompt = f"""
Sen Malatya şehir içi ulaşım sistemi için çalışan bir yapay zeka ulaşım asistanısın.

Kullanıcının kalkış noktası:
{nereden}

Kullanıcının varış noktası:
{nereye}

Veritabanında kayıtlı aktif hatlar:
{hatlar}

Veritabanında kayıtlı aktif duraklardan bazıları:
{duraklar}

Veritabanındaki örnek sefer saatleri:
{seferler}

Cevap kuralları:
1. Öncelikle yukarıdaki veritabanı bilgilerine göre cevap vermeye çalış.
2. Eğer kalkış veya varış noktası duraklarda geçiyorsa bunu dikkate al.
3. Eğer hat adı veya hat kodu güzergâhla ilgili görünüyorsa öner.
4. Emin olmadığın hatları kesin bilgi gibi söyleme.
5. Eğer yeterli veri yoksa genel yönlendirme yap.
6. Cevapta "kesin hat bilgisi bulunmamaktadır" gibi dürüst bir ifade kullanabilirsin.
7. Cevabı Türkçe, kısa, net ve kullanıcı dostu ver.
8. Cevabın sonunda mutlaka şu notu ekle:
"Güncel hat ve saat bilgisi için MOTAŞ hareket saatleri sayfasını kontrol ediniz."
9. Eğer kullanıcının söylediği yer bir durak adıysa, o durağın geçtiği hatları bulmaya çalış.
10. Aynı hatta geçen duraklar arasında doğrudan ulaşım varsa bunu belirt.
11. Önce direkt hat öner, sonra aktarma öner.

Cevap formatı şu şekilde olsun:

Önerilen Hat:
Aktarma Durumu:
Yol Tarifi:
Not:
"""

    try:
        response = client.chat.completions.create(
            model="gpt-4.1-mini",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Sen Malatya toplu taşıma sistemi için yardımcı bir ulaşım asistanısın. "
                        "Veritabanı bilgilerini kullanırsın, bilmediğin güzergâhı kesinmiş gibi uydurmazsın."
                    )
                },
                {
                    "role": "user",
                    "content": prompt
                }
            ],
            temperature=0.2,
            max_tokens=400
        )

        return response.choices[0].message.content

    except Exception as e:
        return f"AI yol tarifi alınırken hata oluştu: {str(e)}"
# --------------------------------------------------
# AUTH DECORATORS
# --------------------------------------------------

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user' not in session:
            return redirect(url_for('login'))

        return f(*args, **kwargs)

    return decorated_function


def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user' not in session:
            return redirect(url_for('login'))

        if session.get('role_id') != 1:
            return redirect(url_for('home'))

        return f(*args, **kwargs)

    return decorated_function


# --------------------------------------------------
# ANA SAYFA
# --------------------------------------------------

@app.route("/", methods=["GET", "POST"])
def home():
    ai_cevap = None
    nereden = ""
    nereye = ""
    hatlar = []
    duyurular = []

    conn = None
    cursor = None

    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)

        cursor.execute("""
            SELECT hat_id, hat_kodu, hat_adi
            FROM hatlar
            WHERE aktif = TRUE
            ORDER BY hat_kodu ASC
        """)
        hatlar = cursor.fetchall()

        try:
            cursor.execute("""
                SELECT duyuru_id, baslik, aciklama, gorsel_yolu, video_yolu, yayin_durumu, created_at
                FROM duyurular
                WHERE yayin_durumu = TRUE
                ORDER BY created_at DESC
                LIMIT 6
            """)
            duyurular = cursor.fetchall()

        except Exception as duyuru_hatasi:
            print("Duyurular çekilirken hata:", duyuru_hatasi)
            duyurular = []

    except Exception as e:
        print("Ana sayfa verileri çekilirken hata:", e)
        hatlar = []
        duyurular = []

    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()

    if request.method == "POST":
        form_type = request.form.get("form_type")

        if form_type == "nasil_giderim":
            nereden = request.form.get("nereden", "").strip()
            nereye = request.form.get("nereye", "").strip()

            if nereden and nereye:
                ai_cevap = openai_ulasim_cevabi_al(nereden, nereye)
            else:
                ai_cevap = "Lütfen kalkış ve varış noktalarını doldurunuz."

    return render_template(
        "index.html",
        ai_cevap=ai_cevap,
        nereden=nereden,
        nereye=nereye,
        hatlar=hatlar,
        duyurular=duyurular
    )


# --------------------------------------------------
# AI YOL TARİFİ AYRI ROUTE
# --------------------------------------------------

@app.route("/ai-yol-tarifi", methods=["POST"])
def ai_yol_tarifi():
    nereden = request.form.get("nereden")
    nereye = request.form.get("nereye")

    if not nereden or not nereye:
        flash("Lütfen nereden ve nereye bilgilerini doldurun.", "error")
        return redirect(url_for("home"))

    sonuc = openai_ulasim_cevabi_al(nereden, nereye)

    return render_template(
        "ai_yol_tarifi_sonuc.html",
        nereden=nereden,
        nereye=nereye,
        sonuc=sonuc
    )


# --------------------------------------------------
# PUBLIC PAGES - HATLAR
# --------------------------------------------------
@app.route("/hatlar")
def public_hatlar():
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    cur.execute("""
        SELECT 
            hat_id,
            hat_kodu,
            hat_adi,
            aktif
        FROM hatlar
        WHERE aktif = true
        ORDER BY 
            CASE 
                WHEN hat_kodu ~ '^[0-9]+$' THEN CAST(hat_kodu AS INTEGER)
                ELSE 9999
            END,
            hat_kodu ASC
    """)

    hatlar = cur.fetchall()

    cur.close()
    conn.close()

    return render_template("pages/hatlar.html", hatlar=hatlar)




@app.route("/hat-detay/<int:hat_id>")
def hat_detay(hat_id):
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    # 1) Hat bilgisi
    cur.execute("""
        SELECT 
            hat_id,
            hat_kodu,
            hat_adi,
            aktif
        FROM hatlar
        WHERE hat_id = %s
    """, (hat_id,))

    hat = cur.fetchone()

    if not hat:
        cur.close()
        conn.close()
        flash("Hat bulunamadı.", "warning")
        return redirect(url_for("hatlar"))

    # 2) Hattın geçtiği duraklar
    cur.execute("""
        SELECT 
            hd.durak_sirasi,
            d.durak_id,
            d.durak_adi,
            d.latitude,
            d.longitude
        FROM hat_durak hd
        JOIN duraklar d ON d.durak_id = hd.durak_id
        WHERE hd.hat_id = %s
        ORDER BY hd.durak_sirasi ASC
    """, (hat_id,))

    duraklar = cur.fetchall()

    # 3) Hattın sefer saatleri
    cur.execute("""
        SELECT 
            gun_tipi,
            yon,
            saat
        FROM seferler
        WHERE hat_id = %s
        ORDER BY 
            CASE
                WHEN gun_tipi = 'Hafta İçi' THEN 1
                WHEN gun_tipi = 'Hafta Sonu' THEN 2
                WHEN gun_tipi = 'Cumartesi' THEN 2
                WHEN gun_tipi = 'Pazar' THEN 2
                WHEN gun_tipi = 'Resmi Tatil' THEN 3
                ELSE 4
            END,
            CASE
                WHEN yon = 'Gidiş' THEN 1
                WHEN yon = 'Dönüş' THEN 2
                ELSE 3
            END,
            saat ASC
    """, (hat_id,))

    seferler = cur.fetchall()

    cur.close()
    conn.close()

    # 4) Seferleri gün tipi ve yöne göre gruplandır
    sefer_gruplu = {
        "Hafta İçi": {
            "Gidiş": [],
            "Dönüş": []
        },
        "Hafta Sonu": {
            "Gidiş": [],
            "Dönüş": []
        },
        "Resmi Tatil": {
            "Gidiş": [],
            "Dönüş": []
        }
    }

    for sefer in seferler:
        gun = sefer["gun_tipi"]
        yon = sefer["yon"]
        saat = sefer["saat"]

        # Eğer veritabanında Cumartesi/Pazar diye geldiyse Hafta Sonu altında birleştir
        if gun in ["Cumartesi", "Pazar"]:
            gun = "Hafta Sonu"

        # Beklenmeyen gün tipi gelirse yine de sisteme ekle
        if gun not in sefer_gruplu:
            sefer_gruplu[gun] = {
                "Gidiş": [],
                "Dönüş": []
            }

        # Beklenmeyen yön tipi gelirse yine de hata vermesin
        if yon not in sefer_gruplu[gun]:
            sefer_gruplu[gun][yon] = []

        # PostgreSQL time tipini 06:30 formatına çevir
        if hasattr(saat, "strftime"):
            saat = saat.strftime("%H:%M")

        sefer_gruplu[gun][yon].append(saat)

    # 5) Resmi tatil için ayrı veri yoksa hafta sonu saatlerini kullan
    if not sefer_gruplu["Resmi Tatil"]["Gidiş"] and not sefer_gruplu["Resmi Tatil"]["Dönüş"]:
        sefer_gruplu["Resmi Tatil"]["Gidiş"] = sefer_gruplu["Hafta Sonu"]["Gidiş"].copy()
        sefer_gruplu["Resmi Tatil"]["Dönüş"] = sefer_gruplu["Hafta Sonu"]["Dönüş"].copy()

    return render_template(
        "pages/hat_detay.html",
        hat=hat,
        duraklar=duraklar,
        sefer_gruplu=sefer_gruplu
    )

# ==================================================
# PUBLIC PAGES - DURAKLAR
# ==================================================

@app.route('/duraklar')
def public_duraklar():
    conn = None
    cur = None

    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        cur.execute("""
            SELECT 
                durak_id,
                durak_kodu,
                durak_adi,
                latitude,
                longitude,
                aktif
            FROM duraklar
            WHERE aktif = TRUE
            ORDER BY durak_id ASC
        """)

        duraklar = cur.fetchall()

        return render_template(
            'pages/duraklar.html',
            duraklar=duraklar
        )

    except Exception as e:
        return f"Duraklar yüklenirken hata oluştu: {e}", 500

    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


@app.route('/durak/<int:durak_id>')
def public_durak_detay(durak_id):
    conn = None
    cur = None

    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        # 1) Durak bilgisi
        cur.execute("""
            SELECT 
                durak_id,
                durak_kodu,
                durak_adi,
                latitude,
                longitude,
                aktif
            FROM duraklar
            WHERE durak_id = %s
              AND aktif = TRUE
        """, (durak_id,))

        durak = cur.fetchone()

        if not durak:
            flash("Durak bulunamadı.", "warning")
            return redirect(url_for("public_duraklar"))

        # 2) Bu duraktan geçen aktif hatlar
        cur.execute("""
            SELECT 
                h.hat_id,
                h.hat_kodu,
                h.hat_adi,
                MIN(hd.durak_sirasi) AS durak_sirasi
            FROM hat_durak hd
            JOIN hatlar h ON h.hat_id = hd.hat_id
            WHERE hd.durak_id = %s
              AND h.aktif = TRUE
            GROUP BY 
                h.hat_id,
                h.hat_kodu,
                h.hat_adi
            ORDER BY 
                CASE 
                    WHEN h.hat_kodu ~ '^[0-9]+$' THEN CAST(h.hat_kodu AS INTEGER)
                    ELSE 9999
                END,
                h.hat_kodu ASC,
                MIN(hd.durak_sirasi) ASC
        """, (durak_id,))

        gecen_hatlar = cur.fetchall()

        return render_template(
            "pages/durak-detay.html",
            durak=durak,
            gecen_hatlar=gecen_hatlar
        )

    except Exception as e:
        return f"Durak detay yüklenirken hata oluştu: {e}", 500

    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()
# --------------------------------------------------
# AUTH
# --------------------------------------------------

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')

        conn = None
        cur = None

        try:
            conn = get_db_connection()
            cur = conn.cursor()

            cur.execute("""
                SELECT user_id, name, surname, email, password, role_id
                FROM users
                WHERE email = %s AND password = %s
            """, (email, password))

            kullanici = cur.fetchone()

            if kullanici:
                session['user_id'] = kullanici[0]
                session['name'] = kullanici[1]
                session['surname'] = kullanici[2]
                session['user'] = kullanici[3]
                session['role_id'] = kullanici[5]

                if kullanici[5] == 1:
                    return redirect(url_for('admin_dashboard'))

                return redirect(url_for('home'))

            return "Email veya şifre yanlış."

        except Exception as e:
            return f"Giriş sırasında hata oluştu: {e}", 500

        finally:
            if cur:
                cur.close()
            if conn:
                conn.close()

    return render_template('pages/login.html')


@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        name = request.form.get('name')
        surname = request.form.get('surname')
        email = request.form.get('email')
        password = request.form.get('password')

        conn = None
        cur = None

        try:
            conn = get_db_connection()
            cur = conn.cursor()

            cur.execute("SELECT user_id FROM users WHERE email = %s", (email,))
            mevcut_kullanici = cur.fetchone()

            if mevcut_kullanici:
                return "Bu email zaten kayıtlı."

            cur.execute("""
                INSERT INTO users (name, surname, email, password, role_id)
                VALUES (%s, %s, %s, %s, %s)
            """, (name, surname, email, password, 2))

            conn.commit()

            cur.execute("""
                SELECT user_id, name, surname, email, role_id
                FROM users
                WHERE email = %s
            """, (email,))
            yeni_kullanici = cur.fetchone()

            session['user_id'] = yeni_kullanici[0]
            session['name'] = yeni_kullanici[1]
            session['surname'] = yeni_kullanici[2]
            session['user'] = yeni_kullanici[3]
            session['role_id'] = yeni_kullanici[4]

            return redirect(url_for('home'))

        except Exception as e:
            if conn:
                conn.rollback()

            return f"Kayıt sırasında hata oluştu: {e}", 500

        finally:
            if cur:
                cur.close()
            if conn:
                conn.close()

    return render_template('pages/register.html')


@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('home'))


# --------------------------------------------------
# ADMIN DASHBOARD
# --------------------------------------------------

@app.route('/admin/dashboard')
@admin_required
def admin_dashboard():
    return render_template(
        'admin/dashboard.html',
        active_page='dashboard'
    )


# --------------------------------------------------
# ADMIN HATLAR
# --------------------------------------------------

@app.route('/admin/hatlar')
@admin_required
def admin_hatlar():
    conn = None
    cur = None

    try:
        conn = get_db_connection()
        cur = conn.cursor()

        cur.execute("""
            SELECT hat_id, hat_adi, hat_kodu, aktif
            FROM hatlar
            ORDER BY hat_id ASC
        """)
        rows = cur.fetchall()

        hatlar = []
        for row in rows:
            hatlar.append({
                'hat_id': row[0],
                'hat_adi': row[1],
                'hat_kodu': row[2],
                'aktif': row[3]
            })

        return render_template(
            'admin/hatlar.html',
            active_page='hat_yonetimi',
            hatlar=hatlar
        )

    except Exception as e:
        return f"Hatlar yüklenirken hata oluştu: {e}", 500

    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


@app.route('/admin/hat-ekle', methods=['GET', 'POST'])
@admin_required
def admin_hat_ekle():
    if request.method == 'POST':
        hat_adi = request.form.get('hat_adi')
        hat_kodu = request.form.get('hat_kodu')
        aktif = True if request.form.get('aktif') == 'true' else False

        conn = None
        cur = None

        try:
            conn = get_db_connection()
            cur = conn.cursor()

            cur.execute("""
                INSERT INTO hatlar (hat_adi, hat_kodu, aktif)
                VALUES (%s, %s, %s)
            """, (hat_adi, hat_kodu, aktif))

            conn.commit()
            return redirect(url_for('admin_hatlar'))

        except Exception as e:
            if conn:
                conn.rollback()

            return f"Hat eklenirken hata oluştu: {e}", 500

        finally:
            if cur:
                cur.close()
            if conn:
                conn.close()

    return render_template(
        'admin/hat-ekle.html',
        active_page='hat_yonetimi'
    )


@app.route('/admin/hat/<int:hat_id>')
@admin_required
def admin_hat_detay(hat_id):
    conn = None
    cur = None

    try:
        conn = get_db_connection()
        cur = conn.cursor()

        cur.execute("""
            SELECT hat_id, hat_adi, hat_kodu, aktif
            FROM hatlar
            WHERE hat_id = %s
        """, (hat_id,))
        row = cur.fetchone()

        if not row:
            return "Hat bulunamadı", 404

        hat = {
            'hat_id': row[0],
            'hat_adi': row[1],
            'hat_kodu': row[2],
            'aktif': row[3]
        }

        return render_template(
            'admin/hat-detay.html',
            active_page='hat_yonetimi',
            hat=hat
        )

    except Exception as e:
        return f"Hat detay yüklenirken hata oluştu: {e}", 500

    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


@app.route('/admin/hat-duzenle/<int:hat_id>', methods=['GET', 'POST'])
@admin_required
def admin_hat_duzenle(hat_id):
    conn = None
    cur = None

    try:
        conn = get_db_connection()
        cur = conn.cursor()

        if request.method == 'POST':
            hat_adi = request.form.get('hat_adi')
            hat_kodu = request.form.get('hat_kodu')
            aktif = True if request.form.get('aktif') == 'true' else False

            cur.execute("""
                UPDATE hatlar
                SET hat_adi = %s,
                    hat_kodu = %s,
                    aktif = %s
                WHERE hat_id = %s
            """, (hat_adi, hat_kodu, aktif, hat_id))

            conn.commit()
            return redirect(url_for('admin_hatlar'))

        cur.execute("""
            SELECT hat_id, hat_adi, hat_kodu, aktif
            FROM hatlar
            WHERE hat_id = %s
        """, (hat_id,))
        row = cur.fetchone()

        if not row:
            return "Hat bulunamadı", 404

        hat = {
            'hat_id': row[0],
            'hat_adi': row[1],
            'hat_kodu': row[2],
            'aktif': row[3]
        }

        return render_template(
            'admin/hat-duzenle.html',
            active_page='hat_yonetimi',
            hat=hat
        )

    except Exception as e:
        if conn:
            conn.rollback()

        return f"Hat düzenlenirken hata oluştu: {e}", 500

    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


@app.route('/admin/hat-sil/<int:hat_id>')
@admin_required
def admin_hat_sil(hat_id):
    conn = None
    cur = None

    try:
        conn = get_db_connection()
        cur = conn.cursor()

        cur.execute("DELETE FROM hatlar WHERE hat_id = %s", (hat_id,))
        conn.commit()

        return redirect(url_for('admin_hatlar'))

    except Exception as e:
        if conn:
            conn.rollback()

        return f"Hat silinirken hata oluştu: {e}", 500

    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


# --------------------------------------------------
# ADMIN DURAKLAR
# --------------------------------------------------

@app.route('/admin/duraklar')
@admin_required
def admin_duraklar():
    conn = None
    cur = None

    try:
        conn = get_db_connection()
        cur = conn.cursor()

        cur.execute("""
            SELECT durak_id, durak_kodu, durak_adi, latitude, longitude, aktif
            FROM duraklar
            ORDER BY durak_id ASC
        """)
        rows = cur.fetchall()

        duraklar = []
        for row in rows:
            duraklar.append({
                'durak_id': row[0],
                'durak_kodu': row[1],
                'durak_adi': row[2],
                'latitude': row[3],
                'longitude': row[4],
                'aktif': row[5]
            })

        return render_template(
            'admin/duraklar.html',
            active_page='durak_yonetimi',
            duraklar=duraklar
        )

    except Exception as e:
        return f"Duraklar yüklenirken hata oluştu: {e}", 500

    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


@app.route('/admin/duraklar/excel')
@admin_required
def admin_duraklar_excel():
    conn = None

    try:
        conn = get_db_connection()

        query = """
            SELECT durak_id, durak_kodu, durak_adi, latitude, longitude, aktif
            FROM duraklar
            ORDER BY durak_id ASC
        """

        df = pd.read_sql(query, conn)

        dosya_yolu = os.path.join(EXPORT_DIR, 'duraklar_listesi.xlsx')
        df.to_excel(dosya_yolu, index=False)

        return send_file(dosya_yolu, as_attachment=True)

    except Exception as e:
        return f"Durak Excel oluşturulurken hata oluştu: {e}", 500

    finally:
        if conn:
            conn.close()

@app.route('/admin/durak-ekle', methods=['GET', 'POST'])
@admin_required
def admin_durak_ekle():
    if request.method == 'POST':
        durak_kodu = request.form.get('durak_kodu')
        durak_adi = request.form.get('durak_adi')
        latitude = request.form.get('latitude')
        longitude = request.form.get('longitude')
        aktif = True if request.form.get('aktif') == 'true' else False

        conn = None
        cur = None

        try:
            conn = get_db_connection()
            cur = conn.cursor()

            cur.execute("""
                INSERT INTO duraklar (durak_kodu, durak_adi, latitude, longitude, aktif)
                VALUES (%s, %s, %s, %s, %s)
                """, (durak_kodu, durak_adi, latitude, longitude, aktif))

            conn.commit()
            return redirect(url_for('admin_duraklar'))

        except Exception as e:
            if conn:
                conn.rollback()

            return f"Durak eklenirken hata oluştu: {e}", 500

        finally:
            if cur:
                cur.close()
            if conn:
                conn.close()

    return render_template(
        'admin/durak-ekle.html',
        active_page='durak_yonetimi'
    )

@app.route('/admin/durak/<int:durak_id>')
@admin_required
def admin_durak_detay(durak_id):
    conn = None
    cur = None

    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        # 1) Durak bilgisi
        cur.execute("""
            SELECT 
                durak_id,
                durak_kodu,
                durak_adi,
                latitude,
                longitude,
                aktif
            FROM public.duraklar
            WHERE durak_id = %s
        """, (durak_id,))

        durak = cur.fetchone()

        if not durak:
            flash("Durak bulunamadı.", "warning")
            return redirect(url_for("admin_duraklar"))

        # 2) Bu duraktan geçen hatlar
        cur.execute("""
            SELECT DISTINCT
                h.hat_id,
                h.hat_kodu,
                h.hat_adi,
                h.aktif,
                hd.durak_sirasi
            FROM public.hat_durak hd
            JOIN public.hatlar h ON h.hat_id = hd.hat_id
            WHERE hd.durak_id = %s
            ORDER BY 
                h.hat_kodu ASC,
                hd.durak_sirasi ASC
        """, (durak_id,))

        hatlar = cur.fetchall()

        # 3) Kamera dosyası kontrolü
        kamera_dosyasi = f"image/durak_kamera/durak_{durak_id}.jpg"
        kamera_yolu = os.path.join(BASE_DIR, "static", kamera_dosyasi)
        kamera_var = os.path.exists(kamera_yolu)

        return render_template(
            'admin/durak_detay.html',
            active_page='durak_yonetimi',
            durak=durak,
            hatlar=hatlar,
            kamera_var=kamera_var,
            kamera_dosyasi=kamera_dosyasi
        )

    except Exception as e:
        return f"Durak detay yüklenirken hata oluştu: {e}", 500

    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


@app.route('/admin/durak-duzenle/<int:durak_id>', methods=['GET', 'POST'])
@admin_required
def admin_durak_duzenle(durak_id):
    conn = None
    cur = None

    try:
        conn = get_db_connection()
        cur = conn.cursor()

        if request.method == 'POST':
            durak_adi = request.form.get('durak_adi')
            latitude = request.form.get('latitude')
            longitude = request.form.get('longitude')
            aktif = True if request.form.get('aktif') == 'true' else False

            cur.execute("""
                UPDATE duraklar
                SET durak_adi = %s,
                    latitude = %s,
                    longitude = %s,
                    aktif = %s
                WHERE durak_id = %s
            """, (durak_adi, latitude, longitude, aktif, durak_id))

            conn.commit()
            return redirect(url_for('admin_duraklar'))

        cur.execute("""
            SELECT durak_id, durak_adi, latitude, longitude, aktif
            FROM duraklar
            WHERE durak_id = %s
        """, (durak_id,))
        row = cur.fetchone()

        if not row:
            return "Durak bulunamadı", 404

        durak = {
            'durak_id': row[0],
            'durak_adi': row[1],
            'latitude': row[2],
            'longitude': row[3],
            'aktif': row[4]
        }

        return render_template(
            'admin/durak-duzenle.html',
            active_page='durak_yonetimi',
            durak=durak
        )

    except Exception as e:
        if conn:
            conn.rollback()

        return f"Durak düzenlenirken hata oluştu: {e}", 500

    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


@app.route('/admin/durak-sil/<int:durak_id>')
@admin_required
def admin_durak_sil(durak_id):
    conn = None
    cur = None

    try:
        conn = get_db_connection()
        cur = conn.cursor()

        cur.execute("DELETE FROM duraklar WHERE durak_id = %s", (durak_id,))
        conn.commit()

        return redirect(url_for('admin_duraklar'))

    except Exception as e:
        if conn:
            conn.rollback()

        return f"Durak silinirken hata oluştu: {e}", 500

    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


# --------------------------------------------------
# ADMIN ARAÇLAR / OTOBÜS YÖNETİMİ
# --------------------------------------------------

@app.route('/admin/araclar')
@admin_required
def admin_araclar():
    conn = None
    cur = None

    try:
        conn = get_db_connection()
        cur = conn.cursor()

        cur.execute("""
            SELECT 
                otobus_id,
                plaka,
                marka,
                model,
                kapasite,
                kilometre,
                yogunluk,
                durum,
                kamera_yolu,
                son_goruntu_zamani,
                yolcu_sayisi,
                doluluk_orani
            FROM public.otobusler
            ORDER BY otobus_id ASC
        """)

        rows = cur.fetchall()

        araclar = []
        for row in rows:
            araclar.append({
                'otobus_id': row[0],
                'plaka': row[1],
                'marka': row[2],
                'model': row[3],
                'kapasite': row[4],
                'kilometre': row[5],
                'yogunluk': row[6],
                'durum': row[7],
                'kamera_yolu': row[8],
                'son_goruntu_zamani': row[9],
                'yolcu_sayisi': row[10],
                'doluluk_orani': row[11]
            })

        return render_template(
            'admin/araclar.html',
            active_page='otobus_yonetimi',
            araclar=araclar
        )

    except Exception as e:
        return f"Araçlar yüklenirken hata oluştu: {e}", 500

    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


@app.route('/admin/arac-ekle', methods=['GET', 'POST'])
@admin_required
def admin_arac_ekle():
    if request.method == 'POST':
        plaka = request.form.get('plaka')
        marka = request.form.get('marka')
        model = request.form.get('model')
        kapasite = request.form.get('kapasite')
        kilometre = request.form.get('kilometre')
        durum = request.form.get('durum')
        yogunluk = request.form.get('yogunluk')
        kamera_yolu = request.form.get('kamera_yolu')

        conn = None
        cur = None

        try:
            conn = get_db_connection()
            cur = conn.cursor()

            cur.execute("""
                INSERT INTO public.otobusler
                (
                    plaka,
                    marka,
                    model,
                    kapasite,
                    kilometre,
                    durum,
                    yogunluk,
                    kamera_yolu
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """, (
                plaka,
                marka,
                model,
                kapasite,
                kilometre,
                durum,
                yogunluk,
                kamera_yolu
            ))

            conn.commit()
            flash("Araç başarıyla eklendi.", "success")
            return redirect(url_for('admin_araclar'))

        except Exception as e:
            if conn:
                conn.rollback()

            return f"Araç eklenirken hata oluştu: {e}", 500

        finally:
            if cur:
                cur.close()
            if conn:
                conn.close()

    return render_template(
        'admin/arac-ekle.html',
        active_page='otobus_yonetimi'
    )


@app.route('/admin/arac/<int:otobus_id>')
@admin_required
def admin_arac_detay(otobus_id):
    conn = None
    cur = None

    try:
        conn = get_db_connection()
        cur = conn.cursor()

        cur.execute("""
            SELECT 
                otobus_id,
                plaka,
                marka,
                model,
                kapasite,
                kilometre,
                yogunluk,
                durum,
                kamera_yolu,
                son_goruntu_zamani,
                yolcu_sayisi,
                doluluk_orani
            FROM public.otobusler
            WHERE otobus_id = %s
        """, (otobus_id,))

        row = cur.fetchone()

        if not row:
            return "Araç bulunamadı", 404

        arac = {
            'otobus_id': row[0],
            'plaka': row[1],
            'marka': row[2],
            'model': row[3],
            'kapasite': row[4],
            'kilometre': row[5],
            'yogunluk': row[6],
            'durum': row[7],
            'kamera_yolu': row[8],
            'son_goruntu_zamani': row[9],
            'yolcu_sayisi': row[10],
            'doluluk_orani': row[11]
        }

        return render_template(
            'admin/arac-detay.html',
            active_page='otobus_yonetimi',
            arac=arac
        )

    except Exception as e:
        return f"Araç detay yüklenirken hata oluştu: {e}", 500

    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


@app.route('/admin/arac-duzenle/<int:otobus_id>', methods=['GET', 'POST'])
@admin_required
def admin_arac_duzenle(otobus_id):
    conn = None
    cur = None

    try:
        conn = get_db_connection()
        cur = conn.cursor()

        if request.method == 'POST':
            plaka = request.form.get('plaka')
            marka = request.form.get('marka')
            model = request.form.get('model')
            kapasite = request.form.get('kapasite')
            kilometre = request.form.get('kilometre')
            durum = request.form.get('durum')
            yogunluk = request.form.get('yogunluk')
            kamera_yolu = request.form.get('kamera_yolu')
            yolcu_sayisi = request.form.get('yolcu_sayisi')
            doluluk_orani = request.form.get('doluluk_orani')

            yolcu_sayisi = yolcu_sayisi if yolcu_sayisi else None
            doluluk_orani = doluluk_orani if doluluk_orani else None

            cur.execute("""
                UPDATE public.otobusler
                SET 
                    plaka = %s,
                    marka = %s,
                    model = %s,
                    kapasite = %s,
                    kilometre = %s,
                    durum = %s,
                    yogunluk = %s,
                    kamera_yolu = %s,
                    yolcu_sayisi = %s,
                    doluluk_orani = %s
                WHERE otobus_id = %s
            """, (
                plaka,
                marka,
                model,
                kapasite,
                kilometre,
                durum,
                yogunluk,
                kamera_yolu,
                yolcu_sayisi,
                doluluk_orani,
                otobus_id
            ))

            conn.commit()
            flash("Araç bilgileri başarıyla güncellendi.", "success")
            return redirect(url_for('admin_arac_detay', otobus_id=otobus_id))

        cur.execute("""
            SELECT 
                otobus_id,
                plaka,
                marka,
                model,
                kapasite,
                kilometre,
                yogunluk,
                durum,
                kamera_yolu,
                son_goruntu_zamani,
                yolcu_sayisi,
                doluluk_orani
            FROM public.otobusler
            WHERE otobus_id = %s
        """, (otobus_id,))

        row = cur.fetchone()

        if not row:
            return "Araç bulunamadı", 404

        arac = {
            'otobus_id': row[0],
            'plaka': row[1],
            'marka': row[2],
            'model': row[3],
            'kapasite': row[4],
            'kilometre': row[5],
            'yogunluk': row[6],
            'durum': row[7],
            'kamera_yolu': row[8],
            'son_goruntu_zamani': row[9],
            'yolcu_sayisi': row[10],
            'doluluk_orani': row[11]
        }

        return render_template(
            'admin/arac-duzenle.html',
            active_page='otobus_yonetimi',
            arac=arac
        )

    except Exception as e:
        if conn:
            conn.rollback()

        return f"Araç düzenlenirken hata oluştu: {e}", 500

    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


@app.route('/admin/araclar/excel')
@admin_required
def admin_araclar_excel():
    conn = None

    try:
        conn = get_db_connection()

        query = """
            SELECT 
                otobus_id,
                plaka,
                marka,
                model,
                kapasite,
                kilometre,
                yogunluk,
                durum,
                kamera_yolu,
                son_goruntu_zamani,
                yolcu_sayisi,
                doluluk_orani
            FROM public.otobusler
            ORDER BY otobus_id ASC
        """

        df = pd.read_sql(query, conn)

        dosya_yolu = os.path.join(EXPORT_DIR, 'otobusler_listesi.xlsx')
        df.to_excel(dosya_yolu, index=False)

        return send_file(dosya_yolu, as_attachment=True)

    except Exception as e:
        return f"Araç Excel oluşturulurken hata oluştu: {e}", 500

    finally:
        if conn:
            conn.close()


@app.route('/admin/arac-sil/<int:otobus_id>')
@admin_required
def admin_arac_sil(otobus_id):
    conn = None
    cur = None

    try:
        conn = get_db_connection()
        cur = conn.cursor()

        cur.execute("""
            DELETE FROM public.otobusler
            WHERE otobus_id = %s
        """, (otobus_id,))

        conn.commit()
        flash("Araç başarıyla silindi.", "success")
        return redirect(url_for('admin_araclar'))

    except Exception as e:
        if conn:
            conn.rollback()

        return f"Araç silinirken hata oluştu: {e}", 500

    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()

# --------------------------------------------------
# DUYURU DETAY
# --------------------------------------------------

@app.route('/duyuru/<int:duyuru_id>')
def public_duyuru_detay(duyuru_id):
    conn = None
    cur = None

    try:
        conn = get_db_connection()
        cur = conn.cursor()

        cur.execute("""
            SELECT duyuru_id, baslik, aciklama, gorsel_yolu, video_yolu, yayin_durumu, created_at
            FROM duyurular
            WHERE duyuru_id = %s AND yayin_durumu = TRUE
        """, (duyuru_id,))

        row = cur.fetchone()

        if not row:
            return "Duyuru bulunamadı", 404

        duyuru = {
            "duyuru_id": row[0],
            "baslik": row[1],
            "aciklama": row[2],
            "gorsel_yolu": row[3],
            "video_yolu": row[4],
            "yayin_durumu": row[5],
            "created_at": row[6]
        }

        return render_template(
            "pages/duyuru-detay.html",
            duyuru=duyuru
        )

    except Exception as e:
        return f"Duyuru detay yüklenirken hata oluştu: {e}", 500

    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


# --------------------------------------------------
# ADMIN DUYURULAR
# --------------------------------------------------

@app.route('/admin/duyurular')
@admin_required
def admin_duyurular():
    conn = None
    cur = None

    try:
        conn = get_db_connection()
        cur = conn.cursor()

        cur.execute("""
            SELECT duyuru_id, baslik, aciklama, gorsel_yolu, video_yolu, yayin_durumu, created_at
            FROM duyurular
            ORDER BY created_at DESC
        """)

        rows = cur.fetchall()

        duyurular = []
        for row in rows:
            duyurular.append({
                "duyuru_id": row[0],
                "baslik": row[1],
                "aciklama": row[2],
                "gorsel_yolu": row[3],
                "video_yolu": row[4],
                "yayin_durumu": row[5],
                "created_at": row[6]
            })

        return render_template(
            'admin/duyurular.html',
            active_page='duyurular',
            duyurular=duyurular
        )

    except Exception as e:
        return f"Duyurular yüklenirken hata oluştu: {e}", 500

    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


@app.route('/admin/duyuru-ekle', methods=['GET', 'POST'])
@admin_required
def admin_duyuru_ekle():
    if request.method == 'POST':
        baslik = request.form.get('baslik')
        aciklama = request.form.get('aciklama')
        yayin_durumu = True if request.form.get('yayin_durumu') == 'true' else False

        gorsel_yolu = None
        video_yolu = None

        gorsel = request.files.get('gorsel')
        video = request.files.get('video')

        if gorsel and gorsel.filename != "":
            gorsel_adi = secure_filename(gorsel.filename)
            gorsel_kayit_yolu = os.path.join(DUYURU_UPLOAD_FOLDER, gorsel_adi)
            gorsel.save(gorsel_kayit_yolu)
            gorsel_yolu = f"image/duyurular/{gorsel_adi}"

        if video and video.filename != "":
            video_adi = secure_filename(video.filename)
            video_kayit_yolu = os.path.join(DUYURU_UPLOAD_FOLDER, video_adi)
            video.save(video_kayit_yolu)
            video_yolu = f"image/duyurular/{video_adi}"

        conn = None
        cur = None

        try:
            conn = get_db_connection()
            cur = conn.cursor()

            cur.execute("""
                INSERT INTO duyurular
                (baslik, aciklama, gorsel_yolu, video_yolu, yayin_durumu)
                VALUES (%s, %s, %s, %s, %s)
            """, (baslik, aciklama, gorsel_yolu, video_yolu, yayin_durumu))

            conn.commit()
            return redirect(url_for('admin_duyurular'))

        except Exception as e:
            if conn:
                conn.rollback()

            return f"Duyuru eklenirken hata oluştu: {e}", 500

        finally:
            if cur:
                cur.close()
            if conn:
                conn.close()

    return render_template(
        'admin/duyuru-ekle.html',
        active_page='duyurular'
    )


@app.route('/admin/duyuru-sil/<int:duyuru_id>')
@admin_required
def admin_duyuru_sil(duyuru_id):
    conn = None
    cur = None

    try:
        conn = get_db_connection()
        cur = conn.cursor()

        cur.execute("DELETE FROM duyurular WHERE duyuru_id = %s", (duyuru_id,))
        conn.commit()

        return redirect(url_for('admin_duyurular'))

    except Exception as e:
        if conn:
            conn.rollback()

        return f"Duyuru silinirken hata oluştu: {e}", 500

    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


# --------------------------------------------------
# OTHER ADMIN PAGES
# --------------------------------------------------

 # --------------------------------------------------
# ADMIN ŞOFÖRLER
# --------------------------------------------------

@app.route('/admin/soforler')
@admin_required
def admin_soforler():
    conn = None
    cur = None

    try:
        conn = get_db_connection()
        cur = conn.cursor()

        cur.execute("""
            SELECT 
                s.sofor_id,
                s.ad,
                s.soyad,
                s.telefon,
                s.ehliyet_no,
                s.durum,
                s.hat_id,
                h.hat_kodu,
                h.hat_adi,
                s.created_at
            FROM public.soforler s
            LEFT JOIN public.hatlar h ON h.hat_id = s.hat_id
            ORDER BY s.sofor_id ASC
        """)

        rows = cur.fetchall()

        soforler = []
        for row in rows:
            soforler.append({
                "sofor_id": row[0],
                "ad": row[1],
                "soyad": row[2],
                "telefon": row[3],
                "ehliyet_no": row[4],
                "durum": row[5],
                "hat_id": row[6],
                "hat_kodu": row[7],
                "hat_adi": row[8],
                "created_at": row[9]
            })

        return render_template(
            "admin/soforler.html",
            active_page="sofor_yonetimi",
            soforler=soforler
        )

    except Exception as e:
        return f"Şoförler yüklenirken hata oluştu: {e}", 500

    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


@app.route('/admin/sofor-ekle', methods=['GET', 'POST'])
@admin_required
def admin_sofor_ekle():
    conn = None
    cur = None

    try:
        conn = get_db_connection()
        cur = conn.cursor()

        if request.method == 'POST':
            ad = request.form.get('ad')
            soyad = request.form.get('soyad')
            telefon = request.form.get('telefon')
            ehliyet_no = request.form.get('ehliyet_no')
            durum = request.form.get('durum')
            hat_id = request.form.get('hat_id')

            if not ad or not soyad:
                flash("Ad ve soyad alanları zorunludur.", "warning")
                return redirect(url_for("admin_sofor_ekle"))

            hat_id = hat_id if hat_id else None

            cur.execute("""
                INSERT INTO public.soforler
                (ad, soyad, telefon, ehliyet_no, durum, hat_id)
                VALUES (%s, %s, %s, %s, %s, %s)
            """, (ad, soyad, telefon, ehliyet_no, durum, hat_id))

            conn.commit()
            flash("Şoför başarıyla eklendi.", "success")
            return redirect(url_for("admin_soforler"))

        cur.execute("""
            SELECT hat_id, hat_kodu, hat_adi
            FROM public.hatlar
            WHERE aktif = true
            ORDER BY 
                CASE 
                    WHEN hat_kodu ~ '^[0-9]+$' THEN CAST(hat_kodu AS INTEGER)
                    ELSE 9999
                END,
                hat_kodu ASC
        """)

        hatlar = cur.fetchall()

        return render_template(
            "admin/sofor-ekle.html",
            active_page="sofor_yonetimi",
            hatlar=hatlar
        )

    except Exception as e:
        if conn:
            conn.rollback()
        return f"Şoför eklenirken hata oluştu: {e}", 500

    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


@app.route('/admin/sofor/<int:sofor_id>')
@admin_required
def admin_sofor_detay(sofor_id):
    conn = None
    cur = None

    try:
        conn = get_db_connection()
        cur = conn.cursor()

        cur.execute("""
            SELECT 
                s.sofor_id,
                s.ad,
                s.soyad,
                s.telefon,
                s.ehliyet_no,
                s.durum,
                s.hat_id,
                h.hat_kodu,
                h.hat_adi,
                s.created_at
            FROM public.soforler s
            LEFT JOIN public.hatlar h ON h.hat_id = s.hat_id
            WHERE s.sofor_id = %s
        """, (sofor_id,))

        row = cur.fetchone()

        if not row:
            return "Şoför bulunamadı", 404

        sofor = {
            "sofor_id": row[0],
            "ad": row[1],
            "soyad": row[2],
            "telefon": row[3],
            "ehliyet_no": row[4],
            "durum": row[5],
            "hat_id": row[6],
            "hat_kodu": row[7],
            "hat_adi": row[8],
            "created_at": row[9]
        }

        return render_template(
            "admin/sofor-detay.html",
            active_page="sofor_yonetimi",
            sofor=sofor
        )

    except Exception as e:
        return f"Şoför detay yüklenirken hata oluştu: {e}", 500

    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


@app.route('/admin/sofor-duzenle/<int:sofor_id>', methods=['GET', 'POST'])
@admin_required
def admin_sofor_duzenle(sofor_id):
    conn = None
    cur = None

    try:
        conn = get_db_connection()
        cur = conn.cursor()

        if request.method == 'POST':
            ad = request.form.get('ad')
            soyad = request.form.get('soyad')
            telefon = request.form.get('telefon')
            ehliyet_no = request.form.get('ehliyet_no')
            durum = request.form.get('durum')
            hat_id = request.form.get('hat_id')

            hat_id = hat_id if hat_id else None

            cur.execute("""
                UPDATE public.soforler
                SET 
                    ad = %s,
                    soyad = %s,
                    telefon = %s,
                    ehliyet_no = %s,
                    durum = %s,
                    hat_id = %s
                WHERE sofor_id = %s
            """, (ad, soyad, telefon, ehliyet_no, durum, hat_id, sofor_id))

            conn.commit()
            flash("Şoför bilgileri başarıyla güncellendi.", "success")
            return redirect(url_for("admin_sofor_detay", sofor_id=sofor_id))

        cur.execute("""
            SELECT 
                sofor_id,
                ad,
                soyad,
                telefon,
                ehliyet_no,
                durum,
                hat_id,
                created_at
            FROM public.soforler
            WHERE sofor_id = %s
        """, (sofor_id,))

        row = cur.fetchone()

        if not row:
            return "Şoför bulunamadı", 404

        sofor = {
            "sofor_id": row[0],
            "ad": row[1],
            "soyad": row[2],
            "telefon": row[3],
            "ehliyet_no": row[4],
            "durum": row[5],
            "hat_id": row[6],
            "created_at": row[7]
        }

        cur.execute("""
            SELECT hat_id, hat_kodu, hat_adi
            FROM public.hatlar
            WHERE aktif = true
            ORDER BY 
                CASE 
                    WHEN hat_kodu ~ '^[0-9]+$' THEN CAST(hat_kodu AS INTEGER)
                    ELSE 9999
                END,
                hat_kodu ASC
        """)

        hatlar = cur.fetchall()

        return render_template(
            "admin/sofor-duzenle.html",
            active_page="sofor_yonetimi",
            sofor=sofor,
            hatlar=hatlar
        )

    except Exception as e:
        if conn:
            conn.rollback()
        return f"Şoför düzenlenirken hata oluştu: {e}", 500

    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


@app.route('/admin/sofor-sil/<int:sofor_id>')
@admin_required
def admin_sofor_sil(sofor_id):
    conn = None
    cur = None

    try:
        conn = get_db_connection()
        cur = conn.cursor()

        cur.execute("""
            DELETE FROM public.soforler
            WHERE sofor_id = %s
        """, (sofor_id,))

        conn.commit()
        flash("Şoför başarıyla silindi.", "success")
        return redirect(url_for("admin_soforler"))

    except Exception as e:
        if conn:
            conn.rollback()
        return f"Şoför silinirken hata oluştu: {e}", 500

    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


@app.route('/admin/sefer-ekle')
@admin_required
def admin_sefer_ekle():
    return render_template(
        'admin/sefer-saatleri-ekle.html',
        active_page='seferler'
    )


# --------------------------------------------------
# ADMIN KULLANICILAR
# --------------------------------------------------

@app.route('/admin/kullanicilar')
@admin_required
def admin_kullanicilar():
    conn = None
    cur = None

    try:
        conn = get_db_connection()
        cur = conn.cursor()

        cur.execute("""
            SELECT 
                u.user_id,
                u.name,
                u.surname,
                u.email,
                u.role_id,
                u.created_at,
                r.role_name
            FROM public.users u
            LEFT JOIN public.role r ON r.role_id = u.role_id
            ORDER BY u.user_id ASC
        """)

        rows = cur.fetchall()

        kullanicilar = []
        for row in rows:
            kullanicilar.append({
                "user_id": row[0],
                "name": row[1],
                "surname": row[2],
                "email": row[3],
                "role_id": row[4],
                "created_at": row[5],
                "role_name": row[6]
            })

        return render_template(
            "admin/kullanicilar.html",
            active_page="kullanicilar",
            kullanicilar=kullanicilar
        )

    except Exception as e:
        return f"Kullanıcılar yüklenirken hata oluştu: {e}", 500

    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()




# --------------------------------------------------
# TEST DB
# --------------------------------------------------

@app.route('/test-db')
def test_db():
    conn = None
    cur = None

    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT 1")

        return "Veritabanı bağlantısı başarılı!"

    except Exception as e:
        return f"Hata: {str(e)}"

    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


# --------------------------------------------------
# KAYIP EŞYA BAŞVURUSU
# --------------------------------------------------

@app.route("/kayip-esya-basvurusu", methods=["GET", "POST"])
def kayip_esya_basvurusu():
    if request.method == "POST":
        ad_soyad = request.form.get("ad_soyad")
        telefon = request.form.get("telefon")
        email = request.form.get("email")
        esya_turu = request.form.get("esya_turu")
        hat_bilgisi = request.form.get("hat_bilgisi")
        kayip_tarihi = request.form.get("kayip_tarihi")
        aciklama = request.form.get("aciklama")

        conn = None
        cur = None

        try:
            conn = get_db_connection()
            cur = conn.cursor()

            cur.execute("""
                INSERT INTO kayip_esya_basvurulari
                (ad_soyad, telefon, email, esya_turu, hat_bilgisi, kayip_tarihi, aciklama)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
            """, (
                ad_soyad,
                telefon,
                email,
                esya_turu,
                hat_bilgisi,
                kayip_tarihi if kayip_tarihi else None,
                aciklama
            ))

            conn.commit()

            flash("Kayıp eşya başvurunuz başarıyla alınmıştır.", "success")
            return redirect(url_for("kayip_esya_basvurusu"))

        except Exception as e:
            if conn:
                conn.rollback()

            return f"Kayıp eşya başvurusu kaydedilirken hata oluştu: {e}", 500

        finally:
            if cur:
                cur.close()
            if conn:
                conn.close()

    return render_template("pages/kayip_esya_basvurusu.html")

#---------------------------------------------------
#   Bize Ulaşım
#---------------------------------------------------
@app.route("/bize-ulasin", methods=["GET", "POST"])
def bize_ulasin():
    secili_tur = request.args.get("tur", "")

    if request.method == "POST":
        ad_soyad = request.form.get("ad_soyad")
        email = request.form.get("email")
        telefon = request.form.get("telefon")
        basvuru_turu = request.form.get("basvuru_turu")
        konu = request.form.get("konu")
        mesaj = request.form.get("mesaj")

        if not ad_soyad or not basvuru_turu or not konu or not mesaj:
            flash("Lütfen zorunlu alanları doldurunuz.", "warning")
            return redirect(url_for("bize_ulasin"))

        conn = get_db_connection()
        cur = conn.cursor()

        cur.execute("""
            INSERT INTO sikayet_talepler
            (ad_soyad, email, telefon, basvuru_turu, konu, mesaj)
            VALUES (%s, %s, %s, %s, %s, %s)
        """, (
            ad_soyad,
            email,
            telefon,
            basvuru_turu,
            konu,
            mesaj
        ))

        conn.commit()
        cur.close()
        conn.close()

        flash("Başvurunuz başarıyla alınmıştır. En kısa sürede değerlendirilecektir.", "success")
        return redirect(url_for("bize_ulasin"))

    return render_template("pages/bize_ulasin.html", secili_tur=secili_tur)
# ==============================
# ADMIN - ŞİKAYET / TALEP YÖNETİMİ
# ==============================
@app.route('/admin/sikayet-talep')
@admin_required
def admin_sikayet_talep():
    return redirect(url_for("admin_sikayet_talepler"))

@app.route("/admin/sikayet-talepler")
@admin_required
def admin_sikayet_talepler():
    tur = request.args.get("tur", "Tümü")
    durum = request.args.get("durum", "Tümü")

    if tur == "":
        tur = "Tümü"

    if durum == "":
        durum = "Tümü"

    conn = None
    cur = None

    try:
        conn, cur = get_dict_cursor()

        query = """
            SELECT 
                id,
                ad_soyad,
                email,
                telefon,
                basvuru_turu,
                konu,
                mesaj,
                durum,
                admin_notu,
                created_at
            FROM public.sikayet_talepler
            WHERE 1=1
        """

        params = []

        if tur != "Tümü":
            query += " AND basvuru_turu = %s"
            params.append(tur)

        if durum != "Tümü":
            query += " AND durum = %s"
            params.append(durum)

        query += " ORDER BY created_at DESC, id DESC"

        cur.execute(query, params)
        basvurular = cur.fetchall()

        return render_template(
            "admin/sikayet_talepler.html",
            active_page="sikayet_talep",
            basvurular=basvurular,
            secili_tur=tur,
            secili_durum=durum
        )

    except Exception as e:
        return f"Şikayet / talep kayıtları yüklenirken hata oluştu: {e}", 500

    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()

@app.route("/admin/sikayet-talepler/<int:basvuru_id>", methods=["GET", "POST"])
@admin_required
def admin_sikayet_talep_detay(basvuru_id):
    conn = None
    cur = None

    try:
        conn, cur = get_dict_cursor()

        if request.method == "POST":
            durum = request.form.get("durum")
            admin_notu = request.form.get("admin_notu")

            cur.execute("""
                UPDATE public.sikayet_talepler
                SET durum = %s,
                    admin_notu = %s
                WHERE id = %s
            """, (durum, admin_notu, basvuru_id))

            conn.commit()

            flash("Başvuru durumu başarıyla güncellendi.", "success")
            return redirect(url_for("admin_sikayet_talep_detay", basvuru_id=basvuru_id))

        cur.execute("""
            SELECT 
                id,
                ad_soyad,
                email,
                telefon,
                basvuru_turu,
                konu,
                mesaj,
                durum,
                admin_notu,
                created_at
            FROM public.sikayet_talepler
            WHERE id = %s
        """, (basvuru_id,))

        basvuru = cur.fetchone()

        if not basvuru:
            flash("Başvuru bulunamadı.", "warning")
            return redirect(url_for("admin_sikayet_talepler"))

        return render_template(
            "admin/sikayet_talep_detay.html",
            active_page="sikayet_talep",
            basvuru=basvuru
        )

    except Exception as e:
        if conn:
            conn.rollback()

        return f"Şikayet / talep detay yüklenirken hata oluştu: {e}", 500

    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()



@app.route("/admin/sikayet-talepler/<int:basvuru_id>/sil", methods=["POST"])
@admin_required
def admin_sikayet_talep_sil(basvuru_id):
    conn = None
    cur = None

    try:
        conn = get_db_connection()
        cur = conn.cursor()

        cur.execute("""
            DELETE FROM public.sikayet_talepler
            WHERE id = %s
        """, (basvuru_id,))

        conn.commit()

        flash("Başvuru başarıyla silindi.", "success")
        return redirect(url_for("admin_sikayet_talepler"))

    except Exception as e:
        if conn:
            conn.rollback()

        return f"Başvuru silinirken hata oluştu: {e}", 500

    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()



# ==============================
# ADMIN - SEFERLER
# ==============================

@app.route("/admin/seferler")
@admin_required
def admin_seferler():
    conn = None
    cur = None

    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        cur.execute("""
            SELECT 
                h.hat_id,
                h.hat_kodu,
                h.hat_adi,
                h.aktif,

                COUNT(s.sefer_id) AS toplam_sefer,

                COUNT(CASE WHEN s.yon = 'Gidiş' THEN 1 END) AS gidis_sayisi,
                COUNT(CASE WHEN s.yon = 'Dönüş' THEN 1 END) AS donus_sayisi,

                COUNT(CASE WHEN s.gun_tipi = 'Hafta İçi' THEN 1 END) AS hafta_ici_sayisi,

                COUNT(
                    CASE 
                        WHEN s.gun_tipi IN ('Hafta Sonu', 'Cumartesi', 'Pazar') THEN 1 
                    END
                ) AS hafta_sonu_sayisi,

                COUNT(CASE WHEN s.gun_tipi = 'Resmi Tatil' THEN 1 END) AS resmi_tatil_sayisi

            FROM public.hatlar h
            LEFT JOIN public.seferler s ON s.hat_id = h.hat_id
            WHERE h.aktif = TRUE
            GROUP BY h.hat_id, h.hat_kodu, h.hat_adi, h.aktif
            ORDER BY 
                CASE 
                    WHEN h.hat_kodu ~ '^[0-9]+$' THEN CAST(h.hat_kodu AS INTEGER)
                    ELSE 9999
                END,
                h.hat_kodu ASC
        """)

        hatlar = cur.fetchall()

        return render_template(
            "admin/seferler.html",
            active_page="seferler",
            hatlar=hatlar
        )

    except Exception as e:
        return f"Sefer yönetimi yüklenirken hata oluştu: {e}", 500

    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


@app.route("/admin/seferler/hat/<int:hat_id>", methods=["GET", "POST"])
@admin_required
def admin_sefer_hat_detay(hat_id):
    conn = None
    cur = None

    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        # 1) Hat bilgisi
        cur.execute("""
            SELECT 
                hat_id,
                hat_kodu,
                hat_adi,
                aktif
            FROM public.hatlar
            WHERE hat_id = %s
        """, (hat_id,))

        hat = cur.fetchone()

        if not hat:
            flash("Hat bulunamadı.", "warning")
            return redirect(url_for("admin_seferler"))

        # 2) Yeni sefer ekleme
        if request.method == "POST":
            gun_tipi = request.form.get("gun_tipi")
            yon = request.form.get("yon")
            saat = request.form.get("saat")

            if not gun_tipi or not yon or not saat:
                flash("Lütfen gün tipi, yön ve saat alanlarını doldurunuz.", "warning")
                return redirect(url_for("admin_sefer_hat_detay", hat_id=hat_id))

            # Bizim sistemde sadece bu 3 gün tipi kullanılacak.
            izinli_gun_tipleri = ["Hafta İçi", "Hafta Sonu", "Resmi Tatil"]
            izinli_yonler = ["Gidiş", "Dönüş"]

            if gun_tipi not in izinli_gun_tipleri:
                flash("Geçersiz gün tipi seçildi.", "warning")
                return redirect(url_for("admin_sefer_hat_detay", hat_id=hat_id))

            if yon not in izinli_yonler:
                flash("Geçersiz yön seçildi.", "warning")
                return redirect(url_for("admin_sefer_hat_detay", hat_id=hat_id))

            cur.execute("""
                INSERT INTO public.seferler
                (hat_id, gun_tipi, yon, saat)
                VALUES (%s, %s, %s, %s)
            """, (hat_id, gun_tipi, yon, saat))

            conn.commit()

            flash("Sefer başarıyla eklendi.", "success")
            return redirect(url_for("admin_sefer_hat_detay", hat_id=hat_id))

        # 3) Bu hatta ait seferleri çek
        cur.execute("""
            SELECT 
                sefer_id,
                hat_id,
                gun_tipi,
                yon,
                saat
            FROM public.seferler
            WHERE hat_id = %s
            ORDER BY 
                CASE
                    WHEN gun_tipi = 'Hafta İçi' THEN 1
                    WHEN gun_tipi = 'Hafta Sonu' THEN 2
                    WHEN gun_tipi = 'Cumartesi' THEN 2
                    WHEN gun_tipi = 'Pazar' THEN 2
                    WHEN gun_tipi = 'Resmi Tatil' THEN 3
                    ELSE 4
                END,
                CASE
                    WHEN yon = 'Gidiş' THEN 1
                    WHEN yon = 'Dönüş' THEN 2
                    ELSE 3
                END,
                saat ASC
        """, (hat_id,))

        seferler = cur.fetchall()

        # 4) Seferleri kullanıcı tarafındaki sistemle aynı şekilde gruplandır
        # Sadece 3 sekme olacak:
        # Hafta İçi | Hafta Sonu | Resmi Tatil
        sefer_gruplu = {
            "Hafta İçi": {
                "Gidiş": [],
                "Dönüş": []
            },
            "Hafta Sonu": {
                "Gidiş": [],
                "Dönüş": []
            },
            "Resmi Tatil": {
                "Gidiş": [],
                "Dönüş": []
            }
        }

        for sefer in seferler:
            gun = sefer["gun_tipi"]
            yon = sefer["yon"]

            # Eski verilerde Cumartesi / Pazar varsa Hafta Sonu altında göster.
            if gun in ["Cumartesi", "Pazar"]:
                gun = "Hafta Sonu"

            # Beklenmeyen gün tipi varsa Resmi Tatil altında göster.
            if gun not in sefer_gruplu:
                gun = "Resmi Tatil"

            # Beklenmeyen yön varsa listeye alma.
            if yon not in ["Gidiş", "Dönüş"]:
                continue

            saat = sefer["saat"]

            if hasattr(saat, "strftime"):
                saat = saat.strftime("%H:%M")

            sefer["saat_formatli"] = saat
            sefer_gruplu[gun][yon].append(sefer)

        # 5) Saatleri kendi içinde sırala
        for gun in sefer_gruplu:
            sefer_gruplu[gun]["Gidiş"].sort(key=lambda x: x["saat_formatli"])
            sefer_gruplu[gun]["Dönüş"].sort(key=lambda x: x["saat_formatli"])

        return render_template(
            "admin/sefer_hat_detay.html",
            active_page="seferler",
            hat=hat,
            sefer_gruplu=sefer_gruplu
        )

    except Exception as e:
        if conn:
            conn.rollback()

        return f"Sefer hat detay yüklenirken hata oluştu: {e}", 500

    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


@app.route("/admin/seferler/<int:sefer_id>/sil", methods=["POST"])
@admin_required
def admin_sefer_sil(sefer_id):
    conn = None
    cur = None

    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        # Silmeden önce hat_id alıyoruz.
        # Böylece sildikten sonra aynı hattın detay sayfasına döneceğiz.
        cur.execute("""
            SELECT 
                sefer_id,
                hat_id
            FROM public.seferler
            WHERE sefer_id = %s
        """, (sefer_id,))

        sefer = cur.fetchone()

        if not sefer:
            flash("Sefer bulunamadı.", "warning")
            return redirect(url_for("admin_seferler"))

        hat_id = sefer["hat_id"]

        cur.execute("""
            DELETE FROM public.seferler
            WHERE sefer_id = %s
        """, (sefer_id,))

        conn.commit()

        flash("Sefer başarıyla silindi.", "success")
        return redirect(url_for("admin_sefer_hat_detay", hat_id=hat_id))

    except Exception as e:
        if conn:
            conn.rollback()

        return f"Sefer silinirken hata oluştu: {e}", 500

    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()
# --------------------------------------------------
# RUN
# --------------------------------------------------

if __name__ == '__main__':
    app.run(host='127.0.0.1', port=5001, debug=True)