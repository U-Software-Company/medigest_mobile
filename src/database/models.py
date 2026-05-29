"""
Modèles de données pour la base de données locale SQLite
"""

from dataclasses import dataclass, asdict, field
from datetime import datetime
from typing import Optional, List, Dict, Any
import json
import logging
import uuid

logger = logging.getLogger(__name__)


@dataclass
class User:
    """Modèle Utilisateur"""
    id: str  # UUID string
    username: str
    email: str
    full_name: str
    branch_id: str  # UUID string
    branch_name: Optional[str] = None
    role: str = "seller"
    token: str = ""
    last_sync: Optional[str] = None
    
    def to_dict(self) -> Dict:
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict) -> 'User':
        return cls(**data)


@dataclass
class Product:
    """Modèle Produit - Support complet des UUID"""
    server_id: str  # UUID string (36 caractères)
    name: str
    code: Optional[str] = None
    selling_price: float = 0.0
    stock: int = 0
    quantity: int = 0  # Alias de stock
    category: Optional[str] = None
    branch_id: str = ""  # UUID string
    pharmacy_id: Optional[str] = None  # UUID string
    tenant_id: Optional[str] = None  # UUID string
    pharmacy_name: Optional[str] = None
    tenant_name: Optional[str] = None
    updated_at: Optional[str] = None
    is_active: bool = True
    is_deleted: bool = False
    description: Optional[str] = None
    barcode: Optional[str] = None
    min_stock: int = 0
    max_stock: int = 0
    unit: str = "pièce"
    tax_rate: float = 0.0
    expiry_date: Optional[str] = None
    expiry_status: Optional[str] = None
    manufacturing_date: Optional[str] = None
    lot_number: Optional[str] = None
    supplier: Optional[str] = None
    location: Optional[str] = None
    status: str = "active"
    alert_threshold_days: int = 30
    # ✅ NOUVEAUX CHAMPS POUR VERSIONNEMENT
    stock_version: int = 1
    last_sync_at: Optional[str] = None
    synced_quantity: int = 0
    pending_quantity_change: int = 0
    
    def __post_init__(self):
        """Synchroniser stock et quantity après initialisation"""
        if self.stock == 0 and self.quantity != 0:
            self.stock = self.quantity
        elif self.quantity == 0 and self.stock != 0:
            self.quantity = self.stock
        
        # Initialiser synced_quantity si pas défini
        if self.synced_quantity == 0 and self.quantity > 0:
            self.synced_quantity = self.quantity
    
    @property
    def price(self) -> float:
        """Alias pour selling_price"""
        return self.selling_price
    
    def to_dict(self) -> Dict:
        data = asdict(self)
        if 'quantity' not in data or data['quantity'] == 0:
            data['quantity'] = self.stock
        return data
    
    @classmethod
    def from_dict(cls, data: Dict) -> 'Product':
        if 'stock' not in data and 'quantity' in data:
            data['stock'] = data['quantity']
        elif 'quantity' not in data and 'stock' in data:
            data['quantity'] = data['stock']
        return cls(**data)
    
    def to_sync_item(self, action: str = "upsert") -> Dict:
        """Convertir en item de synchronisation"""
        data = {
            "id": self.server_id,
            "name": self.name,
            "code": self.code,
            "selling_price": self.selling_price,
            "quantity": self.quantity,
            "category": self.category,
            "branch_id": self.branch_id,
            "description": self.description,
            "barcode": self.barcode,
            "min_stock": self.min_stock,
            "max_stock": self.max_stock,
            "unit": self.unit,
            "is_deleted": self.is_deleted,
            "is_active": self.is_active,
            "tax_rate": self.tax_rate,
            "expiry_date": self.expiry_date,
            "manufacturing_date": self.manufacturing_date,
            "lot_number": self.lot_number,
            "supplier": self.supplier,
            "location": self.location,
            "stock_version": self.stock_version,
            "updated_at": self.updated_at or datetime.now().isoformat()
        }
        if self.pharmacy_id:
            data["pharmacy_id"] = self.pharmacy_id
        if self.tenant_id:
            data["tenant_id"] = self.tenant_id
        
        return {
            "table_name": "products",
            "action": action,
            "data": data
        }


