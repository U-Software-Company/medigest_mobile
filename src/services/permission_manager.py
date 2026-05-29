# services/permission_manager.py
"""
Gestionnaire de permissions pour l'application
Contrôle l'accès aux écrans/screens selon les permissions utilisateur
"""
import flet as ft
import logging
from typing import Dict, List, Optional, Any
from functools import wraps

logger = logging.getLogger(__name__)


class PermissionManager:
    """Gestionnaire central des permissions utilisateur"""
    
    # Mapping permission -> écran/screen
    PERMISSION_SCREENS = {
        # Ventes
        "can_sell": "sale_screen",
        "can_view_sales_history": "history_screen",
        "can_cancel_sale": "cancel_sale_action",
        
        # Produits
        "can_view_products": "products_screen",
        "can_add_product": "add_product_screen",
        "can_edit_product": "product_details_screen",
        "can_edit_stock": "stock_adjust_screen",
        "can_edit_price": "price_edit_screen",
        "can_delete_product": "delete_product_action",
        
        # Rapports
        "can_view_sales_reports": "sales_report_screen",
        "can_view_stock_reports": "stock_report_screen",
        "can_view_financial_reports": "cash_report_screen",
        
        # Finances
        "can_view_expenses": "expense_screen",
        "can_add_expense": "add_expense_screen",
        "can_view_debts": "debt_screen",
        "can_manage_debts": "debt_detail_screen",
        
        # Facturation
        "can_view_invoices": "invoice_screen",
        "can_print_invoice": "print_invoice_action",
        
        # Administration
        "can_manage_users": "user_management_screen",
        "can_manage_permissions": "permission_screen",
        "can_manage_branches": "branch_switch_screen",
        "can_view_sync": "sync_screen",
        "can_configure_system": "config_screen",
        
        # Inventaire
        "can_do_inventory": "inventory_screen",
        "can_export_data": "export_screen",
    }
    
    # Menu du sidebar avec leurs permissions requises
    SIDEBAR_MENU_ITEMS = [
        {"key": "dashboard", "label": "Tableau de bord", "icon": "DASHBOARD", "permission": None},
        {"key": "sale", "label": "Vente", "icon": "SHOPPING_CART", "permission": "can_sell"},
        {"key": "history", "label": "Historique", "icon": "HISTORY", "permission": "can_view_sales_history"},
        {"key": "products", "label": "Produits", "icon": "INVENTORY", "permission": "can_view_products"},
        {"key": "cash", "label": "Trésorerie", "icon": "PAYMENT", "permission": "can_view_financial_reports"},
        {"key": "expenses", "label": "Dépenses", "icon": "MONEY_OFF", "permission": "can_view_expenses"},
        {"key": "debts", "label": "Dettes", "icon": "ACCOUNT_BALANCE_WALLET", "permission": "can_view_debts"},
        {"key": "invoice", "label": "Factures", "icon": "RECEIPT", "permission": "can_view_invoices"},
        {"key": "stock", "label": "Rapport stock", "icon": "ASSESSMENT", "permission": "can_view_stock_reports"},
        {"key": "inventory", "label": "Inventaire", "icon": "CHECKLIST", "permission": "can_do_inventory"},
        {"key": "abo", "label": "Abonnement", "icon": "SUBSCRIPTIONS", "permission": None},
        {"key": "sync", "label": "Synchronisation", "icon": "SYNC", "permission": "can_view_sync"},
        {"key": "branch", "label": "Changer succursale", "icon": "STORE", "permission": "can_manage_branches"},
        {"key": "users", "label": "Utilisateurs", "icon": "PEOPLE", "permission": "can_manage_users"},
        {"key": "permissions", "label": "Permissions", "icon": "SECURITY", "permission": "can_manage_permissions"},
        {"key": "config", "label": "Configuration", "icon": "SETTINGS", "permission": "can_configure_system"},
        {"key": "export", "label": "Exporter", "icon": "DOWNLOAD", "permission": "can_export_data"},
    ]
    
    def __init__(self, db_manager, auth_service):
        self.db = db_manager
        self.auth_service = auth_service
        self._permissions_cache = {}
        self._init_tables()
    
    def _init_tables(self):
        """Initialise les tables nécessaires"""
        try:
            if hasattr(self.db, 'init_permissions_tables'):
                self.db.init_permissions_tables()
            elif hasattr(self.db, 'get_connection'):
                # Initialisation directe si la méthode n'existe pas
                with self.db.get_connection() as conn:
                    cursor = conn.cursor()
                    cursor.execute("""
                        CREATE TABLE IF NOT EXISTS user_permissions (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            user_id TEXT NOT NULL,
                            branch_id TEXT NOT NULL,
                            permission_key TEXT NOT NULL,
                            is_allowed INTEGER DEFAULT 0,
                            granted_by TEXT,
                            granted_at TEXT,
                            updated_at TEXT,
                            UNIQUE(user_id, branch_id, permission_key)
                        )
                    """)
                    cursor.execute("""
                        CREATE TABLE IF NOT EXISTS branch_users (
                            id TEXT PRIMARY KEY,
                            full_name TEXT,
                            email TEXT,
                            role TEXT,
                            branch_id TEXT,
                            is_active INTEGER DEFAULT 1,
                            updated_at TEXT
                        )
                    """)
                    conn.commit()
        except Exception as e:
            logger.error(f"Erreur _init_tables: {e}")
    
    def get_user_permissions(self, user_id: str = None, branch_id: str = None) -> Dict[str, bool]:
        """
        Récupère toutes les permissions d'un utilisateur
        
        Args:
            user_id: ID de l'utilisateur (par défaut: utilisateur courant)
            branch_id: ID de la branche (par défaut: branche active)
        
        Returns:
            Dictionnaire des permissions
        """
        # Si pas d'ID, utiliser l'utilisateur courant
        if not user_id:
            current_user = self.auth_service.get_current_user()
            if not current_user:
                return {}
            user_id = current_user.get('id')
            
            # Vérifier le cache
            if user_id in self._permissions_cache:
                cache_time = self._permissions_cache[user_id].get('_cached_at', 0)
                from datetime import datetime
                if (datetime.now().timestamp() - cache_time) < 60:  # Cache 60 secondes
                    cached = self._permissions_cache[user_id].copy()
                    cached.pop('_cached_at', None)
                    return cached
        
        # Déterminer la branche
        if not branch_id:
            current_user = self.auth_service.get_current_user()
            if current_user:
                branch_id = current_user.get('active_branch_id') or current_user.get('branch_id')
        
        # Récupérer le rôle de l'utilisateur
        user_role = self._get_user_role(user_id)
        
        # Récupérer les permissions depuis la base
        permissions = self._load_permissions_from_db(user_id, branch_id)
        
        # Vérifier aussi dans l'utilisateur courant (pour les permissions en mémoire)
        if not permissions:
            current_user = self.auth_service.get_current_user()
            if current_user and str(current_user.get('id')) == str(user_id):
                permissions = current_user.get('permissions', {})
        
        # Si toujours rien, utiliser les permissions par défaut basées sur le rôle
        if not permissions:
            from screens.permission_screen import PermissionScreen
            permissions = PermissionScreen.DEFAULT_ROLE_PERMISSIONS.get(user_role, {})
        
        # ✅ ADMIN: S'assurer que toutes les permissions sont à True
        if user_role == 'admin':
            # Toutes les permissions possibles
            all_permissions = [
                "can_sell", "can_view_sales_history", "can_cancel_sale",
                "can_view_products", "can_add_product", "can_edit_product",
                "can_edit_stock", "can_edit_price", "can_delete_product",
                "can_view_sales_reports", "can_view_stock_reports", "can_view_financial_reports",
                "can_view_expenses", "can_add_expense", "can_view_debts",
                "can_manage_debts", "can_view_invoices", "can_print_invoice",
                "can_manage_users", "can_manage_permissions", "can_manage_branches",
                "can_view_sync", "can_configure_system", "can_do_inventory", "can_export_data"
            ]
            
            # Forcer toutes les permissions à True pour admin
            for perm in all_permissions:
                permissions[perm] = True
            
            logger.info(f"✅ Admin {user_id} - Toutes les permissions activées (y compris can_manage_permissions)")
        
        # Mettre en cache
        self._permissions_cache[user_id] = permissions.copy()
        self._permissions_cache[user_id]['_cached_at'] = __import__('datetime').datetime.now().timestamp()
        
        return permissions
    
    def _load_permissions_from_db(self, user_id: str, branch_id: str) -> Dict[str, bool]:
        """Charge les permissions depuis la base de données"""
        permissions = {}
        
        try:
            if hasattr(self.db, 'get_user_permissions'):
                permissions = self.db.get_user_permissions(user_id, branch_id)
            else:
                # Fallback direct
                with self.db.get_connection() as conn:
                    cursor = conn.cursor()
                    cursor.execute("""
                        SELECT permission_key, is_allowed 
                        FROM user_permissions 
                        WHERE user_id = ? AND branch_id = ?
                    """, (user_id, branch_id))
                    rows = cursor.fetchall()
                    for row in rows:
                        permissions[row['permission_key']] = bool(row['is_allowed'])
                    
        except Exception as e:
            logger.error(f"Erreur chargement permissions DB: {e}")
        
        return permissions
    
    def _get_user_role(self, user_id: str) -> str:
        """Récupère le rôle d'un utilisateur"""
        try:
            with self.db.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT role FROM branch_users WHERE id = ?", (user_id,))
                row = cursor.fetchone()
                if row:
                    return row['role']
        except Exception as e:
            logger.error(f"Erreur récupération rôle: {e}")
        
        # Par défaut
        return 'cashier'
    
    def has_permission(self, permission_key: str) -> bool:
        """
        Vérifie si l'utilisateur courant a une permission spécifique
        
        Args:
            permission_key: Clé de la permission (ex: 'can_sell')
        
        Returns:
            True si l'utilisateur a la permission
        """
        permissions = self.get_user_permissions()
        return permissions.get(permission_key, False)
    
    def can_access_screen(self, screen_name: str) -> bool:
        """
        Vérifie si l'utilisateur courant peut accéder à un écran
        
        Args:
            screen_name: Nom de l'écran (ex: 'sale_screen')
        
        Returns:
            True si l'utilisateur peut accéder
        """
        # Trouver la permission correspondant à l'écran
        for perm_key, screen in self.PERMISSION_SCREENS.items():
            if screen == screen_name:
                return self.has_permission(perm_key)
        
        # Écrans sans permission requise (toujours accessibles)
        public_screens = ['dashboard', 'login', 'abonnement']
        if screen_name in public_screens:
            return True
        
        # Par défaut, refuser l'accès
        logger.warning(f"Accès non autorisé à l'écran {screen_name}")
        return False
    
    def get_accessible_menu_items(self) -> List[Dict]:
        """
        Récupère les éléments du menu auxquels l'utilisateur a accès
        
        Returns:
            Liste des menus accessibles
        """
        accessible_items = []
        
        for item in self.SIDEBAR_MENU_ITEMS:
            permission = item.get('permission')
            
            # Pas de permission requise
            if permission is None:
                accessible_items.append(item)
            # Permission spécifique
            elif self.has_permission(permission):
                accessible_items.append(item)
        
        return accessible_items
    
    def get_accessible_actions(self, context: str = None) -> List[str]:
        """
        Récupère les actions accessibles dans un contexte donné
        
        Args:
            context: Contexte (ex: 'product_list', 'sale_cart')
        
        Returns:
            Liste des actions autorisées
        """
        actions = []
        
        # Actions sur les produits
        if context == 'product_list':
            if self.has_permission('can_add_product'):
                actions.append('add_product')
            if self.has_permission('can_edit_product'):
                actions.append('edit_product')
            if self.has_permission('can_delete_product'):
                actions.append('delete_product')
            if self.has_permission('can_edit_stock'):
                actions.append('adjust_stock')
            if self.has_permission('can_edit_price'):
                actions.append('edit_price')
        
        # Actions sur les ventes
        elif context == 'sale':
            if self.has_permission('can_sell'):
                actions.append('create_sale')
            if self.has_permission('can_cancel_sale'):
                actions.append('cancel_sale')
        
        # Actions sur l'historique des ventes
        elif context == 'sales_history':
            if self.has_permission('can_view_sales_history'):
                actions.append('view_history')
            if self.has_permission('can_cancel_sale'):
                actions.append('cancel_sale')
            if self.has_permission('can_print_invoice'):
                actions.append('print_invoice')
        
        # Actions sur les dépenses
        elif context == 'expenses':
            if self.has_permission('can_view_expenses'):
                actions.append('view_expenses')
            if self.has_permission('can_add_expense'):
                actions.append('add_expense')
        
        # Actions sur les dettes
        elif context == 'debts':
            if self.has_permission('can_view_debts'):
                actions.append('view_debts')
            if self.has_permission('can_manage_debts'):
                actions.append('manage_debts')
        
        # Actions sur les factures
        elif context == 'invoices':
            if self.has_permission('can_view_invoices'):
                actions.append('view_invoices')
            if self.has_permission('can_print_invoice'):
                actions.append('print_invoice')
        
        # Actions d'export
        elif context == 'export':
            if self.has_permission('can_export_data'):
                actions.append('export_data')
        
        return actions
    
    def clear_cache(self, user_id: str = None):
        """Vide le cache des permissions"""
        if user_id:
            self._permissions_cache.pop(user_id, None)
        else:
            self._permissions_cache.clear()
    
    def get_user_role_name(self) -> str:
        """Récupère le nom du rôle de l'utilisateur courant"""
        current_user = self.auth_service.get_current_user()
        if current_user:
            role = current_user.get('role', 'cashier')
            role_names = {
                'admin': 'Administrateur',
                'super_admin': 'Super Administrateur',
                'manager': 'Gestionnaire',
                'pharmacist': 'Pharmacien',
                'cashier': 'Caissier',
                'read_only': 'Lecture seule'
            }
            return role_names.get(role.lower(), role)
        return 'Utilisateur'


