import io
from flask import Flask, render_template, redirect, url_for, flash, request
from extensiones import db
from flask_login import LoginManager, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from formularios import FormularioRegistro, FormularioInicioSesion, FormularioCategoria, FormularioTransaccion
from modelos import Transaccion, Categoria, Usuario
from datetime import datetime
import numpy as np  
from flask_mail import Mail, Message
from utils import generar_token, verificar_token
import os
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
from flask import send_file
import io
# ================================
# APP CONFIG
# ================================
app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'mysql+pymysql://root:@localhost/finansmart'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SECRET_KEY'] = 'secreto2'
app.config['MAIL_ASCII_ATTACHMENTS'] = False

db.init_app(app)

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

# ================================
# MAIL CONFIG
# ================================
app.config['MAIL_SERVER'] = 'smtp.gmail.com'
app.config['MAIL_PORT'] = 587
app.config['MAIL_USE_TLS'] = True
app.config['MAIL_USERNAME'] = 'facundo.marin.moscol@cftmail.cl'
app.config['MAIL_PASSWORD'] = 'zjan tkgy unuw zpeo'  # usa contraseña de app
app.config['MAIL_DEFAULT_SENDER'] = ('Finansmarrt', 'facundo.marin.moscol@cftmail.cl')
mail = Mail(app)



@app.route('/guardar_meta', methods=['POST'])
@login_required
def guardar_meta():
    tipo = request.form.get("tipo_meta")
    meta = request.form.get("meta_ahorro", 0)

    try:
        meta = int(meta)
    except:
        flash("La meta debe ser un número válido.", "error")
        return redirect(url_for('panel'))

    if tipo == "mensual":
        current_user.meta_ahorro_mensual = meta
        current_user.tipo_meta = "mensual"
    else:
        current_user.meta_ahorro_anual = meta
        current_user.tipo_meta = "anual"

    current_user.notificado_ahorro = False
    db.session.commit()

    flash("✅ Meta actualizada", "success")
    return redirect(url_for('panel'))





# ================================
# USUARIO LOGIN
# ================================
@login_manager.user_loader
def cargar_usuario(usuario_id):
    return db.session.get(Usuario, int(usuario_id))

@app.route('/')
def home():
    return redirect(url_for('login'))

# ================================
# REGISTRO
# ================================
import os
from flask_mail import Message

@app.route('/registro', methods=['GET', 'POST'])
def registro():
    formulario = FormularioRegistro()
    if formulario.validate_on_submit():
        existente = Usuario.query.filter(
            (Usuario.nombre_usuario == formulario.nombre_usuario.data) |
            (Usuario.correo == formulario.correo.data)
        ).first()
        if existente:
            flash('El nombre de usuario o correo ya está registrado.', 'error')
            return render_template('registro.html', formulario=formulario)

        # Crear usuario
        clave_encriptada = generate_password_hash(formulario.contrasena.data)
        nuevo_usuario = Usuario(
            nombre_usuario=formulario.nombre_usuario.data,
            correo=formulario.correo.data,
            contrasena=clave_encriptada,
            activo=False
        )
        db.session.add(nuevo_usuario)
        db.session.commit()

        # Generar token
        token = generar_token(nuevo_usuario.correo)

        # Determinar dominio público
        ngrok_url = os.environ.get('NGROK_URL')  # si pones NGROK_URL en tu entorno, usa ese
        if ngrok_url:
            enlace = f"{ngrok_url}/activar/{token}"
        else:
            enlace = url_for('activar_cuenta', token=token, _external=True)

        # Usando template HTML
        html_correo = render_template('correo_activacion.html',
                                      nombre_usuario=nuevo_usuario.nombre_usuario,
                                      enlace=enlace)
        msg = Message('Activa tu cuenta - Finansmarrt', recipients=[nuevo_usuario.correo])
        msg.html = html_correo
        msg.charset = 'utf-8'  # Esto asegura que se envíe correctamente
        mail.send(msg)


        flash('Registro exitoso. Revisa tu correo para activar tu cuenta.', 'info')
        return redirect(url_for('login'))
    
    return render_template('registro.html', formulario=formulario)


