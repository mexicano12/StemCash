import os
import pytz
from flask import Flask, render_template, request, redirect, url_for, flash, session
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from flask_migrate import Migrate
from sqlalchemy import func
from datetime import datetime, date, timedelta # Añadí timedelta que lo usamos en el dashboard

# --- 1. IMPORTACIÓN DE MODELOS ---
# Asegúrate de que models.py esté en la misma carpeta
from models import db, Familia, Usuario, Movimiento, Categoria, Producto, MovimientoInventario, PagoPendiente

# --- 2. CONFIGURACIÓN DE RUTAS Y CARPETAS ---
basedir = os.path.abspath(os.path.dirname(__file__))
# Cambiamos a una ruta relativa más amigable para Render
UPLOAD_FOLDER = os.path.join(basedir, 'static', 'uploads', 'productos')
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}

if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER, exist_ok=True)

app = Flask(__name__)

# --- 3. CONFIGURACIÓN DE SEGURIDAD Y BD (EL CAMBIO MAESTRO) ---
# En Render usaremos variables de entorno para no exponer contraseñas
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'stemcash_secret_2026_pro')

# Lógica para detectar si estamos en Render (Postgres) o en tu PC (SQLite)
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

# --- 5. INICIALIZACIÓN DE DATOS ---
# Nota: db.create_all() es seguro, pero con Migrate es mejor usar 'flask db upgrade'
with app.app_context():
    db.create_all()
    
    if not Familia.query.first():
        familia = Familia(nombre="Familia Pérez")
        db.session.add(familia)
        db.session.commit()
        
        nuevo_usuario = Usuario(
            nombre="Erick", 
            email="erick@test.com", 
            password_hash="12345", # En producción usa generate_password_hash
            familia_id=familia.id
        )
        db.session.add(nuevo_usuario)
        
        cats_egreso = ['Comida', 'Servicios', 'Renta', 'Ocio', 'Transporte', 'Salud', 'Inventario', 'Despensa']
        cats_ingreso = ['Sueldo', 'Venta Ceravette', 'Venta StemRare', 'Regalo', 'Otros']
        
        for c in cats_egreso:
            db.session.add(Categoria(nombre=c, tipo='egreso', familia_id=familia.id))
        for c in cats_ingreso:
            db.session.add(Categoria(nombre=c, tipo='ingreso', familia_id=familia.id))

        db.session.commit()
        print("✅ Base de datos inicializada correctamente.")

# --- RUTAS ---

from datetime import datetime, timedelta
@app.route('/')
@login_required
def dashboard():
    f_id = current_user.familia_id
    
    # --- 🌍 CONFIGURACIÓN DE TIEMPO (MÉXICO) ---
    zona_mx = pytz.timezone('America/Mexico_City')
    ahora_mx = datetime.now(zona_mx)
    hoy_str = ahora_mx.strftime('%Y-%m-%d')
    
    # Rangos de tiempo
    hoy_date = ahora_mx.date()
    inicio_semana = (hoy_date - timedelta(days=hoy_date.weekday())).strftime('%Y-%m-%d')
    inicio_mes = hoy_date.replace(day=1).strftime('%Y-%m-%d')

    # 1. CÁLCULOS DE BALANCE REAL
    ingresos_totales = db.session.query(func.sum(Movimiento.monto)).filter(
        Movimiento.familia_id == f_id, Movimiento.tipo == 'ingreso').scalar() or 0
        
    gastos_totales = db.session.query(func.sum(Movimiento.monto)).filter(
        Movimiento.familia_id == f_id, Movimiento.tipo == 'egreso').scalar() or 0
    
    balance = ingresos_totales - gastos_totales

    # 2. CÁLCULOS DE TARJETAS
    gastado_hoy = db.session.query(func.sum(Movimiento.monto)).filter(
        Movimiento.familia_id == f_id, 
        Movimiento.tipo == 'egreso',
        func.strftime('%Y-%m-%d', Movimiento.fecha) == hoy_str
    ).scalar() or 0

    gastado_semana = db.session.query(func.sum(Movimiento.monto)).filter(
        Movimiento.familia_id == f_id,
        Movimiento.tipo == 'egreso',
        func.strftime('%Y-%m-%d', Movimiento.fecha) >= inicio_semana
    ).scalar() or 0

    ingresos_mes = db.session.query(func.sum(Movimiento.monto)).filter(
        Movimiento.familia_id == f_id,
        Movimiento.tipo == 'ingreso',
        func.strftime('%Y-%m-%d', Movimiento.fecha) >= inicio_mes
    ).scalar() or 0
    
    gastos_mes = db.session.query(func.sum(Movimiento.monto)).filter(
        Movimiento.familia_id == f_id,
        Movimiento.tipo == 'egreso',
        func.strftime('%Y-%m-%d', Movimiento.fecha) >= inicio_mes
    ).scalar() or 0

    # 3. VALOR DEL INVENTARIO
    productos = Producto.query.filter_by(familia_id=f_id).all()
    valor_inventario_calculado = sum((p.stock or 0) * (p.precio_compra or 0) for p in productos)

    # --- 4. GANANCIA REAL DE HOY ---
    ventas_hoy = MovimientoInventario.query.join(Producto).filter(
        MovimientoInventario.tipo.ilike('salida'),
        Producto.familia_id == f_id,
        func.strftime('%Y-%m-%d', MovimientoInventario.fecha) == hoy_str
    ).all()

    ganancia_hoy = sum(v.monto_total - ((v.producto.precio_compra or 0) * v.cantidad) for v in ventas_hoy)
    num_ventas_hoy = len(ventas_hoy)

    # --- 🆕 5. AGENDA DE PAGOS PENDIENTES ---
    # Traemos los pagos pendientes ordenados por la fecha de vencimiento más cercana
    pendientes = PagoPendiente.query.filter_by(
        familia_id=f_id, 
        estatus='pendiente'
    ).order_by(PagoPendiente.fecha_limite.asc()).all()
    
    total_deuda = sum(p.monto for p in pendientes)

    # 6. LISTA DE MOVIMIENTOS
    movimientos = Movimiento.query.filter_by(familia_id=f_id).order_by(Movimiento.id.desc()).limit(10).all()
    categorias = Categoria.query.filter_by(familia_id=f_id).all()

    return render_template('dashboard.html', 
                           balance_total=balance, 
                           ingresos_mes=ingresos_mes, 
                           gastos_mes=gastos_mes,
                           gastado_hoy=gastado_hoy,
                           gastado_semana=gastado_semana,
                           valor_inventario=valor_inventario_calculado,
                           ganancia_hoy=ganancia_hoy,
                           num_ventas=num_ventas_hoy,
                           user=current_user,
                           movimientos=movimientos,
                           categorias=categorias,
                           pendientes=pendientes,       # <--- Enviamos a la plantilla
                           total_deuda=total_deuda)     # <--- Enviamos a la plantilla