# Décorateur pour protéger les méthodes des écrans
def require_permission(permission_key: str):
    """
    Décorateur pour vérifier une permission avant d'exécuter une méthode
    
    Utilisation:
        @require_permission('can_edit_product')
        def edit_product(self, e):
            ...
    """
    def decorator(func):
        @wraps(func)
        def wrapper(self, *args, **kwargs):
            # Récupérer le permission_manager depuis l'instance
            permission_manager = getattr(self, 'permission_manager', None)
            
            if permission_manager is None:
                # Essayer de récupérer depuis les services globaux
                import sys
                for item in sys.modules.values():
                    if hasattr(item, 'permission_manager'):
                        permission_manager = item.permission_manager
                        break
            
            if permission_manager and permission_manager.has_permission(permission_key):
                return func(self, *args, **kwargs)
            else:
                # Afficher un message d'erreur
                if hasattr(self, '_show_snackbar'):
                    self._show_snackbar("Vous n'avez pas la permission d'effectuer cette action", 
                                       "red" if hasattr(self, 'page') else None)
                elif hasattr(self, 'page') and hasattr(self.page, 'show_snack_bar'):
                    snack = ft.SnackBar(content=ft.Text("Permission refusée"))
                    self.page.show_snack_bar(snack)
                else:
                    print(f"Permission refusée: {permission_key}")
                return None
        
        return wrapper
    return decorator