# ================================
# ACTIVACION
# ================================
@app.route('/activar/<token>')
def activar_cuenta(token):
    correo = verificar_token(token)
    if not correo:
        flash('El enlace de activación no es válido o ha expirado.', 'error')
        return redirect(url_for('login'))

    usuario = Usuario.query.filter_by(correo=correo).first()
    if usuario:
        if usuario.activo:
            flash('Tu cuenta ya estaba activada.', 'info')
        else:
            usuario.activo = True
            db.session.commit()
            flash('Cuenta activada correctamente ✅. Ya puedes iniciar sesión.', 'success')
    else:
        flash('Usuario no encontrado.', 'error')

    return redirect(url_for('login'))

# ================================
# LOGIN / LOGOUT
# ================================
@app.route('/login', methods=['GET', 'POST'])
def login():
    formulario = FormularioInicioSesion()
    if formulario.validate_on_submit():
        usuario = Usuario.query.filter_by(correo=formulario.correo.data).first()
        if usuario and check_password_hash(usuario.contrasena, formulario.contrasena.data):
            if not usuario.activo:
                flash('Debes activar tu cuenta desde el correo que te enviamos.', 'warning')
                return redirect(url_for('login'))
            login_user(usuario)
            return redirect(url_for('panel'))
        flash('Correo o contraseña incorrectos.', 'error')
    return render_template('login.html', formulario=formulario)

@app.route('/cerrar_sesion')
@login_required
def cerrar_sesion():
    logout_user()
    return redirect(url_for('login'))
# ================================
# PANEL PRINCIPAL (reemplazar)
# ================================
@app.route('/panel')
@login_required
def panel():
    transacciones = Transaccion.query.filter_by(usuario_id=current_user.id).all()
    ingresos = int(sum(t.monto for t in transacciones if t.tipo == 'Ingreso'))
    egresos = int(sum(t.monto for t in transacciones if t.tipo == 'Egreso'))
    saldo = ingresos - egresos

    # Determinar qué meta usar (mensual o anual)
    tipo_meta = getattr(current_user, 'tipo_meta', 'mensual') or 'mensual'
    if tipo_meta == 'anual':
        meta = getattr(current_user, 'meta_ahorro_anual', 0) or 0
        # Si la meta anual está, calculamos progreso anual: puedes optar por comparar con ahorro anual,
        # pero aquí usamos saldo total como simplificación (ajusta si guardas ahorro por año).
    else:
        meta = getattr(current_user, 'meta_ahorro_mensual', 0) or 0

    ahorro_actual = saldo  # actualmente usas saldo global; si prefieres usar solo ingresos/egresos del mes, cambia aquí.

    # Porcentaje y faltante
    porcentaje_ahorro = 0
    faltante = 0
    if meta > 0:
        porcentaje_ahorro = int((ahorro_actual / meta) * 100) if meta else 0
        porcentaje_ahorro = max(0, min(porcentaje_ahorro, 100))
        faltante = max(meta - ahorro_actual, 0)
    else:
        porcentaje_ahorro = 0
        faltante = 0

    from collections import defaultdict

    # Categorías de gasto
    categorias_gasto = defaultdict(float)
    for t in transacciones:
        if t.tipo == 'Egreso' and t.categoria:
            categorias_gasto[t.categoria.nombre] += t.monto
    labels = list(categorias_gasto.keys())
    values = list(categorias_gasto.values())

    # Predicción siguiente mes
    gastos_por_mes = defaultdict(float)
    for t in transacciones:
        if t.tipo == 'Egreso':
            mes = t.fecha.strftime("%Y-%m")
            gastos_por_mes[mes] += t.monto

    prediccion = None
    alerta = None
    if len(gastos_por_mes) >= 2:
        meses_sorted = sorted(gastos_por_mes.keys())
        gastos_mensuales = np.array([gastos_por_mes[m] for m in meses_sorted])
        prediccion = int(np.mean(gastos_mensuales))

        mes_actual = datetime.now().strftime("%Y-%m")
        gasto_actual_mes = gastos_por_mes.get(mes_actual, 0)

        if gasto_actual_mes > prediccion * 1.5:
            alerta = f"¡Cuidado! Este mes has gastado ${gasto_actual_mes}, que es mayor al promedio histórico."

    # Envío de correo cuando se alcanza la meta (solo una vez)
    try:
        if meta > 0 and ahorro_actual >= meta and not getattr(current_user, 'notificado_ahorro', False):
            asunto = "🎉 ¡Meta alcanzada en Finansmarrt!"
            cuerpo = f"¡Felicitaciones {current_user.nombre_usuario}! Has alcanzado tu meta de ahorro ({tipo_meta}) de ${meta}.\n\nSaldo actual: ${ahorro_actual}"
            msg = Message(asunto, recipients=[current_user.correo])
            msg.body = cuerpo
            mail.send(msg)

            # Marcar como notificado para no repetir el email
            current_user.notificado_ahorro = True
            db.session.commit()
    except Exception as e:
        # No dejar que un fallo en el envío rompa la vista; loguea si quieres.
        print("Error al enviar email de meta alcanzada:", e)

    return render_template(
        'panel.html',
        ingresos=ingresos,
        egresos=egresos,
        saldo=saldo,
        labels=labels,
        values=values,
        prediccion=prediccion,
        alerta=alerta,
        meta=meta,
        tipo_meta=tipo_meta,
        ahorro_actual=ahorro_actual,
        porcentaje_ahorro=porcentaje_ahorro,
        faltante=faltante
    )