@app.route('/registrar', methods=['POST'])
@login_required
def registrar():
    # 1. Obtener IDs y textos básicos
    cat_id_raw = request.form.get('categoria_id')
    nombre_nueva = request.form.get('nombre_nueva_cat')
    tipo = request.form.get('tipo') # 'ingreso' o 'egreso'
    descripcion = request.form.get('descripcion')
    
    # 2. Obtener datos numéricos con nombres correctos del HTML
    try:
        # Usamos .get('precio_u') porque así está en tu HTML actual
        cant = float(request.form.get('cantidad') or 1)
        p_unitario = float(request.form.get('precio_u') or 0)
        monto_manual = request.form.get('monto')
        
        # Si es ingreso (monto manual), priorizamos ese valor
        if monto_manual and float(monto_manual) > 0:
            monto_total = float(monto_manual)
        else:
            monto_total = cant * p_unitario
    except ValueError:
        monto_total = 0
        cant = 1
        p_unitario = 0

    # 3. Manejo de Categoría (EL ARREGLO CRÍTICO)
    final_cat_id = None
    
    if cat_id_raw == 'nueva' and nombre_nueva:
        nueva_cat = Categoria(
            nombre=nombre_nueva, 
            tipo=tipo, 
            familia_id=current_user.familia_id
        )
        db.session.add(nueva_cat)
        db.session.commit()
        final_cat_id = nueva_cat.id
    elif cat_id_raw and str(cat_id_raw).isdigit():
        final_cat_id = int(cat_id_raw)

    # 4. Crear el movimiento
    nuevo_movimiento = Movimiento(
        tipo=tipo,
        cantidad=cant,
        precio_unitario=p_unitario,
        monto=monto_total,
        descripcion=descripcion,
        categoria_id=final_cat_id, # Aquí ya va el ID limpio
        familia_id=current_user.familia_id,
        usuario_id=current_user.id
    )
    
    db.session.add(nuevo_movimiento)
    db.session.commit()
    
    # Debug para que veas en la consola si funcionó
    print(f"✅ Movimiento registrado: {descripcion} - Cat ID: {final_cat_id}")
    
    return redirect(url_for('dashboard'))

@app.route('/inventario')
@login_required # <-- Protege la ruta para que siempre haya un current_user
def inventario():
    # 1. Usamos el ID del usuario y de su familia actual
    u_id = current_user.id
    f_id = current_user.familia_id
    
    # 2. Filtramos productos por FAMILIA (así todos tus miembros los ven)
    # Si prefieres que solo TÚ los veas, usa: usuario_id=u_id
    productos = Producto.query.filter_by(familia_id=f_id).all()
    
    # 3. Cálculos dinámicos
    valor_total_stock = sum(p.stock * p.precio_compra for p in productos)
    ganancia_potencial = sum(p.stock * (p.precio_venta - p.precio_compra) for p in productos)
    
    # 4. Categorías de egreso exclusivas de TU familia
    categorias = Categoria.query.filter_by(tipo='egreso', familia_id=f_id).all()

    return render_template('inventario.html', 
                           productos=productos, 
                           valor_total_stock=valor_total_stock,
                           ganancia_potencial=ganancia_potencial,
                           categorias=categorias,
                           user=current_user)

