"""
Constantes globales pour l'application mobile
"""

# URLs
BASE_URL = "https://my-backend-ydit.onrender.com"
API_URL = f"{BASE_URL}/api/v1"
FRONTEND_URL = "https://medigestpro.net"

# Endpoints
ENDPOINTS = {
    "login": f"{API_URL}/auth/login",
    "logout": f"{API_URL}/auth/logout",
    "refresh": f"{API_URL}/auth/refresh",
    "sync_push": f"{API_URL}/sync/",
    "sync_pull": f"{API_URL}/sync/pull",
    "sync_status": f"{API_URL}/sync/status",
    "sync_health": f"{API_URL}/sync/health",
    "sync_batch": f"{API_URL}/sync/batch",
    "products": f"{API_URL}/stock",
    "sales": f"{API_URL}/sales",
    "sales_batch": f"{API_URL}/sales/batch",
    "branches": f"{API_URL}/branches",
    "health": f"{BASE_URL}/health",
}

# Noms des tables (pour synchronisation)
TABLE_NAMES = {
    "products": "products",
    "produits": "products",
    "produit": "products",
    "categories": "categories",
    "categorie": "categories",
    "sales": "sales",
    "ventes": "sales",
    "vente": "sales",
    "expenses": "expenses",
    "depenses": "expenses",
    "depense": "expenses",
    "customers": "customers",
    "clients": "customers",
    "client": "customers",
}

# Actions de synchronisation
SYNC_ACTIONS = {
    "create": "create",
    "update": "update",
    "delete": "delete",
    "upsert": "upsert",
}

# Statuts de synchronisation
SYNC_STATUS = {
    "pending": 0,
    "synced": 1,
    "error": 2,
}

# Rôles utilisateurs
USER_ROLES = {
    "admin": "admin",
    "manager": "manager",
    "seller": "seller",
    "viewer": "viewer",
}

# Types de transactions
TRANSACTION_TYPES = {
    "sale": "vente",
    "expense": "depense",
    "debt": "dette",
    "payment": "paiement",
}

# Chemins des fichiers locaux
LOCAL_STORAGE_PATHS = {
    "user": "current_user.json",
    "settings": "app_settings.json",
    "sync_log": "sync_log.json",
    "cache": "cache/",
}

# Paramètres de synchronisation
SYNC_CONFIG = {
    "max_retries": 3,
    "retry_delay": 5,  # secondes
    "batch_size": 100,
    "timeout": 30,
    "max_concurrent": 5,
}

# Paramètres de l'application
APP_CONFIG = {
    "name": "MediGest Mobile",
    "version": "1.0.0",
    "offline_mode": True,
    "auto_sync": True,
    "sync_interval": 300,  # secondes (5 minutes)
    "max_offline_days": 30,
    "database_name": "medigest_local.db",
}

# Messages d'erreur
ERROR_MESSAGES = {
    "network": "Pas de connexion Internet",
    "auth": "Session expirée, veuillez vous reconnecter",
    "sync_failed": "Échec de la synchronisation",
    "data_error": "Erreur de données",
    "server_error": "Erreur serveur, veuillez réessayer plus tard",
}

# Messages de succès
SUCCESS_MESSAGES = {
    "sync_success": "Synchronisation réussie",
    "sale_saved": "Vente enregistrée localement",
    "data_imported": "Données importées avec succès",
}

# Formats de date
DATE_FORMATS = {
    "iso": "%Y-%m-%dT%H:%M:%S",
    "iso_with_ms": "%Y-%m-%dT%H:%M:%S.%f",
    "date": "%Y-%m-%d",
    "datetime": "%d/%m/%Y %H:%M",
    "date_fr": "%d/%m/%Y",
    "time": "%H:%M:%S",
}

# Thèmes de l'application
THEMES = {
    "light": {
        "primary": "#1976D2",
        "secondary": "#42A5F5",
        "success": "#4CAF50",
        "error": "#F44336",
        "warning": "#FF9800",
        "info": "#2196F3",
        "background": "#FFFFFF",
        "surface": "#F5F5F5",
        "text": "#333333",
        "text_secondary": "#666666",
    },
    "dark": {
        "primary": "#90CAF9",
        "secondary": "#64B5F6",
        "success": "#81C784",
        "error": "#E57373",
        "warning": "#FFB74D",
        "info": "#64B5F6",
        "background": "#121212",
        "surface": "#1E1E1E",
        "text": "#FFFFFF",
        "text_secondary": "#B0B0B0",
    }
}