# ================================
# TRANSACCIONES
# ================================
@app.route('/transacciones')
@login_required
def listar_transacciones():
    transacciones = Transaccion.query.filter_by(usuario_id=current_user.id).all()
    return render_template('transacciones.html', transacciones=transacciones)

@app.route('/agregar_transaccion', methods=['GET', 'POST'])
@login_required
def agregar_transaccion():
    formulario = FormularioTransaccion()
    formulario.categoria.choices = [(c.id, c.nombre) for c in Categoria.query.filter_by(usuario_id=current_user.id).all()]

    if formulario.descripcion.data:
        desc = formulario.descripcion.data.lower()
        if "uber" in desc:
            auto = Categoria.query.filter_by(nombre="Transporte", usuario_id=current_user.id).first()
            if auto:
                formulario.categoria.data = auto.id
        elif "super" in desc or "mercado" in desc:
            auto = Categoria.query.filter_by(nombre="Comida", usuario_id=current_user.id).first()
            if auto:
                formulario.categoria.data = auto.id

    if formulario.validate_on_submit():
        nueva = Transaccion(
            monto=formulario.monto.data,
            tipo=formulario.tipo.data,
            categoria_id=formulario.categoria.data,
            fecha=formulario.fecha.data,
            descripcion=formulario.descripcion.data,
            usuario_id=current_user.id
        )
        db.session.add(nueva)
        db.session.commit()
        flash('Transacción agregada con éxito', 'success')
        return redirect(url_for('panel'))

    return render_template('agregar_transaccion.html', form=formulario)






@app.route('/transacciones/pdf')
@login_required
def transacciones_pdf():
    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=letter)
    width, height = letter

    transacciones = Transaccion.query.filter_by(usuario_id=current_user.id).all()

    y = height - 40
    c.setFont("Helvetica-Bold", 16)
    c.drawString(200, y, f"Transacciones de {current_user.nombre_usuario}")
    y -= 40
    c.setFont("Helvetica", 12)

    for t in transacciones:
        c.drawString(40, y, f"{t.fecha.strftime('%Y-%m-%d')} - {t.tipo} - ${t.monto} - {t.categoria.nombre if t.categoria else ''} - {t.descripcion}")
        y -= 20
        if y < 50:
            c.showPage()
            y = height - 40

    c.save()
    buffer.seek(0)
    return send_file(buffer, as_attachment=True, download_name="transacciones.pdf", mimetype='application/pdf')

