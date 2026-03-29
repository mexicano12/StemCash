from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
import pytz # <-- IMPORTANTE: Instala con 'pip install pytz'

# Inicializamos la base de datos
db = SQLAlchemy()
def hora_mexico():
    zona_mx = pytz.timezone('America/Mexico_City')
    return datetime.now(zona_mx)

class Familia(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(100), nullable=False)
    
    # Relaciones: Una familia tiene usuarios, movimientos, categorías y productos
    usuarios = db.relationship('Usuario', backref='familia', lazy=True)
    movimientos = db.relationship('Movimiento', backref='familia', lazy=True)
    categorias = db.relationship('Categoria', backref='familia', lazy=True)
    
    # OJO: Tienes dos tipos de inventario, ambos vinculados aquí:
    productos = db.relationship('Producto', backref='familia', lazy=True)
    inventario_general = db.relationship('Inventario', backref='familia', lazy=True)

class Usuario(db.Model, UserMixin):
    id = db.Column(db.Integer, primary_key=True)
    rol = db.Column(db.String(20), default='miembro') 
    nombre = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(128), nullable=False)
    familia_id = db.Column(db.Integer, db.ForeignKey('familia.id'), nullable=False)
    
    # Relación con productos que este usuario específico dio de alta
    productos_creados = db.relationship('Producto', backref='dueno', lazy=True)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

class Movimiento(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    tipo = db.Column(db.String(10), nullable=False)
    
    # Ponemos nullable=True temporalmente si vas por la Opción B, 
    # o déjalos así si vas por la Opción A (Borrar todo)
    cantidad = db.Column(db.Float, default=1.0, nullable=False) 
    precio_unitario = db.Column(db.Float, default=0.0, nullable=False)
    
    monto = db.Column(db.Float, nullable=False)
    descripcion = db.Column(db.String(200))
    fecha = db.Column(db.DateTime, default=hora_mexico)
    categoria = db.relationship('Categoria', backref='movimientos_rel')
    
    categoria_id = db.Column(db.Integer, db.ForeignKey('categoria.id'))
    familia_id = db.Column(db.Integer, db.ForeignKey('familia.id'), nullable=False)
    usuario_id = db.Column(db.Integer, db.ForeignKey('usuario.id'), nullable=False)

class Categoria(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(50), nullable=False)
    tipo = db.Column(db.String(10), nullable=False) # 'ingreso' o 'egreso'
    familia_id = db.Column(db.Integer, db.ForeignKey('familia.id'), nullable=False)

# --- CLASE RECUPERADA ---
class Inventario(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    nombre_producto = db.Column(db.String(100), nullable=False)
    cantidad = db.Column(db.Float, default=0.0) 
    precio_costo = db.Column(db.Float, default=0.0)
    familia_id = db.Column(db.Integer, db.ForeignKey('familia.id'), nullable=False)

class Producto(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(100), nullable=False)
    descripcion = db.Column(db.String(200))
    stock = db.Column(db.Float, default=0.0)
    precio_compra = db.Column(db.Float, default=0.0)
    precio_venta = db.Column(db.Float, default=0.0)
    
    categoria_prod = db.Column(db.String(50), default="General")
    plataforma = db.Column(db.String(50)) 
    imagen_url = db.Column(db.String(255), default='default_product.png')
    
    usuario_id = db.Column(db.Integer, db.ForeignKey('usuario.id')) 
    familia_id = db.Column(db.Integer, db.ForeignKey('familia.id'))
    categoria_prod_id = db.Column(db.Integer, db.ForeignKey('categoria_producto.id'), nullable=True)
    
    movimientos_inv = db.relationship('MovimientoInventario', backref='producto', lazy=True, cascade="all, delete-orphan")

    def __repr__(self):
        return f'<Producto {self.nombre}>'

class MovimientoInventario(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    producto_id = db.Column(db.Integer, db.ForeignKey('producto.id'))
    tipo = db.Column(db.String(10), nullable=False) # 'ENTRADA' o 'SALIDA'
    cantidad = db.Column(db.Float, nullable=False)
    fecha = db.Column(db.DateTime, default=hora_mexico)
    monto_total = db.Column(db.Float) 
    
class CategoriaProducto(db.Model):
    __tablename__ = 'categoria_producto'
    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(50), nullable=False)
    productos = db.relationship('Producto', backref='categoria_rel', lazy=True)
    
class PagoPendiente(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    descripcion = db.Column(db.String(200), nullable=False)
    monto = db.Column(db.Float, nullable=False)
    fecha_limite = db.Column(db.Date)
    estatus = db.Column(db.String(20), default='pendiente') # 'pendiente' o 'pagado'
    prioridad = db.Column(db.String(10), default='media') # 'alta', 'media', 'baja'
    familia_id = db.Column(db.Integer, db.ForeignKey('familia.id'), nullable=False)