@dataclass
class Sale:
    """Modèle Vente - Support des UUID"""
    id: Optional[int] = None
    product_id: str = ""  # ✅ STRING pour UUID (pas int)
    product_name: str = ""
    quantity: int = 0
    unit_price: float = 0.0
    total_price: float = 0.0
    sale_date: str = ""
    customer_name: str = ""
    branch_id: str = ""  # ✅ STRING pour UUID
    is_synced: bool = False
    sync_error: Optional[str] = None
    seller_id: Optional[str] = None  # ✅ STRING pour UUID
    payment_method: str = "cash"
    invoice_number: Optional[str] = None
    # ✅ NOUVEAUX CHAMPS POUR GESTION DE CONFLITS
    stock_version_at_sale: int = 0
    stock_quantity_at_sale: int = 0
    device_id: Optional[str] = None
    is_rejected: bool = False
    rejection_reason: Optional[str] = None
    is_partial: bool = False
    rejected_quantity: int = 0
    
    def __post_init__(self):
        if not self.sale_date:
            self.sale_date = datetime.now().isoformat()
    
    def to_dict(self) -> Dict:
        return {
            "id": self.id,
            "product_id": self.product_id,
            "product_name": self.product_name,
            "quantity": self.quantity,
            "unit_price": self.unit_price,
            "total_price": self.total_price,
            "sale_date": self.sale_date,
            "customer_name": self.customer_name,
            "branch_id": self.branch_id,
            "is_synced": 1 if self.is_synced else 0,
            "sync_error": self.sync_error,
            "seller_id": self.seller_id,
            "payment_method": self.payment_method,
            "invoice_number": self.invoice_number,
            "stock_version_at_sale": self.stock_version_at_sale,
            "stock_quantity_at_sale": self.stock_quantity_at_sale,
            "device_id": self.device_id,
            "is_rejected": 1 if self.is_rejected else 0,
            "rejection_reason": self.rejection_reason,
            "is_partial": 1 if self.is_partial else 0,
            "rejected_quantity": self.rejected_quantity
        }
    
    @classmethod
    def from_dict(cls, data: Dict) -> 'Sale':
        return cls(
            id=data.get('id'),
            product_id=str(data.get('product_id', '')),
            product_name=data.get('product_name', ''),
            quantity=data.get('quantity', 0),
            unit_price=data.get('unit_price', 0.0),
            total_price=data.get('total_price', 0.0),
            sale_date=data.get('sale_date', ''),
            customer_name=data.get('customer_name', ''),
            branch_id=str(data.get('branch_id', '')),
            is_synced=bool(data.get('is_synced', 0)),
            sync_error=data.get('sync_error'),
            seller_id=str(data.get('seller_id')) if data.get('seller_id') else None,
            payment_method=data.get('payment_method', 'cash'),
            invoice_number=data.get('invoice_number'),
            stock_version_at_sale=data.get('stock_version_at_sale', 0),
            stock_quantity_at_sale=data.get('stock_quantity_at_sale', 0),
            device_id=data.get('device_id'),
            is_rejected=bool(data.get('is_rejected', 0)),
            rejection_reason=data.get('rejection_reason'),
            is_partial=bool(data.get('is_partial', 0)),
            rejected_quantity=data.get('rejected_quantity', 0)
        )
    
    def to_sync_item(self) -> Dict:
        """Convertir en item de synchronisation pour le serveur"""
        return {
            "table_name": "sales",
            "action": "create",
            "data": {
                "product_id": self.product_id,
                "product_name": self.product_name,
                "quantity": self.quantity,
                "unit_price": self.unit_price,
                "total_price": self.total_price,
                "sale_date": self.sale_date,
                "customer_name": self.customer_name,
                "branch_id": self.branch_id,
                "payment_method": self.payment_method,
                "seller_id": self.seller_id,
                "stock_version_at_sale": self.stock_version_at_sale,
                "stock_quantity_at_sale": self.stock_quantity_at_sale,
                "device_id": self.device_id
            }
        }


@dataclass
class CartItem:
    """Modèle Article du Panier"""
    id: Optional[int] = None
    product_id: str = ""  # ✅ STRING pour UUID
    product_name: str = ""
    quantity: int = 1
    unit_price: float = 0.0
    total_price: float = 0.0
    added_at: str = ""
    
    def __post_init__(self):
        if not self.added_at:
            self.added_at = datetime.now().isoformat()
        self.total_price = self.quantity * self.unit_price
    
    def to_dict(self) -> Dict:
        return {
            "id": self.id,
            "product_id": self.product_id,
            "product_name": self.product_name,
            "quantity": self.quantity,
            "unit_price": self.unit_price,
            "total_price": self.total_price,
            "added_at": self.added_at
        }
    
    @classmethod
    def from_dict(cls, data: Dict) -> 'CartItem':
        return cls(**data)