@app.route('/transacciones/eliminar/<int:id>', methods=['POST'])
@login_required
def eliminar_transaccion(id):
    transaccion = Transaccion.query.get_or_404(id)
    if transaccion.usuario_id != current_user.id:
        flash("No tienes permiso para eliminar esta transacción.", "error")
        return redirect(url_for('listar_transacciones'))

    db.session.delete(transaccion)
    db.session.commit()
    flash("Transacción eliminada.", "success")
    return redirect(url_for('listar_transacciones'))

# ================================
# CATEGORÍAS
# ================================
@app.route('/categorias', methods=['GET', 'POST'])
@login_required
def categorias():
    form = FormularioCategoria()
    categorias = Categoria.query.filter_by(usuario_id=current_user.id).all()

    if form.validate_on_submit():
        existe = Categoria.query.filter_by(usuario_id=current_user.id, nombre=form.nombre.data).first()
        if existe:
            flash("Esa categoría ya existe.", "error")
            return redirect(url_for('categorias'))

        nueva = Categoria(nombre=form.nombre.data, usuario_id=current_user.id)
        db.session.add(nueva)
        db.session.commit()
        flash('Categoría agregada.', 'success')
        return redirect(url_for('categorias'))

    return render_template('categorias.html', form=form, categorias=categorias)
@app.route('/transacciones/editar/<int:id>', methods=['GET', 'POST'])
@login_required
def editar_transaccion(id):
    transaccion = Transaccion.query.get_or_404(id)
    if transaccion.usuario_id != current_user.id:
        flash("No tienes permiso para editar esta transacción.", "error")
        return redirect(url_for('listar_transacciones'))

    form = FormularioTransaccion(obj=transaccion)
    form.categoria.choices = [(c.id, c.nombre) for c in Categoria.query.filter_by(usuario_id=current_user.id).all()]

    if form.validate_on_submit():
        transaccion.monto = form.monto.data
        transaccion.tipo = form.tipo.data
        transaccion.categoria_id = form.categoria.data
        transaccion.fecha = form.fecha.data
        transaccion.descripcion = form.descripcion.data
        db.session.commit()
        flash("Transacción actualizada.", "success")
        return redirect(url_for('listar_transacciones'))

    return render_template('editar_transaccion.html', form=form)

@app.route('/categorias/editar/<int:id>', methods=['GET', 'POST'])
@login_required
def editar_categoria(id):
    categoria = Categoria.query.get_or_404(id)
    if categoria.usuario_id != current_user.id:
        flash("No tienes permiso para editar esta categoría.", "error")
        return redirect(url_for('categorias'))

    form = FormularioCategoria(obj=categoria)
    if form.validate_on_submit():
        categoria.nombre = form.nombre.data
        db.session.commit()
        flash("Categoría actualizada.", "success")
        return redirect(url_for('categorias'))

    return render_template('editar_categoria.html', form=form)

@app.route('/categorias/eliminar/<int:id>', methods=['POST'])
@login_required
def eliminar_categoria(id):
    categoria = Categoria.query.get_or_404(id)
    if categoria.usuario_id != current_user.id:
        flash("No tienes permiso para eliminar esta categoría.", "error")
        return redirect(url_for('categorias'))

    if categoria.transacciones:
        flash("No puedes eliminar una categoría con transacciones asociadas.", "error")
        return redirect(url_for('categorias'))

    db.session.delete(categoria)
    db.session.commit()
    flash("Categoría eliminada.", "success")
    return redirect(url_for('categorias'))

# ================================
# ARRANQUE
# ================================
if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(debug=True)
    