@app.route('/comprar_producto', methods=['POST'])
@login_required # <-- Vital para que funcione current_user
def comprar_producto():
    prod_id = request.form.get('producto_id')
    cantidad = float(request.form.get('cantidad') or 0)
    costo_total = float(request.form.get('costo_total') or 0)
    
    # Usamos los datos reales del usuario logueado
    u_id = current_user.id
    f_id = current_user.familia_id
    
    # Buscamos el producto asegurándonos que pertenezca a este usuario/familia
    producto = Producto.query.filter_by(id=prod_id, usuario_id=u_id).first()
    
    if producto and cantidad > 0:
        # 1. Actualizar el stock y el precio de compra
        producto.stock += cantidad
        producto.precio_compra = costo_total / cantidad 
        
        # 2. Buscar la categoría "Inventario" de TU familia
        cat_inv = Categoria.query.filter_by(nombre="Inventario", familia_id=f_id).first()
        
        # 3. Registrar la salida de dinero (Movimiento)
        nuevo_mov = Movimiento(
            monto=costo_total,
            tipo='egreso', # Esto es lo que el Dashboard suma en "Gastos"
            descripcion=f"📦 Compra Stock: {producto.nombre} ({int(cantidad)} pzs)",
            categoria_id=cat_inv.id if cat_inv else None,
            familia_id=f_id, # <-- ID Dinámico
            usuario_id=u_id   # <-- ID Dinámico
        )
        
        # 4. Registrar en el historial de Inventario (Kardex)
        nuevo_kardex = MovimientoInventario(
            producto_id=producto.id,
            tipo='ENTRADA',
            cantidad=cantidad,
            monto_total=costo_total
        )
        
        db.session.add(nuevo_mov)
        db.session.add(nuevo_kardex)
        db.session.commit()
        print(f"✅ Compra registrada: {producto.nombre} para Familia {f_id}")
    else:
        print("❌ Error: Producto no encontrado o cantidad inválida")
    
    return redirect(url_for('inventario'))
@app.route('/crear_producto', methods=['POST'])
@login_required # <-- Indispensable para usar current_user
def crear_producto():
    # USAMOS EL ID REAL DEL USUARIO LOGUEADO
    u_id = current_user.id
    f_id = current_user.familia_id
    
    imagen_nombre = 'default_product.png'
    
    # Manejo de la imagen
    if 'imagen' in request.files:
        file = request.files['imagen']
        if file and file.filename != '' and allowed_file(file.filename):
            filename = secure_filename(file.filename)
            filename = f"{datetime.now().strftime('%Y%m%d%H%M%S')}_{filename}"
            file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
            imagen_nombre = filename

    nuevo_prod = Producto(
        nombre=request.form.get('nombre'),
        descripcion=request.form.get('descripcion'),
        categoria_prod=request.form.get('categoria_prod') or "General",
        plataforma=request.form.get('plataforma'),
        stock=float(request.form.get('stock') or 0),
        precio_compra=float(request.form.get('precio_compra') or 0),
        precio_venta=float(request.form.get('precio_venta') or 0),
        imagen_url=imagen_nombre,
        usuario_id=u_id,       # <-- CAMBIADO: Ya no es 1
        familia_id=f_id        # <-- AÑADIDO: Para que toda la familia lo vea
    )
    
    db.session.add(nuevo_prod)
    db.session.commit()
    print(f"✅ Producto '{nuevo_prod.nombre}' creado para usuario {u_id}")
    return redirect(url_for('inventario'))
    
    db.session.add(nuevo_prod)
    db.session.commit()
    return redirect(url_for('inventario'))

@app.route('/vender_producto', methods=['POST'])
@login_required
def vender_producto():
    prod_id = request.form.get('producto_id')
    
    # 1. Forzamos el uso de float para que 0.5 no sea redondeado a 0 o 1
    try:
        cantidad_vender = float(request.form.get('cantidad') or 0)
        precio_venta_real = float(request.form.get('precio_venta') or 0)
    except ValueError:
        return redirect(url_for('inventario'))
    
    producto = Producto.query.get(prod_id)
    cat_venta = Categoria.query.filter_by(nombre="Venta", familia_id=current_user.familia_id).first()
    
    # 2. Validación con decimales
    if producto and producto.stock >= cantidad_vender:
        # La resta de floats en Python es precisa para estos casos
        producto.stock = round(producto.stock - cantidad_vender, 3)
        
        monto_total_venta = precio_venta_real * cantidad_vender
        
        nuevo_mov = Movimiento(
            tipo='ingreso',
            monto=monto_total_venta, 
            # Guardamos con decimales en la descripción para que tu hermana lo vea claro
            descripcion=f"💰 Venta: {producto.nombre} ({cantidad_vender} kg/pzs)",
            categoria_id=cat_venta.id if cat_venta else None,
            familia_id=current_user.familia_id,
            usuario_id=current_user.id
        )
        
        nuevo_kardex = MovimientoInventario(
            producto_id=producto.id,
            tipo='SALIDA',
            cantidad=cantidad_vender, # Se guarda como 0.5 en la DB
            monto_total=monto_total_venta
        )
        
        db.session.add(nuevo_mov)
        db.session.add(nuevo_kardex)
        db.session.commit()
        print(f"✅ Venta exitosa: se descontaron {cantidad_vender} de {producto.nombre}")
    else:
        # Podrías usar un flash mensaje aquí para que aparezca en el celular
        print("❌ Error: Stock insuficiente")
        
    return redirect(url_for('ventas')) # Te sugiero redirigir a ventas para ver el resultado
