# StemCash 💰

**StemCash** es una plataforma web funcional diseñada para la gestión financiera personal y el control operativo de microempresas. El objetivo principal de este proyecto es resolver problemas reales de administración mediante una arquitectura de software robusta, lógica de negocio sólida y automatización de reportes clave.

🚀 **Link del proyecto desplegado:** [stemcash.onrender.com](https://stemcash.onrender.com)

---

## 🛠️ Stack Tecnológico

El proyecto está construido utilizando tecnologías modernas, eficientes y altamente escalables:

### Backend y Lógica de Negocio
* **Lenguaje:** [Python 3.11+](https://www.python.org/)
* **Framework Web:** [Flask](https://flask.palletsprojects.com/) (Control de rutas, lógica del dashboard y autenticación).
* **ORM:** [SQLAlchemy](https://www.sqlalchemy.org/) (Gestión y abstracción de la base de datos mediante programación orientada a objetos).

### Frontend (Interfaz de Usuario)
* **Estructura y Estilos:** HTML5 y CSS3 (Diseño responsivo y limpio).
* **Motor de Plantillas:** [Jinja2](https://jinja.palletsprojects.com/) (Renderizado dinámico de datos desde el backend hacia las vistas del usuario).

### Base de Datos y Almacenamiento
* **Motor de BD:** [PostgreSQL](https://www.postgresql.org/)
* **Hosting de Datos:** [Neon.tech](https://neon.tech/) (Plataforma de base de datos serverless en la nube, optimizada para rendimiento y escalabilidad).

### Infraestructura y Despliegue
* **Control de Versiones:** [GitHub](https://github.com/)
* **Servicio de Hosting:** [Render](https://render.com/) (Despliegue automatizado y continuo).

---

## 🚀 Arquitectura del Proyecto

A continuación se muestra la estructura base utilizada para el entorno Flask:

```text
stemcash/
│
├── app/
│   ├── __init__.py          # Inicialización de la app, Flask y SQLAlchemy
│   ├── models.py            # Modelos de la base de datos (PostgreSQL)
│   ├── routes.py            # Definición de rutas y lógica de control
│   ├── static/              # Archivos estáticos (CSS, JS, Imágenes)
│   │   └── css/
│   │       └── styles.css
│   └── templates/           # Vistas y plantillas Jinja2
│       ├── base.html
│       ├── dashboard.html
│       └── login.html
│
├── config.py                # Configuración de variables de entorno y BD
├── requirements.txt         # Dependencias del proyecto
├── run.py                   # Punto de entrada de la aplicación
└── README.md                # Documentación del proyecto
