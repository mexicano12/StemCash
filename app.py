import os
import pytz
from flask import Flask, render_template, request, redirect, url_for, flash, session
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from flask_migrate import Migrate
from sqlalchemy import func, cast, Date, extract, text
from datetime import datetime, date, timedelta
from werkzeug.utils import secure_filename

# --- 1. IMPORTACIÓN DE MODELOS ---
from models import db, Familia, Usuario, Movimiento, Categoria, Producto, MovimientoInventario, PagoPendiente

# --- 2. CONFIGURACIÓN DE RUTAS Y CARPETAS ---
basedir = os.path.abspath(os.path.dirname(__file__))
UPLOAD_FOLDER = os.path.join(basedir, 'static', 'uploads', 'productos')
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}

if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER, exist_ok=True)

app = Flask(__name__)

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# --- 3. CONFIGURACIÓN DE SEGURIDAD Y BD ---
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'stemcash_secret_2026_pro')

db_url = os.environ.get('DATABASE_URL')
if db_url and db_url.startswith("postgres://"):
    db_url = db_url.replace("postgres://", "postgresql://", 1)

app.config['SQLALCHEMY_DATABASE_URI'] = db_url or 'sqlite:///' + os.path.join(basedir, 'instance', 'stemcash.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

# --- 4. INICIALIZACIÓN DE EXTENSIONES ---
db.init_app(app)
migrate = Migrate(app, db)
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

@login_manager.user_loader
def load_user(user_id):
    return Usuario.query.get(int(user_id))

# 🚀 SINCRONIZACIÓN AUTOMÁTICA DE TABLAS AL INICIAR
with app.app_context():
    db.create_all()
    
    # Inicialización de datos base si la BD está vacía
    if not Familia.query.first():
        familia = Familia(nombre="Familia Pérez")
        db.session.add(familia)
        db.session.commit()
        
        nuevo_usuario = Usuario(
            nombre="Erick", 
            email="erick@test.com", 
            familia_id=familia.id
        )
        nuevo_usuario.set_password("12345")
        db.session.add(nuevo_usuario)
        
        cats_egreso = ['Comida', 'Servicios', 'Renta', 'Ocio', 'Transporte', 'Salud', 'Inventario', 'Despensa']
        cats_ingreso = ['Sueldo', 'Venta Ceravette', 'Venta StemRare', 'Regalo', 'Otros']
        
        for c in cats_egreso:
            db.session.add(Categoria(nombre=c, tipo='egreso', familia_id=familia.id))
        for c in cats_ingreso:
            db.session.add(Categoria(nombre=c, tipo='ingreso', familia_id=familia.id))

        db.session.commit()
        print("✅ Base de datos inicializada correctamente.")

# --- 5. RUTAS DEL DASHBOARD Y REGISTRO ---

@app.route('/')
@login_required
def dashboard():
    f_id = current_user.familia_id
    zona_mx = pytz.timezone('America/Mexico_City')
    ahora_mx = datetime.now(zona_mx)
    hoy_date = ahora_mx.date()
    
    inicio_semana = hoy_date - timedelta(days=hoy_date.weekday())
    inicio_mes = hoy_date.replace(day=1)

    # Balances Totales
    ingresos_totales = db.session.query(func.sum(Movimiento.monto)).filter(
        Movimiento.familia_id == f_id, Movimiento.tipo == 'ingreso').scalar() or 0
    gastos_totales = db.session.query(func.sum(Movimiento.monto)).filter(
        Movimiento.familia_id == f_id, Movimiento.tipo == 'egreso').scalar() or 0
    balance = ingresos_totales - gastos_totales

    # Cálculos Temporales (CORREGIDOS PARA POSTGRES/SQLITE)
    gastado_hoy = db.session.query(func.sum(Movimiento.monto)).filter(
        Movimiento.familia_id == f_id, Movimiento.tipo == 'egreso',
        cast(Movimiento.fecha, Date) == hoy_date).scalar() or 0

    gastado_semana = db.session.query(func.sum(Movimiento.monto)).filter(
        Movimiento.familia_id == f_id, Movimiento.tipo == 'egreso',
        cast(Movimiento.fecha, Date) >= inicio_semana).scalar() or 0

    ingresos_mes = db.session.query(func.sum(Movimiento.monto)).filter(
        Movimiento.familia_id == f_id, Movimiento.tipo == 'ingreso',
        cast(Movimiento.fecha, Date) >= inicio_mes).scalar() or 0
    
    gastos_mes = db.session.query(func.sum(Movimiento.monto)).filter(
        Movimiento.familia_id == f_id, Movimiento.tipo == 'egreso',
        cast(Movimiento.fecha, Date) >= inicio_mes).scalar() or 0

    # Inventario y Ganancias
    productos = Producto.query.filter_by(familia_id=f_id).all()
    valor_inventario_calculado = sum((p.stock or 0) * (p.precio_compra or 0) for p in productos)

    ventas_hoy = MovimientoInventario.query.join(Producto).filter(
        MovimientoInventario.tipo.ilike('salida'),
        Producto.familia_id == f_id,
        cast(MovimientoInventario.fecha, Date) == hoy_date).all()

    ganancia_hoy = sum(v.monto_total - ((v.producto.precio_compra or 0) * v.cantidad) for v in ventas_hoy)

    pendientes = PagoPendiente.query.filter_by(familia_id=f_id, estatus='pendiente').order_by(PagoPendiente.fecha_limite.asc()).all()
    movimientos = Movimiento.query.filter_by(familia_id=f_id).order_by(Movimiento.id.desc()).limit(10).all()
    categorias = Categoria.query.filter_by(familia_id=f_id).all()

    return render_template('dashboard.html', 
                           balance_total=balance, ingresos_mes=ingresos_mes, gastos_mes=gastos_mes,
                           gastado_hoy=gastado_hoy, gastado_semana=gastado_semana,
                           valor_inventario=valor_inventario_calculado, ganancia_hoy=ganancia_hoy,
                           num_ventas=len(ventas_hoy), user=current_user, movimientos=movimientos,
                           categorias=categorias, pendientes=pendientes, total_deuda=sum(p.monto for p in pendientes))

@app.route('/registrar', methods=['POST'])
@login_required
def registrar():
    cat_id_raw = request.form.get('categoria_id')
    nombre_nueva = request.form.get('nombre_nueva_cat')
    tipo = request.form.get('tipo')
    descripcion = request.form.get('descripcion')
    
    try:
        cant = float(request.form.get('cantidad') or 1)
        p_unitario = float(request.form.get('precio_u') or 0)
        monto_manual = request.form.get('monto')
        monto_total = float(monto_manual) if monto_manual and float(monto_manual) > 0 else (cant * p_unitario)
    except ValueError:
        monto_total = 0; cant = 1; p_unitario = 0

    final_cat_id = None
    if cat_id_raw == 'nueva' and nombre_nueva:
        nueva_cat = Categoria(nombre=nombre_nueva, tipo=tipo, familia_id=current_user.familia_id)
        db.session.add(nueva_cat); db.session.commit()
        final_cat_id = nueva_cat.id
    elif cat_id_raw and str(cat_id_raw).isdigit():
        final_cat_id = int(cat_id_raw)

    nuevo_movimiento = Movimiento(
        tipo=tipo, cantidad=cant, precio_unitario=p_unitario, monto=monto_total,
        descripcion=descripcion, categoria_id=final_cat_id,
        familia_id=current_user.familia_id, usuario_id=current_user.id
    )
    db.session.add(nuevo_movimiento); db.session.commit()
    return redirect(url_for('dashboard'))

# --- 6. RUTAS DE INVENTARIO Y VENTAS ---

@app.route('/inventario')
@login_required
def inventario():
    productos = Producto.query.filter_by(familia_id=current_user.familia_id).all()
    valor_total_stock = sum(p.stock * p.precio_compra for p in productos)
    ganancia_potencial = sum(p.stock * (p.precio_venta - p.precio_compra) for p in productos)
    categorias = Categoria.query.filter_by(tipo='egreso', familia_id=current_user.familia_id).all()
    return render_template('inventario.html', productos=productos, valor_total_stock=valor_total_stock,
                           ganancia_potencial=ganancia_potencial, categorias=categorias, user=current_user)

@app.route('/crear_producto', methods=['POST'])
@login_required
def crear_producto():
    imagen_nombre = 'default_product.png'
    if 'imagen' in request.files:
        file = request.files['imagen']
        if file and file.filename != '' and allowed_file(file.filename):
            filename = f"{datetime.now().strftime('%Y%m%d%H%M%S')}_{secure_filename(file.filename)}"
            file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
            imagen_nombre = filename

    nuevo_prod = Producto(
        nombre=request.form.get('nombre'), descripcion=request.form.get('descripcion'),
        categoria_prod=request.form.get('categoria_prod') or "General", plataforma=request.form.get('plataforma'),
        stock=float(request.form.get('stock') or 0), precio_compra=float(request.form.get('precio_compra') or 0),
        precio_venta=float(request.form.get('precio_venta') or 0), imagen_url=imagen_nombre,
        usuario_id=current_user.id, familia_id=current_user.familia_id
    )
    db.session.add(nuevo_prod); db.session.commit()
    return redirect(url_for('inventario'))

@app.route('/vender_producto', methods=['POST'])
@login_required
def vender_producto():
    prod_id = request.form.get('producto_id')
    try:
        cantidad_vender = float(request.form.get('cantidad') or 0)
        precio_venta_real = float(request.form.get('precio_venta') or 0)
    except ValueError: return redirect(url_for('inventario'))
    
    producto = Producto.query.get(prod_id)
    cat_venta = Categoria.query.filter_by(nombre="Venta", familia_id=current_user.familia_id).first()
    
    if producto and producto.stock >= cantidad_vender:
        producto.stock = round(producto.stock - cantidad_vender, 3)
        monto_total_venta = precio_venta_real * cantidad_vender
        
        db.session.add(Movimiento(tipo='ingreso', monto=monto_total_venta, familia_id=current_user.familia_id,
                                  usuario_id=current_user.id, categoria_id=cat_venta.id if cat_venta else None,
                                  descripcion=f"💰 Venta: {producto.nombre} ({cantidad_vender} kg/pzs)"))
        db.session.add(MovimientoInventario(producto_id=producto.id, tipo='SALIDA', cantidad=cantidad_vender, monto_total=monto_total_venta))
        db.session.commit()
    return redirect(url_for('ventas'))

@app.route('/ventas')
@login_required
def ventas():
    productos = Producto.query.filter_by(familia_id=current_user.familia_id).filter(Producto.stock > 0).all()
    historial = MovimientoInventario.query.join(Producto).filter(
        MovimientoInventario.tipo == 'SALIDA', Producto.familia_id == current_user.familia_id
    ).order_by(MovimientoInventario.fecha.desc()).all()
    ganancia_total = sum((m.monto_total - (m.producto.precio_compra * m.cantidad)) for m in historial if m.producto)
    return render_template('ventas.html', productos=productos, historial=historial, ganancia_total=ganancia_total, user=current_user)

@app.route('/compras')
@login_required
def compras():
    productos = Producto.query.filter_by(familia_id=current_user.familia_id).all()
    historial = MovimientoInventario.query.join(Producto).filter(
        MovimientoInventario.tipo == 'ENTRADA', Producto.familia_id == current_user.familia_id
    ).order_by(MovimientoInventario.fecha.desc()).all()
    valor_total_stock = sum(p.stock * p.precio_compra for p in productos)
    return render_template('compras.html', productos=productos, historial=historial, valor_total_stock=valor_total_stock, user=current_user)

# --- 7. REPORTES E HISTORIAL (CORREGIDOS) ---

@app.route('/reportes')
@login_required
def reportes():
    f_id = current_user.familia_id
    
    # Gráfica de Gastos por Categoría
    gastos_cat = db.session.query(Categoria.nombre, func.sum(Movimiento.monto)).join(Movimiento).filter(
        Movimiento.familia_id == f_id, Movimiento.tipo == 'egreso').group_by(Categoria.nombre).all()
    
    # Ranking de Utilidad (Postgres compatible)
    ranking_oro = db.session.query(
        Producto.nombre,
        func.sum(MovimientoInventario.monto_total - (Producto.precio_compra * MovimientoInventario.cantidad)).label('ganancia_neta')
    ).join(Producto).filter(MovimientoInventario.tipo.ilike('salida'), Producto.familia_id == f_id).group_by(Producto.nombre).order_by(text('ganancia_neta DESC')).limit(5).all()

    return render_template('reportes.html', 
                           labels_g=[g[0] for g in gastos_cat], valores_g=[float(g[1]) for g in gastos_cat],
                           labels_oro=[r[0] for r in ranking_oro], valores_oro=[float(r[1]) for r in ranking_oro],
                           user=current_user)

@app.route('/historial')
@login_required
def historial():
    f_id = current_user.familia_id
    mes_filtro = request.args.get('mes', datetime.now().month, type=int)
    
    # REEMPLAZO DE strftime POR extract (COMPATIBLE CON POSTGRES)
    movimientos = Movimiento.query.filter(
        Movimiento.familia_id == f_id,
        extract('month', Movimiento.fecha) == mes_filtro
    ).order_by(Movimiento.fecha.desc()).all()
    
    g_mes = sum(m.monto for m in movimientos if m.tipo == 'egreso')
    i_mes = sum(m.monto for m in movimientos if m.tipo == 'ingreso')

    return render_template('historial.html', todos=movimientos, g_semana=g_mes, i_semana=i_mes, mes_actual=mes_filtro, user=current_user)

# --- 8. AUTENTICACIÓN Y CONFIGURACIÓN ---

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        user = Usuario.query.filter_by(email=request.form.get('email').lower()).first()
        if user and user.check_password(request.form.get('password')):
            login_user(user); return redirect(url_for('dashboard'))
        return render_template('error_login.html')
    return render_template('login.html')

@app.route('/registro', methods=['GET', 'POST'])
def registro():
    inv_id = session.get('invitacion_familia_id')
    f_invitada = Familia.query.get(inv_id) if inv_id else None

    if request.method == 'POST':
        email = request.form.get('email').lower().strip()
        if Usuario.query.filter_by(email=email).first():
            flash('Email ya registrado', 'danger'); return redirect(url_for('registro'))
        
        if f_invitada:
            f_id = f_invitada.id; rol = 'miembro'; session.pop('invitacion_familia_id', None)
        else:
            nueva_f = Familia(nombre=request.form.get('nombre_familia') or f"Familia de {request.form.get('nombre_usuario')}")
            db.session.add(nueva_f); db.session.commit()
            f_id = nueva_f.id; rol = 'admin'
            
        nuevo = Usuario(nombre=request.form.get('nombre_usuario'), email=email, familia_id=f_id, rol=rol)
        nuevo.set_password(request.form.get('password'))
        db.session.add(nuevo); db.session.commit()
        login_user(nuevo); return redirect(url_for('dashboard'))
    return render_template('registro.html', familia_invitada=f_invitada)

@app.route('/logout')
def logout():
    logout_user(); return redirect(url_for('login'))

@app.route('/pagar_ahora/<int:id>')
@login_required
def pagar_ahora(id):
    pago = PagoPendiente.query.get_or_404(id)
    if pago.familia_id == current_user.familia_id:
        db.session.add(Movimiento(tipo='egreso', monto=pago.monto, descripcion=f"✅ Pago: {pago.descripcion}",
                                  familia_id=current_user.familia_id, usuario_id=current_user.id))
        db.session.delete(pago); db.session.commit()
    return redirect(url_for('dashboard'))

if __name__ == '__main__':
    app.run(debug=True, port=5001)