@app.route('/ventas')
@login_required # <-- Para que funcione current_user
def ventas():
    # 1. Traemos los productos de TU familia que tengan stock (para no vender aire)
    productos = Producto.query.filter_by(familia_id=current_user.familia_id).filter(Producto.stock > 0).all()
    
    # 2. Traemos el historial de ventas de TU familia (filtrado por el Kardex)
    # Necesitamos unirlo con Producto para poder mostrar el nombre
    historial_ventas = MovimientoInventario.query.join(Producto).filter(
        MovimientoInventario.tipo == 'SALIDA',
        Producto.familia_id == current_user.familia_id
    ).order_by(MovimientoInventario.fecha.desc()).all()
    
    # 3. Calculamos la ganancia total rápida para el resumen
    ganancia_total = sum((m.monto_total - (m.producto.precio_compra * m.cantidad)) for m in historial_ventas if m.producto)

    return render_template('ventas.html', 
                           productos=productos, 
                           historial=historial_ventas,
                           ganancia_total=ganancia_total,
                           user=current_user)

@app.route('/eliminar_venta/<int:id>')
def eliminar_venta(id):
    venta = MovimientoInventario.query.get_or_404(id)
    producto = venta.producto
    
    # 1. Devolvemos el stock al producto
    producto.stock += venta.cantidad
    
    # 2. Buscamos el movimiento de dinero asociado para borrarlo también
    # (Buscamos uno que coincida en monto y fecha aproximada)
    mov_dinero = Movimiento.query.filter_by(
        monto=venta.monto_total, 
        tipo='ingreso'
    ).order_by(Movimiento.fecha.desc()).first()
    
    if mov_dinero:
        db.session.delete(mov_dinero)
        
    db.session.delete(venta)
    db.session.commit()
    return redirect(url_for('ventas'))

@app.route('/editar_venta', methods=['POST'])
def editar_venta():
    venta_id = request.form.get('venta_id')
    nuevo_precio = float(request.form.get('nuevo_precio'))
    
    venta = MovimientoInventario.query.get(venta_id)
    monto_anterior = venta.monto_total # Guardamos el viejo para buscar el movimiento
    
    # 1. Actualizamos la venta en el historial de inventario
    venta.monto_total = nuevo_precio * venta.cantidad
    
    # 2. Buscamos el movimiento de dinero (ingreso) asociado
    # Buscamos por el monto anterior y que sea un ingreso reciente
    movimiento_dinero = Movimiento.query.filter_by(
        monto=monto_anterior, 
        tipo='ingreso'
    ).order_by(Movimiento.fecha.desc()).first()
    
    if movimiento_dinero:
        movimiento_dinero.monto = venta.monto_total
        movimiento_dinero.descripcion = f"💰 Venta Editada: {venta.producto.nombre}"

    db.session.commit()
    return redirect(url_for('ventas'))

@app.route('/registrar_compra', methods=['POST'])
@login_required # <-- Indispensable
def registrar_compra():
    # Datos generales de la compra
    f_id = current_user.familia_id
    u_id = current_user.id
    
    prod_id_input = request.form.get('producto_id')
    cantidad_comprada = float(request.form.get('cantidad') or 1)
    costo_total = float(request.form.get('costo_total') or 0)
    
    # Datos por si es un producto nuevo
    nombre_nuevo = request.form.get('nombre_nuevo')
    precio_venta_nuevo = float(request.form.get('precio_venta_nuevo') or 0)
    
    producto = None

    # --- LÓGICA PARA PRODUCTO NUEVO O EXISTENTE ---
    if prod_id_input == 'nuevo' and nombre_nuevo:
        # A. Crear el producto si no existe
        producto = Producto(
            nombre=nombre_nuevo,
            stock=0, # Empezamos en 0, la compra lo sumará
            precio_compra=costo_total / cantidad_comprada if cantidad_comprada > 0 else 0,
            precio_venta=precio_venta_nuevo,
            familia_id=f_id,
            usuario_id=u_id,
            categoria_prod="Insumos" # Categoría por defecto para Ceravette
        )
        db.session.add(producto)
        db.session.commit() # Necesitamos el ID del producto nuevo
        print(f"✅ Nuevo producto creado desde compras: {producto.nombre}")
        
    elif prod_id_input != 'nuevo':
        # B. Buscar el producto existente asegurándonos que sea de la familia
        producto = Producto.query.filter_by(id=prod_id_input, familia_id=f_id).first()

    # --- REGISTRAR LA COMPRA (SI HAY PRODUCTO) ---
    if producto and cantidad_comprada > 0:
        # 1. Actualizar el Stock y el costo de compra del producto
        producto.stock += cantidad_comprada
        producto.precio_compra = costo_total / cantidad_comprada
        
        # 2. Buscar la categoría "Inventario" de TU familia
        cat_inv = Categoria.query.filter_by(nombre="Inventario", familia_id=f_id).first()
        
        # 3. Registrar el GASTO (Movimiento de dinero)
        nuevo_gasto = Movimiento(
            monto=costo_total,
            tipo='egreso', # Esto es lo que suma el Dashboard en "Gastos"
            descripcion=f"🛒 Compra: {producto.nombre} ({int(cantidad_comprada)} pzs)",
            categoria_id=cat_inv.id if cat_inv else None,
            familia_id=f_id,
            usuario_id=u_id
        )
        
        # 4. Registrar en el historial de Inventario (Kardex)
        nuevo_kardex = MovimientoInventario(
            producto_id=producto.id,
            tipo='ENTRADA',
            cantidad=cantidad_comprada,
            monto_total=costo_total
            # Si tu modelo Kardex tiene familia_id, agrégalo también aquí
        )
        
        db.session.add(nuevo_gasto)
        db.session.add(nuevo_kardex)
        db.session.commit()
        print(f"✅ Compra registrada para: {producto.nombre}")
    else:
        print("❌ Error: No se pudo determinar el producto o cantidad inválida")
        
    return redirect(url_for('compras'))