@dataclass
class Expense:
    """Modèle Dépense"""
    id: Optional[int] = None
    description: str = ""
    amount: float = 0.0
    expense_date: str = ""
    category: str = ""
    branch_id: str = ""  # ✅ STRING pour UUID
    is_synced: bool = False
    receipt_url: Optional[str] = None
    
    def __post_init__(self):
        if not self.expense_date:
            self.expense_date = datetime.now().isoformat()
    
    def to_dict(self) -> Dict:
        return {
            "id": self.id,
            "description": self.description,
            "amount": self.amount,
            "expense_date": self.expense_date,
            "category": self.category,
            "branch_id": self.branch_id,
            "is_synced": 1 if self.is_synced else 0,
            "receipt_url": self.receipt_url
        }
    
    def to_sync_item(self) -> Dict:
        return {
            "table_name": "expenses",
            "action": "create",
            "data": {
                "description": self.description,
                "amount": self.amount,
                "expense_date": self.expense_date,
                "category": self.category,
                "branch_id": self.branch_id
            }
        }


@dataclass
class Debt:
    """Modèle Dette Client"""
    id: Optional[int] = None
    server_id: Optional[str] = None  # ✅ STRING pour UUID
    customer_name: str = ""
    amount: float = 0.0
    remaining_amount: float = 0.0
    due_date: str = ""
    status: str = "pending"
    branch_id: str = ""  # ✅ STRING pour UUID
    created_at: str = ""
    updated_at: str = ""
    is_synced: bool = False
    notes: Optional[str] = None
    product_id: Optional[str] = None  # ✅ STRING pour UUID
    product_name: Optional[str] = None
    quantity: int = 1
    unit_price: float = 0.0
    
    def __post_init__(self):
        if not self.created_at:
            self.created_at = datetime.now().isoformat()
        if not self.updated_at:
            self.updated_at = self.created_at
        if self.remaining_amount == 0:
            self.remaining_amount = self.amount
    
    def to_dict(self) -> Dict:
        return {
            "id": self.id,
            "server_id": self.server_id,
            "customer_name": self.customer_name,
            "amount": self.amount,
            "remaining_amount": self.remaining_amount,
            "due_date": self.due_date,
            "status": self.status,
            "branch_id": self.branch_id,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "is_synced": 1 if self.is_synced else 0,
            "notes": self.notes,
            "product_id": self.product_id,
            "product_name": self.product_name,
            "quantity": self.quantity,
            "unit_price": self.unit_price
        }


@dataclass
class SyncLog:
    """Modèle Log de Synchronisation"""
    id: Optional[int] = None
    sync_type: str = ""
    sync_date: str = ""
    records_synced: int = 0
    status: str = ""
    error_message: Optional[str] = None
    details: Optional[str] = None
    
    def __post_init__(self):
        if not self.sync_date:
            self.sync_date = datetime.now().isoformat()
    
    def to_dict(self) -> Dict:
        return {
            "id": self.id,
            "sync_type": self.sync_type,
            "sync_date": self.sync_date,
            "records_synced": self.records_synced,
            "status": self.status,
            "error_message": self.error_message,
            "details": self.details
        }


@dataclass
class DashboardStats:
    """Statistiques pour le tableau de bord"""
    today_sales: float = 0.0
    week_sales: float = 0.0
    month_sales: float = 0.0
    today_expenses: float = 0.0
    week_expenses: float = 0.0
    month_expenses: float = 0.0
    pending_sales: float = 0.0
    pending_sync_count: int = 0
    total_debts: float = 0.0
    low_stock_count: int = 0
    
    def to_dict(self) -> Dict:
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict) -> 'DashboardStats':
        return cls(**data)


@dataclass
class Branch:
    """Modèle Succursale"""
    id: str  # UUID string
    name: str
    address: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    manager_name: Optional[str] = None
    parent_pharmacy_id: Optional[str] = None 
    is_active: bool = True
    
    def to_dict(self) -> Dict:
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict) -> 'Branch':
        return cls(**data)


# Utilitaires pour les modèles
def model_to_sync_items(models: List[Any], table_name: str, action: str = "upsert") -> List[Dict]:
    """Convertir une liste de modèles en items de synchronisation"""
    items = []
    for model in models:
        if hasattr(model, 'to_sync_item'):
            items.append(model.to_sync_item())
        else:
            items.append({
                "table_name": table_name,
                "action": action,
                "data": model.to_dict()
            })
    return items


def dict_to_model(data: Dict, model_class):
    """Convertir un dictionnaire en modèle"""
    return model_class.from_dict(data)


def dicts_to_models(data_list: List[Dict], model_class):
    """Convertir une liste de dictionnaires en modèles"""
    return [dict_to_model(data, model_class) for data in data_list]