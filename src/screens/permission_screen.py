# screens/permission_screen.py
"""
Écran de gestion des permissions utilisateur (réservé à l'admin)
Permet d'assigner des interfaces/screens aux utilisateurs selon leur rôle
"""

import flet as ft
from datetime import datetime
import logging
from typing import Dict, List, Optional, Any
import threading
import requests

logger = logging.getLogger(__name__)


class PermissionScreen:
    """
    Écran de gestion des permissions - Réservé aux administrateurs
    Chaque permission correspond à l'accès à une interface/screen
    """
    
    # Définition des permissions disponibles (interface = permission)
    PERMISSIONS = {
        # Ventes
        "can_sell": {
            "label": "💰 Vendre",
            "description": "Accès à l'écran de vente (SaleScreen)",
            "screen": "sale_screen",
            "icon": ft.Icons.SHOPPING_CART,
            "category": "Ventes",
            "order": 1
        },
        "can_cancel_sale": {
            "label": "❌ Annuler une vente",
            "description": "Permission d'annuler des ventes",
            "screen": None,
            "icon": ft.Icons.CANCEL,
            "category": "Ventes",
            "order": 2
        },
        "can_view_sales_history": {
            "label": "📜 Historique des ventes",
            "description": "Accès à l'historique des ventes",
            "screen": "history_screen",
            "icon": ft.Icons.HISTORY,
            "category": "Ventes",
            "order": 3
        },
        
        # Produits
        "can_view_products": {
            "label": "📦 Voir les produits",
            "description": "Accès à la liste des produits",
            "screen": "products_screen",
            "icon": ft.Icons.INVENTORY,
            "category": "Produits",
            "order": 4
        },
        "can_add_product": {
            "label": "➕ Ajouter un produit",
            "description": "Permission d'ajouter de nouveaux produits",
            "screen": "add_product_screen",
            "icon": ft.Icons.ADD,
            "category": "Produits",
            "order": 5
        },
        "can_edit_product": {
            "label": "✏️ Modifier produit",
            "description": "Modifier les informations des produits (prix, nom, etc.)",
            "screen": "product_details_screen",
            "icon": ft.Icons.EDIT,
            "category": "Produits",
            "order": 6
        },
        "can_edit_stock": {
            "label": "📊 Modifier le stock",
            "description": "Ajuster manuellement les quantités en stock",
            "screen": "stock_adjust_screen",
            "icon": ft.Icons.STACKED_BAR_CHART,
            "category": "Produits",
            "order": 7
        },
        "can_edit_price": {
            "label": "🏷️ Modifier les prix",
            "description": "Modifier les prix de vente des produits",
            "screen": "price_edit_screen",
            "icon": ft.Icons.PRICE_CHANGE,
            "category": "Produits",
            "order": 8
        },
        "can_delete_product": {
            "label": "🗑️ Supprimer produit",
            "description": "Supprimer définitivement un produit",
            "screen": None,
            "icon": ft.Icons.DELETE,
            "category": "Produits",
            "order": 9
        },
        
        # Rapports
        "can_view_sales_reports": {
            "label": "📈 Rapports de ventes",
            "description": "Accès aux rapports et statistiques de ventes",
            "screen": "sales_report_screen",
            "icon": ft.Icons.BAR_CHART,
            "category": "Rapports",
            "order": 10
        },
        "can_view_stock_reports": {
            "label": "📊 Rapports de stock",
            "description": "Accès aux rapports d'inventaire",
            "screen": "stock_report_screen",
            "icon": ft.Icons.ASSESSMENT,
            "category": "Rapports",
            "order": 11
        },
        "can_view_financial_reports": {
            "label": "💰 Rapports financiers",
            "description": "Accès aux rapports financiers (trésorerie)",
            "screen": "cash_report_screen",
            "icon": ft.Icons.PAYMENT,
            "category": "Rapports",
            "order": 12
        },
        
        # Finances
        "can_view_expenses": {
            "label": "💸 Voir les dépenses",
            "description": "Accès à la gestion des dépenses",
            "screen": "expense_screen",
            "icon": ft.Icons.MONEY_OFF,
            "category": "Finances",
            "order": 13
        },
        "can_add_expense": {
            "label": "➕ Ajouter une dépense",
            "description": "Ajouter de nouvelles dépenses",
            "screen": "add_expense_screen",
            "icon": ft.Icons.ADD_CARD,
            "category": "Finances",
            "order": 14
        },
        "can_view_debts": {
            "label": "📋 Voir les dettes",
            "description": "Accès à la gestion des dettes clients",
            "screen": "debt_screen",
            "icon": ft.Icons.ACCOUNT_BALANCE_WALLET,
            "category": "Finances",
            "order": 15
        },
        "can_manage_debts": {
            "label": "💳 Gérer les dettes",
            "description": "Encaisser des paiements, modifier des dettes",
            "screen": "debt_detail_screen",
            "icon": ft.Icons.PAYMENT,
            "category": "Finances",
            "order": 16
        },
        
        # Facturation
        "can_view_invoices": {
            "label": "🧾 Voir les factures",
            "description": "Accès à la liste des factures",
            "screen": "invoice_screen",
            "icon": ft.Icons.RECEIPT,
            "category": "Facturation",
            "order": 17
        },
        "can_print_invoice": {
            "label": "🖨️ Imprimer les factures",
            "description": "Permission d'imprimer les factures",
            "screen": None,
            "icon": ft.Icons.PRINT,
            "category": "Facturation",
            "order": 18
        },
        
        # Administration
        "can_manage_users": {
            "label": "👥 Gérer les utilisateurs",
            "description": "Ajouter/modifier/supprimer des utilisateurs",
            "screen": "user_management_screen",
            "icon": ft.Icons.PEOPLE,
            "category": "Administration",
            "order": 19
        },
        "can_manage_permissions": {
            "label": "🔐 Gérer les permissions",
            "description": "Accès à cet écran de gestion des permissions",
            "screen": "permission_screen",
            "icon": ft.Icons.SECURITY,
            "category": "Administration",
            "order": 20
        },
        "can_manage_branches": {
            "label": "🏢 Gérer les succursales",
            "description": "Accès à la gestion des succursales",
            "screen": "branch_switch_screen",
            "icon": ft.Icons.STORE,
            "category": "Administration",
            "order": 21
        },
        "can_view_sync": {
            "label": "🔄 Synchronisation",
            "description": "Accès à l'écran de synchronisation",
            "screen": "sync_screen",
            "icon": ft.Icons.SYNC,
            "category": "Administration",
            "order": 22
        },
        "can_configure_system": {
            "label": "⚙️ Configuration système",
            "description": "Accès à la configuration de l'application",
            "screen": "config_screen",
            "icon": ft.Icons.SETTINGS,
            "category": "Administration",
            "order": 23
        },
        
        # Inventaire
        "can_do_inventory": {
            "label": "📋 Faire l'inventaire",
            "description": "Accès à l'écran d'inventaire (comptage physique)",
            "screen": "inventory_screen",
            "icon": ft.Icons.CHECKLIST,
            "category": "Inventaire",
            "order": 24
        },
        "can_export_data": {
            "label": "📤 Exporter les données",
            "description": "Exporter des rapports en CSV/Excel",
            "screen": "export_screen",
            "icon": ft.Icons.DOWNLOAD,
            "category": "Administration",
            "order": 25
        },
    }
    
    # Rôles prédéfinis avec leurs permissions par défaut
    DEFAULT_ROLE_PERMISSIONS = {
        "admin": {
            "can_sell": True,
            "can_cancel_sale": True,
            "can_view_sales_history": True,
            "can_view_products": True,
            "can_add_product": True,
            "can_edit_product": True,
            "can_edit_stock": True,
            "can_edit_price": True,
            "can_delete_product": True,
            "can_view_sales_reports": True,
            "can_view_stock_reports": True,
            "can_view_financial_reports": True,
            "can_view_expenses": True,
            "can_add_expense": True,
            "can_view_debts": True,
            "can_manage_debts": True,
            "can_view_invoices": True,
            "can_print_invoice": True,
            "can_manage_users": True,
            "can_manage_permissions": True,
            "can_manage_branches": True,
            "can_view_sync": True,
            "can_configure_system": True,
            "can_do_inventory": True,
            "can_export_data": True,
        },
        "manager": {
            "can_sell": True,
            "can_cancel_sale": True,
            "can_view_sales_history": True,
            "can_view_products": True,
            "can_add_product": True,
            "can_edit_product": True,
            "can_edit_stock": True,
            "can_edit_price": True,
            "can_view_sales_reports": True,
            "can_view_stock_reports": True,
            "can_view_financial_reports": True,
            "can_view_expenses": True,
            "can_add_expense": True,
            "can_view_debts": True,
            "can_manage_debts": True,
            "can_view_invoices": True,
            "can_print_invoice": True,
            "can_view_sync": True,
            "can_do_inventory": True,
            "can_export_data": True,
            "can_manage_users": False,
            "can_manage_permissions": False,
            "can_manage_branches": False,
            "can_configure_system": False,
            "can_delete_product": False,
        },
        "pharmacist": {
            "can_sell": True,
            "can_view_sales_history": True,
            "can_view_products": True,
            "can_edit_stock": True,
            "can_view_sales_reports": True,
            "can_view_stock_reports": True,
            "can_do_inventory": True,
            "can_view_invoices": True,
            "can_cancel_sale": False,
            "can_add_product": False,
            "can_edit_product": False,
            "can_edit_price": False,
            "can_delete_product": False,
            "can_view_financial_reports": False,
            "can_view_expenses": False,
            "can_add_expense": False,
            "can_view_debts": False,
            "can_manage_debts": False,
            "can_print_invoice": False,
            "can_manage_users": False,
            "can_manage_permissions": False,
            "can_manage_branches": False,
            "can_view_sync": False,
            "can_configure_system": False,
            "can_export_data": False,
        },
        "cashier": {
            "can_sell": True,
            "can_view_invoices": True,
            "can_view_sales_history": True,
            "can_view_products": True,
            "can_cancel_sale": False,
            "can_add_product": False,
            "can_edit_product": False,
            "can_edit_stock": False,
            "can_edit_price": False,
            "can_delete_product": False,
            "can_view_sales_reports": False,
            "can_view_stock_reports": False,
            "can_view_financial_reports": False,
            "can_view_expenses": True,
            "can_add_expense": True,
            "can_view_debts": True,
            "can_manage_debts": True,
            "can_print_invoice": False,
            "can_manage_users": False,
            "can_manage_permissions": False,
            "can_manage_branches": False,
            "can_view_sync": False,
            "can_configure_system": False,
            "can_do_inventory": False,
            "can_export_data": False,
        },
        "read_only": {
            "can_view_products": True,
            "can_view_sales_history": True,
            "can_view_invoices": True,
            "can_view_stock_reports": True,
            "can_sell": False,
            "can_cancel_sale": False,
            "can_add_product": False,
            "can_edit_product": False,
            "can_edit_stock": False,
            "can_edit_price": False,
            "can_delete_product": False,
            "can_view_sales_reports": True,
            "can_view_financial_reports": True,
            "can_view_expenses": True,
            "can_add_expense": False,
            "can_view_debts": True,
            "can_manage_debts": False,
            "can_print_invoice": False,
            "can_manage_users": False,
            "can_manage_permissions": False,
            "can_manage_branches": False,
            "can_view_sync": False,
            "can_configure_system": False,
            "can_do_inventory": False,
            "can_export_data": False,
        }
    }
    
    def __init__(
        self,
        page: ft.Page,
        db_manager,
        sync_service,
        auth_service,
        current_user: Dict,
        notification_manager=None,
        on_back=None
    ):
        self.page = page
        self.db = db_manager
        self.sync_service = sync_service
        self.auth_service = auth_service
        self.current_user = current_user
        self.notification_manager = notification_manager
        self.on_back = on_back
        
        # Vérifier si l'utilisateur est admin
        user_role = current_user.get('role', '').lower() if current_user else ''
        if user_role not in ['admin', 'super_admin', 'superadmin']:
            raise PermissionError("Accès réservé aux administrateurs")
        
        # Conteneur principal
        self.container = ft.Container(expand=True)
        
        # État
        self.users = []
        self.selected_user = None
        self.user_permissions = {}
        self.is_loading = False
        
        # ✅ Remplacer les Column avec scroll par des ListView pour de meilleures performances
        self.permission_list_view = ft.ListView(spacing=10, expand=True, height=400)
        self.user_list_view = ft.ListView(spacing=5, expand=True, height=350)
        
        # Filtres
        self.search_field = ft.TextField(
            hint_text="Rechercher un utilisateur...",
            prefix_icon=ft.Icons.SEARCH,
            border_radius=20,
            expand=True,
            bgcolor=ft.Colors.WHITE,
        )
        self.search_field.on_change = self._filter_users
        
        self.role_filter = ft.Dropdown(
            hint_text="Filtrer par rôle",
            options=[
                ft.dropdown.Option("tous", "Tous les rôles"),
                ft.dropdown.Option("admin", "Administrateur"),
                ft.dropdown.Option("manager", "Gestionnaire"),
                ft.dropdown.Option("pharmacist", "Pharmacien"),
                ft.dropdown.Option("cashier", "Caissier"),
                ft.dropdown.Option("read_only", "Lecture seule"),
            ],
            value="tous",
            width=150,
            bgcolor=ft.Colors.WHITE,
        )
        self.role_filter.on_change = self._filter_users
        
        # Sélecteur de rôle prédéfini
        self.preset_role_dropdown = ft.Dropdown(
            hint_text="Appliquer un rôle prédéfini",
            options=[
                ft.dropdown.Option("", "--- Choisir un rôle ---"),
                ft.dropdown.Option("admin", "Administrateur (toutes permissions)"),
                ft.dropdown.Option("manager", "Gestionnaire"),
                ft.dropdown.Option("pharmacist", "Pharmacien"),
                ft.dropdown.Option("cashier", "Caissier"),
                ft.dropdown.Option("read_only", "Lecture seule"),
            ],
            width=220,
            bgcolor=ft.Colors.WHITE,
        )
        self.preset_role_dropdown.on_change = self._apply_preset_role
        
        # Indicateur de chargement
        self.loading_indicator = ft.ProgressRing(visible=False)
        self.progress_bar = ft.ProgressBar(visible=False) 
        
        self._init_permissions_tables()
        
    def _init_permissions_tables(self):
        """Initialise les tables de permissions"""
        try:
            if hasattr(self.db, 'init_permissions_tables'):
                self.db.init_permissions_tables()
            elif hasattr(self.db, 'get_connection'):
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
                    logger.info("Tables de permissions vérifiées/créées")
        except Exception as e:
            logger.error(f"Erreur init tables permissions: {e}")
    
    def _get_headers(self) -> Optional[Dict]:
        """Récupère les headers d'authentification"""
        if self.auth_service:
            user = self.auth_service.get_current_user()
            if user and user.get('token'):
                return {
                    "Authorization": f"Bearer {user.get('token')}",
                    "Content-Type": "application/json"
                }
        return None
    
    def _load_users_from_server(self) -> List[Dict]:
        """
        Récupère TOUS les utilisateurs du tenant depuis le serveur
        """
        headers = self._get_headers()
        if not headers:
            logger.warning("Impossible de récupérer les headers d'authentification")
            return []
        
        # URL pour récupérer tous les utilisateurs du tenant
        # L'endpoint peut varier selon votre API
        urls_to_try = [
            f"{self.sync_service.api_url}/users/tenant/all" if self.sync_service else None,
            f"{self.sync_service.api_url}/users/all" if self.sync_service else None,
            f"{self.sync_service.api_url}/admin/users" if self.sync_service else None,
            f"{self.sync_service.api_url}/users" if self.sync_service else None,
        ]
        
        # Filtrer les None
        urls_to_try = [url for url in urls_to_try if url]
        
        # Essayer aussi l'endpoint /users/branch/{branch_id}
        branch_id = self.current_user.get('active_branch_id') or self.current_user.get('branch_id')
        if branch_id and self.sync_service:
            urls_to_try.insert(0, f"{self.sync_service.api_url}/users/branch/{branch_id}")
        
        for url in urls_to_try:
            try:
                logger.info(f"Tentative de récupération des utilisateurs depuis: {url}")
                response = self.sync_service.session.get(
                    url,
                    headers=headers,
                    timeout=30
                )
                
                if response.status_code == 200:
                    data = response.json()
                    
                    # Gérer différents formats de réponse
                    if isinstance(data, list):
                        users = data
                    elif isinstance(data, dict):
                        users = data.get('users', data.get('data', data.get('items', [])))
                    else:
                        users = []
                    
                    if users and len(users) > 0:
                        logger.info(f"✅ {len(users)} utilisateurs récupérés depuis {url}")
                        
                        # Enrichir les données utilisateur
                        enriched_users = []
                        for user in users:
                            enriched_user = {
                                'id': str(user.get('id', '')),
                                'full_name': user.get('full_name', user.get('name', user.get('nom_complet', 'Sans nom'))),
                                'name': user.get('name', user.get('full_name', '')),
                                'email': user.get('email', ''),
                                'role': user.get('role', 'cashier').lower(),
                                'is_active': user.get('is_active', user.get('actif', True)),
                                'branch_id': user.get('branch_id', user.get('active_branch_id', branch_id)),
                                'username': user.get('username', user.get('email', '')),
                            }
                            enriched_users.append(enriched_user)
                        
                        # Sauvegarder localement
                        self._save_users_local(enriched_users, branch_id)
                        return enriched_users
                        
            except Exception as e:
                logger.warning(f"Erreur avec l'URL {url}: {e}")
                continue
        
        # Fallback: récupérer depuis la base locale
        logger.info("Fallback: récupération des utilisateurs depuis la base locale")
        return self._load_users_from_local()
    
    def _load_users_from_local(self) -> List[Dict]:
        """Charge les utilisateurs depuis la base locale"""
        branch_id = self.current_user.get('active_branch_id') or self.current_user.get('branch_id')
        
        try:
            if hasattr(self.db, 'get_branch_users'):
                local_users = self.db.get_branch_users(branch_id)
                if local_users and len(local_users) > 0:
                    logger.info(f"Chargé {len(local_users)} utilisateurs depuis la base locale")
                    return local_users
            
            # Fallback: récupérer depuis la table branch_users
            with self.db.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT id, full_name, email, role, branch_id, is_active
                    FROM branch_users 
                    WHERE branch_id = ? OR branch_id IS NULL
                """, (branch_id,))
                rows = cursor.fetchall()
                if rows:
                    users = [dict(row) for row in rows]
                    logger.info(f"Chargé {len(users)} utilisateurs depuis branch_users")
                    return users
            
            # Sinon, retourner l'utilisateur courant
            return [self.current_user]
            
        except Exception as e:
            logger.error(f"Erreur chargement utilisateurs locaux: {e}")
            return [self.current_user]
    
    def _save_users_local(self, users: List[Dict], branch_id: str):
        """Sauvegarde les utilisateurs localement"""
        try:
            with self.db.get_connection() as conn:
                cursor = conn.cursor()
                
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
                
                for user in users:
                    cursor.execute("""
                        INSERT OR REPLACE INTO branch_users 
                        (id, full_name, email, role, branch_id, is_active, updated_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                    """, (
                        user.get('id'),
                        user.get('full_name', user.get('name', '')),
                        user.get('email', ''),
                        user.get('role', 'cashier'),
                        branch_id,
                        1 if user.get('is_active', True) else 0,
                        datetime.now().isoformat()
                    ))
                conn.commit()
                logger.info(f"Sauvegardé {len(users)} utilisateurs localement")
        except Exception as e:
            logger.error(f"Erreur sauvegarde utilisateurs: {e}")
    
    def _get_user_by_id(self, user_id: str) -> Optional[Dict]:
        """Récupère un utilisateur par son ID"""
        for user in self.users:
            if str(user.get('id')) == str(user_id):
                return user
        return None
    
    def _load_user_permissions(self, user_id: str, branch_id: str) -> Dict[str, bool]:
        """Charge les permissions d'un utilisateur"""
        permissions = {}
        
        # Initialiser avec les permissions par défaut basées sur le rôle
        user = self._get_user_by_id(user_id)
        user_role = user.get('role', 'cashier').lower() if user else 'cashier'
        
        # Récupérer les permissions par défaut du rôle
        default_perms = self.DEFAULT_ROLE_PERMISSIONS.get(user_role, {})
        permissions = default_perms.copy()
        
        try:
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
            logger.error(f"Erreur chargement permissions pour {user_id}: {e}")
        
        # S'assurer que toutes les permissions existent
        for perm_key in self.PERMISSIONS.keys():
            if perm_key not in permissions:
                permissions[perm_key] = False
        
        return permissions
    
    def _save_user_permissions(self, user_id: str, branch_id: str, permissions: Dict[str, bool]) -> bool:
        """Sauvegarde les permissions d'un utilisateur"""
        try:
            with self.db.get_connection() as conn:
                cursor = conn.cursor()
                
                for perm_key, is_allowed in permissions.items():
                    cursor.execute("""
                        INSERT OR REPLACE INTO user_permissions 
                        (user_id, branch_id, permission_key, is_allowed, granted_by, granted_at, updated_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                    """, (
                        user_id,
                        branch_id,
                        perm_key,
                        1 if is_allowed else 0,
                        self.current_user.get('id'),
                        datetime.now().isoformat(),
                        datetime.now().isoformat()
                    ))
                conn.commit()
                
            logger.info(f"Permissions sauvegardées pour l'utilisateur {user_id}")
            return True
            
        except Exception as e:
            logger.error(f"Erreur sauvegarde permissions: {e}")
            return False
    
    def _filter_users(self, e=None):
        """Filtre les utilisateurs par recherche et rôle"""
        search_term = self.search_field.value.lower() if self.search_field.value else ""
        role_filter = self.role_filter.value if self.role_filter.value else "tous"
        
        filtered = []
        for user in self.users:
            # Filtre par rôle
            if role_filter != "tous":
                user_role = user.get('role', '').lower()
                if user_role != role_filter:
                    continue
            
            # Filtre par recherche
            if search_term:
                name = user.get('full_name', user.get('name', '')).lower()
                email = user.get('email', '').lower()
                if search_term not in name and search_term not in email:
                    continue
            
            filtered.append(user)
        
        self._update_user_list(filtered)
    
    def _update_user_list(self, users: List[Dict]):
        """Met à jour l'affichage de la liste des utilisateurs"""
        self.user_list_view.controls.clear()
        
        if not users:
            self.user_list_view.controls.append(
                ft.Container(
                    content=ft.Text("Aucun utilisateur trouvé", color=ft.Colors.GREY_600),
                    padding=20,
                    alignment=ft.alignment.center,
                )
            )
        else:
            for user in users:
                user_id = user.get('id')
                user_name = user.get('full_name', user.get('name', 'Sans nom'))
                user_email = user.get('email', '')
                user_role = user.get('role', 'cashier')
                
                role_labels = {
                    'admin': '👑 Admin',
                    'manager': '📋 Manager',
                    'pharmacist': '💊 Pharmacien',
                    'cashier': '💰 Caissier',
                    'read_only': '👁️ Lecture seule'
                }
                role_text = role_labels.get(user_role.lower(), user_role)
                
                is_selected = self.selected_user and str(self.selected_user.get('id')) == str(user_id)
                
                user_item = ft.Container(
                    content=ft.Row([
                        ft.CircleAvatar(
                            content=ft.Text(user_name[0].upper() if user_name else 'U'),
                            bgcolor=ft.Colors.BLUE_300 if not is_selected else ft.Colors.BLUE_700,
                            color=ft.Colors.WHITE,
                            radius=20,
                        ),
                        ft.Column([
                            ft.Text(user_name, weight=ft.FontWeight.BOLD, size=14),
                            ft.Text(user_email, size=11, color=ft.Colors.GREY_600),
                            ft.Text(role_text, size=10, color=ft.Colors.BLUE_600),
                        ], spacing=2, expand=True),
                    ], spacing=10),
                    padding=ft.Padding.all(10),
                    bgcolor=ft.Colors.BLUE_50 if is_selected else ft.Colors.WHITE,
                    border_radius=10,
                    ink=True,
                )
                user_item.on_click = lambda e, u=user: self._select_user(u)
                self.user_list_view.controls.append(user_item)
        
        self.page.update()
    
    def _select_user(self, user: Dict):
        """Sélectionne un utilisateur et charge ses permissions"""
        self.selected_user = user
        branch_id = self.current_user.get('active_branch_id') or self.current_user.get('branch_id')
        
        # Charger les permissions
        self.user_permissions = self._load_user_permissions(user.get('id'), branch_id)
        
        # Mettre à jour l'affichage
        self._update_user_list(self.users)
        self._update_permission_list()
        self._update_selected_user_info()
    
    def _update_selected_user_info(self):
        """Met à jour l'affichage des informations de l'utilisateur sélectionné"""
        if not self.selected_user:
            return
        
        if hasattr(self, 'selected_user_container'):
            user = self.selected_user
            user_name = user.get('full_name', user.get('name', 'Sans nom'))
            user_email = user.get('email', '')
            user_role = user.get('role', 'cashier')
            
            role_labels = {
                'admin': 'Administrateur',
                'manager': 'Gestionnaire',
                'pharmacist': 'Pharmacien',
                'cashier': 'Caissier',
                'read_only': 'Lecture seule'
            }
            
            self.selected_user_container.content = ft.Column([
                ft.Row([
                    ft.CircleAvatar(
                        content=ft.Text(user_name[0].upper() if user_name else 'U', size=24),
                        bgcolor=ft.Colors.BLUE_700,
                        color=ft.Colors.WHITE,
                        radius=30,
                    ),
                    ft.Column([
                        ft.Text(user_name, size=18, weight=ft.FontWeight.BOLD),
                        ft.Text(user_email, size=12, color=ft.Colors.GREY_600),
                        ft.Text(role_labels.get(user_role.lower(), user_role), size=12, color=ft.Colors.BLUE_700),
                    ], spacing=2),
                ], spacing=15),
                ft.Divider(),
            ])
            self.page.update()
    
    def _update_permission_list(self):
        """Met à jour l'affichage de la liste des permissions"""
        self.permission_list_view.controls.clear()
        
        if not self.selected_user:
            self.permission_list_view.controls.append(
                ft.Container(
                    content=ft.Text("Sélectionnez un utilisateur pour gérer ses permissions", 
                                  size=16, color=ft.Colors.GREY_600),
                    padding=40,
                    alignment=ft.alignment.center,
                )
            )
            return
        
        # Grouper les permissions par catégorie
        permissions_by_category = {}
        for perm_key, perm_info in self.PERMISSIONS.items():
            category = perm_info.get('category', 'Autres')
            if category not in permissions_by_category:
                permissions_by_category[category] = []
            permissions_by_category[category].append((perm_key, perm_info))
        
        # Trier les catégories
        category_order = ['Ventes', 'Produits', 'Rapports', 'Finances', 'Facturation', 'Inventaire', 'Administration', 'Autres']
        
        for category in category_order:
            if category not in permissions_by_category:
                continue
            
            perms = sorted(permissions_by_category[category], key=lambda x: x[1].get('order', 999))
            
            # En-tête de catégorie
            category_header = ft.Container(
                content=ft.Row([
                    ft.Icon(ft.Icons.FOLDER, size=18, color=ft.Colors.BLUE_700),
                    ft.Text(category, size=16, weight=ft.FontWeight.BOLD, color=ft.Colors.BLUE_800),
                ], spacing=8),
                padding=ft.Padding.only(top=15, bottom=5),
            )
            self.permission_list_view.controls.append(category_header)
            
            # Permissions de la catégorie
            for perm_key, perm_info in perms:
                is_allowed = self.user_permissions.get(perm_key, False)
                
                switch = ft.Switch(
                    value=is_allowed,
                    active_color=ft.Colors.GREEN,
                )
                switch.on_change = lambda e, k=perm_key: self._toggle_permission(k, e.control.value)
                
                # ✅ Supprimer le fond gris en utilisant bgcolor transparent
                permission_item = ft.Container(
                    content=ft.Row([
                        ft.Icon(perm_info.get('icon', ft.Icons.CHECK_CIRCLE), 
                               size=20, 
                               color=ft.Colors.GREEN if is_allowed else ft.Colors.GREY_400),
                        ft.Column([
                            ft.Text(perm_info['label'], size=14, weight=ft.FontWeight.W_500),
                            ft.Text(perm_info['description'], size=11, color=ft.Colors.GREY_600),
                            ft.Text(f"Écran: {perm_info['screen'] or 'N/A'}", size=10, color=ft.Colors.BLUE_500) if perm_info.get('screen') else None,
                        ], spacing=2, expand=True),
                        switch,
                    ], spacing=12, alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                    padding=ft.Padding.all(8),
                    bgcolor=None,  # ✅ Pas de fond pour éviter le gris
                    border_radius=8,
                )
                self.permission_list_view.controls.append(permission_item)
        
        self.page.update()
    
    def _toggle_permission(self, permission_key: str, value: bool):
        """Active/désactive une permission"""
        if not self.selected_user:
            return
        
        self.user_permissions[permission_key] = value
        logger.info(f"Permission {permission_key} = {value} pour {self.selected_user.get('id')}")
    
    def _apply_preset_role(self, e):
        """Applique un rôle prédéfini à l'utilisateur sélectionné"""
        if not self.selected_user:
            self._show_snackbar("Veuillez d'abord sélectionner un utilisateur", ft.Colors.ORANGE)
            self.preset_role_dropdown.value = ""
            self.page.update()
            return
        
        role = self.preset_role_dropdown.value
        if not role:
            return
        
        # Confirmation
        def confirm_apply(e):
            default_perms = self.DEFAULT_ROLE_PERMISSIONS.get(role, {})
            for perm_key in self.PERMISSIONS.keys():
                self.user_permissions[perm_key] = default_perms.get(perm_key, False)
            
            self._update_permission_list()
            self._show_snackbar(f"Permissions du rôle '{role}' appliquées à {self.selected_user.get('full_name', 'l\'utilisateur')}", 
                              ft.Colors.GREEN)
            dialog.open = False
            self.preset_role_dropdown.value = ""
            self.page.update()
        
        def close_dialog(e):
            dialog.open = False
            self.preset_role_dropdown.value = ""
            self.page.update()
        
        dialog = ft.AlertDialog(
            title=ft.Text("Confirmation"),
            content=ft.Text(f"Appliquer les permissions du rôle '{role}' à {self.selected_user.get('full_name', 'cet utilisateur')} ?\n\nCela remplacera toutes les permissions actuelles."),
            actions=[
                ft.TextButton("Annuler", on_click=close_dialog),
                ft.ElevatedButton("Confirmer", on_click=confirm_apply),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
        )
        
        self.page.dialog = dialog
        dialog.open = True
        self.page.update()
    
    def _save_all_permissions(self, e):
        """Sauvegarde toutes les permissions pour l'utilisateur sélectionné"""
        if not self.selected_user:
            self._show_snackbar("Veuillez d'abord sélectionner un utilisateur", ft.Colors.ORANGE)
            return
        
        branch_id = self.current_user.get('active_branch_id') or self.current_user.get('branch_id')
        
        if self._save_user_permissions(self.selected_user.get('id'), branch_id, self.user_permissions):
            self._show_snackbar(f"Permissions sauvegardées pour {self.selected_user.get('full_name', 'l\'utilisateur')}", 
                              ft.Colors.GREEN)
        else:
            self._show_snackbar("Erreur lors de la sauvegarde", ft.Colors.RED)
    
    def _show_snackbar(self, message: str, color, duration=3000):
        """Affiche un snackbar"""
        snack = ft.SnackBar(
            content=ft.Text(message),
            bgcolor=color,
            duration=duration,
            show_close_icon=True,
        )
        self.page.snack_bar = snack
        snack.open = True
        self.page.update()
    
    def _build(self):
        """Construit l'interface utilisateur"""
        
        # Conteneur pour l'utilisateur sélectionné
        self.selected_user_container = ft.Container(
            content=ft.Column([ft.Text("Sélectionnez un utilisateur", color=ft.Colors.GREY_600)], spacing=10),
            padding=15,
            bgcolor=ft.Colors.GREY_50,
            border_radius=10,
        )
        
        # Barre d'actions
        save_button = ft.ElevatedButton(
            "💾 Sauvegarder",
            icon=ft.Icons.SAVE,
            style=ft.ButtonStyle(bgcolor=ft.Colors.GREEN_700, color=ft.Colors.WHITE),
            on_click=self._save_all_permissions,
        )
        
        action_bar = ft.Container(
            content=ft.Row([
                self.preset_role_dropdown,
                save_button,
            ], spacing=10, alignment=ft.MainAxisAlignment.END),
            padding=ft.Padding.only(bottom=10),
        )
        
        # Panneau principal avec fond blanc
        main_content = ft.Row(
            [
                # Panneau gauche: liste des utilisateurs
                ft.Container(
                    content=ft.Column([
                        ft.Text("👥 Utilisateurs", size=16, weight=ft.FontWeight.BOLD),
                        ft.Row([self.search_field, self.role_filter], spacing=8),
                        ft.Container(
                            content=self.user_list_view,
                            height=450,
                            border=ft.border.all(1, ft.Colors.GREY_200),
                            border_radius=10,
                            padding=5,
                            bgcolor=ft.Colors.WHITE,
                        ),
                    ], spacing=10),
                    width=320,
                    padding=10,
                    bgcolor=ft.Colors.WHITE,
                ),
                
                # Panneau droit: permissions
                ft.Container(
                    content=ft.Column([
                        ft.Text("🔐 Permissions", size=16, weight=ft.FontWeight.BOLD),
                        self.selected_user_container,
                        action_bar,
                        ft.Text("☑️ Activer/Désactiver les accès", size=12, color=ft.Colors.GREY_600),
                        ft.Container(
                            content=self.permission_list_view,
                            expand=True,
                            border=ft.border.all(1, ft.Colors.GREY_200),
                            border_radius=10,
                            padding=10,
                            bgcolor=ft.Colors.WHITE,
                        ),
                    ], spacing=10, expand=True),
                    expand=True,
                    padding=10,
                    bgcolor=ft.Colors.WHITE,
                ),
            ],
            expand=True,
            spacing=10,
        )
        
        # Header
        header = ft.Container(
            bgcolor=ft.Colors.BLUE_700,
            padding=ft.padding.symmetric(horizontal=12, vertical=10),
            content=ft.Row([
                ft.IconButton(
                    icon=ft.Icons.ARROW_BACK,
                    icon_color=ft.Colors.WHITE,
                    tooltip="Retour",
                    on_click=lambda e: self._go_back(),
                ),
                ft.Text(
                    "🔐 Gestion des permissions",
                    size=18,
                    weight=ft.FontWeight.BOLD,
                    color=ft.Colors.WHITE,
                    expand=True,
                ),
                ft.Container(
                    content=ft.Text("Admin", size=12, color=ft.Colors.WHITE, weight=ft.FontWeight.BOLD),
                    bgcolor=ft.Colors.BLUE_900,
                    padding=ft.Padding.symmetric(horizontal=8, vertical=4),
                    border_radius=10,
                ),
                # Indicateur de chargement
                self.loading_indicator,
            ]),
        )
        
        # Barre de progression pour le chargement
        self.progress_bar = ft.ProgressBar(visible=False)
        
        # Assemblage
        self.container.content = ft.Column([
            header,
            ft.Container(content=main_content, expand=True, padding=15, bgcolor=ft.Colors.WHITE),
            self.progress_bar,
        ], spacing=0, expand=True)
    
    def _go_back(self):
        """Retourne à l'écran précédent"""
        if self.on_back:
            self.on_back()
    
    def show(self):
        """Affiche l'écran des permissions"""
        # Afficher le chargement
        self.loading_indicator.visible = True
        self.progress_bar.visible = True
        self.page.update()
        
        def load_data():
            try:
                # Charger les utilisateurs depuis le serveur
                self.users = self._load_users_from_server()
                
                # Mettre à jour l'interface
                self.page.run_coroutine(self._update_ui_after_load)
            except Exception as e:
                logger.error(f"Erreur chargement des données: {e}")
                self.page.run_coroutine(self._show_error, str(e))
        
        def load_data_thread():
            load_data()
        
        # Démarrer le chargement dans un thread
        threading.Thread(target=load_data_thread, daemon=True).start()
    
    def _update_ui_after_load(self):
        """Met à jour l'interface après le chargement"""
        self._init_permissions_tables()
        self._build()
        
        # Sélectionner le premier utilisateur par défaut
        if self.users and not self.selected_user:
            self._select_user(self.users[0])
        
        # Mettre à jour la liste
        self._update_user_list(self.users)
        
        # Masquer le chargement
        self.loading_indicator.visible = False
        self.progress_bar.visible = False
        
        # Afficher
        self.page.clean()
        self.page.add(self.container)
        self.page.update()
    
    def _show_error(self, error_message: str):
        """Affiche une erreur"""
        self._show_snackbar(f"Erreur: {error_message}", ft.Colors.RED)
        self.loading_indicator.visible = False
        self.progress_bar.visible = False
        self.page.update()