@app.route('/compras')
@login_required
def compras():
    f_id = current_user.familia_id
    
    productos = Producto.query.filter_by(familia_id=f_id).all()
    historial = MovimientoInventario.query.join(Producto).filter(
        MovimientoInventario.tipo == 'ENTRADA',
        Producto.familia_id == f_id
    ).order_by(MovimientoInventario.fecha.desc()).all()
    
    # 🚨 AQUÍ ESTÁ EL TRUCO: Tienes que calcular esta variable
    valor_total_stock = sum(p.stock * p.precio_compra for p in productos)

    return render_template('compras.html', 
                           productos=productos, 
                           historial=historial, 
                           valor_total_stock=valor_total_stock, # <--- ¡ASEGÚRATE DE PASARLA!
                           user=current_user)

@app.route('/editar_producto', methods=['POST'])
@login_required
def editar_producto():
    prod_id = request.form.get('id')
    producto = Producto.query.get_or_404(prod_id)
    
    if producto.usuario_id == current_user.id:
        producto.nombre = request.form.get('nombre')
        producto.precio_compra = float(request.form.get('precio_compra'))
        producto.precio_venta = float(request.form.get('precio_venta'))
        producto.stock = float(request.form.get('stock'))
        db.session.commit()
        
    return redirect(url_for('inventario'))

from sqlalchemy import func
from sqlalchemy import func, text

@app.route('/reportes')
@login_required
def reportes():
    f_id = current_user.familia_id
    
    # 0. OBTENER TODOS LOS PRODUCTOS DE LA FAMILIA
    productos_familia = Producto.query.filter_by(familia_id=f_id).all()

    # 1. SUMA DE INVERSIÓN (Movimientos de compra + Valor del Stock actual)
    inv_movimientos = db.session.query(func.sum(MovimientoInventario.monto_total)).join(Producto).filter(
        MovimientoInventario.tipo.ilike('entrada'), Producto.familia_id == f_id
    ).scalar() or 0
    
    inv_stock_inicial = sum([(p.stock * (p.precio_compra or 0)) for p in productos_familia])
    total_inversion = inv_movimientos + inv_stock_inicial

    # 2. SUMA DE RECUPERACIÓN (Ventas totales brutas)
    total_recuperado = db.session.query(func.sum(MovimientoInventario.monto_total)).join(Producto).filter(
        MovimientoInventario.tipo.ilike('salida'), Producto.familia_id == f_id
    ).scalar() or 0

    # 3. FLUJO DE DINERO GENERAL (Efectivo en mano)
    ingresos_totales_cash = db.session.query(func.sum(Movimiento.monto)).filter_by(
        familia_id=f_id, tipo='ingreso').scalar() or 0
    
    gastos_totales_cash = db.session.query(func.sum(Movimiento.monto)).filter_by(
        familia_id=f_id, tipo='egreso').scalar() or 0

    # 4. GASTOS POR CATEGORÍA (Para la Gráfica de Dona)
    gastos_cat_query = db.session.query(
        Categoria.nombre, func.sum(Movimiento.monto)
    ).join(Movimiento).filter(
        Movimiento.familia_id == f_id, Movimiento.tipo == 'egreso'
    ).group_by(Categoria.nombre).all()
    
    labels_gastos = [g[0] for g in gastos_cat_query]
    valores_gastos = [float(g[1]) for g in gastos_cat_query]

    # 5. RENDIMIENTO POR MARCA/PLATAFORMA (Gráfica de Barras Actual)
    ventas_agrupadas = db.session.query(
        Producto.plataforma, 
        func.sum(MovimientoInventario.monto_total)
    ).join(Producto).filter(
        MovimientoInventario.tipo.ilike('salida'),
        Producto.familia_id == f_id
    ).group_by(Producto.plataforma).all()

    stats_categorias = [(cat if cat else "General", float(monto)) for cat, monto in ventas_agrupadas]

    # --- 🏆 6. EL RANKING DE ORO: UTILIDAD NETA POR PRODUCTO (NUEVO) ---
    # Calculamos: (Venta total - (Costo Compra * Cantidad)) para cada producto
    ranking_query = db.session.query(
        Producto.nombre,
        func.sum(MovimientoInventario.monto_total - (Producto.precio_compra * MovimientoInventario.cantidad)).label('ganancia_neta'),
        func.sum(MovimientoInventario.cantidad).label('unidades')
    ).join(Producto).filter(
        MovimientoInventario.tipo.ilike('salida'),
        Producto.familia_id == f_id
    ).group_by(Producto.nombre).order_by(text('ganancia_neta DESC')).limit(5).all()

    labels_oro = [r[0] for r in ranking_query]
    valores_oro = [float(r[1]) for r in ranking_query]

    # 7. CÁLCULOS FINALES Y GANANCIA REAL TOTAL
    # Usamos la suma de las utilidades de todas las ventas
    ganancia_total_real = db.session.query(
        func.sum(MovimientoInventario.monto_total - (Producto.precio_compra * MovimientoInventario.cantidad))
    ).join(Producto).filter(
        MovimientoInventario.tipo.ilike('salida'), Producto.familia_id == f_id
    ).scalar() or 0

    porcentaje = (total_recuperado / total_inversion * 100) if total_inversion > 0 else 0
    faltante = max(0, total_inversion - total_recuperado)

    return render_template('reportes.html', 
                           inversion=total_inversion,
                           recuperado=total_recuperado,
                           porcentaje=round(min(porcentaje, 100), 2),
                           porcentaje_real=round(porcentaje, 2),
                           faltante=faltante,
                           ganancia_neta=ganancia_total_real,
                           ingresos_cash=ingresos_totales_cash,
                           gastos_cash=gastos_totales_cash,
                           balance_neto=ingresos_totales_cash - gastos_totales_cash,
                           labels_g=labels_gastos,
                           valores_g=valores_gastos,
                           stats_categorias=stats_categorias,
                           labels_oro=labels_oro,      # <--- NUEVO
                           valores_oro=valores_oro,    # <--- NUEVO
                           ranking_oro=ranking_query,  # <--- NUEVO
                           user=current_user)
