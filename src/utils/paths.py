import os
import sys


def get_app_dir():
    """
    Retourne le répertoire de l'application de manière sécurisée sur tous les OS.
    
    - Android: Stockage interne privé de l'application (Sandbox)
    - Windows: %APPDATA%/MediGestPro
    - macOS: ~/Library/Application Support/MediGestPro
    - Linux: ~/.local/share/MediGestPro
    """
    # 1. Détection d'Android (Flet Mobile s'exécute souvent avec la variable d'environnement HOME configurée)
    # On vérifie aussi si "android" est présent dans le platform ou si les variables d'environnement spécifiques existent
    is_android = (
        sys.platform == "linux" and 
        (os.environ.get("ANDROID_ROOT") is not None or os.environ.get("ANDROID_DATA") is not None)
    )

    if is_android:
        # Sur Android, la variable HOME pointe vers le stockage privé de l'application
        # Si elle est absente, on utilise le dossier temporaire par défaut d'Android
        base = os.environ.get("HOME", os.environ.get("TMPDIR", "/data/data/"))
        app_dir = os.path.join(base, "MediGestPro")
        
    # 2. Détection des systèmes de bureau (Desktop)
    elif sys.platform == "win32":
        base = os.getenv("APPDATA", os.path.expanduser("~"))
        app_dir = os.path.join(base, "MediGestPro")
    elif sys.platform == "darwin":  # macOS
        base = os.path.join(os.path.expanduser("~"), "Library", "Application Support")
        app_dir = os.path.join(base, "MediGestPro")
    else:  # Linux Bureau standard
        base = os.path.join(os.path.expanduser("~"), ".local", "share")
        app_dir = os.path.join(base, "MediGestPro")
    
    # Crée le dossier si nécessaire (autorisé sur Android uniquement dans ce dossier "HOME")
    try:
        os.makedirs(app_dir, exist_ok=True)
    except PermissionError:
        # Solution de secours ultime si les dossiers personnalisés échouent sur mobile
        if is_android:
            import tempfile
            app_dir = os.path.join(tempfile.gettempdir(), "MediGestPro")
            os.makedirs(app_dir, exist_ok=True)
            
    return app_dir


def get_db_path():
    """Chemin vers la base de données SQLite principale."""
    return os.path.join(get_app_dir(), "pos_app.db")


def get_backup_path():
    """Chemin vers la sauvegarde de la base de données."""
    return os.path.join(get_app_dir(), "backup.db")


def get_storage_dir():
    """Retourne le répertoire de stockage pour les fichiers JSON."""
    storage_dir = os.path.join(get_app_dir(), "storage")
    os.makedirs(storage_dir, exist_ok=True)
    return storage_dir


def get_user_data_path():
    """Chemin vers le fichier de données utilisateur (fallback JSON)."""
    return os.path.join(get_app_dir(), "current_user.json")
