"""
Gestionnaire de base de données locale SQLite
Gère toutes les opérations CRUD et la synchronisation avec le backend
"""

import sqlite3
import json
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any, Tuple
from contextlib import contextmanager
import logging
import os

# Import des modèles
from .models import (
    User, Product, Sale, CartItem, Expense, Debt, 
    SyncLog, DashboardStats, Branch
)
from utils.paths import get_db_path

logger = logging.getLogger(__name__)


class DatabaseManager:
    """Gestionnaire principal de la base de données locale"""
    
    def __init__(self, db_path: str = None):
        self.db_path = db_path or get_db_path()
        self._init_database()
        self._migrate_products_table() 
        self._migrate_products_for_versioning()  
        self._migrate_sales_for_versioning()  
        self._ensure_sales_columns()
    
    @contextmanager
    def get_connection(self):
        """Context manager pour les connexions SQLite"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception as e:
            conn.rollback()
            raise e
        finally:
            conn.close()
    
    def _init_database(self):
        """Initialise toutes les tables de la base de données"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            # Table user avec string IDs
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS user (
                    id TEXT PRIMARY KEY,
                    username TEXT NOT NULL,
                    email TEXT,
                    full_name TEXT,
                    branch_id TEXT,
                    branch_name TEXT,
                    role TEXT,
                    token TEXT NOT NULL,
                    last_sync TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # Table products avec string IDs
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS products (
                    server_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    code TEXT,
                    selling_price REAL DEFAULT 0,
                    quantity INTEGER DEFAULT 0,
                    category TEXT,
                    branch_id TEXT,
                    pharmacy_id TEXT,
                    tenant_id TEXT,
                    pharmacy_name TEXT,
                    tenant_name TEXT,
                    updated_at TEXT,
                    is_active INTEGER DEFAULT 0,
                    is_deleted INTEGER DEFAULT 0,
                    description TEXT,
                    barcode TEXT,
                    min_stock INTEGER DEFAULT 0,
                    max_stock INTEGER DEFAULT 0,
                    unit TEXT DEFAULT 'piece',
                    tax_rate REAL DEFAULT 0,
                    expiry_date TEXT,
                    expiry_status TEXT,
                    manufacturing_date TEXT,
                    lot_number TEXT,
                    supplier TEXT,
                    location TEXT,
                    status TEXT DEFAULT 'active',
                    alert_threshold_days INTEGER DEFAULT 30,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # Index pour les recherches rapides
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_products_branch ON products(branch_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_products_code ON products(code)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_products_barcode ON products(barcode)")
            
            # Table sales avec string IDs
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS sales (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    product_id TEXT NOT NULL,
                    product_name TEXT,
                    quantity INTEGER NOT NULL,
                    unit_price REAL NOT NULL,
                    total_price REAL NOT NULL,
                    sale_date TEXT NOT NULL,
                    customer_name TEXT,
                    branch_id TEXT NOT NULL,
                    is_synced INTEGER DEFAULT 0,
                    sync_error TEXT,
                    seller_id TEXT,
                    payment_method TEXT DEFAULT 'cash',
                    invoice_number TEXT,
                    is_returned INTEGER DEFAULT 0,
                    return_id INTEGER,
                    returned_at TEXT,
                    is_exchange INTEGER DEFAULT 0,
                    total_amount REAL DEFAULT 0,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # Ajouter les colonnes manquantes à la table sales
            try:
                cursor.execute("ALTER TABLE sales ADD COLUMN is_modified INTEGER DEFAULT 0")
            except sqlite3.OperationalError:
                pass  # La colonne existe déjà

            try:
                cursor.execute("ALTER TABLE sales ADD COLUMN modification_date TEXT")
            except sqlite3.OperationalError:
                pass

            try:
                cursor.execute("ALTER TABLE sales ADD COLUMN modification_reason TEXT")
            except sqlite3.OperationalError:
                pass

            try:
                cursor.execute("ALTER TABLE sales ADD COLUMN original_invoice_number TEXT")
            except sqlite3.OperationalError:
                pass

            try:
                cursor.execute("ALTER TABLE sales ADD COLUMN returned_quantity INTEGER DEFAULT 0")
            except sqlite3.OperationalError:
                pass  # La colonne existe déjà
            
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_sales_invoice ON sales(invoice_number)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_sales_customer ON sales(customer_name)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_sales_date ON sales(sale_date)")

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS debts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    server_id TEXT,
                    customer_name TEXT NOT NULL,
                    amount REAL NOT NULL,
                    remaining_amount REAL NOT NULL,
                    due_date TEXT NOT NULL,
                    status TEXT DEFAULT 'pending',
                    branch_id TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    is_synced INTEGER DEFAULT 0,
                    notes TEXT,
                    product_id TEXT,
                    product_name TEXT,
                    quantity INTEGER DEFAULT 1,
                    unit_price REAL DEFAULT 0
                )
            """)

            # Ajoutez la table returns_history
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS returns_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    sale_id INTEGER,
                    invoice_number TEXT,
                    product_id TEXT,
                    product_name TEXT,
                    quantity INTEGER NOT NULL,
                    unit_price REAL NOT NULL,
                    total_price REAL NOT NULL,
                    reason TEXT,
                    return_type TEXT DEFAULT 'return',
                    branch_id TEXT NOT NULL,
                    customer_name TEXT,
                    return_date TEXT,
                    exchange_product_name TEXT,
                    exchange_quantity INTEGER DEFAULT 0,
                    exchange_unit_price REAL DEFAULT 0,
                    is_synced INTEGER DEFAULT 0,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            """)
            # Ajoutez la table sale_items (si elle n'existe pas)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS sale_items (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    sale_id INTEGER NOT NULL,
                    product_id TEXT NOT NULL,
                    product_name TEXT NOT NULL,
                    quantity INTEGER NOT NULL,
                    unit_price REAL NOT NULL,
                    total_price REAL NOT NULL,
                    returned_quantity INTEGER DEFAULT 0,
                    is_returned INTEGER DEFAULT 0,
                    return_date TEXT,
                    exchange_product_id TEXT,
                    exchange_product_name TEXT,
                    exchange_quantity INTEGER DEFAULT 0,
                    exchange_unit_price REAL DEFAULT 0,
                    exchange_total REAL DEFAULT 0,
                    FOREIGN KEY (sale_id) REFERENCES sales(id)
                )
            """)

            # Table invoices (factures)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS invoices (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    invoice_number TEXT UNIQUE NOT NULL,
                    sale_date TEXT NOT NULL,
                    customer_name TEXT NOT NULL,
                    total_amount REAL NOT NULL,
                    payment_method TEXT DEFAULT 'cash',
                    branch_id TEXT NOT NULL,
                    seller_id TEXT,
                    seller_name TEXT,
                    status TEXT DEFAULT 'completed',
                    is_modified INTEGER DEFAULT 0,
                    original_invoice_number TEXT,
                    modification_date TEXT,
                    modification_reason TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            """)

            cursor.execute("CREATE INDEX IF NOT EXISTS idx_invoices_number ON invoices(invoice_number)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_invoices_date ON invoices(sale_date)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_invoices_customer ON invoices(customer_name)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_invoices_branch ON invoices(branch_id)")
            
            # Table invoice_items (lignes de facture)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS invoice_items (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    invoice_number TEXT NOT NULL,
                    product_id TEXT NOT NULL,
                    product_name TEXT NOT NULL,
                    quantity INTEGER NOT NULL,
                    unit_price REAL NOT NULL,
                    total_price REAL NOT NULL,
                    is_returned INTEGER DEFAULT 0,
                    returned_quantity INTEGER DEFAULT 0,
                    exchange_product_id TEXT,
                    exchange_product_name TEXT,
                    exchange_quantity INTEGER DEFAULT 0,
                    exchange_unit_price REAL DEFAULT 0,
                    exchange_total REAL DEFAULT 0,
                    FOREIGN KEY (invoice_number) REFERENCES invoices(invoice_number)
                )
            """)

            cursor.execute("CREATE INDEX IF NOT EXISTS idx_invoice_items_invoice ON invoice_items(invoice_number)")

            # Table cart_items
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS cart_items (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    product_id TEXT NOT NULL,
                    product_name TEXT NOT NULL,
                    quantity INTEGER NOT NULL,
                    unit_price REAL NOT NULL,
                    total_price REAL NOT NULL,
                    added_at TEXT NOT NULL,
                    session_id TEXT DEFAULT 'current'
                )
            """)

            # Table invoice_counter (compteur de factures)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS invoice_counter (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    current_number INTEGER DEFAULT 1,
                    last_updated TEXT DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # Initialiser le compteur si vide
            cursor.execute("INSERT OR IGNORE INTO invoice_counter (id, current_number) VALUES (1, 1)")
            
            # Table expenses
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS expenses (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    description TEXT NOT NULL,
                    amount REAL NOT NULL,
                    expense_date TEXT NOT NULL,
                    category TEXT,
                    branch_id TEXT NOT NULL,
                    is_synced INTEGER DEFAULT 0,
                    receipt_url TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # Table debts
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS debts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    server_id TEXT,
                    customer_name TEXT NOT NULL,
                    amount REAL NOT NULL,
                    remaining_amount REAL NOT NULL,
                    due_date TEXT NOT NULL,
                    status TEXT DEFAULT 'pending',
                    branch_id TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    is_synced INTEGER DEFAULT 0,
                    notes TEXT
                )
            """)

            # Ajouter la table returns
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS returns (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    sale_id INTEGER,
                    product_id TEXT,
                    product_name TEXT,
                    quantity INTEGER NOT NULL,
                    unit_price REAL NOT NULL,
                    total_price REAL NOT NULL,
                    return_date TEXT NOT NULL,
                    reason TEXT,
                    return_type TEXT DEFAULT 'return',
                    branch_id TEXT NOT NULL,
                    customer_name TEXT,
                    invoice_number TEXT,
                    is_synced INTEGER DEFAULT 0,
                    synced_at TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            """)

            cursor.execute("CREATE INDEX IF NOT EXISTS idx_returns_sale_id ON returns(sale_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_returns_branch ON returns(branch_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_returns_date ON returns(return_date)")

            # Ajouter la colonne is_returned à la table sales si elle n'existe pas
            try:
                cursor.execute("ALTER TABLE sales ADD COLUMN is_returned INTEGER DEFAULT 0")
            except sqlite3.OperationalError:
                pass  # La colonne existe déjà

            try:
                cursor.execute("ALTER TABLE sales ADD COLUMN return_id INTEGER")
            except sqlite3.OperationalError:
                pass

            try:
                cursor.execute("ALTER TABLE sales ADD COLUMN returned_at TEXT")
            except sqlite3.OperationalError:
                pass

            try:
                cursor.execute("ALTER TABLE sales ADD COLUMN product_name TEXT")
            except sqlite3.OperationalError:
                pass

            try:
                cursor.execute("ALTER TABLE sales ADD COLUMN is_exchange INTEGER DEFAULT 0")
            except sqlite3.OperationalError:
                pass
            
            # Table sync_logs
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS sync_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    sync_type TEXT NOT NULL,
                    sync_date TEXT NOT NULL,
                    records_synced INTEGER DEFAULT 0,
                    status TEXT NOT NULL,
                    error_message TEXT,
                    details TEXT
                )
            """)
            
            # Table branches
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS branches (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    address TEXT,
                    phone TEXT,
                    email TEXT,
                    manager_name TEXT,
                    parent_pharmacy_id TEXT,
                    is_active INTEGER DEFAULT 1
                )
            """)
            
            conn.commit()
            logger.info("Base de données initialisée avec succès")
        
        self._ensure_sales_columns()
    
    # ==================== UTILISATEUR ====================
    
    def save_user(self, user: User) -> bool:
        """Sauvegarde ou met à jour un utilisateur"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT OR REPLACE INTO user 
                    (id, username, email, full_name, branch_id, branch_name, role, token, last_sync)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    user.id, user.username, user.email, user.full_name,
                    user.branch_id, user.branch_name, user.role, user.token, user.last_sync
                ))
                return True
        except Exception as e:
            logger.error(f"Erreur sauvegarde utilisateur: {e}")
            return False
    
    def _migrate_products_table(self):
        """Ajoute les colonnes de versionnement à la table products"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            # Vérifier les colonnes existantes
            cursor.execute("PRAGMA table_info(products)")
            existing_columns = [col[1] for col in cursor.fetchall()]
            
            # Ajouter les colonnes manquantes
            columns_to_add = {
                'stock_version': 'INTEGER DEFAULT 1',
                'last_sync_at': 'TEXT',
                'synced_quantity': 'INTEGER DEFAULT 0',
                'pending_quantity_change': 'INTEGER DEFAULT 0'
            }
            
            for col_name, col_type in columns_to_add.items():
                if col_name not in existing_columns:
                    try:
                        cursor.execute(f"ALTER TABLE products ADD COLUMN {col_name} {col_type}")
                        logger.info(f"Colonne {col_name} ajoutée à products")
                    except Exception as e:
                        logger.error(f"Erreur ajout colonne {col_name}: {e}")
            
            conn.commit()
    
    def _migrate_products_for_versioning(self):
        """Ajoute les colonnes nécessaires pour le versionnement des stocks"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            # Vérifier les colonnes existantes
            cursor.execute("PRAGMA table_info(products)")
            existing_columns = [col[1] for col in cursor.fetchall()]
            
            # Colonnes à ajouter
            columns_to_add = {
                'stock_version': 'INTEGER DEFAULT 1',
                'last_sync_at': 'TEXT',
                'synced_quantity': 'INTEGER DEFAULT 0',
                'pending_quantity_change': 'INTEGER DEFAULT 0'
            }
            
            for col_name, col_type in columns_to_add.items():
                if col_name not in existing_columns:
                    try:
                        cursor.execute(f"ALTER TABLE products ADD COLUMN {col_name} {col_type}")
                        print(f"✅ Colonne {col_name} ajoutée à products")
                    except Exception as e:
                        print(f"Erreur ajout colonne {col_name}: {e}")
            
            conn.commit()
    
    def _init_invoice_sync_table(self):
        """Crée la table de suivi des factures locales non synchronisées"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS pending_invoices (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    invoice_number TEXT NOT NULL,
                    local_number INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    is_resolved INTEGER DEFAULT 0,
                    resolved_at TEXT
                )
            """)
            
            # Ajouter la colonne server_invoice_number si elle n'existe pas
            cursor.execute("PRAGMA table_info(invoices)")
            columns = [col[1] for col in cursor.fetchall()]
            
            if 'server_invoice_number' not in columns:
                cursor.execute("ALTER TABLE invoices ADD COLUMN server_invoice_number TEXT")
            
            if 'sync_status' not in columns:
                cursor.execute("ALTER TABLE invoices ADD COLUMN sync_status TEXT DEFAULT 'pending'")
            
            conn.commit()
    
    def _migrate_sales_for_versioning(self):
        """Ajoute les colonnes nécessaires pour le versionnement des ventes"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            cursor.execute("PRAGMA table_info(sales)")
            existing_columns = [col[1] for col in cursor.fetchall()]
            
            columns_to_add = {
                'stock_version_at_sale': 'INTEGER DEFAULT 0',
                'stock_quantity_at_sale': 'INTEGER DEFAULT 0',
                'is_rejected': 'INTEGER DEFAULT 0',
                'rejection_reason': 'TEXT',
                'is_partial': 'INTEGER DEFAULT 0',
                'rejected_quantity': 'INTEGER DEFAULT 0',
                'synced_at': 'TEXT',
                'device_id': 'TEXT'
            }
            
            for col_name, col_type in columns_to_add.items():
                if col_name not in existing_columns:
                    try:
                        cursor.execute(f"ALTER TABLE sales ADD COLUMN {col_name} {col_type}")
                        print(f"✅ Colonne {col_name} ajoutée à sales")
                    except Exception as e:
                        print(f"Erreur ajout colonne {col_name}: {e}")
            
            conn.commit()
    
    def get_current_user(self) -> Optional[User]:
        """Récupère l'utilisateur courant"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT * FROM user LIMIT 1")
                row = cursor.fetchone()
                if row:
                    return User(
                        id=row['id'],
                        username=row['username'],
                        email=row['email'],
                        full_name=row['full_name'],
                        branch_id=row['branch_id'],
                        branch_name=row['branch_name'],
                        role=row['role'],
                        token=row['token'],
                        last_sync=row['last_sync']
                    )
                return None
        except Exception as e:
            logger.error(f"Erreur récupération utilisateur: {e}")
            return None
    
    def get_user_branch_id(self) -> Optional[int]:
        """Récupère l'ID de la branche de l'utilisateur"""
        user = self.get_current_user()
        return user.branch_id if user else None
    
    def get_user_token(self) -> Optional[str]:
        """Récupère le token de l'utilisateur"""
        user = self.get_current_user()
        return user.token if user else None
    
    def update_last_sync(self, sync_time: str) -> bool:
        """Met à jour la dernière synchronisation"""
        user = self.get_current_user()
        if not user:
            return False
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("UPDATE user SET last_sync = ? WHERE id = ?", (sync_time, user.id))
                return True
        except Exception as e:
            logger.error(f"Erreur mise à jour last_sync: {e}")
            return False
    
    def logout_user(self) -> bool:
        """Déconnecte l'utilisateur (supprime ses données)"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("DELETE FROM user")
                return True
        except Exception as e:
            logger.error(f"Erreur déconnexion: {e}")
            return False
    
    # ==================== PRODUITS ====================
    
    def save_products(self, products: List[Product]) -> int:
        """Sauvegarde des produits avec support UUID (ne pas convertir en entier)"""
        saved_count = 0
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                for product in products:
                    # S'assurer que server_id est bien une string (UUID)
                    server_id = str(product.server_id) if product.server_id else None
                    
                    # Récupérer la quantité
                    quantity_value = product.quantity if hasattr(product, 'quantity') and product.quantity else product.stock
                    
                    cursor.execute("""
                        INSERT OR REPLACE INTO products 
                        (server_id, name, code, selling_price, quantity, category, branch_id, 
                        pharmacy_id, tenant_id, updated_at, is_deleted, description, barcode, 
                        min_stock, max_stock, unit, tax_rate, expiry_date, expiry_status, 
                        manufacturing_date, lot_number, supplier, location, status, 
                        alert_threshold_days, stock_version, last_sync_at, synced_quantity)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        server_id,
                        product.name,
                        product.code,
                        product.selling_price,
                        quantity_value,
                        product.category,
                        product.branch_id,
                        getattr(product, 'pharmacy_id', None),
                        getattr(product, 'tenant_id', None),
                        product.updated_at,
                        1 if product.is_deleted else 0,
                        product.description,
                        product.barcode,
                        product.min_stock,
                        product.max_stock,
                        product.unit,
                        product.tax_rate,
                        product.expiry_date,
                        product.expiry_status,
                        product.manufacturing_date,
                        product.lot_number,
                        product.supplier,
                        product.location,
                        product.status,
                        product.alert_threshold_days,
                        getattr(product, 'stock_version', 1),
                        product.last_sync_at if hasattr(product, 'last_sync_at') else None,
                        getattr(product, 'synced_quantity', quantity_value)
                    ))
                    saved_count += 1
                return saved_count
        except Exception as e:
            logger.error(f"Erreur sauvegarde produits: {e}")
            return 0

    def get_products(self, branch_id: Optional[str] = None) -> List[Product]:
        """Récupère tous les produits"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                if branch_id:
                    cursor.execute(
                        "SELECT * FROM products WHERE is_deleted = 0 AND branch_id = ? ORDER BY name",
                        (branch_id,)
                    )
                else:
                    cursor.execute("SELECT * FROM products WHERE is_deleted = 0 ORDER BY name")
                
                rows = cursor.fetchall()
                products = []
                for row in rows:
                    product = self._row_to_product(row)
                    # S'assurer que server_id est stocké comme string
                    if product.server_id:
                        product.server_id = str(product.server_id)
                    products.append(product)
                return products
        except Exception as e:
            logger.error(f"Erreur récupération produits: {e}")
            return []
    
    def get_all_products(self, branch_id: Optional[str] = None) -> List[Product]:
        """Récupère tous les produits (filtre par branche si spécifié)"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                if branch_id:
                    cursor.execute(
                        "SELECT * FROM products WHERE is_deleted = 0 AND branch_id = ? ORDER BY name",
                        (branch_id,)
                    )
                else:
                    cursor.execute("SELECT * FROM products WHERE is_deleted = 0 ORDER BY name")
                
                rows = cursor.fetchall()
                return [self._row_to_product(row) for row in rows]
        except Exception as e:
            logger.error(f"Erreur récupération produits: {e}")
            return []
        
    def get_products(self, branch_id: Optional[str] = None) -> List[Product]:
        """Récupère tous les produits (alias de get_all_products)"""
        return self.get_all_products(branch_id)
    
    def get_product_by_id(self, server_id: str) -> Optional[Product]:
        """Récupère un produit par son UUID (string)"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT * FROM products WHERE server_id = ?", (str(server_id),))
                row = cursor.fetchone()
                if row:
                    return self._row_to_product(row)
                return None
        except Exception as e:
            logger.error(f"Erreur récupération produit: {e}")
            return None
    
    def search_products(self, query: str, branch_id: Optional[int] = None) -> List[Product]:
        """Recherche des produits par nom, code ou code-barres"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                search_term = f"%{query}%"
                
                sql = """
                    SELECT * FROM products 
                    WHERE is_deleted = 0 
                    AND (name LIKE ? OR code LIKE ? OR barcode LIKE ?)
                """
                params = [search_term, search_term, search_term]
                
                if branch_id:
                    sql += " AND branch_id = ?"
                    params.append(branch_id)
                
                sql += " ORDER BY name LIMIT 50"
                
                cursor.execute(sql, params)
                rows = cursor.fetchall()
                return [Product(
                    server_id=row['server_id'],
                    name=row['name'],
                    code=row['code'],
                    selling_price=row['selling_price'],
                    quantity=row['quantity'],
                    category=row['category'],
                    branch_id=row['branch_id'],
                    updated_at=row['updated_at'],
                    is_deleted=bool(row['is_deleted']),
                    description=row['description'],
                    barcode=row['barcode'],
                    min_stock=row['min_stock'],
                    max_stock=row['max_stock'],
                    unit=row['unit'],
                    tax_rate=row['tax_rate']
                ) for row in rows]
        except Exception as e:
            logger.error(f"Erreur recherche produits: {e}")
            return []
    
    def get_low_stock_products(self, branch_id: Optional[int] = None) -> List[Product]:
        """Récupère les produits avec stock bas"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                # Utiliser la colonne 'quantity' de la base
                sql = "SELECT * FROM products WHERE is_deleted = 0 AND quantity <= min_stock"
                params = []
                
                if branch_id:
                    sql += " AND branch_id = ?"
                    params.append(branch_id)
                
                cursor.execute(sql, params)
                rows = cursor.fetchall()
                
                products = []
                for row in rows:
                    quantity_value = row['quantity']
                    product = Product(
                        server_id=row['server_id'],
                        name=row['name'],
                        code=row['code'],
                        selling_price=row['selling_price'],
                        stock=quantity_value,
                        quantity=quantity_value,
                        category=row['category'],
                        branch_id=row['branch_id'],
                        updated_at=row['updated_at'],
                        is_deleted=bool(row['is_deleted']),
                        description=row['description'],
                        barcode=row['barcode'],
                        min_stock=row['min_stock'],
                        max_stock=row['max_stock'],
                        unit=row['unit'],
                        tax_rate=row['tax_rate']
                    )
                    products.append(product)
                return products
        except Exception as e:
            logger.error(f"Erreur récupération stock bas: {e}")
            return []
        
    def update_product_stock(self, product_id: int, quantity: int) -> bool:
        """Met à jour le stock d'un produit"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                # La colonne dans la base s'appelle 'quantity'
                cursor.execute(
                    "UPDATE products SET quantity = quantity - ? WHERE server_id = ? AND quantity >= ?",
                    (quantity, product_id, quantity)
                )
                return cursor.rowcount > 0
        except Exception as e:
            logger.error(f"Erreur mise à jour stock: {e}")
            return False
    

    # ==================== PRODUITS - GESTION DES ID STRING ====================

    def save_products_string_id(self, products: List[Dict]) -> int:
        """Sauvegarde des produits avec ID string (UUID) - NE PAS CONVERTIR"""
        saved_count = 0
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                for p in products:
                    # ✅ CORRECTION: Garder l'UUID comme string
                    server_id = str(p.get('id', ''))
                    if not server_id:
                        continue
                    
                    cursor.execute("""
                        INSERT OR REPLACE INTO products 
                        (server_id, name, code, selling_price, quantity, category, branch_id, 
                        updated_at, is_deleted, description, barcode, min_stock, max_stock, unit, tax_rate)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        server_id,  # ✅ UUID string, pas converti
                        p.get('name', ''),
                        p.get('code', ''),
                        float(p.get('selling_price', 0)),
                        int(p.get('quantity', 0)),
                        p.get('category', ''),
                        p.get('branch_id', ''),
                        p.get('updated_at', datetime.now().isoformat()),
                        0,
                        p.get('description', ''),
                        p.get('barcode', ''),
                        int(p.get('min_stock', 0)),
                        int(p.get('max_stock', 0)),
                        p.get('unit', 'piece'),
                        float(p.get('tax_rate', 0))
                    ))
                    saved_count += 1
                return saved_count
        except Exception as e:
            logger.error(f"Erreur sauvegarde produits string id: {e}")
            return 0


    def get_product_by_string_id(self, product_uuid: str) -> Optional[Product]:
        """Récupère un produit par son UUID string - SANS CONVERSION"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                # ✅ CORRECTION: Chercher directement avec l'UUID string
                cursor.execute("SELECT * FROM products WHERE server_id = ?", (product_uuid,))
                row = cursor.fetchone()
                if row:
                    return self._row_to_product(row)
                return None
        except Exception as e:
            logger.error(f"Erreur récupération produit par string id: {e}")
            return None

    def get_products_unsynced(self, since_date: str = None) -> List[Product]:
        """
        Récupère les produits qui n'ont pas été synchronisés récemment.
        
        Args:
            since_date: Date limite (format ISO) - produits non synchronisés depuis cette date
        
        Returns:
            Liste des produits non synchronisés
        """
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                
                if since_date:
                    # Récupérer les produits non synchronisés depuis la date donnée
                    cursor.execute("""
                        SELECT * FROM products 
                        WHERE is_deleted = 0 
                        AND (last_sync_at IS NULL OR last_sync_at < ?)
                        ORDER BY name
                        LIMIT 100
                    """, (since_date,))
                else:
                    # Récupérer tous les produits actifs
                    cursor.execute("""
                        SELECT * FROM products 
                        WHERE is_deleted = 0 
                        ORDER BY name
                    """)
                
                rows = cursor.fetchall()
                products = []
                for row in rows:
                    product = self._row_to_product(row)
                    products.append(product)
                
                logger.info(f"Récupéré {len(products)} produits non synchronisés")
                return products
                
        except Exception as e:
            logger.error(f"Erreur get_products_unsynced: {e}")
            return []


    def get_products_need_sync(self, branch_id: str = None, limit: int = 100) -> List[Dict]:
        """
        Récupère les produits qui nécessitent une synchronisation.
        (Produits modifiés localement et non synchronisés)
        """
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                
                query = """
                    SELECT 
                        p.server_id,
                        p.name,
                        p.code,
                        p.quantity,
                        p.selling_price,
                        p.purchase_price,
                        p.stock_version,
                        p.last_sync_at,
                        p.updated_at,
                        p.branch_id,
                        p.category
                    FROM products p
                    WHERE p.is_deleted = 0
                    AND (
                        p.last_sync_at IS NULL 
                        OR p.updated_at > p.last_sync_at
                        OR p.stock_version > 1
                    )
                """
                params = []
                
                if branch_id:
                    query += " AND p.branch_id = ?"
                    params.append(branch_id)
                
                query += " ORDER BY p.updated_at DESC LIMIT ?"
                params.append(limit)
                
                cursor.execute(query, params)
                rows = cursor.fetchall()
                
                products = []
                for row in rows:
                    products.append({
                        "server_id": row["server_id"],
                        "name": row["name"],
                        "code": row["code"],
                        "quantity": row["quantity"],
                        "selling_price": row["selling_price"],
                        "purchase_price": row["purchase_price"],
                        "stock_version": row["stock_version"],
                        "last_sync_at": row["last_sync_at"],
                        "updated_at": row["updated_at"],
                        "branch_id": row["branch_id"],
                        "category": row["category"]
                    })
                
                return products
                
        except Exception as e:
            logger.error(f"Erreur get_products_need_sync: {e}")
            return []


    def update_product_sync_status(self, product_id: str, sync_time: str = None) -> bool:
        """
        Met à jour le statut de synchronisation d'un produit.
        
        Args:
            product_id: ID du produit (server_id)
            sync_time: Date/heure de synchronisation (si None, utilise datetime.now)
        
        Returns:
            True si mise à jour réussie
        """
        try:
            if sync_time is None:
                sync_time = datetime.now().isoformat()
            
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    UPDATE products 
                    SET last_sync_at = ?,
                        updated_at = ?
                    WHERE server_id = ?
                """, (sync_time, sync_time, product_id))
                
                success = cursor.rowcount > 0
                if success:
                    logger.debug(f"Produit {product_id} marqué synchronisé à {sync_time}")
                return success
                
        except Exception as e:
            logger.error(f"Erreur update_product_sync_status: {e}")
            return False
    # ==================== DETTES - MÉTHODES MANQUANTES ====================

    def get_active_debts(self, branch_id: Optional[int] = None) -> List[Debt]:
        """Récupère les dettes actives (non payées)"""
        return self.get_pending_debts(branch_id)


    def get_debts(self, branch_id: Optional[int] = None) -> List[Debt]:
        """Récupère toutes les dettes"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                sql = "SELECT * FROM debts"
                params = []
                
                if branch_id:
                    sql += " WHERE branch_id = ?"
                    params.append(branch_id)
                
                sql += " ORDER BY due_date"
                
                cursor.execute(sql, params)
                rows = cursor.fetchall()
                return [Debt(
                    id=row['id'],
                    server_id=row['server_id'],
                    customer_name=row['customer_name'],
                    amount=row['amount'],
                    remaining_amount=row['remaining_amount'],
                    due_date=row['due_date'],
                    status=row['status'],
                    branch_id=row['branch_id'],
                    created_at=row['created_at'],
                    updated_at=row['updated_at'],
                    is_synced=bool(row['is_synced']),
                    notes=row['notes']
                ) for row in rows]
        except Exception as e:
            logger.error(f"Erreur récupération dettes: {e}")
            return []
    
    def get_debt_by_id(self, debt_id: int) -> Optional[Dict]:
        """Récupère une dette par son ID"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT * FROM debts WHERE id = ?", (debt_id,))
                row = cursor.fetchone()
                if row:
                    return dict(row)
                return None
        except Exception as e:
            logger.error(f"Erreur récupération dette par ID: {e}")
            return None

    def update_debt(self, debt_id: int, **kwargs) -> bool:
        """Met à jour une dette"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                
                fields = []
                values = []
                
                # Champs autorisés pour la mise à jour
                allowed_fields = ['customer_name', 'amount', 'remaining_amount', 
                                'due_date', 'status', 'notes', 'updated_at']
                
                for key, value in kwargs.items():
                    if key in allowed_fields:
                        fields.append(f"{key} = ?")
                        values.append(value)
                
                if not fields:
                    return False
                
                # Ajouter updated_at automatiquement
                fields.append("updated_at = ?")
                values.append(datetime.now().isoformat())
                values.append(debt_id)
                
                query = f"UPDATE debts SET {', '.join(fields)} WHERE id = ?"
                cursor.execute(query, values)
                return cursor.rowcount > 0
        except Exception as e:
            logger.error(f"Erreur mise à jour dette: {e}")
            return False

    def delete_debt(self, debt_id: int) -> bool:
        """Supprime une dette"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("DELETE FROM debts WHERE id = ?", (debt_id,))
                return cursor.rowcount > 0
        except Exception as e:
            logger.error(f"Erreur suppression dette: {e}")
            return False

    # ==================== DÉPENSES - CORRECTION ====================

    def add_expense_from_dict(self, expense_data: Dict) -> Optional[int]:
        """Ajoute une dépense à partir d'un dictionnaire"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT INTO expenses 
                    (description, amount, expense_date, category, branch_id, is_synced, receipt_url)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (
                    expense_data.get('description', ''),
                    float(expense_data.get('amount', 0)),
                    expense_data.get('expense_date', datetime.now().isoformat()),
                    expense_data.get('category', ''),
                    expense_data.get('branch_id', 0),
                    0,
                    expense_data.get('receipt_url')
                ))
                return cursor.lastrowid
        except Exception as e:
            logger.error(f"Erreur ajout dépense depuis dict: {e}")
            return None

    # ==================== VENTES - MÉTHODES SUPPLÉMENTAIRES ====================

    def get_sales_count_today(self, branch_id: Optional[int] = None) -> int:
        """Nombre de ventes aujourd'hui"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                today = datetime.now().date().isoformat()
                sql = "SELECT COUNT(*) as count FROM sales WHERE date(sale_date) = ?"
                params = [today]
                
                if branch_id:
                    sql += " AND branch_id = ?"
                    params.append(branch_id)
                
                cursor.execute(sql, params)
                row = cursor.fetchone()
                return row['count'] if row else 0
        except Exception as e:
            logger.error(f"Erreur comptage ventes jour: {e}")
            return 0


    def get_sales_value_today(self, branch_id: Optional[int] = None) -> float:
        """Valeur des ventes aujourd'hui"""
        return self.get_today_sales(branch_id)


    def get_sales_value_week(self, branch_id: Optional[int] = None) -> float:
        """Valeur des ventes de la semaine"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                week_start = (datetime.now().date() - timedelta(days=datetime.now().date().weekday())).isoformat()
                sql = "SELECT COALESCE(SUM(total_price), 0) as total FROM sales WHERE date(sale_date) >= ?"
                params = [week_start]
                
                if branch_id:
                    sql += " AND branch_id = ?"
                    params.append(branch_id)
                
                cursor.execute(sql, params)
                row = cursor.fetchone()
                return row['total'] if row else 0.0
        except Exception as e:
            logger.error(f"Erreur calcul ventes semaine: {e}")
            return 0.0


    def get_sales_value_month(self, branch_id: Optional[int] = None) -> float:
        """Valeur des ventes du mois"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                month_start = datetime.now().date().replace(day=1).isoformat()
                sql = "SELECT COALESCE(SUM(total_price), 0) as total FROM sales WHERE date(sale_date) >= ?"
                params = [month_start]
                
                if branch_id:
                    sql += " AND branch_id = ?"
                    params.append(branch_id)
                
                cursor.execute(sql, params)
                row = cursor.fetchone()
                return row['total'] if row else 0.0
        except Exception as e:
            logger.error(f"Erreur calcul ventes mois: {e}")
            return 0.0


    # ==================== PRODUITS - MÉTHODES SUPPLÉMENTAIRES ====================

    def get_product_count(self, branch_id: Optional[int] = None) -> int:
        """Nombre de produits"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                sql = "SELECT COUNT(*) as count FROM products WHERE is_deleted = 0"
                params = []
                
                if branch_id:
                    sql += " AND branch_id = ?"
                    params.append(branch_id)
                
                cursor.execute(sql, params)
                row = cursor.fetchone()
                return row['count'] if row else 0
        except Exception as e:
            logger.error(f"Erreur comptage produits: {e}")
            return 0


    def get_expiring_products(self, days: int = 30, branch_id: Optional[int] = None) -> List[Product]:
        """Produits expirant dans X jours"""
        # Cette méthode dépend de la structure de vos données
        # Si vous avez une date d'expiration, ajoutez la logique ici
        return []


    # ==================== STATISTIQUES GLOBALES ====================

    def get_global_stats(self, branch_id: Optional[int] = None) -> Dict:
        """Statistiques globales pour le dashboard"""
        try:
            if branch_id is None:
                user = self.get_current_user()
                branch_id = user.branch_id if user else None
            
            return {
                'sales_count_today': self.get_sales_count_today(branch_id),
                'sales_value_today': self.get_sales_value_today(branch_id),
                'sales_value_week': self.get_sales_value_week(branch_id),
                'sales_value_month': self.get_sales_value_month(branch_id),
                'total_debts': self.get_total_debts(branch_id),
                'pending_debts_count': len(self.get_pending_debts(branch_id)),
                'low_stock_count': len(self.get_low_stock_products(branch_id)),
                'products_count': self.get_product_count(branch_id),
                'pending_sync_count': self.get_pending_sync_count()
            }
        except Exception as e:
            logger.error(f"Erreur stats globales: {e}")
            return {}
    # ==================== VENTES ====================

    def add_sale(self, sale: Sale) -> Optional[int]:
        """Ajoute une vente avec enregistrement du stock au moment de la vente"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                
                # Récupérer le stock actuel du produit
                cursor.execute("SELECT quantity, stock_version FROM products WHERE server_id = ?", (sale.product_id,))
                product_row = cursor.fetchone()
                
                stock_at_sale = product_row['quantity'] if product_row else 0
                stock_version_at_sale = product_row['stock_version'] if product_row else 1
                
                cursor.execute("""
                    INSERT INTO sales 
                    (product_id, product_name, quantity, unit_price, total_price, sale_date, 
                    customer_name, branch_id, is_synced, seller_id, payment_method, invoice_number,
                    stock_version_at_sale, stock_quantity_at_sale, device_id)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    sale.product_id, sale.product_name, sale.quantity, sale.unit_price, sale.total_price,
                    sale.sale_date, sale.customer_name, sale.branch_id,
                    0,  # is_synced = False par défaut
                    sale.seller_id, sale.payment_method, sale.invoice_number,
                    stock_version_at_sale,
                    stock_at_sale,
                    getattr(sale, 'device_id', None)
                ))
                
                # Mettre à jour le stock local
                cursor.execute("""
                    UPDATE products 
                    SET quantity = quantity - ?, 
                        stock_version = stock_version + 1
                    WHERE server_id = ? AND quantity >= ?
                """, (sale.quantity, sale.product_id, sale.quantity))
                
                sale_id = cursor.lastrowid
                logger.info(f"Vente ajoutée: id={sale_id}, qty={sale.quantity}, stock_at_sale={stock_at_sale}, version={stock_version_at_sale}")
                
                return sale_id
                
        except Exception as e:
            logger.error(f"Erreur ajout vente: {e}")
            return None
    
    def add_sales_batch(self, sales: List[Sale]) -> int:
        """Ajoute plusieurs ventes en lot"""
        added_count = 0
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                for sale in sales:
                    cursor.execute("""
                        INSERT INTO sales 
                        (product_id, quantity, unit_price, total_price, sale_date, 
                         customer_name, branch_id, is_synced, seller_id, payment_method, invoice_number)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        sale.product_id, sale.quantity, sale.unit_price, sale.total_price,
                        sale.sale_date, sale.customer_name, sale.branch_id,
                        1 if sale.is_synced else 0, sale.seller_id, sale.payment_method, sale.invoice_number
                    ))
                    added_count += 1
                return added_count
        except Exception as e:
            logger.error(f"Erreur ajout ventes batch: {e}")
            return 0
    
    def get_unsynced_sales(self) -> List[Dict]:
        """Récupère les ventes non synchronisées"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT * FROM sales 
                    WHERE is_synced = 0 
                    ORDER BY sale_date
                """)
                rows = cursor.fetchall()
                return [dict(row) for row in rows]
        except Exception as e:
            logger.error(f"Erreur récupération ventes non sync: {e}")
            return []
    
    def mark_sales_synced(self, sale_ids: List[int]) -> bool:
        """Marque des ventes comme synchronisées"""
        if not sale_ids:
            return True
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                placeholders = ','.join('?' * len(sale_ids))
                cursor.execute(
                    f"UPDATE sales SET is_synced = 1 WHERE id IN ({placeholders})",
                    sale_ids
                )
                return True
        except Exception as e:
            logger.error(f"Erreur marquage ventes sync: {e}")
            return False
    
    def get_today_sales(self, branch_id: Optional[int] = None) -> float:
        """Total des ventes du jour"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                today = datetime.now().date().isoformat()
                sql = "SELECT COALESCE(SUM(total_price), 0) as total FROM sales WHERE date(sale_date) = ?"
                params = [today]
                
                if branch_id:
                    sql += " AND branch_id = ?"
                    params.append(branch_id)
                
                cursor.execute(sql, params)
                row = cursor.fetchone()
                return row['total'] if row else 0.0
        except Exception as e:
            logger.error(f"Erreur calcul ventes jour: {e}")
            return 0.0

    def get_total_sales(self, branch_id: Optional[int] = None) -> float:
        """Total des ventes"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                sql = "SELECT COALESCE(SUM(total_price), 0) as total FROM sales"
                params = []
                
                if branch_id:
                    sql += " WHERE branch_id = ?"
                    params.append(branch_id)
                
                cursor.execute(sql, params)
                row = cursor.fetchone()
                return row['total'] if row else 0.0
        except Exception as e:
            logger.error(f"Erreur total ventes: {e}")
            return 0.0

    def get_recent_sales(self, limit: int = 50, branch_id: Optional[int] = None) -> List[Dict]:
        """Récupère les ventes récentes"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                sql = """
                    SELECT s.*, p.name as product_name, p.code as product_code
                    FROM sales s
                    LEFT JOIN products p ON s.product_id = p.server_id
                    ORDER BY s.sale_date DESC
                    LIMIT ?
                """
                params = [limit]
                
                if branch_id:
                    sql = """
                        SELECT s.*, p.name as product_name, p.code as product_code
                        FROM sales s
                        LEFT JOIN products p ON s.product_id = p.server_id
                        WHERE s.branch_id = ?
                        ORDER BY s.sale_date DESC
                        LIMIT ?
                    """
                    params = [branch_id, limit]
                
                cursor.execute(sql, params)
                rows = cursor.fetchall()
                return [dict(row) for row in rows]
        except Exception as e:
            logger.error(f"Erreur récupération ventes récentes: {e}")
            return []

    def get_product_by_barcode(self, barcode: str, branch_id: Optional[int] = None) -> Optional[Product]:
        """Récupère un produit par son code-barres"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                if branch_id:
                    cursor.execute(
                        "SELECT * FROM products WHERE barcode = ? AND branch_id = ? AND is_deleted = 0",
                        (barcode, branch_id)
                    )
                else:
                    cursor.execute(
                        "SELECT * FROM products WHERE barcode = ? AND is_deleted = 0",
                        (barcode,)
                    )
                row = cursor.fetchone()
                if row:
                    return self._row_to_product(row)
                return None
        except Exception as e:
            logger.error(f"Erreur recherche par code-barres: {e}")
            return None

    def get_product_by_code(self, code: str, branch_id: Optional[int] = None) -> Optional[Product]:
        """Récupère un produit par son code"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                if branch_id:
                    cursor.execute(
                        "SELECT * FROM products WHERE code = ? AND branch_id = ? AND is_deleted = 0",
                        (code, branch_id)
                    )
                else:
                    cursor.execute(
                        "SELECT * FROM products WHERE code = ? AND is_deleted = 0",
                        (code,)
                    )
                row = cursor.fetchone()
                if row:
                    return self._row_to_product(row)
                return None
        except Exception as e:
            logger.error(f"Erreur recherche par code: {e}")
            return None
    
    def get_sales_stats(self, branch_id: Optional[int] = None) -> Dict:
        """Statistiques des ventes (jour, semaine, mois)"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                today = datetime.now().date()
                week_start = (today - timedelta(days=today.weekday())).isoformat()
                month_start = today.replace(day=1).isoformat()
                today_str = today.isoformat()
                
                stats = {}
                
                for period, start_date in [('today', today_str), ('week', week_start), ('month', month_start)]:
                    sql = """
                        SELECT COALESCE(SUM(total_price), 0) as total, COUNT(*) as count
                        FROM sales 
                        WHERE date(sale_date) >= ?
                    """
                    params = [start_date]
                    
                    if branch_id:
                        sql += " AND branch_id = ?"
                        params.append(branch_id)
                    
                    cursor.execute(sql, params)
                    row = cursor.fetchone()
                    stats[f'{period}_sales'] = row['total'] if row else 0.0
                    stats[f'{period}_sales_count'] = row['count'] if row else 0
                
                return stats
        except Exception as e:
            logger.error(f"Erreur stats ventes: {e}")
            return {}
    
    # ==================== PANIER ====================
    
    def add_to_cart(self, cart_item: CartItem) -> Optional[int]:
        """Ajoute un article au panier"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT INTO cart_items 
                    (product_id, product_name, quantity, unit_price, total_price, added_at, session_id)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (
                    cart_item.product_id, cart_item.product_name, cart_item.quantity,
                    cart_item.unit_price, cart_item.total_price, cart_item.added_at, 'current'
                ))
                return cursor.lastrowid
        except Exception as e:
            logger.error(f"Erreur ajout panier: {e}")
            return None
    
    def get_cart(self) -> List[CartItem]:
        """Récupère tous les articles du panier"""
        return self.get_cart_items()
    
    def get_cart_items(self) -> List[CartItem]:
        """Récupère tous les articles du panier"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT * FROM cart_items WHERE session_id = 'current' ORDER BY added_at")
                rows = cursor.fetchall()
                return [CartItem(
                    id=row['id'],
                    product_id=row['product_id'],
                    product_name=row['product_name'],
                    quantity=row['quantity'],
                    unit_price=row['unit_price'],
                    total_price=row['total_price'],
                    added_at=row['added_at']
                ) for row in rows]
        except Exception as e:
            logger.error(f"Erreur récupération panier: {e}")
            return []
    
    def get_cart_count(self) -> int:
        """Récupère le nombre d'articles dans le panier"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT COUNT(*) as count FROM cart_items WHERE session_id = 'current'")
                row = cursor.fetchone()
                return row['count'] if row else 0
        except Exception as e:
            logger.error(f"Erreur comptage panier: {e}")
            return 0
    
    def update_cart_item_quantity(self, item_id: int, quantity: int) -> bool:
        """Met à jour la quantité d'un article du panier"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    UPDATE cart_items 
                    SET quantity = ?, total_price = quantity * unit_price
                    WHERE id = ?
                """, (quantity, item_id))
                return cursor.rowcount > 0
        except Exception as e:
            logger.error(f"Erreur mise à jour panier: {e}")
            return False
    
    def remove_from_cart(self, item_id: int) -> bool:
        """Supprime un article du panier"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("DELETE FROM cart_items WHERE id = ?", (item_id,))
                return cursor.rowcount > 0
        except Exception as e:
            logger.error(f"Erreur suppression panier: {e}")
            return False
    
    def clear_cart(self) -> bool:
        """Vide le panier"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("DELETE FROM cart_items WHERE session_id = 'current'")
                return True
        except Exception as e:
            logger.error(f"Erreur vidage panier: {e}")
            return False
    
    def get_cart_total(self) -> float:
        """Calcule le total du panier"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT COALESCE(SUM(total_price), 0) as total FROM cart_items WHERE session_id = 'current'")
                row = cursor.fetchone()
                return row['total'] if row else 0.0
        except Exception as e:
            logger.error(f"Erreur calcul total panier: {e}")
            return 0.0
    
    # ==================== DÉPENSES ====================
    
    def add_expense(self, expense: Expense) -> Optional[int]:
        """Ajoute une dépense"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT INTO expenses 
                    (description, amount, expense_date, category, branch_id, is_synced, receipt_url)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (
                    expense.description, expense.amount, expense.expense_date,
                    expense.category, expense.branch_id, 1 if expense.is_synced else 0,
                    expense.receipt_url
                ))
                return cursor.lastrowid
        except Exception as e:
            logger.error(f"Erreur ajout dépense: {e}")
            return None
    
    def get_unsynced_expenses(self) -> List[Dict]:
        """Récupère les dépenses non synchronisées"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT * FROM expenses WHERE is_synced = 0 ORDER BY expense_date")
                rows = cursor.fetchall()
                return [dict(row) for row in rows]
        except Exception as e:
            logger.error(f"Erreur récupération dépenses non sync: {e}")
            return []
    
    def get_expenses_by_branch(self, branch_id: Optional[str] = None) -> List[Dict]:
        """Récupère toutes les dépenses d'une branche"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                if branch_id:
                    cursor.execute(
                        "SELECT * FROM expenses WHERE branch_id = ? ORDER BY expense_date DESC",
                        (branch_id,)
                    )
                else:
                    cursor.execute("SELECT * FROM expenses ORDER BY expense_date DESC")
                
                rows = cursor.fetchall()
                return [dict(row) for row in rows]
        except Exception as e:
            logger.error(f"Erreur récupération dépenses par branche: {e}")
            return []
    
    def get_total_expenses(self, branch_id: Optional[str] = None, period: str = "month") -> float:
        """Récupère le total des dépenses pour une période"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                
                now = datetime.now()
                if period == "month":
                    start_date = now.replace(day=1).date().isoformat()
                elif period == "week":
                    start_date = (now.date() - timedelta(days=now.weekday())).isoformat()
                elif period == "today":
                    start_date = now.date().isoformat()
                else:
                    start_date = "1970-01-01"
                
                if branch_id:
                    cursor.execute(
                        "SELECT COALESCE(SUM(amount), 0) as total FROM expenses WHERE branch_id = ? AND date(expense_date) >= ?",
                        (branch_id, start_date)
                    )
                else:
                    cursor.execute(
                        "SELECT COALESCE(SUM(amount), 0) as total FROM expenses WHERE date(expense_date) >= ?",
                        (start_date,)
                    )
                
                row = cursor.fetchone()
                return row['total'] if row else 0.0
        except Exception as e:
            logger.error(f"Erreur total dépenses: {e}")
            return 0.0
    
    def mark_expenses_synced(self, expense_ids: List[int]) -> bool:
        """Marque des dépenses comme synchronisées"""
        if not expense_ids:
            return True
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                placeholders = ','.join('?' * len(expense_ids))
                cursor.execute(
                    f"UPDATE expenses SET is_synced = 1 WHERE id IN ({placeholders})",
                    expense_ids
                )
                return True
        except Exception as e:
            logger.error(f"Erreur marquage dépenses sync: {e}")
            return False
    
    def get_expenses_stats(self, branch_id: Optional[int] = None) -> Dict:
        """Statistiques des dépenses"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                today = datetime.now().date()
                week_start = (today - timedelta(days=today.weekday())).isoformat()
                month_start = today.replace(day=1).isoformat()
                today_str = today.isoformat()
                
                stats = {}
                
                for period, start_date in [('today', today_str), ('week', week_start), ('month', month_start)]:
                    sql = """
                        SELECT COALESCE(SUM(amount), 0) as total
                        FROM expenses 
                        WHERE date(expense_date) >= ?
                    """
                    params = [start_date]
                    
                    if branch_id:
                        sql += " AND branch_id = ?"
                        params.append(branch_id)
                    
                    cursor.execute(sql, params)
                    row = cursor.fetchone()
                    stats[f'{period}_expenses'] = row['total'] if row else 0.0
                
                return stats
        except Exception as e:
            logger.error(f"Erreur stats dépenses: {e}")
            return {}
    
    def update_expense_type(self, expense_id: int, new_type: str) -> bool:
        """
        Met à jour le type d'une dépense
        
        Args:
            expense_id: ID de la dépense
            new_type: Nouveau type
        
        Returns:
            True si mise à jour réussie
        """
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    UPDATE expenses 
                    SET expense_type = ?
                    WHERE id = ?
                """, (new_type, expense_id))
                return cursor.rowcount > 0
        except Exception as e:
            logger.error(f"Erreur update_expense_type: {e}")
            return False

    def update_expense_amount(self, expense_id: int, new_amount: float) -> bool:
        """
        Met à jour le montant d'une dépense
        
        Args:
            expense_id: ID de la dépense
            new_amount: Nouveau montant (absolu)
        
        Returns:
            True si mise à jour réussie
        """
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    UPDATE expenses 
                    SET amount = ?, total_amount = ?
                    WHERE id = ?
                """, (abs(new_amount), abs(new_amount), expense_id))
                return cursor.rowcount > 0
        except Exception as e:
            logger.error(f"Erreur update_expense_amount: {e}")
            return False


    def mark_expense_rejected(self, expense_id: int, reason: str) -> bool:
        """
        Marque une dépense comme rejetée
        
        Args:
            expense_id: ID de la dépense
            reason: Raison du rejet
        
        Returns:
            True si mise à jour réussie
        """
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    UPDATE expenses 
                    SET is_synced = 1, 
                        sync_error = ?,
                        notes = COALESCE(notes || '\n', '') || ?
                    WHERE id = ?
                """, (reason, f"[REJET] {reason}", expense_id))
                return cursor.rowcount > 0
        except Exception as e:
            logger.error(f"Erreur mark_expense_rejected: {e}")
            return False
    
    def update_expense_from_server(self, local_id: int, server_expense: Dict) -> bool:
        """
        Met à jour une dépense locale avec les données du serveur
        
        Args:
            local_id: ID local de la dépense
            server_expense: Données de la dépense depuis le serveur
        
        Returns:
            True si mise à jour réussie
        """
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                
                cursor.execute("""
                    UPDATE expenses 
                    SET description = COALESCE(?, description),
                        amount = COALESCE(?, amount),
                        expense_date = COALESCE(?, expense_date),
                        category = COALESCE(?, category),
                        branch_id = COALESCE(?, branch_id),
                        is_synced = 1,
                        receipt_url = COALESCE(?, receipt_url)
                    WHERE id = ?
                """, (
                    server_expense.get('description'),
                    server_expense.get('amount'),
                    server_expense.get('expense_date'),
                    server_expense.get('expense_type', server_expense.get('category')),
                    server_expense.get('branch_id'),
                    server_expense.get('receipt_url'),
                    local_id
                ))
                
                return cursor.rowcount > 0
                
        except Exception as e:
            logger.error(f"Erreur update_expense_from_server: {e}")
            return False


    def update_expense(self, expense_id: int, **kwargs) -> bool:
        """
        Met à jour une dépense
        
        Args:
            expense_id: ID de la dépense
            **kwargs: Champs à mettre à jour
        
        Returns:
            True si mise à jour réussie
        """
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                
                allowed_fields = ['description', 'amount', 'expense_date', 'category', 
                                'branch_id', 'receipt_url', 'is_synced']
                
                fields = []
                values = []
                
                for key, value in kwargs.items():
                    if key in allowed_fields and value is not None:
                        fields.append(f"{key} = ?")
                        values.append(value)
                
                if not fields:
                    return False
                
                values.append(expense_id)
                query = f"UPDATE expenses SET {', '.join(fields)} WHERE id = ?"
                
                cursor.execute(query, values)
                return cursor.rowcount > 0
                
        except Exception as e:
            logger.error(f"Erreur update_expense: {e}")
            return False


    def get_expenses_by_period(self, start_date: str, end_date: str, branch_id: Optional[str] = None) -> List[Dict]:
        """
        Récupère les dépenses sur une période
        
        Args:
            start_date: Date de début (format ISO)
            end_date: Date de fin (format ISO)
            branch_id: ID de la branche (optionnel)
        
        Returns:
            Liste des dépenses
        """
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                
                sql = """
                    SELECT * FROM expenses 
                    WHERE date(expense_date) >= date(?) AND date(expense_date) <= date(?)
                """
                params = [start_date, end_date]
                
                if branch_id:
                    sql += " AND branch_id = ?"
                    params.append(branch_id)
                
                sql += " ORDER BY expense_date DESC"
                
                cursor.execute(sql, params)
                rows = cursor.fetchall()
                return [dict(row) for row in rows]
                
        except Exception as e:
            logger.error(f"Erreur get_expenses_by_period: {e}")
            return []


    def get_expense_categories(self, branch_id: Optional[str] = None) -> List[str]:
        """
        Récupère les catégories de dépenses distinctes
        
        Args:
            branch_id: ID de la branche (optionnel)
        
        Returns:
            Liste des catégories
        """
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                
                if branch_id:
                    cursor.execute("""
                        SELECT DISTINCT category FROM expenses 
                        WHERE branch_id = ? AND category IS NOT NULL AND category != ''
                        ORDER BY category
                    """, (branch_id,))
                else:
                    cursor.execute("""
                        SELECT DISTINCT category FROM expenses 
                        WHERE category IS NOT NULL AND category != ''
                        ORDER BY category
                    """)
                
                rows = cursor.fetchall()
                return [row['category'] for row in rows]
                
        except Exception as e:
            logger.error(f"Erreur get_expense_categories: {e}")
            return []


    def get_expenses_summary(self, branch_id: Optional[str] = None, period: str = "month") -> Dict:
        """
        Récupère un résumé des dépenses
        
        Args:
            branch_id: ID de la branche (optionnel)
            period: Période ('day', 'week', 'month', 'year')
        
        Returns:
            Dictionnaire avec le résumé
        """
        try:
            from datetime import datetime, timedelta
            
            now = datetime.now()
            
            if period == "day":
                start_date = now.date().isoformat()
            elif period == "week":
                start_date = (now.date() - timedelta(days=now.weekday())).isoformat()
            elif period == "month":
                start_date = now.replace(day=1).date().isoformat()
            elif period == "year":
                start_date = now.replace(month=1, day=1).date().isoformat()
            else:
                start_date = "1970-01-01"
            
            with self.get_connection() as conn:
                cursor = conn.cursor()
                
                sql = """
                    SELECT 
                        COALESCE(SUM(amount), 0) as total_amount,
                        COUNT(*) as count,
                        AVG(amount) as average_amount,
                        MAX(amount) as max_amount,
                        MIN(amount) as min_amount
                    FROM expenses 
                    WHERE date(expense_date) >= date(?)
                """
                params = [start_date]
                
                if branch_id:
                    sql += " AND branch_id = ?"
                    params.append(branch_id)
                
                cursor.execute(sql, params)
                row = cursor.fetchone()
                
                # Dépenses par catégorie
                cat_sql = """
                    SELECT category, COALESCE(SUM(amount), 0) as total, COUNT(*) as count
                    FROM expenses 
                    WHERE date(expense_date) >= date(?) AND category IS NOT NULL AND category != ''
                """
                cat_params = [start_date]
                
                if branch_id:
                    cat_sql += " AND branch_id = ?"
                    cat_params.append(branch_id)
                
                cat_sql += " GROUP BY category ORDER BY total DESC"
                
                cursor.execute(cat_sql, cat_params)
                categories = [dict(row) for row in cursor.fetchall()]
                
                return {
                    "total": row['total_amount'] if row else 0,
                    "count": row['count'] if row else 0,
                    "average": row['average_amount'] if row else 0,
                    "max": row['max_amount'] if row else 0,
                    "min": row['min_amount'] if row else 0,
                    "categories": categories,
                    "period": period,
                    "start_date": start_date
                }
                
        except Exception as e:
            logger.error(f"Erreur get_expenses_summary: {e}")
            return {
                "total": 0,
                "count": 0,
                "average": 0,
                "max": 0,
                "min": 0,
                "categories": [],
                "period": period,
                "start_date": None,
                "error": str(e)
            }
    
    # ==================== DETTES ====================
    
    def add_debt(self, debt: Debt) -> Optional[int]:
        """Ajoute une dette"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT INTO debts 
                    (server_id, customer_name, amount, remaining_amount, due_date, 
                     status, branch_id, created_at, updated_at, is_synced, notes)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    debt.server_id, debt.customer_name, debt.amount, debt.remaining_amount,
                    debt.due_date, debt.status, debt.branch_id, debt.created_at,
                    debt.updated_at, 1 if debt.is_synced else 0, debt.notes
                ))
                return cursor.lastrowid
        except Exception as e:
            logger.error(f"Erreur ajout dette: {e}")
            return None
    
    def get_pending_debts(self, branch_id: Optional[int] = None) -> List[Debt]:
        """Récupère les dettes en attente"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                sql = "SELECT * FROM debts WHERE status IN ('pending', 'partial')"
                params = []
                
                if branch_id:
                    sql += " AND branch_id = ?"
                    params.append(branch_id)
                
                sql += " ORDER BY due_date"
                
                cursor.execute(sql, params)
                rows = cursor.fetchall()
                return [Debt(
                    id=row['id'],
                    server_id=row['server_id'],
                    customer_name=row['customer_name'],
                    amount=row['amount'],
                    remaining_amount=row['remaining_amount'],
                    due_date=row['due_date'],
                    status=row['status'],
                    branch_id=row['branch_id'],
                    created_at=row['created_at'],
                    updated_at=row['updated_at'],
                    is_synced=bool(row['is_synced']),
                    notes=row['notes']
                ) for row in rows]
        except Exception as e:
            logger.error(f"Erreur récupération dettes: {e}")
            return []
    
    def get_total_debts(self, branch_id: Optional[int] = None) -> float:
        """Total des dettes impayées"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                sql = "SELECT COALESCE(SUM(remaining_amount), 0) as total FROM debts WHERE status IN ('pending', 'partial')"
                params = []
                
                if branch_id:
                    sql += " AND branch_id = ?"
                    params.append(branch_id)
                
                cursor.execute(sql, params)
                row = cursor.fetchone()
                return row['total'] if row else 0.0
        except Exception as e:
            logger.error(f"Erreur total dettes: {e}")
            return 0.0
    
    # ==================== SYNCHRONISATION ====================
    
    def save_sync_log(self, sync_data) -> bool:
        """
        Sauvegarde un log de synchronisation
        Accepte soit un dictionnaire de résultats, soit (sync_type, records_synced, status, ...)
        """
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                
                # Vérifier le type d'argument
                if isinstance(sync_data, dict):
                    # Format dictionnaire (de sync_service)
                    sync_type = sync_data.get('sync_type', 'full')
                    records_synced = sync_data.get('products_imported', 0) + sync_data.get('sales_exported', 0) + sync_data.get('expenses_exported', 0)
                    status = "success" if not sync_data.get('errors') else "partial"
                    error_message = "; ".join(sync_data.get('errors', [])) if sync_data.get('errors') else None
                    details = json.dumps(sync_data)
                else:
                    # Format paramètres individuels (legacy)
                    # Dans ce cas, les arguments sont passés normalement
                    # Cette branche ne devrait pas être utilisée directement
                    return False
                
                cursor.execute("""
                    INSERT INTO sync_logs (sync_type, sync_date, records_synced, status, error_message, details)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (
                    sync_type, datetime.now().isoformat(), records_synced, status, error_message, details
                ))
                return True
        except Exception as e:
            logger.error(f"Erreur sauvegarde log sync: {e}")
            return False
    
    def save_sync_log_legacy(self, sync_type: str, records_synced: int, status: str, error_message: str = None, details: str = None) -> bool:
        """Version legacy avec paramètres individuels"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT INTO sync_logs (sync_type, sync_date, records_synced, status, error_message, details)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (
                    sync_type, datetime.now().isoformat(), records_synced, status, error_message, details
                ))
                return True
        except Exception as e:
            logger.error(f"Erreur sauvegarde log sync: {e}")
            return False
    
    def get_last_sync_time(self) -> Optional[str]:
        """Récupère la dernière date de synchronisation"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT MAX(sync_date) as last_sync FROM sync_logs WHERE status = 'success'")
                row = cursor.fetchone()
                return row['last_sync'] if row and row['last_sync'] else None
        except Exception as e:
            logger.error(f"Erreur récupération last_sync: {e}")
            return None
    
    def get_pending_sync_count(self) -> int:
        """Compte les éléments en attente de synchronisation"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT COUNT(*) as count FROM sales WHERE is_synced = 0")
                sales_count = cursor.fetchone()['count']
                
                cursor.execute("SELECT COUNT(*) as count FROM expenses WHERE is_synced = 0")
                expenses_count = cursor.fetchone()['count']
                
                return sales_count + expenses_count
        except Exception as e:
            logger.error(f"Erreur comptage pending sync: {e}")
            return 0
    
    # ==================== TABLEAU DE BORD ====================
    
    def get_stats(self) -> Dict:
        """
        Récupère toutes les statistiques pour le tableau de bord
        
        Returns:
            Dict contenant les statistiques formatées pour l'affichage
        """
        try:
            user = self.get_current_user()
            branch_id = user.branch_id if user else None
            
            dashboard_stats = self.get_dashboard_stats(branch_id)
            
            # Récupérer les produits en stock bas (liste d'objets Product)
            low_stock_products = self.get_low_stock_products(branch_id)
            
            # Convertir les objets Product en dictionnaires pour l'affichage
            # Dans la méthode get_stats, remplacer la conversion des produits low_stock
            low_stock_list = []
            for product in low_stock_products:
                # Utiliser l'attribut stock ou quantity
                stock_value = product.stock if hasattr(product, 'stock') else (product.quantity if hasattr(product, 'quantity') else 0)
                
                low_stock_list.append({
                    'id': product.server_id,
                    'name': product.name,
                    'code': product.code,
                    'stock': stock_value,
                    'min_stock': product.min_stock,
                    'price': product.selling_price,
                    'unit': product.unit
                })
            
            # Récupérer les produits expirés
            expired_products = self.get_expired_products(branch_id)
            expired_count = len(expired_products)
            expired_list = []
            for product in expired_products:
                expired_list.append({
                    'id': product.server_id,
                    'name': product.name,
                    'code': product.code,
                    'stock': product.stock,
                    'expiry_date': product.expiry_date,  # Correction: utiliser expiry_date directement
                    'price': product.price
                })
            
            # Récupérer les produits qui expirent bientôt
            soon_expiring_products = self.get_soon_expiring_products(branch_id)
            soon_expiring_count = len(soon_expiring_products)
            soon_expiring_list = []
            for product in soon_expiring_products:
                soon_expiring_list.append({
                    'id': product.server_id,
                    'name': product.name,
                    'code': product.code,
                    'stock': product.stock,
                    'expiry_date': product.expiry_date,
                    'price': product.price
                })
            
            # Récupérer les dettes en attente
            pending_debts = self.get_pending_debts(branch_id)
            pending_debts_list = []
            for debt in pending_debts:
                pending_debts_list.append({
                    'id': debt.id,
                    'customer_name': debt.customer_name,
                    'amount': debt.amount,
                    'remaining_amount': debt.remaining_amount,
                    'due_date': debt.due_date,
                    'status': debt.status
                })
            
            return {
                # Statistiques de ventes
                'today_sales': dashboard_stats.today_sales,
                'week_sales': dashboard_stats.week_sales,
                'month_sales': dashboard_stats.month_sales,
                'today_sales_count': self.get_sales_count_today(branch_id),
                
                # Statistiques de dépenses
                'today_expenses': dashboard_stats.today_expenses,
                'week_expenses': dashboard_stats.week_expenses,
                'month_expenses': dashboard_stats.month_expenses,
                
                # Statistiques de synchronisation
                'pending_sync_count': dashboard_stats.pending_sync_count,
                
                # Statistiques de dettes
                'total_debts': dashboard_stats.total_debts,
                'pending_debts_count': len(pending_debts),
                'pending_debts': pending_debts_list,
                
                # Statistiques de stock
                'low_stock_count': dashboard_stats.low_stock_count,
                'low_stock_products': low_stock_list,
                
                # Statistiques d'expiration
                'expired_count': expired_count,
                'expired_products': expired_list,
                'soon_expiring_count': soon_expiring_count,
                'soon_expiring_products': soon_expiring_list,
                
                # Statistiques générales
                'total_products': self.get_product_count(branch_id),
                'total_sales': self.get_total_sales(branch_id),
                'last_sync_date': user.last_sync if user else None
            }
            
        except Exception as e:
            logger.error(f"Erreur lors de la récupération des stats: {e}")
            import traceback
            traceback.print_exc()
            
            # Retourner des valeurs par défaut en cas d'erreur
            return {
                'today_sales': 0.0,
                'week_sales': 0.0,
                'month_sales': 0.0,
                'today_sales_count': 0,
                'today_expenses': 0.0,
                'week_expenses': 0.0,
                'month_expenses': 0.0,
                'pending_sync_count': 0,
                'total_debts': 0.0,
                'pending_debts_count': 0,
                'pending_debts': [],
                'low_stock_count': 0,
                'low_stock_products': [],
                'expired_count': 0,
                'expired_products': [],
                'soon_expiring_count': 0,
                'soon_expiring_products': [],
                'total_products': 0,
                'total_sales': 0,
                'last_sync_date': None
            }
    
    def get_dashboard_stats(self, branch_id: Optional[int] = None) -> DashboardStats:
        """Récupère toutes les statistiques pour le tableau de bord"""
        try:
            # Si branch_id non fourni, prendre celui de l'utilisateur connecté
            if branch_id is None:
                user = self.get_current_user()
                branch_id = user.branch_id if user else None
            
            sales_stats = self.get_sales_stats(branch_id)
            expenses_stats = self.get_expenses_stats(branch_id)
            
            # Récupérer les produits en stock bas
            low_stock_products = self.get_low_stock_products(branch_id)
            
            return DashboardStats(
                today_sales=sales_stats.get('today_sales', 0.0),
                week_sales=sales_stats.get('week_sales', 0.0),
                month_sales=sales_stats.get('month_sales', 0.0),
                today_expenses=expenses_stats.get('today_expenses', 0.0),
                week_expenses=expenses_stats.get('week_expenses', 0.0),
                month_expenses=expenses_stats.get('month_expenses', 0.0),
                pending_sales=0.0,
                pending_sync_count=self.get_pending_sync_count(),
                total_debts=self.get_total_debts(branch_id),
                low_stock_count=len(low_stock_products)
            )
        except Exception as e:
            logger.error(f"Erreur stats dashboard: {e}")
            return DashboardStats()
    
    # ==================== SUCCURSALES ====================
    def save_branches(self, branches: List[Branch]) -> int:
        """Sauvegarde les succursales avec parent_pharmacy_id"""
        saved_count = 0
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                for branch in branches:
                    cursor.execute("""
                        INSERT OR REPLACE INTO branches 
                        (id, name, address, phone, email, manager_name, is_active, parent_pharmacy_id)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        branch.id, branch.name, branch.address, branch.phone,
                        branch.email, branch.manager_name, 1 if branch.is_active else 0,
                        getattr(branch, 'parent_pharmacy_id', None)
                    ))
                    saved_count += 1
                return saved_count
        except Exception as e:
            logger.error(f"Erreur sauvegarde branches: {e}")
            return 0
    
    def get_pharmacy_by_branch(self, branch_id: str) -> Optional[str]:
        """Récupère l'ID de la pharmacie associée à une branche"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT parent_pharmacy_id FROM branches WHERE id = ?
                """, (branch_id,))
                row = cursor.fetchone()
                return str(row[0]) if row and row[0] else None
        except Exception as e:
            logger.error(f"Erreur get_pharmacy_by_branch: {e}")
            return None
    
    def get_branches(self) -> List[Branch]:
        """Récupère toutes les succursales"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT * FROM branches WHERE is_active = 1 ORDER BY name")
                rows = cursor.fetchall()
                return [Branch(
                    id=row['id'],
                    name=row['name'],
                    address=row['address'],
                    phone=row['phone'],
                    email=row['email'],
                    manager_name=row['manager_name'],
                    is_active=bool(row['is_active'])
                ) for row in rows]
        except Exception as e:
            logger.error(f"Erreur récupération branches: {e}")
            return []
    
    # ==================== VENTES SUPPLÉMENTAIRES ====================
    
    def add_sale_with_stock_update(self, sale: Sale) -> Optional[int]:
        """Ajoute une vente et met à jour le stock automatiquement"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                
                # Vérifier le stock disponible
                cursor.execute("SELECT stock FROM products WHERE server_id = ?", (sale.product_id,))
                row = cursor.fetchone()
                
                if not row:
                    logger.error(f"Produit {sale.product_id} non trouvé")
                    return None
                
                if row['stock'] < sale.quantity:
                    logger.error(f"Stock insuffisant pour le produit {sale.product_id}")
                    return None
                
                # Mettre à jour le stock
                cursor.execute(
                    "UPDATE products SET stock = stock - ? WHERE server_id = ?",
                    (sale.quantity, sale.product_id)
                )
                
                # Ajouter la vente
                cursor.execute("""
                    INSERT INTO sales 
                    (product_id, quantity, unit_price, total_price, sale_date, 
                     customer_name, branch_id, is_synced, seller_id, payment_method, invoice_number)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    sale.product_id, sale.quantity, sale.unit_price, sale.total_price,
                    sale.sale_date, sale.customer_name, sale.branch_id,
                    1 if sale.is_synced else 0, sale.seller_id, sale.payment_method, sale.invoice_number
                ))
                
                return cursor.lastrowid
        except Exception as e:
            logger.error(f"Erreur ajout vente avec mise à jour stock: {e}")
            return None
    
    def get_sales_by_period(self, start_date: str, end_date: str, branch_id: Optional[int] = None) -> List[Dict]:
        """Récupère les ventes sur une période"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                sql = """
                    SELECT s.*, p.name as product_name, p.code as product_code
                    FROM sales s
                    LEFT JOIN products p ON s.product_id = p.server_id
                    WHERE date(s.sale_date) BETWEEN ? AND ?
                """
                params = [start_date, end_date]
                
                if branch_id:
                    sql += " AND s.branch_id = ?"
                    params.append(branch_id)
                
                sql += " ORDER BY s.sale_date DESC"
                
                cursor.execute(sql, params)
                rows = cursor.fetchall()
                return [dict(row) for row in rows]
        except Exception as e:
            logger.error(f"Erreur récupération ventes période: {e}")
            return []
    
    def get_expired_products(self, branch_id: Optional[int] = None) -> List[Product]:
        """Récupère les produits expirés"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                sql = "SELECT * FROM products WHERE expiry_status = 'expired' AND is_deleted = 0"
                params = []
                
                if branch_id:
                    sql += " AND branch_id = ?"
                    params.append(branch_id)
                
                cursor.execute(sql, params)
                rows = cursor.fetchall()
                return [self._row_to_product(row) for row in rows]
        except Exception as e:
            logger.error(f"Erreur récupération produits expirés: {e}")
            return []

    def get_soon_expiring_products(self, branch_id: Optional[int] = None) -> List[Product]:
        """Récupère les produits qui expirent bientôt"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                sql = "SELECT * FROM products WHERE expiry_status = 'soon' AND is_deleted = 0"
                params = []
                
                if branch_id:
                    sql += " AND branch_id = ?"
                    params.append(branch_id)
                
                cursor.execute(sql, params)
                rows = cursor.fetchall()
                return [self._row_to_product(row) for row in rows]
        except Exception as e:
            logger.error(f"Erreur récupération produits expirant bientôt: {e}")
            return []

    def update_expiry_statuses(self) -> int:
        """Met à jour les statuts d'expiration de tous les produits"""
        from datetime import datetime
        
        updated_count = 0
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT server_id, expiry_date FROM products WHERE expiry_date IS NOT NULL")
                rows = cursor.fetchall()
                
                for row in rows:
                    expiry_date_str = row['expiry_date']
                    if expiry_date_str:
                        try:
                            if 'T' in expiry_date_str:
                                expiry_date = datetime.fromisoformat(expiry_date_str.split('T')[0])
                            else:
                                expiry_date = datetime.fromisoformat(expiry_date_str)
                            
                            today = datetime.now().date()
                            expiry_date = expiry_date.date() if hasattr(expiry_date, 'date') else expiry_date
                            days_left = (expiry_date - today).days
                            
                            if days_left < 0:
                                status = 'expired'
                            elif days_left <= 30:
                                status = 'soon'
                            else:
                                status = 'valid'
                            
                            cursor.execute(
                                "UPDATE products SET expiry_status = ? WHERE server_id = ?",
                                (status, row['server_id'])
                            )
                            updated_count += 1
                        except Exception as e:
                            logger.error(f"Erreur mise à jour statut produit {row['server_id']}: {e}")
                
                return updated_count
        except Exception as e:
            logger.error(f"Erreur mise à jour statuts expiration: {e}")
            return 0

    def _row_to_product(self, row) -> Product:
        """Convertit une ligne SQLite en objet Product"""
        from .models import Product as ProductModel
        
        quantity_value = row['quantity'] if 'quantity' in row.keys() else 0
        
        return ProductModel(
            server_id=row['server_id'],
            name=row['name'],
            code=row['code'],
            selling_price=row['selling_price'],
            stock=quantity_value,
            quantity=quantity_value,
            category=row['category'],
            branch_id=row['branch_id'],
            pharmacy_id=row['pharmacy_id'] if 'pharmacy_id' in row.keys() else None,
            tenant_id=row['tenant_id'] if 'tenant_id' in row.keys() else None,
            updated_at=row['updated_at'],
            is_deleted=bool(row['is_deleted']),
            description=row['description'] if 'description' in row.keys() else '',
            barcode=row['barcode'],
            min_stock=row['min_stock'],
            max_stock=row['max_stock'],
            unit=row['unit'],
            tax_rate=row['tax_rate'],
            expiry_date=row['expiry_date'],
            expiry_status=row['expiry_status'] if 'expiry_status' in row.keys() else 'unknown',
            manufacturing_date=row['manufacturing_date'] if 'manufacturing_date' in row.keys() else None,
            lot_number=row['lot_number'],
            supplier=row['supplier'],
            location=row['location'],
            status=row['status'] if 'status' in row.keys() else 'active',
            alert_threshold_days=row['alert_threshold_days'] if 'alert_threshold_days' in row.keys() else 30,
            stock_version=row['stock_version'] if 'stock_version' in row.keys() else 1,
            last_sync_at=row['last_sync_at'] if 'last_sync_at' in row.keys() else None,
            synced_quantity=row['synced_quantity'] if 'synced_quantity' in row.keys() else quantity_value
        )
            
    # ==================== INITIALISATION ====================
    
    def init_default_data(self):
        """Initialise les données par défaut si la base est vide"""
        # Vérifier si des branches existent
        branches = self.get_branches()
        if not branches:
            # Ajouter une branche par défaut
            default_branch = Branch(
                id=1,
                name="Succursale Principale",
                address="Adresse par défaut",
                phone="+123456789",
                email="contact@pharmacie.com",
                manager_name="Administrateur",
                is_active=True
            )
            self.save_branches([default_branch])
            logger.info("Branche par défaut créée")
    
    # ==================== GESTION DES FACTURES ====================

    def get_next_invoice_number(self) -> str:
        """Génère le prochain numéro de facture depuis la base de données"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                
                # Récupérer et incrémenter le compteur
                cursor.execute("""
                    UPDATE invoice_counter 
                    SET current_number = current_number + 1,
                        last_updated = CURRENT_TIMESTAMP
                    WHERE id = 1
                """)
                
                # Récupérer la nouvelle valeur
                cursor.execute("SELECT current_number FROM invoice_counter WHERE id = 1")
                row = cursor.fetchone()
                
                if row:
                    next_num = row['current_number']
                else:
                    # Si le compteur n'existe pas, l'initialiser
                    cursor.execute("INSERT INTO invoice_counter (id, current_number) VALUES (1, 2)")
                    next_num = 2
                
                # Formater le numéro (ex: INV-20241215-0001)
                date_str = datetime.now().strftime("%Y%m%d")
                return f"INV-{date_str}-{next_num:04d}"
                
        except Exception as e:
            logger.error(f"Erreur génération numéro facture: {e}")
            # Fallback: utiliser timestamp
            return f"INV-{datetime.now().strftime('%Y%m%d%H%M%S')}"
    
    def get_current_invoice_number(self) -> int:
        """Récupère le numéro de facture courant sans l'incrémenter"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT current_number FROM invoice_counter WHERE id = 1")
                row = cursor.fetchone()
                return row['current_number'] if row else 1
        except Exception as e:
            logger.error(f"Erreur récupération numéro courant: {e}")
            return 1
    
    def reset_invoice_counter(self, new_value: int = 1) -> bool:
        """Réinitialise le compteur de factures (utile pour admin)"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    UPDATE invoice_counter 
                    SET current_number = ?, last_updated = CURRENT_TIMESTAMP
                    WHERE id = 1
                """, (new_value,))
                return cursor.rowcount > 0
        except Exception as e:
            logger.error(f"Erreur réinitialisation compteur: {e}")
            return False

    def sync_invoice_counter(self, server_counter: int) -> bool:
        """Synchronise le compteur avec le serveur (prendre le max des deux)"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT current_number FROM invoice_counter WHERE id = 1")
                row = cursor.fetchone()
                local_counter = row['current_number'] if row else 1
                
                # Prendre le maximum entre local et serveur
                new_counter = max(local_counter, server_counter)
                
                cursor.execute("""
                    UPDATE invoice_counter 
                    SET current_number = ?, last_updated = CURRENT_TIMESTAMP
                    WHERE id = 1
                """, (new_counter,))
                
                logger.info(f"Compteur synchronisé: local={local_counter}, serveur={server_counter}, nouveau={new_counter}")
                return True
        except Exception as e:
            logger.error(f"Erreur synchronisation compteur: {e}")
            return False

    
    def save_invoice(self, invoice_data: Dict, items: List[Dict]) -> Optional[str]:
        """Sauvegarde une facture complète avec ses lignes"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                
                # Insérer la facture
                cursor.execute("""
                    INSERT OR REPLACE INTO invoices 
                    (invoice_number, sale_date, customer_name, total_amount, 
                    payment_method, branch_id, seller_id, seller_name, 
                    status, is_modified, original_invoice_number, 
                    modification_date, modification_reason)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    invoice_data.get('invoice_number'),
                    invoice_data.get('sale_date'),
                    invoice_data.get('customer_name'),
                    invoice_data.get('total_amount'),
                    invoice_data.get('payment_method', 'cash'),
                    invoice_data.get('branch_id'),
                    invoice_data.get('seller_id'),
                    invoice_data.get('seller_name'),
                    invoice_data.get('status', 'completed'),
                    invoice_data.get('is_modified', 0),
                    invoice_data.get('original_invoice_number'),
                    invoice_data.get('modification_date'),
                    invoice_data.get('modification_reason')
                ))
                
                # Insérer les lignes
                for item in items:
                    cursor.execute("""
                        INSERT OR REPLACE INTO invoice_items 
                        (invoice_number, product_id, product_name, quantity, 
                        unit_price, total_price, is_returned, returned_quantity,
                        exchange_product_id, exchange_product_name, 
                        exchange_quantity, exchange_unit_price, exchange_total)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        invoice_data.get('invoice_number'),
                        item.get('product_id'),
                        item.get('product_name'),
                        item.get('quantity'),
                        item.get('unit_price'),
                        item.get('total_price'),
                        item.get('is_returned', 0),
                        item.get('returned_quantity', 0),
                        item.get('exchange_product_id'),
                        item.get('exchange_product_name'),
                        item.get('exchange_quantity', 0),
                        item.get('exchange_unit_price', 0),
                        item.get('exchange_total', 0)
                    ))
                
                return invoice_data.get('invoice_number')
                
        except Exception as e:
            logger.error(f"Erreur sauvegarde facture: {e}")
            return None

    def get_invoices(self, branch_id: Optional[str] = None, 
                start_date: Optional[str] = None, 
                end_date: Optional[str] = None,
                search_term: str = "") -> List[Dict]:
        """
        Récupère les factures avec filtres depuis la table sales.
        """
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                
                # Utiliser la table sales (qui contient toutes les factures)
                # et vérifier les colonnes disponibles
                cursor.execute("PRAGMA table_info(sales)")
                sales_columns = [col[1] for col in cursor.fetchall()]
                
                # Construire la requête dynamiquement selon les colonnes existantes
                select_fields = [
                    "id",
                    "invoice_number",
                    "customer_name",
                    "total_price as total_amount",
                    "sale_date",
                    "payment_method",
                    "branch_id",
                    "seller_id",
                    "created_at"
                ]
                
                # Ajouter les colonnes optionnelles si elles existent
                optional_fields = ['is_returned', 'is_exchange', 'is_modified', 'is_synced']
                for field in optional_fields:
                    if field in sales_columns:
                        if field == 'is_synced':
                            select_fields.append(f"{field} as server_synced")
                        else:
                            select_fields.append(field)
                
                sql = f"""
                    SELECT {', '.join(select_fields)}
                    FROM sales 
                    WHERE invoice_number IS NOT NULL 
                    AND invoice_number != '' 
                    AND invoice_number != 'None'
                    AND CAST(invoice_number AS TEXT) != ''
                """
                params = []
                
                if branch_id:
                    sql += " AND branch_id = ?"
                    params.append(branch_id)
                
                if start_date:
                    sql += " AND date(sale_date) >= date(?)"
                    params.append(start_date)
                
                if end_date:
                    sql += " AND date(sale_date) <= date(?)"
                    params.append(end_date)
                
                if search_term:
                    sql += """ AND (invoice_number LIKE ? OR customer_name LIKE ? 
                            OR CAST(total_price AS TEXT) LIKE ?)"""
                    search_pattern = f"%{search_term}%"
                    params.extend([search_pattern, search_pattern, search_pattern])
                
                sql += " ORDER BY sale_date DESC, id DESC"
                
                logger.info(f"get_invoices SQL: {sql}")
                
                cursor.execute(sql, params)
                rows = cursor.fetchall()
                
                invoices = []
                for row in rows:
                    invoice = dict(row)
                    # Convertir les types
                    if 'total_amount' in invoice and invoice['total_amount'] is None:
                        invoice['total_amount'] = 0
                    if 'server_synced' in invoice:
                        invoice['server_synced'] = bool(invoice['server_synced'])
                    else:
                        invoice['server_synced'] = False
                    invoices.append(invoice)
                
                # Si aucune facture trouvée dans sales, essayer la table invoices
                if not invoices:
                    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='invoices'")
                    invoices_table_exists = cursor.fetchone() is not None
                    
                    if invoices_table_exists:
                        logger.info("Aucune facture dans sales, essai dans la table invoices")
                        
                        # Vérifier les colonnes de la table invoices
                        cursor.execute("PRAGMA table_info(invoices)")
                        invoices_columns = [col[1] for col in cursor.fetchall()]
                        
                        # Construire la requête pour invoices
                        inv_select_fields = ["invoice_number", "customer_name", "total_amount", "sale_date", "payment_method", "branch_id", "created_at"]
                        if 'is_modified' in invoices_columns:
                            inv_select_fields.append("is_modified")
                        
                        sql2 = f"""
                            SELECT {', '.join(inv_select_fields)}
                            FROM invoices 
                            WHERE 1=1
                        """
                        params2 = []
                        
                        if branch_id:
                            sql2 += " AND branch_id = ?"
                            params2.append(branch_id)
                        
                        if start_date:
                            sql2 += " AND date(sale_date) >= date(?)"
                            params2.append(start_date)
                        
                        if end_date:
                            sql2 += " AND date(sale_date) <= date(?)"
                            params2.append(end_date)
                        
                        if search_term:
                            sql2 += " AND (invoice_number LIKE ? OR customer_name LIKE ?)"
                            search_pattern = f"%{search_term}%"
                            params2.extend([search_pattern, search_pattern])
                        
                        sql2 += " ORDER BY sale_date DESC"
                        
                        cursor.execute(sql2, params2)
                        rows2 = cursor.fetchall()
                        for row in rows2:
                            invoice = dict(row)
                            invoice['server_synced'] = True  # Les factures de la table invoices sont considérées comme synchronisées
                            invoice['source'] = 'local_table'
                            invoices.append(invoice)
                
                logger.info(f"get_invoices: branch={branch_id}, start={start_date}, end={end_date}, count={len(invoices)}")
                
                # Debug: afficher les premières factures trouvées
                for inv in invoices[:3]:
                    logger.info(f"  - Facture: {inv.get('invoice_number')}, client={inv.get('customer_name')}, montant={inv.get('total_amount')}")
                
                return invoices
                
        except Exception as e:
            logger.error(f"Erreur récupération factures: {e}")
            import traceback
            traceback.print_exc()
            return []

    def get_invoice_by_number(self, invoice_number: str) -> Optional[Dict]:
        """Récupère une facture par son numéro"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT * FROM invoices WHERE invoice_number = ?", (invoice_number,))
                row = cursor.fetchone()
                if row:
                    return dict(row)
                return None
        except Exception as e:
            logger.error(f"Erreur récupération facture: {e}")
            return None

    def get_invoice_items(self, invoice_number: str) -> List[Dict]:
        """Récupère les lignes d'une facture"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT * FROM invoice_items WHERE invoice_number = ?", (invoice_number,))
                rows = cursor.fetchall()
                return [dict(row) for row in rows]
        except Exception as e:
            logger.error(f"Erreur récupération lignes facture: {e}")
            return []

    def get_invoice_with_items(self, invoice_number: str) -> Optional[Dict]:
        """Récupère une facture avec ses lignes"""
        invoice = self.get_invoice_by_number(invoice_number)
        if invoice:
            invoice['items'] = self.get_invoice_items(invoice_number)
        return invoice

    def get_return_history(self, branch_id: Optional[str] = None, 
                        start_date: Optional[str] = None,
                        end_date: Optional[str] = None) -> List[Dict]:
        """Récupère l'historique des retours et échanges"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                
                sql = "SELECT * FROM returns WHERE 1=1"
                params = []
                
                if branch_id:
                    sql += " AND branch_id = ?"
                    params.append(branch_id)
                
                if start_date:
                    sql += " AND date(return_date) >= ?"
                    params.append(start_date)
                
                if end_date:
                    sql += " AND date(return_date) <= ?"
                    params.append(end_date)
                
                sql += " ORDER BY return_date DESC"
                
                cursor.execute(sql, params)
                rows = cursor.fetchall()
                return [dict(row) for row in rows]
                
        except Exception as e:
            logger.error(f"Erreur récupération historique retours: {e}")
            return []

    def get_unsynced_returns(self) -> List[Dict]:
        """Récupère les retours non synchronisés"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT * FROM returns 
                    WHERE is_synced = 0 
                    ORDER BY return_date
                """)
                rows = cursor.fetchall()
                return [dict(row) for row in rows]
        except Exception as e:
            logger.error(f"Erreur récupération retours non sync: {e}")
            return []

    def get_unsynced_debts(self) -> List[Dict]:
        """Récupère les dettes non synchronisées"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT * FROM debts 
                    WHERE is_synced = 0 
                    ORDER BY created_at
                """)
                rows = cursor.fetchall()
                return [dict(row) for row in rows]
        except Exception as e:
            logger.error(f"Erreur récupération dettes non sync: {e}")
            return []

    def mark_returns_synced(self, return_ids: List[int]) -> bool:
        """Marque des retours comme synchronisés"""
        if not return_ids:
            return True
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                placeholders = ','.join('?' * len(return_ids))
                cursor.execute(
                    f"UPDATE returns SET is_synced = 1, synced_at = ? WHERE id IN ({placeholders})",
                    [datetime.now().isoformat()] + return_ids
                )
                return True
        except Exception as e:
            logger.error(f"Erreur marquage retours sync: {e}")
            return False

    def mark_debts_synced(self, debt_ids: List[int]) -> bool:
        """Marque des dettes comme synchronisées"""
        if not debt_ids:
            return True
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                placeholders = ','.join('?' * len(debt_ids))
                cursor.execute(
                    f"UPDATE debts SET is_synced = 1 WHERE id IN ({placeholders})",
                    debt_ids
                )
                return True
        except Exception as e:
            logger.error(f"Erreur marquage dettes sync: {e}")
            return False
    
    def get_product_uuid_by_local_id(self, local_id: int) -> Optional[str]:
        """Récupère l'UUID serveur d'un produit à partir de son ID local"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT server_id FROM products WHERE server_id = ? OR id = ?", (local_id, local_id))
                row = cursor.fetchone()
                if row:
                    return row['server_id']
                return None
        except Exception as e:
            logger.error(f"Erreur get_product_uuid: {e}")
            return None

    def get_sync_logs(self, limit: int = 20) -> List[Dict]:
        """Récupère l'historique des synchronisations"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT * FROM sync_logs 
                    ORDER BY sync_date DESC 
                    LIMIT ?
                """, (limit,))
                rows = cursor.fetchall()
                return [dict(row) for row in rows]
        except Exception as e:
            logger.error(f"Erreur récupération logs sync: {e}")
            return []
    
    def get_unsynced_sales_with_metadata(self) -> List[Dict]:
        """Récupère les ventes avec métadonnées pour la synchronisation"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                
                query = """
                    SELECT 
                        s.id,
                        s.product_id,
                        s.product_name,
                        s.quantity,
                        s.unit_price,
                        s.total_price,
                        s.sale_date,
                        s.customer_name,
                        s.branch_id,
                        s.payment_method,
                        s.invoice_number,
                        s.created_at,
                        s.stock_version_at_sale,
                        s.stock_quantity_at_sale,
                        s.device_id,
                        p.server_id as product_uuid,
                        p.name as product_server_name,
                        p.quantity as product_current_stock,
                        p.stock_version as product_version,
                        p.synced_quantity
                    FROM sales s
                    LEFT JOIN products p ON s.product_id = p.server_id
                    WHERE s.is_synced = 0
                    ORDER BY s.sale_date ASC, s.created_at ASC
                """
                
                cursor.execute(query)
                rows = cursor.fetchall()
                results = []
                
                for row in rows:
                    result = dict(row)
                    # Valeurs par défaut si None
                    if result.get('stock_version_at_sale') is None:
                        result['stock_version_at_sale'] = 1
                    if result.get('stock_quantity_at_sale') is None:
                        result['stock_quantity_at_sale'] = 0
                    if result.get('product_current_stock') is None:
                        result['product_current_stock'] = 0
                    if result.get('product_version') is None:
                        result['product_version'] = 1
                    
                    results.append(result)
                
                logger.info(f"Récupéré {len(results)} ventes non synchronisées")
                return results
                
        except Exception as e:
            logger.error(f"Erreur get_unsynced_sales_with_metadata: {e}")
            import traceback
            traceback.print_exc()
            return []
    
    def update_sale_quantity(self, sale_id: int, accepted_qty: int, rejected_qty: int, reason: str) -> bool:
        """
        Met à jour une vente partiellement acceptée.
        """
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                
                # Vérifier les colonnes disponibles
                cursor.execute("PRAGMA table_info(sales)")
                columns = [col[1] for col in cursor.fetchall()]
                
                # Construire la requête dynamiquement
                set_clauses = ["quantity = ?"]
                params = [accepted_qty]
                
                if 'rejected_quantity' in columns:
                    set_clauses.append("rejected_quantity = ?")
                    params.append(rejected_qty)
                
                if 'rejection_reason' in columns:
                    set_clauses.append("rejection_reason = ?")
                    params.append(reason)
                
                if 'is_partial' in columns:
                    set_clauses.append("is_partial = 1")
                
                if 'is_synced' in columns:
                    set_clauses.append("is_synced = 1")
                
                if 'modified_at' in columns:
                    set_clauses.append("modified_at = CURRENT_TIMESTAMP")
                
                params.append(sale_id)
                
                query = f"UPDATE sales SET {', '.join(set_clauses)} WHERE id = ?"
                cursor.execute(query, params)
                
                logger.info(f"Vente {sale_id} mise à jour: acceptée={accepted_qty}, rejetée={rejected_qty}")
                return cursor.rowcount > 0
                
        except Exception as e:
            logger.error(f"Erreur update_sale_quantity: {e}")
            return False
    
    def mark_sale_rejected(self, sale_id: int, reason: str) -> bool:
        """
        Marque une vente comme rejetée.
        """
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                
                # Vérifier les colonnes disponibles
                cursor.execute("PRAGMA table_info(sales)")
                columns = [col[1] for col in cursor.fetchall()]
                
                # Construire la requête dynamiquement
                set_clauses = ["is_synced = 1"]
                params = []
                
                if 'is_rejected' in columns:
                    set_clauses.append("is_rejected = 1")
                
                if 'rejection_reason' in columns:
                    set_clauses.append("rejection_reason = ?")
                    params.append(reason)
                
                if 'synced_at' in columns:
                    set_clauses.append("synced_at = ?")
                    params.append(datetime.now().isoformat())
                
                params.append(sale_id)
                
                query = f"UPDATE sales SET {', '.join(set_clauses)} WHERE id = ?"
                cursor.execute(query, params)
                
                logger.info(f"Vente {sale_id} marquée comme rejetée: {reason[:50]}")
                return cursor.rowcount > 0
                
        except Exception as e:
            logger.error(f"Erreur mark_sale_rejected: {e}")
            return False
    
    def save_sync_feedback(self, feedback: Dict) -> bool:
        """
        Enregistre les feedbacks de synchronisation pour l'utilisateur.
        """
        try:
            # Créer la table si elle n'existe pas
            with self.get_connection() as conn:
                cursor = conn.cursor()
                
                # Créer la table sync_feedback si elle n'existe pas
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS sync_feedback (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        sale_id INTEGER,
                        feedback_type TEXT NOT NULL,
                        message TEXT NOT NULL,
                        details TEXT,
                        product_name TEXT,
                        accepted_quantity INTEGER,
                        rejected_quantity INTEGER,
                        created_at TEXT NOT NULL,
                        is_read INTEGER DEFAULT 0
                    )
                """)
                
                # Insérer le feedback
                cursor.execute("""
                    INSERT INTO sync_feedback 
                    (sale_id, feedback_type, message, details, product_name, 
                    accepted_quantity, rejected_quantity, created_at, is_read)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    feedback.get('sale_id'),
                    feedback.get('type'),
                    feedback.get('message', ''),
                    json.dumps(feedback.get('details', {})),
                    feedback.get('product_name'),
                    feedback.get('accepted_quantity'),
                    feedback.get('rejected_quantity'),
                    datetime.now().isoformat(),
                    0
                ))
                
                logger.info(f"Feedback enregistré: {feedback.get('type')} pour vente {feedback.get('sale_id')}")
                return True
                
        except Exception as e:
            logger.error(f"Erreur save_sync_feedback: {e}")
            return False
    
    def get_pending_feedback(self, user_id: str = None) -> List[Dict]:
        """
        Récupère les feedbacks non lus.
        """
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                
                cursor.execute("""
                    SELECT * FROM sync_feedback 
                    WHERE is_read = 0
                    ORDER BY created_at DESC
                    LIMIT 50
                """)
                
                rows = cursor.fetchall()
                return [dict(row) for row in rows]
                
        except Exception as e:
            logger.error(f"Erreur get_pending_feedback: {e}")
            return []
    
    def mark_feedback_read(self, feedback_ids: List[int]) -> bool:
        """
        Marque des feedbacks comme lus.
        """
        if not feedback_ids:
            return True
        
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                placeholders = ','.join('?' * len(feedback_ids))
                cursor.execute(
                    f"UPDATE sync_feedback SET is_read = 1 WHERE id IN ({placeholders})",
                    feedback_ids
                )
                return True
        except Exception as e:
            logger.error(f"Erreur mark_feedback_read: {e}")
            return False
    
    def get_product_by_server_id(self, server_id: str) -> Optional[Dict]:
        """Récupère un produit par son server_id (UUID string) sous forme de dict"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT * FROM products WHERE server_id = ?", (server_id,))
                row = cursor.fetchone()
                if row:
                    return dict(row)
                return None
        except Exception as e:
            logger.error(f"Erreur get_product_by_server_id: {e}")
            return None
    
    def get_products_by_branch(self, branch_id: str) -> List[Dict]:
        """
        Récupère tous les produits d'une branche.
        
        Args:
            branch_id: ID de la branche
        
        Returns:
            Liste des produits de la branche
        """
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT * FROM products 
                    WHERE branch_id = ? AND is_deleted = 0 
                    ORDER BY name
                """, (branch_id,))
                rows = cursor.fetchall()
                return [dict(row) for row in rows]
        except Exception as e:
            logger.error(f"Erreur get_products_by_branch: {e}")
            return []
    
    def get_product_by_barcode(self, barcode: str, branch_id: str = None) -> Optional[Dict]:
        """
        Récupère un produit par son code-barres.
        
        Args:
            barcode: Code-barres du produit
            branch_id: ID de la branche (optionnel)
        
        Returns:
            Dictionnaire des données du produit ou None
        """
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                if branch_id:
                    cursor.execute(
                        "SELECT * FROM products WHERE barcode = ? AND branch_id = ? AND is_deleted = 0",
                        (barcode, branch_id)
                    )
                else:
                    cursor.execute(
                        "SELECT * FROM products WHERE barcode = ? AND is_deleted = 0",
                        (barcode,)
                    )
                row = cursor.fetchone()
                if row:
                    return dict(row)
                return None
        except Exception as e:
            logger.error(f"Erreur get_product_by_barcode: {e}")
            return None
    
    def update_local_stock(self, product_id: str, new_quantity: int, version: int) -> bool:
        """Met à jour le stock local avec le stock serveur"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                
                cursor.execute("""
                    UPDATE products 
                    SET quantity = ?,
                        synced_quantity = ?,
                        stock_version = ?,
                        last_sync_at = ?,
                        updated_at = ?
                    WHERE server_id = ?
                """, (
                    new_quantity,
                    new_quantity,
                    version,
                    datetime.now().isoformat(),
                    datetime.now().isoformat(),
                    product_id
                ))
                
                if cursor.rowcount > 0:
                    logger.info(f"Stock mis à jour pour {product_id}: nouvelle quantité={new_quantity}, version={version}")
                    return True
                else:
                    logger.warning(f"Produit {product_id} non trouvé pour mise à jour stock")
                    return False
                    
        except Exception as e:
            logger.error(f"Erreur update_local_stock: {e}")
            return False

    # ==================== EXÉCUTION DE REQUÊTES ====================

    def execute_query(self, query: str, params: tuple = ()) -> List[Dict]:
        """
        Exécute une requête SQL et retourne les résultats sous forme de dictionnaires.
        
        Args:
            query: Requête SQL à exécuter
            params: Paramètres de la requête
        
        Returns:
            Liste de dictionnaires représentant les lignes
        """
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(query, params)
                rows = cursor.fetchall()
                return [dict(row) for row in rows]
        except Exception as e:
            logger.error(f"Erreur execute_query: {e}")
            return []
    
    def execute_update(self, query: str, params: tuple = ()) -> bool:
        """
        Exécute une requête de mise à jour (UPDATE, INSERT, DELETE).
        
        Args:
            query: Requête SQL à exécuter
            params: Paramètres de la requête
        
        Returns:
            True si la mise à jour a réussi, False sinon
        """
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(query, params)
                return cursor.rowcount > 0
        except Exception as e:
            logger.error(f"Erreur execute_update: {e}")
            return False
    # ==================== SALE ITEMS ====================

    def add_sale_item(self, sale_item: Dict) -> Optional[int]:
        """Ajoute un article de vente"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT INTO sale_items 
                    (sale_id, product_id, product_name, quantity, unit_price, total_price)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (
                    sale_item.get('sale_id'),
                    sale_item.get('product_id'),
                    sale_item.get('product_name'),
                    sale_item.get('quantity'),
                    sale_item.get('unit_price'),
                    sale_item.get('total_price')
                ))
                return cursor.lastrowid
        except Exception as e:
            logger.error(f"Erreur ajout sale_item: {e}")
            return None

    def get_sale_items(self, sale_id: int) -> List[Dict]:
        """Récupère les articles d'une vente"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT * FROM sale_items WHERE sale_id = ?", (sale_id,))
                rows = cursor.fetchall()
                return [dict(row) for row in rows]
        except Exception as e:
            logger.error(f"Erreur récupération sale_items: {e}")
            return []

    def get_invoice_items(self, invoice_number: str) -> List[Dict]:
        """Récupère les articles d'une facture"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                
                # Essayer d'abord depuis sale_items
                cursor.execute("""
                    SELECT 
                        si.id,
                        si.product_id,
                        si.product_name,
                        si.quantity,
                        si.unit_price,
                        si.total_price,
                        COALESCE(si.is_returned, 0) as is_returned,
                        COALESCE(si.returned_quantity, 0) as returned_quantity
                    FROM sale_items si
                    JOIN sales s ON si.sale_id = s.id
                    WHERE s.invoice_number = ?
                """, (invoice_number,))
                
                rows = cursor.fetchall()
                
                if rows:
                    return [dict(row) for row in rows]
                
                # Fallback: chercher dans la table invoice_items
                cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='invoice_items'")
                if cursor.fetchone():
                    cursor.execute("""
                        SELECT 
                            id,
                            product_id,
                            product_name,
                            quantity,
                            unit_price,
                            total_price,
                            COALESCE(is_returned, 0) as is_returned,
                            COALESCE(returned_quantity, 0) as returned_quantity
                        FROM invoice_items 
                        WHERE invoice_number = ?
                    """, (invoice_number,))
                    rows = cursor.fetchall()
                    return [dict(row) for row in rows]
                
                # Dernier fallback: chercher directement dans sales (si vente unique)
                cursor.execute("""
                    SELECT 
                        id,
                        product_id,
                        product_name,
                        quantity,
                        unit_price,
                        total_price,
                        COALESCE(is_returned, 0) as is_returned,
                        COALESCE(returned_quantity, 0) as returned_quantity
                    FROM sales 
                    WHERE invoice_number = ?
                """, (invoice_number,))
                rows = cursor.fetchall()
                return [dict(row) for row in rows]
                
        except Exception as e:
            logger.error(f"Erreur récupération invoice_items: {e}")
            return []
    
    def update_sale_item_return(self, item_id: int, returned_qty: int) -> bool:
        """Met à jour la quantité retournée d'un article"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    UPDATE sale_items 
                    SET returned_quantity = ?, is_returned = 1, return_date = ?
                    WHERE id = ?
                """, (returned_qty, datetime.now().isoformat(), item_id))
                return cursor.rowcount > 0
        except Exception as e:
            logger.error(f"Erreur mise à jour retour sale_item: {e}")
            return False

    def update_sale_item_exchange(self, item_id: int, returned_qty: int, 
                                exchange_product_id: str, exchange_product_name: str,
                                exchange_quantity: int) -> bool:
        """Met à jour un article avec échange"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    UPDATE sale_items 
                    SET returned_quantity = ?, 
                        is_returned = 1, 
                        return_date = ?,
                        exchange_product_id = ?,
                        exchange_product_name = ?,
                        exchange_quantity = ?
                    WHERE id = ?
                """, (
                    returned_qty, datetime.now().isoformat(),
                    exchange_product_id, exchange_product_name, exchange_quantity, item_id
                ))
                return cursor.rowcount > 0
        except Exception as e:
            logger.error(f"Erreur mise à jour échange sale_item: {e}")
            return False

    # ==================== RETURNS HISTORY ====================

    def add_return_history(self, return_data: Dict) -> Optional[int]:
        """Ajoute un enregistrement dans l'historique des retours"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT INTO returns_history 
                    (sale_id, invoice_number, product_id, product_name, quantity, 
                    unit_price, total_price, reason, return_type, branch_id, 
                    customer_name, return_date, exchange_product_name, 
                    exchange_quantity, exchange_unit_price, is_synced)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    return_data.get('sale_id'),
                    return_data.get('invoice_number'),
                    return_data.get('product_id'),
                    return_data.get('product_name'),
                    return_data.get('quantity'),
                    return_data.get('unit_price'),
                    return_data.get('total_price'),
                    return_data.get('reason'),
                    return_data.get('return_type', 'return'),
                    return_data.get('branch_id'),
                    return_data.get('customer_name'),
                    return_data.get('return_date', datetime.now().isoformat()),
                    return_data.get('exchange_product_name'),
                    return_data.get('exchange_quantity', 0),
                    return_data.get('exchange_unit_price', 0),
                    0
                ))
                return cursor.lastrowid
        except Exception as e:
            logger.error(f"Erreur ajout return_history: {e}")
            return None

    def get_returns_history(self, branch_id: Optional[str] = None,
                            start_date: Optional[str] = None,
                            end_date: Optional[str] = None,
                            return_type: Optional[str] = None) -> List[Dict]:
        """Récupère l'historique des retours et échanges"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                
                sql = "SELECT * FROM returns_history WHERE 1=1"
                params = []
                
                if branch_id:
                    sql += " AND branch_id = ?"
                    params.append(branch_id)
                
                if start_date:
                    sql += " AND date(return_date) >= date(?)"
                    params.append(start_date)
                
                if end_date:
                    sql += " AND date(return_date) <= date(?)"
                    params.append(end_date)
                
                if return_type:
                    sql += " AND return_type = ?"
                    params.append(return_type)
                
                sql += " ORDER BY return_date DESC"
                
                cursor.execute(sql, params)
                rows = cursor.fetchall()
                return [dict(row) for row in rows]
        except Exception as e:
            logger.error(f"Erreur récupération returns_history: {e}")
            return []

    def mark_returns_synced(self, return_ids: List[int]) -> bool:
        """Marque des retours comme synchronisés"""
        if not return_ids:
            return True
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                placeholders = ','.join('?' * len(return_ids))
                cursor.execute(
                    f"UPDATE returns_history SET is_synced = 1 WHERE id IN ({placeholders})",
                    return_ids
                )
                return True
        except Exception as e:
            logger.error(f"Erreur marquage retours sync: {e}")
            return False

    # ==================== INVOICE METHODS ====================

    def get_invoices_list(self, branch_id: Optional[str] = None,
                        start_date: Optional[str] = None,
                        end_date: Optional[str] = None,
                        search_term: str = "") -> List[Dict]:
        """Récupère la liste des factures"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                
                sql = """
                    SELECT 
                        s.id, s.invoice_number, s.customer_name, 
                        s.total_amount, s.sale_date, s.payment_method,
                        s.is_returned, s.created_at
                    FROM sales s
                    WHERE 1=1
                """
                params = []
                
                if branch_id:
                    sql += " AND s.branch_id = ?"
                    params.append(branch_id)
                
                if start_date:
                    sql += " AND date(s.sale_date) >= date(?)"
                    params.append(start_date)
                
                if end_date:
                    sql += " AND date(s.sale_date) <= date(?)"
                    params.append(end_date)
                
                if search_term:
                    sql += " AND (s.invoice_number LIKE ? OR s.customer_name LIKE ?)"
                    params.extend([f"%{search_term}%", f"%{search_term}%"])
                
                sql += " ORDER BY s.sale_date DESC, s.id DESC"
                
                cursor.execute(sql, params)
                rows = cursor.fetchall()
                return [dict(row) for row in rows]
        except Exception as e:
            logger.error(f"Erreur récupération invoices list: {e}")
            return []

    def get_invoice_by_number(self, invoice_number: str) -> Optional[Dict]:
        """Récupère une facture par son numéro depuis la table sales"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT 
                        id,
                        invoice_number,
                        sale_date,
                        customer_name,
                        total_price as total_amount,
                        payment_method,
                        branch_id,
                        seller_id,
                        is_returned,
                        is_exchange,
                        is_modified,
                        created_at
                    FROM sales 
                    WHERE invoice_number = ?
                    LIMIT 1
                """, (invoice_number,))
                row = cursor.fetchone()
                if row:
                    return dict(row)
                return None
        except Exception as e:
            logger.error(f"Erreur récupération invoice par numéro: {e}")
            return None
    
    def get_invoice_with_items(self, invoice_number: str) -> Optional[Dict]:
        """Récupère une facture avec ses articles"""
        invoice = self.get_invoice_by_number(invoice_number)
        if invoice:
            invoice['items'] = self.get_invoice_items(invoice_number)
        return invoice

    def _ensure_int_id(self, product_id) -> int:
        """⚠️ À SUPPRIMER OU À UTILISER UNIQUEMENT POUR LES ANCIENNES DONNÉES"""
        # Cette méthode ne devrait plus être utilisée avec les nouveaux UUID
        # Garder uniquement pour compatibilité avec anciennes données
        if product_id is None:
            return None
        if isinstance(product_id, str) and len(product_id) == 36:  # UUID standard
            return product_id  # Retourner l'UUID string, pas converti
        return product_id

    def verify_type_consistency(self) -> Dict:
        """Vérifie que les types des colonnes correspondent aux modèles"""
        issues = []
        
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            # Vérifier que server_id sont des UUID valides
            cursor.execute("SELECT server_id FROM products LIMIT 10")
            for row in cursor.fetchall():
                sid = row['server_id']
                if not isinstance(sid, str) or len(sid) != 36:
                    issues.append(f"ID produit invalide: {sid}")
        
        return {
            "status": "error" if issues else "ok",
            "issues": issues
        }
    # ==================== RETURN PROCESSING ====================

    def process_return(self, return_data: Dict) -> bool:
        """Traite un retour de produit complet"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                
                invoice_number = return_data.get('invoice_number')
                product_id = str(return_data.get('product_id'))  # Garder comme string
                quantity = return_data.get('quantity', 0)
                unit_price = return_data.get('unit_price', 0)
                
                # CORRECTION: Vérifier d'abord si la vente existe
                cursor.execute("""
                    SELECT id, product_id, quantity FROM sales 
                    WHERE invoice_number = ? AND product_id = ? AND is_returned = 0
                """, (invoice_number, product_id))
                
                sale = cursor.fetchone()
                
                if not sale:
                    # Essayer sans le filtre is_returned
                    cursor.execute("""
                        SELECT id, product_id, quantity FROM sales 
                        WHERE invoice_number = ? AND product_id = ?
                    """, (invoice_number, product_id))
                    sale = cursor.fetchone()
                
                if not sale:
                    logger.warning(f"Aucune vente trouvée pour retour: {invoice_number}, {product_id}")
                    return False
                
                # 1. Mettre à jour la vente
                cursor.execute("""
                    UPDATE sales 
                    SET is_returned = 1,
                        returned_quantity = COALESCE(returned_quantity, 0) + ?,
                        returned_at = ?,
                        is_modified = 1,
                        modification_date = ?,
                        modification_reason = ?
                    WHERE invoice_number = ? AND product_id = ?
                """, (
                    quantity,
                    datetime.now().isoformat(),
                    datetime.now().isoformat(),
                    f"Retour de {quantity} x {return_data.get('product_name')}",
                    invoice_number,
                    product_id
                ))
                
                # 2. Mettre à jour le stock du produit
                cursor.execute("""
                    UPDATE products 
                    SET quantity = quantity + ? 
                    WHERE server_id = ?
                """, (quantity, product_id))
                
                # 3. Ajouter à l'historique des retours
                cursor.execute("""
                    INSERT INTO returns_history 
                    (sale_id, invoice_number, product_id, product_name, quantity, 
                    unit_price, total_price, reason, return_type, branch_id, 
                    customer_name, return_date, is_synced)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    sale['id'],
                    invoice_number,
                    product_id,
                    return_data.get('product_name'),
                    quantity,
                    unit_price,
                    quantity * unit_price,
                    return_data.get('reason', 'Retour client'),
                    'return',
                    return_data.get('branch_id'),
                    return_data.get('customer_name'),
                    datetime.now().isoformat(),
                    0
                ))
                
                logger.info(f"Retour traité avec succès: {quantity} x {return_data.get('product_name')}")
                return True
                
        except Exception as e:
            logger.error(f"Erreur process_return: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    def process_exchange(self, exchange_data: Dict) -> bool:
        """Traite un échange de produit complet"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                
                invoice_number = exchange_data.get('invoice_number')
                original_product_id = str(exchange_data.get('original_product_id'))
                new_product_id = str(exchange_data.get('new_product_id'))
                original_quantity = exchange_data.get('original_quantity', 0)
                new_quantity = exchange_data.get('new_quantity', original_quantity)
                original_unit_price = exchange_data.get('original_unit_price', 0)
                new_unit_price = exchange_data.get('new_unit_price', 0)
                amount_difference = exchange_data.get('amount_difference', 0)
                
                # Vérifier si la vente originale existe
                cursor.execute("""
                    SELECT id, quantity, returned_quantity 
                    FROM sales 
                    WHERE invoice_number = ? AND product_id = ?
                """, (invoice_number, original_product_id))
                
                sale = cursor.fetchone()
                
                if not sale:
                    logger.warning(f"Aucune vente trouvée pour échange: {invoice_number}, {original_product_id}")
                    return False
                
                # Calculer la nouvelle quantité retournée
                current_returned = sale['returned_quantity'] if sale['returned_quantity'] else 0
                new_returned_qty = current_returned + original_quantity
                
                # Vérifier qu'on ne retourne pas plus que la quantité vendue
                if new_returned_qty > sale['quantity']:
                    logger.warning(f"Quantité de retour trop élevée: {new_returned_qty} > {sale['quantity']}")
                    return False
                
                # 1. Marquer la vente originale comme retournée (partiellement ou totalement)
                is_fully_returned = 1 if new_returned_qty >= sale['quantity'] else 0
                
                cursor.execute("""
                    UPDATE sales 
                    SET is_returned = ?,
                        is_exchange = 1,
                        returned_quantity = ?,
                        returned_at = ?,
                        is_modified = 1,
                        modification_date = ?,
                        modification_reason = ?
                    WHERE invoice_number = ? AND product_id = ?
                """, (
                    is_fully_returned,
                    new_returned_qty,
                    datetime.now().isoformat(),
                    datetime.now().isoformat(),
                    f"Échange: {original_quantity} x {exchange_data.get('original_product_name')} → {new_quantity} x {exchange_data.get('new_product_name')}",
                    invoice_number,
                    original_product_id
                ))
                
                # 2. Restocker l'ancien produit (seulement si non déjà retourné)
                if original_quantity > 0:
                    cursor.execute("""
                        UPDATE products 
                        SET quantity = quantity + ? 
                        WHERE server_id = ?
                    """, (original_quantity, original_product_id))
                    logger.info(f"Restockage de {original_quantity} x {exchange_data.get('original_product_name')}")
                
                # 3. Vérifier le stock du nouveau produit
                cursor.execute("SELECT quantity FROM products WHERE server_id = ?", (new_product_id,))
                product_row = cursor.fetchone()
                
                if not product_row:
                    logger.error(f"Produit d'échange non trouvé: {new_product_id}")
                    return False
                
                if product_row['quantity'] < new_quantity:
                    logger.error(f"Stock insuffisant pour {exchange_data.get('new_product_name')}: {product_row['quantity']} < {new_quantity}")
                    return False
                
                # 4. Déstocker le nouveau produit
                cursor.execute("""
                    UPDATE products 
                    SET quantity = quantity - ? 
                    WHERE server_id = ?
                """, (new_quantity, new_product_id))
                logger.info(f"Déstockage de {new_quantity} x {exchange_data.get('new_product_name')}")
                
                # 5. Si différence positive, créer une nouvelle vente pour le supplément
                if amount_difference > 0:
                    cursor.execute("""
                        INSERT INTO sales 
                        (product_id, product_name, quantity, unit_price, total_price, 
                        sale_date, customer_name, branch_id, is_synced, 
                        payment_method, invoice_number, is_exchange, is_returned)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        new_product_id,
                        exchange_data.get('new_product_name'),
                        new_quantity,
                        new_unit_price,
                        amount_difference,
                        datetime.now().isoformat(),
                        exchange_data.get('customer_name'),
                        exchange_data.get('branch_id'),
                        0,
                        'cash',
                        invoice_number,
                        1,
                        0
                    ))
                    logger.info(f"Supplément de {amount_difference} FC enregistré")
                
                # 6. Ajouter à l'historique des retours
                cursor.execute("""
                    INSERT INTO returns_history 
                    (sale_id, invoice_number, product_id, product_name, quantity, 
                    unit_price, total_price, reason, return_type, branch_id, 
                    customer_name, return_date, exchange_product_name, 
                    exchange_quantity, exchange_unit_price, is_synced)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    sale['id'],
                    invoice_number,
                    original_product_id,
                    exchange_data.get('original_product_name'),
                    original_quantity,
                    original_unit_price,
                    original_quantity * original_unit_price,
                    exchange_data.get('reason', 'Échange produit'),
                    'exchange',
                    exchange_data.get('branch_id'),
                    exchange_data.get('customer_name'),
                    datetime.now().isoformat(),
                    exchange_data.get('new_product_name'),
                    new_quantity,
                    new_unit_price,
                    0
                ))
                
                conn.commit()
                
                logger.info(f"✅ Échange traité avec succès: {original_quantity} x {exchange_data.get('original_product_name')} → {new_quantity} x {exchange_data.get('new_product_name')}")
                return True
                
        except Exception as e:
            logger.error(f"Erreur process_exchange: {e}")
            import traceback
            traceback.print_exc()
            return False
    # ==================== UTILITAIRES ====================
    def _ensure_sales_columns(self):
        """Vérifie et ajoute les colonnes manquantes à la table sales"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            # Vérifier les colonnes existantes
            cursor.execute("PRAGMA table_info(sales)")
            columns = [col[1] for col in cursor.fetchall()]
            
            # Colonnes à ajouter si manquantes
            required_columns = {
                'is_modified': 'INTEGER DEFAULT 0',
                'modification_date': 'TEXT',
                'modification_reason': 'TEXT',
                'original_invoice_number': 'TEXT',
                'returned_quantity': 'INTEGER DEFAULT 0',  # AJOUTER CETTE LIGNE
                'returned_at': 'TEXT'  # AJOUTER CETTE LIGNE
            }
            
            for col_name, col_type in required_columns.items():
                if col_name not in columns:
                    try:
                        cursor.execute(f"ALTER TABLE sales ADD COLUMN {col_name} {col_type}")
                        print(f"Colonne {col_name} ajoutée à sales")
                    except Exception as e:
                        print(f"Erreur ajout colonne {col_name}: {e}")

    def clear_all_data(self) -> bool:
        """Supprime toutes les données (produits, ventes, dépenses, etc.)"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                
                # Liste de toutes les tables de données à vider
                tables = [
                    'products',
                    'sales', 
                    'cart_items', 
                    'expenses', 
                    'debts',
                    'sync_logs',
                    'returns',
                    'returns_history',
                    'sale_items',
                    'invoices',
                    'invoice_items',
                    'branches',
                    'user_permissions',
                    'branch_users',
                    'sync_feedback',
                    'pending_invoices'
                ]
                
                for table in tables:
                    try:
                        cursor.execute(f"DELETE FROM {table}")
                        logger.info(f"Table {table} vidée")
                    except sqlite3.OperationalError as e:
                        # Table n'existe pas, ignorer
                        logger.debug(f"Table {table} non trouvée: {e}")
                    except Exception as e:
                        logger.warning(f"Erreur vidage table {table}: {e}")
                
                # ✅ Réinitialiser le compteur de factures
                try:
                    cursor.execute("UPDATE invoice_counter SET current_number = 1, last_updated = CURRENT_TIMESTAMP WHERE id = 1")
                except Exception as e:
                    logger.warning(f"Erreur réinitialisation compteur: {e}")
                
                # ✅ Vider également la table user (déjà fait par auth_service)
                # mais on la garde pour être sûr
                try:
                    cursor.execute("DELETE FROM user")
                except Exception as e:
                    logger.warning(f"Erreur vidage user: {e}")
                
                conn.commit()
                logger.info("✅ Toutes les données locales ont été supprimées avec succès")
                return True
                
        except Exception as e:
            logger.error(f"Erreur clear_all_data: {e}")
            import traceback
            traceback.print_exc()
            return False
        
    def get_database_size(self) -> int:
        """Taille de la base de données en bytes"""
        try:
            return os.path.getsize(self.db_path)
        except:
            return 0
    
    def verify_product_mapping(self, product_uuid: str) -> Dict:
        """Vérifie si un produit UUID existe et est correctement mappé"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                
                # Chercher par server_id
                cursor.execute(
                    "SELECT server_id, name, code, branch_id, pharmacy_id FROM products WHERE server_id = ?",
                    (product_uuid,)
                )
                row = cursor.fetchone()
                
                if row:
                    return {
                        "exists": True,
                        "server_id": row[0],
                        "name": row[1],
                        "code": row[2],
                        "branch_id": row[3],
                        "pharmacy_id": row[4]
                    }
                
                # Chercher dans les ventes non synchronisées
                cursor.execute(
                    "SELECT DISTINCT product_id FROM sales WHERE is_synced = 0 AND product_id = ?",
                    (product_uuid,)
                )
                if cursor.fetchone():
                    return {"exists": False, "in_unsynced_sales": True}
                
                return {"exists": False}
        except Exception as e:
            logger.error(f"Erreur vérification mapping: {e}")
            return {"exists": False, "error": str(e)}

    def init_permissions_tables(self):
        """Initialise les tables de gestion des permissions"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                
                # Table user_permissions
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
                
                # Table branch_users
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
                
                # Index
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_user_permissions_user ON user_permissions(user_id, branch_id)")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_branch_users_branch ON branch_users(branch_id)")
                
                conn.commit()
                logger.info("Tables de permissions initialisées avec succès")
        except Exception as e:
            logger.error(f"Erreur init_permissions_tables: {e}")

    def get_branch_users(self, branch_id: str) -> List[Dict]:
        """Récupère les utilisateurs d'une branche"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT id, full_name, email, role, is_active 
                    FROM branch_users 
                    WHERE branch_id = ? AND is_active = 1
                    ORDER BY full_name
                """, (branch_id,))
                rows = cursor.fetchall()
                return [dict(row) for row in rows]
        except Exception as e:
            logger.error(f"Erreur get_branch_users: {e}")
            return []

    def save_branch_users(self, users: List[Dict], branch_id: str) -> int:
        """Sauvegarde les utilisateurs d'une branche"""
        saved = 0
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
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
                    saved += 1
                conn.commit()
        except Exception as e:
            logger.error(f"Erreur save_branch_users: {e}")
        return saved

    def get_user_permissions(self, user_id: str, branch_id: str) -> Dict[str, bool]:
        """Récupère les permissions d'un utilisateur"""
        permissions = {}
        try:
            with self.get_connection() as conn:
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
            logger.error(f"Erreur get_user_permissions: {e}")
        return permissions

    def save_user_permissions(self, user_id: str, branch_id: str, permissions: Dict[str, bool], granted_by: str = None) -> bool:
        """Sauvegarde les permissions d'un utilisateur"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                now = datetime.now().isoformat()
                
                for perm_key, is_allowed in permissions.items():
                    cursor.execute("""
                        INSERT OR REPLACE INTO user_permissions 
                        (user_id, branch_id, permission_key, is_allowed, granted_by, granted_at, updated_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                    """, (
                        user_id, branch_id, perm_key, 
                        1 if is_allowed else 0,
                        granted_by, now, now
                    ))
                conn.commit()
                return True
        except Exception as e:
            logger.error(f"Erreur save_user_permissions: {e}")
            return False