@app.route('/registro', methods=['GET', 'POST'])
def registro():
    # 0. Verificamos si existe una invitación en la sesión
    invitacion_id = session.get('invitacion_familia_id')
    familia_invitada = Familia.query.get(invitacion_id) if invitacion_id else None

    if request.method == 'POST':
        nombre_usuario = request.form.get('nombre_usuario')
        email = request.form.get('email').lower().strip()
        password = request.form.get('password')

        # 1. Verificar si el email ya existe
        existe = Usuario.query.filter_by(email=email).first()
        if existe:
            flash('Este correo ya está registrado. Intenta con otro.', 'danger')
            return redirect(url_for('registro'))

        # --- LÓGICA DE UNIÓN O CREACIÓN ---
        if familia_invitada:
            # A. SE UNE A FAMILIA EXISTENTE (Vía Link de WhatsApp)
            f_id = familia_invitada.id
            rol_asignado = 'miembro'
            msg_exito = f'¡Bienvenido/a {nombre_usuario}! Ya eres parte de {familia_invitada.nombre}.'
            # Limpiamos la invitación después de usarla
            session.pop('invitacion_familia_id', None)
        else:
            # B. CREA UNA FAMILIA NUEVA (Registro Normal)
            nombre_familia = request.form.get('nombre_familia') or f"Familia de {nombre_usuario}"
            nueva_familia = Familia(nombre=nombre_familia)
            db.session.add(nueva_familia)
            db.session.commit() # Necesitamos el ID para el usuario
            
            f_id = nueva_familia.id
            rol_asignado = 'admin'
            msg_exito = f'¡Bienvenida/o! Tu familia {nombre_familia} ha sido creada.'

            # Creamos categorías base solo si es una familia NUEVA
            cats_egreso = ['Insumos', 'Servicios', 'Comida', 'Transporte', 'Inventario']
            cats_ingreso = ['Venta', 'Sueldo', 'Otros']
            for c in cats_egreso:
                db.session.add(Categoria(nombre=c, tipo='egreso', familia_id=f_id))
            for c in cats_ingreso:
                db.session.add(Categoria(nombre=c, tipo='ingreso', familia_id=f_id))

        # 2. Crear el Usuario (sea nuevo admin o miembro invitado)
        nuevo_usuario = Usuario(
            nombre=nombre_usuario,
            email=email,
            familia_id=f_id,
            rol=rol_asignado
        )
        nuevo_usuario.set_password(password)
        
        db.session.add(nuevo_usuario)
        db.session.commit()
        
        login_user(nuevo_usuario)
        flash(msg_exito, 'success')
        return redirect(url_for('dashboard'))

    # Pasamos 'familia_invitada' al template para que el HTML sepa qué mostrar
    return render_template('registro.html', familia_invitada=familia_invitada)
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        user = Usuario.query.filter_by(email=email).first()

        if user and user.check_password(password):
            login_user(user)
            return redirect(url_for('dashboard'))
        else:
            # --- CAMBIO AQUÍ: Renderizamos la plantilla bonita ---
            return render_template('error_login.html')

    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

@app.route('/configuracion')
@login_required
def configuracion():
    # Obtenemos todos los miembros de la misma familia
    miembros = Usuario.query.filter_by(familia_id=current_user.familia_id).all()
    familia = Familia.query.get(current_user.familia_id)
    
    return render_template('configuracion.html', 
                           familia=familia, 
                           miembros=miembros,
                           user=current_user)

@app.route('/invitar_miembro', methods=['POST'])
@login_required
def invitar_miembro():
    nombre = request.form.get('nombre')
    email = request.form.get('email')
    password = request.form.get('password')
    
    # Creamos el nuevo usuario vinculado a la MISMA familia
    nuevo_usuario = Usuario(
        nombre=nombre,
        email=email,
        familia_id=current_user.familia_id
    )
    nuevo_usuario.set_password(password)
    
    db.session.add(nuevo_usuario)
    db.session.commit()

    flash('¡Miembro añadido correctamente!', 'success') # <-- El mensaje
    return redirect(url_for('configuracion'))
@app.route('/eliminar_miembro/<int:id>')
@login_required
def eliminar_miembro(id):
    # Seguridad: No puedes eliminarte a ti mismo
    if id == current_user.id:
        flash('No puedes eliminar tu propia cuenta.', 'danger')
        return redirect(url_for('configuracion'))
        
    user_a_borrar = Usuario.query.get_or_404(id)
    # Solo si pertenecen a la misma familia
    if user_a_borrar.familia_id == current_user.familia_id:
        db.session.delete(user_a_borrar)
        db.session.commit()
        flash('Miembro eliminado.', 'success')
    return redirect(url_for('configuracion'))

@app.route('/cambiar_rol/<int:id>/<string:nuevo_rol>')
@login_required
def cambiar_rol(id, nuevo_rol):
    user = Usuario.query.get_or_404(id)
    if user.familia_id == current_user.familia_id:
        user.rol = nuevo_rol
        db.session.commit()
        flash(f'Rol de {user.nombre} actualizado a {nuevo_rol}.', 'success')
    return redirect(url_for('configuracion'))

@app.route('/fix_inventory')
@login_required
def fix_inventory():
    # Pasamos todos los productos del usuario 1 al usuario actual (Erick)
    prods = Producto.query.filter_by(usuario_id=1).all()
    for p in prods:
        p.usuario_id = current_user.id
        p.familia_id = current_user.familia_id
    db.session.commit()
    return f"Se han recuperado {len(prods)} productos para tu inventario."

@app.route('/eliminar_compra/<int:id>')
@login_required
def eliminar_compra(id):
    # 1. Buscamos el registro en el historial (Kardex)
    compra = MovimientoInventario.query.get_or_404(id)
    producto = compra.producto
    f_id = current_user.familia_id
    
    # Seguridad: Solo puedes borrar si el producto es de tu familia
    if producto.familia_id == f_id:
        # 2. Devolvemos el stock a como estaba antes (restamos lo que entró)
        producto.stock -= compra.cantidad
        
        # 3. Buscamos el movimiento de dinero asociado para borrar el gasto del Dashboard
        # Buscamos por monto exacto y que sea un egreso de la misma familia
        mov_dinero = Movimiento.query.filter_by(
            monto=compra.monto_total, 
            tipo='egreso',
            familia_id=f_id
        ).order_by(Movimiento.fecha.desc()).first()
        
        if mov_dinero:
            db.session.delete(mov_dinero)
            
        # 4. Borramos el registro del historial
        db.session.delete(compra)
        db.session.commit()
        flash('Compra eliminada y stock actualizado.', 'success')
    
    return redirect(url_for('compras'))
@app.route('/eliminar_producto/<int:id>')
@login_required
def eliminar_producto(id):
    producto = Producto.query.get_or_404(id)
    
    # Seguridad: Solo el dueño de la familia puede borrar sus productos
    if producto.familia_id == current_user.familia_id:
        # Nota: Al borrar un producto, se borrarán sus fotos e historial 
        # si configuraste el 'cascade delete' en los modelos.
        db.session.delete(producto)
        db.session.commit()
        flash(f"Producto {producto.nombre} eliminado correctamente.", "success")
    else:
        flash("No tienes permiso para eliminar este producto.", "danger")
        
    return redirect(url_for('inventario'))

@app.route('/eliminar_movimiento/<int:id>')
@login_required
def eliminar_movimiento(id):
    movimiento = Movimiento.query.get_or_404(id)
    
    if movimiento.familia_id != current_user.familia_id:
        flash("No tienes permiso.", "danger")
        return redirect(url_for('dashboard'))

    try:
        # Buscamos en el inventario algo que coincida con la descripción o monto
        # ya que el modelo Movimiento no conoce directamente al Producto
        mov_inv = MovimientoInventario.query.filter(
            MovimientoInventario.monto_total == movimiento.monto,
            MovimientoInventario.fecha >= movimiento.fecha - timedelta(minutes=5)
        ).first()
        
        if mov_inv:
            producto = Producto.query.get(mov_inv.producto_id)
            if producto:
                if movimiento.tipo == 'egreso': # Si borramos un gasto, el stock sube
                    producto.stock += mov_inv.cantidad
                else: # Si borramos un ingreso (venta), el stock baja
                    producto.stock -= mov_inv.cantidad
                db.session.delete(mov_inv)

    except Exception as e:
        print(f"⚠️ Aviso: Falló ajuste de stock: {e}")

    db.session.delete(movimiento)
    db.session.commit()
    flash("Registro eliminado con éxito.", "success")
    return redirect(url_for('dashboard'))
@app.route('/historial')
@app.route('/historial')
@login_required
def historial():
    f_id = current_user.familia_id
    zona_mx = pytz.timezone('America/Mexico_City')
    ahora_mx = datetime.now(zona_mx)

    # Obtenemos el mes del filtro (por defecto el mes actual de MÉXICO)
    mes_filtro = request.args.get('mes', ahora_mx.month, type=int)
    anio_filtro = ahora_mx.year

    # Usamos CAST para asegurar que SQLite entienda la comparación de fechas
    todos_los_movimientos = Movimiento.query.filter(
        Movimiento.familia_id == f_id,
        func.strftime('%m', Movimiento.fecha) == f"{mes_filtro:02d}",
        func.strftime('%Y', Movimiento.fecha) == str(anio_filtro)
    ).order_by(Movimiento.fecha.desc()).all()
    
    gasto_mes = sum(m.monto for m in todos_los_movimientos if m.tipo == 'egreso')
    ingreso_mes = sum(m.monto for m in todos_los_movimientos if m.tipo == 'ingreso')

    return render_template('historial.html', 
                           todos=todos_los_movimientos,
                           g_semana=gasto_mes, 
                           i_semana=ingreso_mes,
                           mes_actual=mes_filtro,
                           user=current_user)
@app.route('/eliminar_mi_cuenta_y_familia', methods=['POST'])
@login_required
def eliminar_familia_completa():
    familia_id = current_user.familia_id
    familia = Familia.query.get_or_404(familia_id)
    
    try:
        # 1. Borrar Movimientos e Inventarios
        Movimiento.query.filter_by(familia_id=familia_id).delete()
        
        # 2. Borrar Productos (y sus movimientos de inventario)
        productos = Producto.query.filter_by(familia_id=familia_id).all()
        for p in productos:
            MovimientoInventario.query.filter_by(producto_id=p.id).delete()
            db.session.delete(p)
            
        # 3. Borrar Categorías
        Categoria.query.filter_by(familia_id=familia_id).delete()
        
        # 4. Borrar Usuarios de esa familia
        Usuario.query.filter_by(familia_id=familia_id).delete()
        
        # 5. Finalmente, borrar la Familia
        db.session.delete(familia)
        
        db.session.commit()
        logout_user() # Sacamos al usuario porque ya no existe
        
        flash('Tu cuenta y todos tus datos han sido eliminados permanentemente.', 'success')
        return redirect(url_for('registro'))
        
    except Exception as e:
        db.session.rollback()
        flash(f'Error al eliminar: {str(e)}', 'danger')
        return redirect(url_for('configuracion'))
   

@app.route('/unirse/<int:familia_id>')
def unirse_familia(familia_id):
    # Buscamos que la familia exista
    familia = Familia.query.get_or_404(familia_id)
    
    # Guardamos el ID en la sesión para el registro
    session['invitacion_familia_id'] = familia_id
    
    # Mandamos al usuario a la página de registro con un mensaje bonito
    flash(f"🎉 ¡Invitación aceptada! Regístrate para unirte a {familia.nombre}", "success")
    return redirect(url_for('registro'))

@app.route('/agregar_pago_pendiente', methods=['POST'])
@login_required
def agregar_pago_pendiente():
    descripcion = request.form.get('descripcion')
    monto = float(request.form.get('monto') or 0)
    fecha_limite_str = request.form.get('fecha_limite')
    
    # Convertimos el texto de la fecha a un objeto real de Python
    from datetime import datetime
    fecha_dt = datetime.strptime(fecha_limite_str, '%Y-%m-%d').date()

    nuevo_pago = PagoPendiente(
        descripcion=descripcion,
        monto=monto,
        fecha_limite=fecha_dt,
        familia_id=current_user.familia_id
    )
    
    db.session.add(nuevo_pago)
    db.session.commit()
    flash("Pago agendado correctamente", "success")
    return redirect(url_for('dashboard'))
@app.route('/pagar_ahora/<int:id>')
@login_required
def pagar_ahora(id):
    # 1. Buscamos el recordatorio de pago
    pago = PagoPendiente.query.get_or_404(id)
    
    # Seguridad: Verificar que sea de la familia del usuario
    if pago.familia_id != current_user.familia_id:
        flash("No tienes permiso para realizar este pago.", "danger")
        return redirect(url_for('dashboard'))

    try:
        # 2. Registramos el GASTO REAL en la tabla Movimiento
        # (Esto es lo que descontará el dinero de tu balance)
        nuevo_gasto = Movimiento(
            tipo='egreso',
            monto=pago.monto,
            descripcion=f"✅ Pago: {pago.descripcion}",
            familia_id=current_user.familia_id,
            usuario_id=current_user.id
            # Puedes asignar una categoría por defecto si quieres, ej: categoria_id=1
        )
        
        # 3. Borramos el pendiente de la agenda (porque ya se pagó)
        db.session.delete(pago)
        db.session.add(nuevo_gasto)
        
        db.session.commit()
        flash(f"¡Pago de {pago.descripcion} realizado con éxito!", "success")
        
    except Exception as e:
        db.session.rollback()
        print(f"Error al procesar pago: {e}")
        flash("Hubo un error al procesar el pago.", "danger")

    return redirect(url_for('dashboard'))
if __name__ == '__main__':
    app.run(debug=True, port=5001)
