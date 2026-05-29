import requests
import json
from datetime import datetime, timedelta
from typing import Dict, List, Optional
import logging
from uuid import UUID
import uuid

# Import des modèles
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from database.models import Product
from services.connection_manager import ConnectionManager
from collections import defaultdict
from dataclasses import dataclass, field

# Configuration du logging
logger = logging.getLogger(__name__)
import ssl
from requests.adapters import HTTPAdapter
from urllib3.poolmanager import PoolManager

@dataclass
class StockOperation:
    """Représente une opération de stock"""
    product_id: UUID
    quantity_change: int  # Négatif pour vente, positif pour approvisionnement
    sale_id: Optional[int] = None
    sale_reference: Optional[str] = None
    timestamp: datetime = field(default_factory=datetime.utcnow)
    device_id: Optional[str] = None
    seller_id: Optional[str] = None
    force: bool = False

class TLSAdapter(HTTPAdapter):
    """Adaptateur SSL/TLS personnalisé pour résoudre les problèmes de négociation"""
    
    def init_poolmanager(self, *args, **kwargs):
        ctx = ssl.create_default_context()
        
        # Désactiver complètement la vérification (pour test)
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        
        # Forcer TLS 1.2 (plus stable que TLS 1.3)
        ctx.minimum_version = ssl.TLSVersion.TLSv1_2
        ctx.maximum_version = ssl.TLSVersion.TLSv1_2
        
        kwargs['ssl_context'] = ctx
        return super().init_poolmanager(*args, **kwargs)

class SyncService:
    """Service de synchronisation avec le backend"""

    def __init__(self, db, auth_service):
        self.db = db
        self.auth_service = auth_service
        self.connection_manager = ConnectionManager() 
        self.base_url = "https://my-backend-ydit.onrender.com"
        self.api_url = f"{self.base_url}/api/v1"
        
        # ✅ Désactiver les avertissements SSL
        import urllib3
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        
        # ✅ Créer une session avec configuration SSL pour TOUS les appels
        self.session = requests.Session()
        self.session.mount('https://', TLSAdapter())
        self.session.verify = False
        self.diagnose_missing_products()
        
        # ✅ Configurer les retries
        from requests.adapters import HTTPAdapter
        from urllib3.util.retry import Retry
        
        retry_strategy = Retry(
            total=3,
            backoff_factor=1,
            status_forcelist=[429, 500, 502, 503, 504],
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        self.session.mount("http://", adapter)
        self.session.mount("https://", adapter)
    
    def _is_online(self) -> bool:
        """Vérifie rapidement si on est en mode online"""
        return self.connection_manager.is_online_mode()
    
    def _ensure_online(self, operation_name: str = "opération") -> bool:
        """
        Vérifie la connexion avant une opération réseau.
        Log un warning et retourne False si offline.
        """
        if not self._is_online():
            logger.warning(f"⚠️ Hors ligne - {operation_name} ignorée")
            return False
        return True

    def check_internet_connection(self) -> bool:
        """
        Vérifie la connexion internet et la disponibilité du serveur.
        Utilise plusieurs endpoints pour plus de fiabilité.
        """
        import socket
        import requests
        
        # Méthode 1: Vérification DNS rapide
        try:
            socket.setdefaulttimeout(3)
            socket.gethostbyname('google.com')
            logger.debug("✅ DNS check passed")
            return True
        except Exception as e:
            logger.debug(f"DNS check failed: {e}")
        
        # Méthode 2: Ping sur Google DNS
        try:
            response = requests.get('https://8.8.8.8', timeout=5, verify=False)
            if response.status_code >= 200:
                logger.debug("✅ IP check passed")
                return True
        except Exception as e:
            logger.debug(f"IP check failed: {e}")
        
        # Méthode 3: Vérification du backend avec endpoint /health
        endpoints_to_try = [
            f"{self.base_url}/health",
            f"{self.base_url}/",
            "https://google.com",
        ]
        
        for url in endpoints_to_try:
            try:
                response = self.session.get(url, timeout=5, verify=False)
                if response.status_code in [200, 201, 204, 301, 302, 303, 307, 308]:
                    logger.debug(f"✅ Endpoint check passed: {url}")
                    return True
            except Exception as e:
                logger.debug(f"Endpoint {url} failed: {e}")
                continue
        
        # Méthode 4: Vérification avec session existante
        try:
            response = self.session.get(
                f"{self.base_url}/health",
                timeout=8,
                verify=False
            )
            if response.status_code == 200:
                logger.debug("✅ Session check passed")
                return True
        except Exception as e:
            logger.debug(f"Session check failed: {e}")
        
        logger.debug("❌ All connection checks failed")
        return False
    
    def _get_headers(self) -> Optional[Dict]:
        """Récupère les headers uniquement si online"""
        if not self._is_online():
            return None
        
        user = self.auth_service.get_current_user()
        if not user:
            logger.warning("Aucun utilisateur connecté")
            return None
        
        token = user.get('token')
        if not token:
            logger.warning("Aucun token d'authentification")
            return None
        
        return {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json"
        }
        
    def _make_request(self, method: str, url: str, **kwargs) -> requests.Response:
        """Fait une requête HTTP avec gestion SSL automatique"""
        # Toujours désactiver la vérification SSL
        kwargs.setdefault('verify', False)
        kwargs.setdefault('timeout', 60)
        
        # Utiliser la session
        response = self.session.request(method, url, **kwargs)
        return response
    
    def _safe_int(self, value, default=0):
        """Convertit une valeur en int de manière sécurisée"""
        if value is None:
            return default
        try:
            return int(value)
        except (ValueError, TypeError):
            return default

    def _safe_float(self, value, default=0.0):
        """Convertit une valeur en float de manière sécurisée"""
        if value is None:
            return default
        try:
            return float(value)
        except (ValueError, TypeError):
            return default

    def _safe_str(self, value, default=''):
        """Convertit une valeur en str de manière sécurisée"""
        if value is None:
            return default
        return str(value)

    def import_products_with_versions(self, branch_id: str = None) -> Dict:
        """
        Importe les produits avec leurs versions pour détection des conflits
        """
        headers = self._get_headers()
        if not headers:
            return {"error": "Utilisateur non authentifié", "success": False}
        
        user = self.auth_service.get_current_user()
        
        if not branch_id:
            branch_id = user.get('active_branch_id') or user.get('branch_id')
        
        try:
            # Récupérer les produits avec métadonnées de version
            response = self.session.get(
                f"{self.api_url}/stock/with-versions",
                headers=headers,
                params={"branch_id": branch_id, "include_versions": True},
                timeout=60
            )
            
            if response.status_code != 200:
                # Fallback vers /stock
                response = self.session.get(
                    f"{self.api_url}/stock",
                    headers=headers,
                    params={"branch_id": branch_id},
                    timeout=60
                )
            
            if response.status_code != 200:
                return {"error": f"Erreur serveur: {response.status_code}", "success": False}
            
            data = response.json()
            products_data = data if isinstance(data, list) else data.get('products', data.get('data', []))
            
            from database.models import Product as LocalProduct
            
            products_updated = 0
            products_created = 0
            version_conflicts = []
            
            for p in products_data:
                try:
                    server_id = self._safe_str(p.get('id', ''))
                    if not server_id:
                        continue
                    
                    server_version = p.get('stock_version', 1)
                    server_quantity = self._safe_int(p.get('quantity', p.get('stock', 0)))
                    
                    # Chercher le produit local
                    local_product = self.db.get_product_by_id(server_id)
                    
                    if local_product:
                        # Vérifier le conflit de version
                        local_version = getattr(local_product, 'stock_version', 1)
                        
                        if local_version != server_version:
                            # Conflit détecté - prendre le max des quantités
                            version_conflicts.append({
                                "product_id": server_id,
                                "product_name": p.get('name'),
                                "local_version": local_version,
                                "server_version": server_version,
                                "local_quantity": getattr(local_product, 'quantity', 0),
                                "server_quantity": server_quantity,
                                "resolution": "server_wins"  # ou "merge"
                            })
                            
                            # Stratégie: le serveur gagne (plus récent)
                            local_product.quantity = server_quantity
                            local_product.stock_version = server_version
                            local_product.synced_quantity = server_quantity
                            local_product.last_sync_at = datetime.now()
                            products_updated += 1
                        else:
                            # Pas de conflit, mise à jour normale
                            local_product.quantity = server_quantity
                            local_product.synced_quantity = server_quantity
                            local_product.last_sync_at = datetime.now()
                            local_product.stock_version = server_version
                            products_updated += 1
                        
                        # Mettre à jour les autres champs
                        local_product.name = self._safe_str(p.get('name', local_product.name))
                        local_product.selling_price = self._safe_float(p.get('selling_price', local_product.selling_price))
                        
                    else:
                        # Créer un nouveau produit
                        product_data = {
                            'server_id': server_id,
                            'name': self._safe_str(p.get('name', 'Sans nom')),
                            'code': self._safe_str(p.get('code', '')),
                            'selling_price': self._safe_float(p.get('selling_price', 0)),
                            'stock': server_quantity,
                            'quantity': server_quantity,
                            'synced_quantity': server_quantity,
                            'stock_version': server_version,
                            'last_sync_at': datetime.now(),
                            'category': self._safe_str(p.get('category', '')),
                            'branch_id': branch_id,
                            'updated_at': datetime.now().isoformat(),
                            'is_deleted': p.get('is_deleted', False),
                            'barcode': self._safe_str(p.get('barcode', '')),
                        }
                        
                        from database.models import Product as LocalProduct
                        product = LocalProduct(**product_data)
                        self.db.save_products([product])
                        products_created += 1
                    
                except Exception as e:
                    logger.error(f"Erreur import produit {p.get('id')}: {e}")
                    continue
            
            # Sauvegarder les modifications
            if products_updated > 0:
                self.db.save_products([])  # Commit implicite
            
            return {
                "success": True,
                "products_updated": products_updated,
                "products_created": products_created,
                "version_conflicts": version_conflicts,
                "total_products": len(products_data)
            }
            
        except Exception as e:
            logger.error(f"Erreur import_products_with_versions: {e}")
            return {"error": str(e), "success": False}
        
    def import_products(self, branch_id: str = None) -> Dict:
        """
        Importe TOUS les produits depuis le serveur avec pagination automatique
        """
        if not self._ensure_online("import produits"):
            return {"error": "Mode hors ligne - import impossible", "success": False, "count": 0}

        user = self.auth_service.get_current_user()
        headers = self._get_headers()
        if not headers:
            return {"error": "Utilisateur non authentifié", "code": 401}
        
        try:
            params = {}
            if branch_id:
                params["branch_id"] = branch_id
            elif user and user.get('branch_id'):
                params["branch_id"] = user.get('branch_id')
            elif user and user.get('active_branch_id'):
                params["branch_id"] = user.get('active_branch_id')
            
            logger.info(f"Import des produits pour la branche: {params.get('branch_id')}")
            
            # === PAGINATION POUR RÉCUPÉRER TOUS LES PRODUITS ===
            all_products = []
            skip = 0
            limit = 500
            total_count = None
            max_iterations = 50
            iteration = 0
            
            while iteration < max_iterations:
                iteration += 1
                pagination_params = params.copy()
                pagination_params["skip"] = skip
                pagination_params["limit"] = limit
                
                logger.info(f"Requête {iteration}: skip={skip}, limit={limit}")
                
                response = self.session.get(
                    f"{self.api_url}/stock",
                    headers=headers,
                    params=pagination_params,
                    timeout=120
                )
                
                if response.status_code != 200:
                    error_msg = f"Erreur serveur: {response.status_code}"
                    logger.error(error_msg)
                    return {"error": error_msg, "code": response.status_code, "success": False}
                
                data = response.json()
                
                # Gérer différents formats de réponse
                if isinstance(data, list):
                    products_batch = data
                elif isinstance(data, dict):
                    products_batch = data.get('products', data.get('data', data.get('items', [])))
                    if total_count is None:
                        total_count = data.get('total', data.get('total_count', None))
                        logger.info(f"Total des produits sur le serveur: {total_count}")
                else:
                    products_batch = []
                
                batch_size = len(products_batch)
                if batch_size == 0:
                    logger.info("Plus aucun produit reçu, fin de la pagination")
                    break
                
                all_products.extend(products_batch)
                logger.info(f"Batch {iteration}: {batch_size} produits récupérés (total cumulé: {len(all_products)})")
                
                if total_count is not None and len(all_products) >= total_count:
                    logger.info(f"Tous les produits récupérés: {len(all_products)}/{total_count}")
                    break
                
                if batch_size < limit:
                    logger.info(f"Dernier batch: {batch_size} < {limit}, fin de la pagination")
                    break
                
                skip += limit
            
            if iteration >= max_iterations:
                logger.warning(f"Nombre maximum d'itérations atteint ({max_iterations}), arrêt de la pagination")
            
            logger.info(f"✅ Récupération terminée: {len(all_products)} produits depuis le serveur")
            
            # === CORRECTION: Construction sécurisée des objets Product ===
            products = []
            
            for p in all_products:
                try:
                    # Récupération sécurisée de la quantité
                    quantity = 0
                    if 'quantity' in p and p['quantity'] is not None:
                        quantity = self._safe_int(p['quantity'])
                    elif 'stock' in p and p['stock'] is not None:
                        quantity = self._safe_int(p['stock'])
                    elif 'available_quantity' in p and p['available_quantity'] is not None:
                        quantity = self._safe_int(p['available_quantity'])
                    
                    # Calcul du statut d'expiration
                    expiry_date = p.get('expiry_date') or p.get('expiration_date') or p.get('peremption_date')
                    expiry_status = self._calculate_expiry_status(expiry_date)
                    
                    # CRITIQUE: Utiliser server_id comme champ unique pour l'ID serveur
                    # Ne pas utiliser 'id' directement car cela cause des conflits
                    server_id = p.get('id', '')
                    if server_id and isinstance(server_id, str):
                        # S'assurer que l'ID est bien une chaîne
                        pass
                    
                    # Créer le produit avec les bons champs
                    product_data = {
                        'server_id': self._safe_str(p.get('id', '')),
                        'name': self._safe_str(p.get('name', p.get('product_name', 'Sans nom'))),
                        'code': self._safe_str(p.get('code', p.get('product_code', ''))),
                        'selling_price': self._safe_float(p.get('selling_price', p.get('price', 0))),
                        'stock': quantity,
                        'quantity': quantity,
                        'category': self._safe_str(p.get('category', p.get('categorie', ''))),
                        'branch_id': self._safe_str(p.get('branch_id') or params.get('branch_id', '')),
                        'updated_at': p.get('updated_at', datetime.now().isoformat()),
                        'is_deleted': p.get('is_deleted', False),
                        'description': self._safe_str(p.get('description', '')),
                        'barcode': self._safe_str(p.get('barcode', p.get('bar_code', ''))),
                        'min_stock': self._safe_int(p.get('min_stock', p.get('alert_threshold', 0))),
                        'max_stock': self._safe_int(p.get('max_stock', p.get('maximum_stock', 0))),
                        'unit': self._safe_str(p.get('unit', p.get('unite', 'pièce'))),
                        'tax_rate': self._safe_float(p.get('tax_rate', p.get('tva', 0))),
                        'expiry_date': expiry_date,
                        'expiry_status': expiry_status,
                        'manufacturing_date': p.get('manufacturing_date') or p.get('fabrication_date'),
                        'lot_number': self._safe_str(p.get('lot_number', p.get('lot', ''))),
                        'supplier': self._safe_str(p.get('supplier', p.get('fournisseur', ''))),
                        'location': self._safe_str(p.get('location', p.get('emplacement', ''))),
                        'status': self._safe_str(p.get('status'), 'active'),
                        'alert_threshold_days': self._safe_int(p.get('alert_threshold_days'), 30),
                        # Champs supplémentaires optionnels
                        #'purchase_price': self._safe_float(p.get('purchase_price', 0)),
                        #'wholesale_price': self._safe_float(p.get('wholesale_price', 0)),
                        #'product_type': self._safe_str(p.get('product_type', 'medicament')),
                        #'therapeutic_class': self._safe_str(p.get('therapeutic_class', '')),
                        #'active_ingredient': self._safe_str(p.get('active_ingredient', '')),
                        #'dosage': self._safe_str(p.get('dosage', '')),
                        #'galenic_form': self._safe_str(p.get('galenic_form', '')),
                        #'laboratory': self._safe_str(p.get('laboratory', '')),
                        #'prescription_required': p.get('prescription_required', False),
                    }
                    
                    # Filtrer les champs None ou vides pour éviter les erreurs
                    product_data = {k: v for k, v in product_data.items() if v is not None}
                    
                    # Vérifier que le produit a un nom
                    if not product_data.get('name'):
                        logger.warning(f"Produit sans nom ignoré: {p.get('id', 'unknown')}")
                        continue
                    
                    # Créer l'objet Product avec les bons paramètres
                    # Adapter selon la structure de votre modèle Product local
                    try:
                        # Essayer d'importer le modèle Product local
                        from database.models import Product as LocalProduct
                        
                        product = LocalProduct(**product_data)
                        products.append(product)
                        logger.debug(f"Produit converti: {product.name} (ID serveur: {product.server_id})")
                    except TypeError as e:
                        # Si le modèle n'accepte pas tous les champs, créer avec les champs de base
                        logger.warning(f"Erreur de type pour le produit {p.get('id')}: {e}")
                        
                        # Créer avec les champs de base uniquement
                        basic_product = {
                            'server_id': self._safe_str(p.get('id', '')),
                            'name': self._safe_str(p.get('name', 'Sans nom')),
                            'code': self._safe_str(p.get('code', '')),
                            'selling_price': self._safe_float(p.get('selling_price', 0)),
                            'stock': quantity,
                            'quantity': quantity,
                            'category': self._safe_str(p.get('category', '')),
                            'branch_id': self._safe_str(params.get('branch_id', '')),
                            'updated_at': p.get('updated_at', datetime.now().isoformat()),
                            'is_deleted': p.get('is_deleted', False),
                            'barcode': self._safe_str(p.get('barcode', '')),
                            'expiry_date': expiry_date,
                        }
                        basic_product = {k: v for k, v in basic_product.items() if v is not None}
                        
                        from database.models import Product as LocalProduct
                        product = LocalProduct(**basic_product)
                        products.append(product)
                    
                except Exception as e:
                    logger.error(f"Erreur conversion produit {p.get('id', 'unknown')}: {e}")
                    continue
            
            # Sauvegarder dans la base locale
            if products:
                saved_count = self.db.save_products(products)
                logger.info(f"{saved_count} produits sauvegardés localement")
                
                # Vérification
                test_products = self.db.get_all_products(params.get('branch_id'))
                if test_products:
                    total_stock = sum(getattr(p, 'stock', 0) or 0 for p in test_products)
                    logger.info(f"Stock total importé: {total_stock} unités")
                
                return {
                    "count": saved_count,
                    "products": products,
                    "success": True,
                    "total_products": len(products),
                    "total_stock": sum(getattr(p, 'stock', 0) or 0 for p in products)
                }
            else:
                return {"count": 0, "products": [], "success": True, "message": "Aucun produit converti"}
                
        except requests.exceptions.RequestException as e:
            error_msg = f"Erreur réseau: {str(e)}"
            logger.error(error_msg)
            return {"error": error_msg, "success": False}
        except Exception as e:
            error_msg = f"Erreur import: {str(e)}"
            logger.error(error_msg)
            return {"error": error_msg, "success": False}
    
    def import_products_improved(self, branch_id: str = None) -> Dict:
        """Importe TOUS les produits depuis le serveur (sans limite)"""
        if not self._ensure_online("import produits"):
            return {"error": "Mode hors ligne - import impossible", "success": False, "count": 0}

        user = self.auth_service.get_current_user()
        headers = self._get_headers()
        if not headers:
            return {"error": "Utilisateur non authentifié", "code": 401, "success": False}
        
        # Déterminer la branche
        if not branch_id:
            branch_id = user.get('active_branch_id') or user.get('branch_id')
        
        if not branch_id:
            return {"error": "Aucune branche spécifiée", "success": False}
        
        logger.info(f"📦 Import des produits pour la branche: {branch_id}")
        
        try:
            # === PARAMÈTRES POUR RÉCUPÉRER TOUS LES PRODUITS ===
            params = {
                "branch_id": branch_id,
                "get_all": True,      # ← IGNORE LA PAGINATION
                "limit": 10000,       # ← GRANDE LIMITE
                "include_sales_stats": False
            }
            
            response = self.session.get(
                f"{self.api_url}/stock",
                headers=headers,
                params=params,
                timeout=120
            )
            
            if response.status_code != 200:
                # Fallback: essayer sans get_all
                logger.warning(f"⚠️ get_all=true échoué (HTTP {response.status_code}), fallback pagination")
                return self._import_products_with_pagination(branch_id)
            
            data = response.json()
            
            # Extraire les produits
            if isinstance(data, list):
                products_data = data
            elif isinstance(data, dict):
                products_data = data.get('products', data.get('data', data.get('items', [])))
            else:
                products_data = []
            
            logger.info(f"✅ {len(products_data)} produits récupérés depuis le serveur")
            
            if not products_data:
                return {"count": 0, "products": [], "success": True, "message": "Aucun produit"}
            
            # Conversion des produits
            from database.models import Product as LocalProduct
            
            products = []
            for p in products_data:
                try:
                    server_id = str(p.get('id', ''))
                    if not server_id:
                        continue
                    
                    quantity = self._safe_int(p.get('quantity', p.get('stock', 0)))
                    selling_price = self._safe_float(p.get('selling_price', p.get('price', 0)))
                    expiry_date = p.get('expiry_date') or p.get('expiration_date')
                    expiry_status = self._calculate_expiry_status(expiry_date)
                    stock_version = p.get('stock_version', 1)
                    
                    product = LocalProduct(
                        server_id=server_id,
                        name=self._safe_str(p.get('name', p.get('product_name', 'Sans nom'))),
                        code=self._safe_str(p.get('code', p.get('product_code', ''))),
                        barcode=self._safe_str(p.get('barcode', p.get('bar_code', ''))),
                        selling_price=selling_price,
                        stock=quantity,
                        quantity=quantity,
                        synced_quantity=quantity,
                        stock_version=stock_version,
                        min_stock=self._safe_int(p.get('min_stock', p.get('alert_threshold', 0))),
                        category=self._safe_str(p.get('category', p.get('categorie', ''))),
                        unit=self._safe_str(p.get('unit', 'pièce')),
                        branch_id=branch_id,
                        pharmacy_id=user.get('pharmacy_id'),
                        tenant_id=user.get('tenant_id'),
                        updated_at=p.get('updated_at', datetime.now().isoformat()),
                        is_active=p.get('is_active', True),
                        is_deleted=p.get('is_deleted', False),
                        expiry_date=expiry_date,
                        expiry_status=expiry_status,
                        description=self._safe_str(p.get('description', '')),
                        last_sync_at=datetime.now().isoformat(),
                        # Champs supplémentaires
                        #purchase_price=self._safe_float(p.get('purchase_price', 0)),
                        supplier=self._safe_str(p.get('supplier', p.get('main_supplier', ''))),
                        location=self._safe_str(p.get('location', '')),
                        lot_number=self._safe_str(p.get('lot_number', p.get('batch_number', ''))),
                        tax_rate=self._safe_float(p.get('tax_rate', p.get('tva_rate', 0))),
                        #has_tva=p.get('has_tva', False)
                    )
                    products.append(product)
                    logger.debug(f"✅ Produit converti: {product.name} (ID: {product.server_id})")
                    
                except Exception as e:
                    logger.error(f"❌ Erreur conversion produit {p.get('id')}: {e}")
                    continue
            
            if products:
                # Sauvegarder dans la base locale
                saved_count = self.db.save_products(products)
                logger.info(f"✅ {saved_count} produits sauvegardés localement")
                
                return {
                    "count": saved_count,
                    "products": products,
                    "success": True,
                    "total_products": len(products),
                    "branch_id": branch_id,
                    "message": f"{saved_count} produits importés sur {len(products_data)}"
                }
            else:
                return {"count": 0, "products": [], "success": True, "message": "Aucun produit converti"}
                
        except Exception as e:
            logger.error(f"❌ Erreur import_products_improved: {str(e)}", exc_info=True)
            return {"error": str(e), "success": False, "count": 0}


    def _import_products_with_pagination(self, branch_id: str) -> Dict:
        """Fallback: import avec pagination"""
        if not self._ensure_online("import produits"):
            return {"error": "Mode hors ligne - import impossible", "success": False, "count": 0}

        user = self.auth_service.get_current_user()
        headers = self._get_headers()
        
        all_products = []
        skip = 0
        limit = 500
        max_iterations = 50
        
        logger.info(f"📦 Import paginé pour branche {branch_id}")
        
        for iteration in range(max_iterations):
            response = self.session.get(
                f"{self.api_url}/stock",
                headers=headers,
                params={
                    "branch_id": branch_id,
                    "skip": skip,
                    "limit": limit
                },
                timeout=60
            )
            
            if response.status_code != 200:
                logger.error(f"Erreur HTTP {response.status_code}")
                break
            
            data = response.json()
            
            if isinstance(data, list):
                batch = data
            elif isinstance(data, dict):
                batch = data.get('products', data.get('data', data.get('items', [])))
                total = data.get('total', 0)
                logger.info(f"Total produits sur le serveur: {total}")
            else:
                batch = []
            
            if not batch:
                logger.info("Plus de produits, fin de pagination")
                break
            
            all_products.extend(batch)
            logger.info(f"Batch {iteration+1}: {len(batch)} produits (total: {len(all_products)})")
            
            if len(batch) < limit:
                break
            
            skip += limit
        
        logger.info(f"✅ {len(all_products)} produits récupérés via pagination")
        
        # Convertir et sauvegarder
        from database.models import Product as LocalProduct
        
        products = []
        for p in all_products:
            try:
                server_id = str(p.get('id', ''))
                if not server_id:
                    continue
                
                quantity = self._safe_int(p.get('quantity', p.get('stock', 0)))
                
                product = LocalProduct(
                    server_id=server_id,
                    name=self._safe_str(p.get('name', 'Sans nom')),
                    code=self._safe_str(p.get('code', '')),
                    barcode=self._safe_str(p.get('barcode', '')),
                    selling_price=self._safe_float(p.get('selling_price', 0)),
                    stock=quantity,
                    quantity=quantity,
                    branch_id=branch_id,
                    updated_at=datetime.now().isoformat(),
                    is_active=True,
                    is_deleted=False
                )
                products.append(product)
            except Exception as e:
                logger.error(f"Erreur conversion: {e}")
                continue
        
        if products:
            saved_count = self.db.save_products(products)
            return {
                "count": saved_count,
                "products": products,
                "success": True,
                "total_products": len(products),
                "branch_id": branch_id
            }
        
        return {"count": 0, "products": [], "success": False, "message": "Aucun produit importé"}
                
    def _calculate_expiry_status(self, expiry_date_str: Optional[str]) -> str:
        """
        Calcule le statut d'expiration d'un produit
        
        Args:
            expiry_date_str: Date d'expiration au format ISO
            
        Returns:
            str: 'expired', 'soon', 'valid', 'unknown'
        """
        if not expiry_date_str:
            return 'unknown'
        
        try:
            from datetime import datetime
            
            # Parse la date d'expiration
            if 'T' in expiry_date_str:
                expiry_date = datetime.fromisoformat(expiry_date_str.split('T')[0])
            else:
                expiry_date = datetime.fromisoformat(expiry_date_str)
            
            today = datetime.now().date()
            expiry_date = expiry_date.date() if hasattr(expiry_date, 'date') else expiry_date
            
            # Calcul de la différence en jours
            days_until_expiry = (expiry_date - today).days
            
            if days_until_expiry < 0:
                return 'expired'
            elif days_until_expiry <= 30:
                return 'soon'
            else:
                return 'valid'
        except Exception as e:
            logger.error(f"Erreur calcul statut expiration: {e}")
            return 'unknown'


    def get_expiring_products(self, days_threshold: int = 30, branch_id: str = None) -> List[Dict]:
        """
        Récupère les produits qui expirent bientôt
        
        Args:
            days_threshold: Nombre de jours avant expiration pour alerter
            branch_id: ID de la branche (optionnel)
            
        Returns:
            List des produits qui expirent bientôt
        """
        try:
            # Récupérer les produits depuis la base locale
            products = self.db.get_all_products(branch_id)
            
            expiring_products = []
            for product in products:
                # ✅ Utiliser hasattr et getattr, pas product.get()
                if hasattr(product, 'expiry_date') and product.expiry_date:
                    status = self._calculate_expiry_status(product.expiry_date)
                    if status == 'soon':
                        expiring_products.append({
                            'id': product.server_id,
                            'name': product.name,
                            'code': product.code,
                            'expiry_date': product.expiry_date,
                            'stock': product.stock if hasattr(product, 'stock') else product.quantity,
                            'days_left': self._get_days_until_expiry(product.expiry_date)
                        })
            
            return expiring_products
        except Exception as e:
            logger.error(f"Erreur récupération produits expirants: {e}")
            return []


    def _get_days_until_expiry(self, expiry_date_str: str) -> int:
        """Calcule le nombre de jours jusqu'à l'expiration"""
        try:
            from datetime import datetime
            
            if not expiry_date_str:
                return 999
            
            if 'T' in expiry_date_str:
                expiry_date = datetime.fromisoformat(expiry_date_str.split('T')[0])
            else:
                expiry_date = datetime.fromisoformat(expiry_date_str)
            
            today = datetime.now().date()
            expiry_date = expiry_date.date() if hasattr(expiry_date, 'date') else expiry_date
            
            return (expiry_date - today).days
        except Exception:
            return 999

    def get_expired_products(self, branch_id: str = None) -> List[Dict]:
        """
        Récupère les produits expirés
        
        Args:
            branch_id: ID de la branche (optionnel)
            
        Returns:
            List des produits expirés
        """
        try:
            products = self.db.get_all_products(branch_id)
            
            expired_products = []
            for product in products:
                # ✅ Utiliser hasattr et getattr, pas product.get()
                if hasattr(product, 'expiry_date') and product.expiry_date:
                    status = self._calculate_expiry_status(product.expiry_date)
                    if status == 'expired':
                        expired_products.append({
                            'id': product.server_id,
                            'name': product.name,
                            'code': product.code,
                            'expiry_date': product.expiry_date,
                            'stock': product.stock if hasattr(product, 'stock') else product.quantity,
                            'days_expired': abs(self._get_days_until_expiry(product.expiry_date))
                        })
            
            return expired_products
        except Exception as e:
            logger.error(f"Erreur récupération produits expirés: {e}")
            return []
    
    def get_products_by_branch(self, branch_id: str) -> Dict:
        """Récupère spécifiquement les produits d'une branche"""
        return self.import_products(branch_id)

    def _get_unsynced_products(self) -> List:
        """Récupère les produits qui n'ont pas été synchronisés récemment"""
        try:
            # Produits non synchronisés depuis plus de 1 heure
            one_hour_ago = (datetime.now() - timedelta(hours=1)).isoformat()
            
            if hasattr(self.db, 'get_products_unsynced'):
                return self.db.get_products_unsynced(one_hour_ago)
            else:
                # Fallback: utiliser get_all_products
                logger.warning("get_products_unsynced non disponible, fallback vers get_all_products")
                return self.db.get_all_products()
                
        except Exception as e:
            logger.error(f"Erreur _get_unsynced_products: {e}")
            return []
    
    def export_sales_with_conflict_handling(self, force_resolution: bool = True) -> Dict:
        """
        Exporte les ventes avec gestion intelligente des conflits de stock.
        
        Stratégies de résolution:
        - "last_write_wins": La dernière vente prévaut (timestamp le plus récent)
        - "quantity_priority": La vente avec la plus grande quantité prévaut
        - "ask_user": Demander à l'utilisateur comment résoudre
        - "split": Accepter partiellement la vente
        """
        unsynced_sales = self.db.get_unsynced_sales_with_metadata()
        
        if not unsynced_sales:
            return {"count": 0, "message": "Aucune vente à exporter"}
        
        headers = self._get_headers()
        if not headers:
            return {"error": "Authentification requise", "count": 0}
        
        try:
            user = self.auth_service.get_current_user()
            branch_id = user.get('active_branch_id') or user.get('branch_id')
            
            # Grouper les ventes par produit pour détecter les conflits
            sales_by_product = {}
            for sale in unsynced_sales:
                product_id = sale.get('product_id')
                if product_id not in sales_by_product:
                    sales_by_product[product_id] = []
                sales_by_product[product_id].append(sale)
            
            # Envoyer avec métadonnées de conflit
            enriched_sales = []
            for product_id, sales in sales_by_product.items():
                # Calculer la quantité totale demandée pour ce produit
                total_requested = sum(s.get('quantity', 0) for s in sales)
                
                for sale in sales:
                    enriched_sale = {
                        'id': sale.get('id'),
                        'original_id': sale.get('original_id', sale.get('id')),
                        'items': [{
                            'product_id': sale.get('product_uuid'),
                            'quantity': float(sale.get('quantity', 1)),
                            'unit_price': float(sale.get('unit_price', 0)),
                            'discount_percent': float(sale.get('discount', 0))
                        }],
                        'client_name': sale.get('customer_name', 'Client synchro'),
                        'client_phone': sale.get('customer_phone', ''),
                        'payment_method': sale.get('payment_method', 'cash'),
                        'is_credit': sale.get('is_credit', False),
                        'global_discount': float(sale.get('global_discount', 0)),
                        'notes': sale.get('notes', ''),
                        'branch_id': branch_id,
                        'pharmacy_id': user.get('pharmacy_id'),
                        
                        # 🔑 MÉTADONNÉES POUR GESTION DES CONFLITS
                        'conflict_metadata': {
                            'client_timestamp': sale.get('created_at', datetime.now().isoformat()),
                            'client_version': sale.get('stock_version', 1),
                            'client_known_stock': sale.get('stock_at_sale_time', 0),
                            'quantity_sold': sale.get('quantity', 1),
                            'sale_uuid': str(uuid.uuid4()),  # ID unique de la vente
                            'device_id': sale.get('device_id', user.get('device_id')),
                            'seller_id': str(user.get('id', '')),
                            'seller_name': user.get('nom_complet', user.get('email', '')),
                            'offline_sale': True
                        },
                        
                        # Stratégie de résolution demandée
                        'conflict_resolution_strategy': force_resolution and "last_write_wins" or "ask_user"
                    }
                    enriched_sales.append(enriched_sale)
            
            # Envoyer à l'endpoint spécialisé
            response = self.session.post(
                f"{self.api_url}/sales/with-conflict-handling",
                headers=headers,
                json={
                    "sales": enriched_sales,
                    "batch_id": str(uuid.uuid4()),
                    "branch_id": branch_id,
                    "default_strategy": "last_write_wins" if force_resolution else "ask_user"
                },
                timeout=120
            )
            
            if response.status_code == 200:
                data = response.json()
                
                # Traiter les conflits résolus
                resolved_sales = data.get('resolved_sales', [])
                partial_sales = data.get('partial_sales', [])
                rejected_sales = data.get('rejected_sales', [])
                stock_updates = data.get('stock_updates', [])
                
                # Mettre à jour la base locale avec les résolutions
                self._apply_conflict_resolutions(
                    resolved_sales, partial_sales, rejected_sales, stock_updates
                )
                
                return {
                    "count": len(resolved_sales),
                    "success": True,
                    "partial_sales": partial_sales,
                    "rejected_sales": rejected_sales,
                    "stock_updates": stock_updates,
                    "total_attempted": len(unsynced_sales)
                }
            else:
                return self._handle_sync_error(response, unsynced_sales)
                
        except Exception as e:
            logger.error(f"Erreur export_sales_with_conflict_handling: {str(e)}", exc_info=True)
            return {"error": str(e), "count": 0, "success": False}
    
    def _apply_conflict_resolutions(self, resolved, partial, rejected, stock_updates):
        """Applique les résolutions de conflits dans la base locale"""
        try:
            # Marquer les ventes complètement résolues
            if resolved and hasattr(self.db, 'mark_sales_resolved'):
                self.db.mark_sales_resolved([s['original_id'] for s in resolved])
            
            # Traiter les ventes partielles (quantité ajustée)
            for partial_sale in partial:
                original_id = partial_sale.get('original_id')
                accepted_quantity = partial_sale.get('accepted_quantity', 0)
                rejected_quantity = partial_sale.get('rejected_quantity', 0)
                reason = partial_sale.get('reason', '')
                
                # Mettre à jour la vente locale avec la quantité acceptée
                if hasattr(self.db, 'update_sale_quantity'):
                    self.db.update_sale_quantity(original_id, accepted_quantity, rejected_quantity, reason)
                
                # Enregistrer le feedback pour l'utilisateur
                self._save_sync_feedback({
                    'sale_id': original_id,
                    'type': 'partial',
                    'message': f"Vente partiellement acceptée: {accepted_quantity} unités sur {accepted_quantity + rejected_quantity}",
                    'details': reason,
                    'product_name': partial_sale.get('product_name'),
                    'accepted_quantity': accepted_quantity,
                    'rejected_quantity': rejected_quantity
                })
            
            # Traiter les ventes rejetées
            for rejected_sale in rejected:
                original_id = rejected_sale.get('original_id')
                reason = rejected_sale.get('reason', '')
                
                # Marquer comme rejetée
                if hasattr(self.db, 'mark_sale_rejected'):
                    self.db.mark_sale_rejected(original_id, reason)
                
                # Enregistrer le feedback
                self._save_sync_feedback({
                    'sale_id': original_id,
                    'type': 'rejected',
                    'message': f"Vente rejetée: {reason}",
                    'details': rejected_sale.get('details', {}),
                    'product_name': rejected_sale.get('product_name')
                })
            
            # Mettre à jour les stocks locaux
            for stock_update in stock_updates:
                if hasattr(self.db, 'update_local_stock'):
                    self.db.update_local_stock(
                        stock_update.get('product_id'),
                        stock_update.get('new_quantity'),
                        stock_update.get('sync_version')
                    )
                    
        except Exception as e:
            logger.error(f"Erreur application résolutions: {e}")

    def export_sales(self) -> Dict:
        """
        Exporte les ventes non synchronisées vers le serveur
        Utilise le mode force pour ignorer les contraintes de stock
        """
        # Utiliser directement la version force_stock
        return self.export_sales_force_stock(force=True)
    
    # =====================
    # EXPORT DES VENTES AVEC FIFO ET GESTION DE CONFLITS
    # =====================
    
    def export_sales_fifo(self, force: bool = False) -> Dict:
        """
        Exporte les ventes avec traitement FIFO et gestion intelligente des conflits.
        """
        unsynced_sales = self.db.get_unsynced_sales_with_metadata()
        
        if not unsynced_sales:
            return {"count": 0, "message": "Aucune vente à exporter"}
        
        headers = self._get_headers()
        if not headers:
            return {"error": "Authentification requise", "count": 0}
        
        try:
            user = self.auth_service.get_current_user()
            branch_id = user.get('active_branch_id') or user.get('branch_id')
            
            # 1. Grouper les ventes par produit
            sales_by_product = defaultdict(list)
            product_ids_set = set()
            
            for sale in unsynced_sales:
                product_id = sale.get('product_id')
                if product_id:
                    product_ids_set.add(str(product_id))
                    sales_by_product[product_id].append(sale)
            
            logger.info(f"📊 {len(unsynced_sales)} ventes à traiter pour {len(product_ids_set)} produits")
            
            # 2. Récupérer les stocks serveur
            server_stocks = self._get_server_stocks_batch(list(product_ids_set))
            
            logger.info(f"✅ Stocks récupérés pour {len(server_stocks)}/{len(product_ids_set)} produits")
            
            # 3. Traiter les ventes par produit avec FIFO
            synced_sales = []
            partial_sales = []
            rejected_sales = []
            stock_updates = []
            fifo_trace = []
            
            for product_id, sales in sales_by_product.items():
                stock_info = server_stocks.get(str(product_id), {})
                current_stock = stock_info.get('quantity', 0)
                product_name = stock_info.get('name', 'Inconnu')
                server_id = stock_info.get('server_id', str(product_id))
                server_version = stock_info.get('version', 1)
                
                # Si le produit n'existe pas sur le serveur
                if not stock_info:
                    for sale in sales:
                        rejected_sales.append({
                            "original_id": sale.get('id'),
                            "product_id": str(product_id),
                            "product_name": sale.get('product_name', 'Inconnu'),
                            "requested_quantity": sale.get('quantity', 1),
                            "reason": f"Le produit '{sale.get('product_name', 'Inconnu')}' n'existe pas sur le serveur. Il a peut-être été supprimé par l'administrateur.",
                            "server_stock": 0,
                            "local_stock": sale.get('stock_quantity_at_sale', 0),
                            "status": "rejected"
                        })
                    continue
                
                # Trier les ventes par date (FIFO - plus ancienne d'abord)
                sales_sorted = sorted(sales, key=lambda x: x.get('sale_date', x.get('created_at', '')))
                
                logger.info(f"📊 Produit '{product_name}': stock serveur={current_stock}, {len(sales_sorted)} ventes en attente")
                
                stock_remaining = current_stock
                total_requested = sum(s.get('quantity', 0) for s in sales_sorted)
                
                fifo_trace.append({
                    "product_name": product_name,
                    "product_id": str(product_id),
                    "initial_stock": current_stock,
                    "total_requested": total_requested,
                    "sales_count": len(sales_sorted)
                })
                
                for sale in sales_sorted:
                    requested_qty = sale.get('quantity', 1)
                    sale_id = sale.get('id')
                    sale_date = sale.get('sale_date', sale.get('created_at', ''))
                    stock_at_sale = sale.get('stock_quantity_at_sale', 0)
                    
                    if stock_remaining >= requested_qty:
                        # Acceptation complète
                        stock_remaining -= requested_qty
                        synced_sales.append({
                            "original_id": sale_id,
                            "product_id": server_id,
                            "product_name": product_name,
                            "quantity": requested_qty,
                            "accepted": requested_qty,
                            "rejected": 0,
                            "sale_date": sale_date,
                            "stock_at_sale": stock_at_sale,
                            "server_stock_at_sync": current_stock,
                            "status": "full"
                        })
                        logger.info(f"✅ Vente {sale_id}: {requested_qty} unités acceptées (stock restant: {stock_remaining})")
                        
                    elif stock_remaining > 0:
                        # Acceptation partielle
                        accepted_qty = stock_remaining
                        rejected_qty = requested_qty - accepted_qty
                        
                        partial_sales.append({
                            "original_id": sale_id,
                            "product_id": server_id,
                            "product_name": product_name,
                            "requested_quantity": requested_qty,
                            "accepted_quantity": accepted_qty,
                            "rejected_quantity": rejected_qty,
                            "reason": f"Stock insuffisant sur le serveur. {accepted_qty}/{requested_qty} unités acceptées. "
                                    f"Stock serveur: {current_stock}, Stock lors de la vente locale: {stock_at_sale}. "
                                    f"Le produit a été partiellement vendu par un autre vendeur entre-temps.",
                            "server_stock": current_stock,
                            "local_stock": stock_at_sale,
                            "sale_date": sale_date,
                            "status": "partial"
                        })
                        
                        stock_remaining = 0
                        logger.warning(f"⚠️ Vente partielle {sale_id}: {accepted_qty}/{requested_qty} unités acceptées")
                        
                    else:
                        # Rejet complet
                        rejected_sales.append({
                            "original_id": sale_id,
                            "product_id": server_id,
                            "product_name": product_name,
                            "requested_quantity": requested_qty,
                            "reason": f"Stock épuisé sur le serveur. {requested_qty} unités demandées mais stock serveur = {current_stock}. "
                                    f"Stock lors de la vente locale: {stock_at_sale}. "
                                    f"Ce produit a été entièrement vendu par un autre vendeur entre-temps.",
                            "server_stock": current_stock,
                            "local_stock": stock_at_sale,
                            "sale_date": sale_date,
                            "status": "rejected"
                        })
                        logger.error(f"❌ Vente rejetée {sale_id}: stock épuisé (serveur={current_stock}, local={stock_at_sale})")
                
                # Enregistrer la mise à jour du stock
                stock_updates.append({
                    "product_id": server_id,
                    "product_name": product_name,
                    "old_quantity": current_stock,
                    "new_quantity": stock_remaining,
                    "sold_quantity": current_stock - stock_remaining,
                    "total_requested": total_requested,
                    "sync_version": server_version + 1
                })
            
            # 4. Mettre à jour la base locale
            self._apply_fifo_results(synced_sales, partial_sales, rejected_sales, stock_updates)
            
            # 5. Générer le rapport détaillé
            return {
                "success": True,
                "count": len(synced_sales),
                "partial_count": len(partial_sales),
                "rejected_count": len(rejected_sales),
                "synced_sales": synced_sales,
                "partial_sales": partial_sales,
                "rejected_sales": rejected_sales,
                "stock_updates": stock_updates,
                "fifo_trace": fifo_trace,
                "total_attempted": len(unsynced_sales),
                "force_mode_used": force,
                "message": self._generate_fifo_summary(synced_sales, partial_sales, rejected_sales)
            }
            
        except Exception as e:
            logger.error(f"Erreur export_sales_fifo: {e}", exc_info=True)
            return {"error": str(e), "count": 0, "success": False}
    
    def _send_accepted_sales_to_server(self, synced_sales: List[Dict], partial_sales: List[Dict], 
                                        headers: Dict, branch_id: str) -> Dict:
        """Envoie les ventes acceptées au serveur"""
        if not synced_sales and not partial_sales:
            return {"success": True, "sent": 0}
        
        # Construire les données pour le serveur
        sales_to_send = []
        
        for sale in synced_sales:
            sales_to_send.append({
                "original_id": sale["original_id"],
                "product_id": sale["product_id"],
                "quantity": sale["accepted"],
                "sale_date": sale.get("sale_date"),
                "status": "full"
            })
        
        for sale in partial_sales:
            sales_to_send.append({
                "original_id": sale["original_id"],
                "product_id": sale["product_id"],
                "quantity": sale["accepted_quantity"],
                "sale_date": sale.get("sale_date"),
                "status": "partial",
                "rejected_quantity": sale["rejected_quantity"],
                "reason": sale["reason"]
            })
        
        try:
            response = self.session.post(
                f"{self.api_url}/sales/batch",
                headers=headers,
                json={
                    "sales": sales_to_send,
                    "branch_id": branch_id,
                    "sync_mode": "fifo",
                    "timestamp": datetime.now().isoformat()
                },
                timeout=120
            )
            
            if response.status_code in [200, 201]:
                return {"success": True, "sent": len(sales_to_send)}
            else:
                logger.error(f"Erreur envoi au serveur: {response.status_code}")
                return {"success": False, "error": f"Status {response.status_code}"}
                
        except Exception as e:
            logger.error(f"Erreur envoi au serveur: {e}")
            return {"success": False, "error": str(e)}
    
    def _apply_fifo_results(self, synced_sales: List[Dict], partial_sales: List[Dict],
                            rejected_sales: List[Dict], stock_updates: List[Dict]):
        """Applique les résultats FIFO dans la base locale"""
        try:
            # Marquer les ventes synchronisées
            synced_ids = [s["original_id"] for s in synced_sales]
            if synced_ids and hasattr(self.db, 'mark_sales_synced'):
                self.db.mark_sales_synced(synced_ids)
            
            # Mettre à jour les ventes partielles
            for sale in partial_sales:
                if hasattr(self.db, 'update_sale_quantity'):
                    self.db.update_sale_quantity(
                        sale["original_id"],
                        sale["accepted_quantity"],
                        sale["rejected_quantity"],
                        sale["reason"]
                    )
                
                # Enregistrer le feedback
                self._save_sync_feedback({
                    'sale_id': sale["original_id"],
                    'type': 'partial',
                    'message': f"Vente partiellement acceptée: {sale['accepted_quantity']}/{sale['requested_quantity']} unités",
                    'details': sale,
                    'product_name': sale['product_name']
                })
            
            # Marquer les ventes rejetées
            for sale in rejected_sales:
                if hasattr(self.db, 'mark_sale_rejected'):
                    self.db.mark_sale_rejected(sale["original_id"], sale["reason"])
                
                self._save_sync_feedback({
                    'sale_id': sale["original_id"],
                    'type': 'rejected',
                    'message': f"Vente rejetée: {sale['reason']}",
                    'details': sale,
                    'product_name': sale['product_name']
                })
            
            # Mettre à jour les stocks locaux avec version
            for update in stock_updates:
                product = self.db.get_product_by_id(update["product_id"])
                if product:
                    product.quantity = update["new_quantity"]
                    product.synced_quantity = update["new_quantity"]
                    product.stock_version = update["sync_version"]
                    product.last_sync_at = datetime.now()
                    
                    if hasattr(product, 'refresh_statuses'):
                        product.refresh_statuses()
            
            logger.info(f"✅ Résultats FIFO appliqués: {len(synced_sales)} complètes, "
                       f"{len(partial_sales)} partielles, {len(rejected_sales)} rejetées")
            
        except Exception as e:
            logger.error(f"Erreur application résultats FIFO: {e}")
    
    def _save_sync_feedback(self, feedback: Dict):
        """Sauvegarde un feedback de synchronisation"""
        try:
            if hasattr(self.db, 'save_sync_feedback'):
                self.db.save_sync_feedback(feedback)
        except Exception as e:
            logger.error(f"Erreur sauvegarde feedback: {e}")
    
    def _generate_fifo_summary(self, synced: List, partial: List, rejected: List) -> str:
        """Génère un résumé du traitement FIFO"""
        total = len(synced) + len(partial) + len(rejected)
        parts = []
        
        if synced:
            parts.append(f"{len(synced)} ventes complètes")
        if partial:
            parts.append(f"{len(partial)} ventes partielles")
        if rejected:
            parts.append(f"{len(rejected)} ventes rejetées")
        
        if not parts:
            return "Aucune vente traitée"
        
        return f"Traitement FIFO terminé: {', '.join(parts)} sur {total} total"
    
    # =====================
    # SYNCHRONISATION COMPLÈTE
    # =====================
    
    def sync_all_fifo(self) -> Dict:
        """
        Synchronisation complète avec traitement FIFO et versionnement
        """
        logger.info("=== DÉBUT SYNCHRONISATION COMPLÈTE (FIFO) ===")
        
        is_online = self.check_internet_connection()
        
        results = {
            "products_imported": 0,
            "products_updated": 0,
            "sales_exported": 0,
            "partial_sales": 0,
            "rejected_sales": 0,
            "version_conflicts": [],
            "fifo_trace": [],
            "errors": [],
            "success": True,
            "sync_date": datetime.now().isoformat(),
            "online": is_online
        }
        
        if not is_online:
            results["errors"].append("Mode hors ligne - synchronisation différée")
            results["success"] = False
            return results
        
        # 1. Synchroniser la branche
        branch_sync = self.auth_service.sync_user_branch_from_server()
        branch_id = branch_sync.get('branch_id') if branch_sync.get('success') else None
        
        # 2. Importer les produits avec versions
        logger.info("📦 Import des produits avec versionnement...")
        products_result = self.import_products_with_versions(branch_id)
        
        if products_result.get("success"):
            results["products_imported"] = products_result.get("products_created", 0)
            results["products_updated"] = products_result.get("products_updated", 0)
            results["version_conflicts"] = products_result.get("version_conflicts", [])
            logger.info(f"✅ Produits: {results['products_imported']} nouveaux, "
                       f"{results['products_updated']} mis à jour")
        else:
            results["errors"].append(f"Produits: {products_result.get('error')}")
        
        # 3. Exporter les ventes avec FIFO
        logger.info("💰 Export des ventes avec traitement FIFO...")
        sales_result = self.export_sales_fifo(force=True)
        
        if sales_result.get("success"):
            results["sales_exported"] = sales_result.get("count", 0)
            results["partial_sales"] = sales_result.get("partial_count", 0)
            results["rejected_sales"] = sales_result.get("rejected_count", 0)
            results["fifo_trace"] = sales_result.get("fifo_trace", [])
            logger.info(f"✅ Ventes: {results['sales_exported']} complètes, "
                       f"{results['partial_sales']} partielles, "
                       f"{results['rejected_sales']} rejetées")
        else:
            results["errors"].append(f"Ventes: {sales_result.get('error')}")
        
        # 4. Exporter les dépenses
        logger.info("📉 Export des dépenses...")
        expenses_result = self.export_expenses()
        if expenses_result.get("success"):
            results["expenses_exported"] = expenses_result.get("count", 0)
        elif expenses_result.get("error"):
            results["errors"].append(f"Dépenses: {expenses_result.get('error')}")
        
        # 5. Exporter les retours
        logger.info("🔄 Export des retours...")
        returns_result = self.export_returns()
        if returns_result.get("success"):
            results["returns_exported"] = returns_result.get("count", 0)
        
        # 6. Exporter les dettes
        logger.info("💳 Export des dettes...")
        debts_result = self.export_debts()
        if debts_result.get("success"):
            results["debts_exported"] = debts_result.get("count", 0)
        
        # Sauvegarder le log
        if hasattr(self.db, 'save_sync_log'):
            try:
                self.db.save_sync_log(results)
            except Exception as e:
                logger.error(f"Erreur sauvegarde log: {e}")
        
        # Mettre à jour la dernière synchronisation
        try:
            self.auth_service.update_last_sync(datetime.now().isoformat())
        except Exception as e:
            logger.error(f"Erreur mise à jour last_sync: {e}")
        
        results["success"] = len(results["errors"]) == 0
        
        logger.info(f"=== FIN SYNCHRONISATION FIFO ===")
        
        return results

    def export_sales_force_stock(self, force: bool = True) -> Dict:
        logger.info(f"=== export_sales_force_stock: force={force} ===")
        
        unsynced_sales = self.db.get_unsynced_sales()
        logger.info(f"Nombre de ventes non synchronisées: {len(unsynced_sales)}")
        if not unsynced_sales:
            return {"count": 0, "message": "Aucune vente à exporter"}

        headers = self._get_headers()
        if not headers:
            return {"error": "Authentification requise", "count": 0}
        
        try:
            user = self.auth_service.get_current_user()
            pharmacy_id = user.get('pharmacy_id')
            branch_id = user.get('active_branch_id') or user.get('branch_id')
            
            synced_ids = []
            errors = []
            stock_warnings = []
            
            # Préparer les ventes pour l'envoi
            sales_to_sync = []
            
            for sale in unsynced_sales:
                # Récupérer le product_id original (UUID)
                product_id_local = sale.get('product_id')
                
                # Récupérer le produit avec son UUID serveur
                product = self.db.get_product_by_id(product_id_local)
                if not product:
                    errors.append({
                        "id": sale.get('id'),
                        "error": f"Produit {product_id_local} non trouvé dans la base locale"
                    })
                    continue
                
                # Utiliser le server_id (UUID) pour l'API
                product_uuid = product.server_id
                
                # ✅ CORRECTION: Ajouter reference unique pour éviter conflits
                import uuid
                unique_ref = f"OFFLINE-{uuid.uuid4().hex[:12].upper()}"
                
                # Construction de la vente
                cleaned_sale = {
                    'items': [{
                        'product_id': product_uuid,
                        'product_code': product.code if product.code else "", 
                        'product_name': product.name, 
                        'quantity': float(sale.get('quantity', 1)),
                        'discount_percent': float(sale.get('discount', 0))
                    }],
                    'client_name': sale.get('customer_name', 'Client comptant'),
                    'client_phone': sale.get('customer_phone', ''),
                    'client_email': sale.get('customer_email', ''),
                    'payment_method': sale.get('payment_method', 'cash'),  # ✅ S'assurer présent
                    'is_credit': sale.get('is_credit', False),
                    'global_discount': float(sale.get('global_discount', 0)),
                    'notes': f"Synced from offline - Original ID: {sale.get('id')}",
                    'branch_id': branch_id,
                    'pharmacy_id': pharmacy_id,
                    'force_stock_ignore': force,
                    'sale_date': sale.get('sale_date', datetime.now().isoformat()),
                    'subtotal': float(sale.get('subtotal', sale.get('total_price', 0))),
                    'total_discount': float(sale.get('total_discount', 0)),
                    'total_tva': float(sale.get('total_tva', 0)),
                    'total_amount': float(sale.get('total_price', 0)),
                    'status': 'completed',
                    #'reference': unique_ref,  # ✅ Ajouter reference unique
                }
                
                # ✅ Retirer invoice_number pour que le serveur le génère
                # Ne pas envoyer invoice_number
                
                sales_to_sync.append({
                    'original_id': sale.get('id'),
                    'data': cleaned_sale,
                    'product_name': product.name,
                    'quantity': sale.get('quantity', 1),
                    'product_stock': product.stock if hasattr(product, 'stock') else 0
                })
                
                logger.info(f"📤 Préparation vente {sale.get('id')}: product={product_uuid}, qty={sale.get('quantity')}, force={force}")
            
            if not sales_to_sync:
                return {
                    "count": 0,
                    "success": False,
                    "errors": errors,
                    "message": "Aucune vente valide à exporter"
                }
            
            # ✅ CORRECTION: Envoyer une vente à la fois, pas en batch
            synced_count = 0
            for sale_item in sales_to_sync:
                try:
                    response = self.session.post(
                        f"{self.api_url}/sales",
                        headers=headers,
                        json=sale_item['data'],
                        timeout=120
                    )
                    
                    if response.status_code in [200, 201]:
                        synced_ids.append(sale_item['original_id'])
                        synced_count += 1
                        logger.info(f"✅ Vente {sale_item['original_id']} synchronisée")
                    else:
                        error_text = response.text[:500]
                        logger.error(f"❌ Erreur HTTP {response.status_code}: {error_text}")
                        errors.append({
                            "id": sale_item['original_id'],
                            "status": response.status_code,
                            "error": error_text
                        })
                except Exception as e:
                    logger.error(f"❌ Erreur envoi vente {sale_item['original_id']}: {e}")
                    errors.append({"id": sale_item['original_id'], "error": str(e)})
            
            # Marquer les ventes synchronisées
            if synced_ids and hasattr(self.db, 'mark_sales_synced'):
                self.db.mark_sales_synced(synced_ids)
            
            logger.info(f"✅ Ventes synchronisées: {len(synced_ids)} succès, {len(errors)} erreurs")
            
            return {
                "count": len(synced_ids),
                "success": len(errors) == 0,
                "synced_ids": synced_ids,
                "stock_warnings": stock_warnings,
                "force_mode_used": force,
                "errors": errors,
                "total_attempted": len(unsynced_sales)
            }
            
        except Exception as e:
            logger.error(f"Erreur export_sales_force_stock: {str(e)}", exc_info=True)
            return {"error": str(e), "count": 0, "success": False}


    def _export_sales_fallback(self, sales_to_sync: List[Dict], headers: Dict, force: bool = True) -> Dict:
        """
        Méthode de fallback pour exporter les ventes une par une
        """
        synced_ids = []
        errors = []
        stock_warnings = []
        
        for sale_item in sales_to_sync:
            sale_data = sale_item['data'].copy()  # Créer une copie pour ne pas modifier l'original
            
            # ✅ CORRECTION 1: S'assurer que payment_method est présent
            if 'payment_method' not in sale_data or not sale_data['payment_method']:
                sale_data['payment_method'] = 'cash'
            
            # ✅ CORRECTION 2: Générer une reference unique pour éviter les conflits
            if 'reference' not in sale_data or not sale_data['reference']:
                import uuid
                sale_data['reference'] = f"OFFLINE-{uuid.uuid4().hex[:12].upper()}"
            
            try:
                # ✅ CORRECTION 3: Envoyer directement l'objet sale, pas {"sales": [...]}
                response = self.session.post(
                    f"{self.api_url}/sales/?force_stock_ignore={str(force).lower()}",
                    headers=headers,
                    json=sale_data,  # ← Envoyer l'objet directement
                    timeout=60
                )
                
                if response.status_code in [200, 201]:
                    synced_ids.append(sale_item['original_id'])
                    logger.info(f"✅ Vente {sale_item['original_id']} synchronisée (fallback)")
                    
                    # Récupérer le numéro de facture généré par le serveur
                    try:
                        data = response.json()
                        server_invoice = data.get('generated_invoice_number') or data.get('invoice_number')
                        if server_invoice:
                            logger.info(f"   Numéro facture serveur: {server_invoice}")
                    except:
                        pass
                        
                else:
                    error_detail = response.text[:500]
                    try:
                        error_json = response.json()
                        error_detail = error_json.get('detail', error_detail)
                    except:
                        pass
                    
                    errors.append({
                        "id": sale_item['original_id'],
                        "status": response.status_code,
                        "error": error_detail
                    })
                    logger.error(f"❌ Erreur sync vente {sale_item['original_id']}: {response.status_code} - {error_detail}")
                    
            except Exception as e:
                errors.append({"id": sale_item['original_id'], "error": str(e)})
                logger.error(f"❌ Erreur réseau vente {sale_item['original_id']}: {str(e)}")
        
        # Marquer les ventes synchronisées
        if synced_ids and hasattr(self.db, 'mark_sales_synced'):
            self.db.mark_sales_synced(synced_ids)
        
        return {
            "count": len(synced_ids),
            "success": len(errors) == 0,
            "synced_ids": synced_ids,
            "errors": errors,
            "stock_warnings": stock_warnings,
            "force_mode_used": force,
            "total_attempted": len(sales_to_sync)
        }

    def sync_sales_force_stock(self) -> Dict:
        """
        Synchronise uniquement les ventes en ignorant les contraintes de stock.
        Utile quand le stock local est désynchronisé.
        
        Returns:
            Dict avec le résultat de la synchronisation
        """
        if not self.check_internet_connection():
            return {"error": "Pas de connexion internet", "success": False}
        
        result = self.export_sales_force_stock(force=True)
        if "error" in result:
            return {"error": result["error"], "success": False}
        
        return {
            "sales_exported": result.get("count", 0),
            "success": True,
            "force_mode_used": True,
            "stock_warnings": result.get("stock_warnings", []),
            "errors": result.get("errors", [])
        }


    def sync_sales_with_retry(self, max_retries: int = 3) -> Dict:
        """
        Synchronise les ventes avec tentative de reprise en cas d'erreur de stock.
        D'abord essaie normalement, puis en mode force si échec.
        
        Args:
            max_retries: Nombre maximum de tentatives
            
        Returns:
            Dict avec le résultat de la synchronisation
        """
        if not self.check_internet_connection():
            return {"error": "Pas de connexion internet", "success": False}
        
        # Première tentative: mode normal
        logger.info("Tentative 1: Synchronisation normale des ventes")
        result_normal = self.export_sales()
        
        if result_normal.get("success", False):
            return {
                "sales_exported": result_normal.get("count", 0),
                "success": True,
                "mode": "normal",
                "errors": result_normal.get("errors", [])
            }
        
        # Si erreur de stock, réessayer en mode force
        errors = result_normal.get("errors", [])
        stock_errors = [e for e in errors if "stock" in str(e).lower() or "insuffisant" in str(e).lower()]
        
        if stock_errors:
            logger.info(f"Détection d'erreurs de stock ({len(stock_errors)}), tentative en mode force")
            
            for retry in range(1, max_retries):
                logger.info(f"Tentative {retry + 1}: Synchronisation en mode force")
                result_force = self.export_sales_force_stock(force=True)
                
                if result_force.get("success", False):
                    return {
                        "sales_exported": result_force.get("count", 0),
                        "success": True,
                        "mode": "force",
                        "retry_count": retry,
                        "stock_warnings": result_force.get("stock_warnings", []),
                        "errors": result_force.get("errors", [])
                    }
        
        # Échec total
        return {
            "sales_exported": 0,
            "success": False,
            "mode": "failed",
            "errors": errors
        }

    def sync_all(self, force_stock: bool = True, retry_on_stock_error: bool = False) -> Dict:
        """
        Synchronise toutes les données avec priorité à la branche
        
        Args:
            force_stock: Si True, ignore les contraintes de stock (recommandé pour offline)
            retry_on_stock_error: Si True, réessaie en mode force en cas d'erreur (déprécié)
        """
        logger.info(f"=== DÉBUT SYNCHRONISATION COMPLÈTE ===")
        
        # 1. D'abord, synchroniser la branche de l'utilisateur
        branch_sync = self.auth_service.sync_user_branch_from_server()
        if branch_sync.get('success'):
            logger.info(f"✅ Branche synchronisée: {branch_sync.get('branch_name')} ({branch_sync.get('branch_id')})")
        else:
            logger.warning(f"⚠️ Impossible de synchroniser la branche: {branch_sync.get('error')}")
        
        # 2. Synchroniser l'abonnement
        subscription = self.sync_subscription()
        if subscription.get('success'):
            logger.info(f"✅ Abonnement synchronisé - Actif: {subscription.get('is_active', False)}")
        else:
            logger.warning(f"⚠️ Erreur synchronisation abonnement: {subscription.get('error')}")
        
        # 3. Importer les produits
        is_online = self.check_internet_connection()
        
        results = {
            "products_imported": 0,
            "sales_exported": 0,
            "expenses_exported": 0,
            "returns_exported": 0,
            "debts_exported": 0,
            "subscription_synced": subscription.get('success', False),
            "subscription_active": subscription.get('is_active', True),
            "branch_synced": branch_sync.get('success', False),
            "branch_name": branch_sync.get('branch_name'),
            "branch_id": branch_sync.get('branch_id'),
            "errors": [],
            "success": True,
            "sync_date": datetime.now().isoformat(),
            "online": is_online
        }
        
        # Importer les produits
        if is_online:
            branch_id = branch_sync.get('branch_id') or self.auth_service.get_user_branch_id()
            
            res_prod = self.import_products_improved(branch_id)
            if "error" in res_prod:
                results["errors"].append(f"Produits: {res_prod['error']}")
                results["success"] = False
                logger.error(f"❌ Erreur import produits: {res_prod['error']}")
            else:
                results["products_imported"] = res_prod.get("count", 0)
                logger.info(f"✅ {results['products_imported']} produits importés")
        else:
            logger.info("Mode offline - import produits ignoré")
        
        # Vérifier l'abonnement avant d'exporter
        if not results["subscription_active"]:
            results["errors"].append("Abonnement inactif - Mode lecture seule")
            logger.warning("⚠️ Abonnement inactif - Mode lecture seule")
        
        # Exporter les ventes - TOUJOURS en mode force_stock=True
        if results["subscription_active"] and is_online:
            # Utiliser directement export_sales_force_stock avec force=True
            res_sales = self.export_sales_force_stock(force=True)
            
            if "error" in res_sales:
                results["errors"].append(f"Ventes: {res_sales['error']}")
                results["success"] = False
            else:
                results["sales_exported"] = res_sales.get("count", 0)
                # Ajouter les avertissements de stock si présents
                if res_sales.get("stock_warnings"):
                    results["stock_warnings"] = res_sales.get("stock_warnings")
                    logger.warning(f"⚠️ {len(res_sales['stock_warnings'])} avertissements de stock")
                logger.info(f"✅ {results['sales_exported']} ventes exportées (mode force)")
        
        # Exporter les dépenses
        if results["subscription_active"] and is_online:
            res_expenses = self.export_expenses()
            if "error" in res_expenses:
                results["errors"].append(f"Dépenses: {res_expenses['error']}")
            else:
                results["expenses_exported"] = res_expenses.get("count", 0)
                logger.info(f"✅ {results['expenses_exported']} dépenses exportées")
        
        # Exporter les retours
        if results["subscription_active"] and is_online:
            res_returns = self.export_returns()
            if "error" in res_returns:
                results["errors"].append(f"Retours: {res_returns['error']}")
            else:
                results["returns_exported"] = res_returns.get("count", 0)
                logger.info(f"✅ {results['returns_exported']} retours exportés")
        
        # Exporter les dettes
        if results["subscription_active"] and is_online:
            res_debts = self.export_debts()
            if "error" in res_debts:
                results["errors"].append(f"Dettes: {res_debts['error']}")
            else:
                results["debts_exported"] = res_debts.get("count", 0)
                logger.info(f"✅ {results['debts_exported']} dettes exportées")
        
        # Sauvegarder le log
        if hasattr(self.db, 'save_sync_log'):
            try:
                self.db.save_sync_log(results)
            except Exception as e:
                logger.error(f"Erreur sauvegarde log: {e}")
        
        # Mettre à jour la dernière synchronisation
        try:
            self.auth_service.update_last_sync(datetime.now().isoformat())
        except Exception as e:
            logger.error(f"Erreur mise à jour last_sync: {e}")
        
        logger.info(f"=== FIN SYNCHRONISATION - Produits: {results['products_imported']}, Ventes: {results['sales_exported']} ===")
        
        return results
    
    def sync_all_with_stock_update(self) -> Dict:
        """
        Synchronisation complète qui récupère le stock serveur et met à jour le stock local
        """
        logger.info("=== DÉBUT SYNCHRONISATION AVEC MISE À JOUR STOCK ===")
        
        is_online = self.check_internet_connection()
        
        results = {
            "products_updated": 0,
            "sales_exported": 0,
            "stock_updates": [],
            "errors": [],
            "success": True,
            "sync_date": datetime.now().isoformat()
        }
        
        if not is_online:
            results["errors"].append("Mode hors ligne - synchronisation impossible")
            results["success"] = False
            return results
        
        try:
            # 1. Récupérer tous les produits non synchronisés
            unsynced_products = self._get_unsynced_products()
            
            # 2. Pour chaque produit, récupérer le stock serveur
            for product in unsynced_products:
                server_stock = self._get_server_product_stock(product.server_id)
                if server_stock:
                    self.db.update_local_stock(
                        product.server_id,
                        server_stock['quantity'],
                        server_stock['version']
                    )
                    results["products_updated"] += 1
                    results["stock_updates"].append({
                        "product_id": product.server_id,
                        "product_name": product.name,
                        "old_stock": product.quantity,
                        "new_stock": server_stock['quantity']
                    })
            
            # 3. Exporter les ventes avec le stock serveur
            sales_result = self.export_sales_with_server_stock()
            results["sales_exported"] = sales_result.get("count", 0)
            
            if sales_result.get("partial_sales"):
                results["partial_sales"] = sales_result.get("partial_sales")
            if sales_result.get("rejected_sales"):
                results["rejected_sales"] = sales_result.get("rejected_sales")
            
            logger.info(f"✅ Synchronisation terminée: {results['products_updated']} produits mis à jour, "
                    f"{results['sales_exported']} ventes exportées")
            
            return results
            
        except Exception as e:
            logger.error(f"Erreur sync_all_with_stock_update: {e}")
            results["errors"].append(str(e))
            results["success"] = False
            return results
    
    def _get_unsynced_products(self) -> List:
        """Récupère les produits qui n'ont pas été synchronisés récemment"""
        try:
            # Produits non synchronisés depuis plus de 1 heure
            one_hour_ago = (datetime.now() - timedelta(hours=1)).isoformat()
            
            query = """
                SELECT * FROM products 
                WHERE is_deleted = 0 
                AND (last_sync_at IS NULL OR last_sync_at < ?)
                LIMIT 100
            """
            # Cette requête dépend de votre db_manager
            return self.db.get_products_unsynced(one_hour_ago)
        except Exception as e:
            logger.error(f"Erreur _get_unsynced_products: {e}")
            return []
    
    def _get_server_product_stock(self, product_id: str) -> Optional[Dict]:
        """
        Récupère le stock d'un produit depuis le serveur.
        Utilise l'endpoint /stock/{product_id}
        """
        if not self._ensure_online(f"récupération stock produit {product_id}"):
            return None
        
        try:
            headers = self._get_headers()
            if not headers:
                return None
            
            # Endpoint correct: /stock/{product_id}
            endpoint = f"{self.api_url}/stock/{product_id}"
            
            logger.debug(f"Récupération du stock pour {product_id} via {endpoint}")
            
            response = self.session.get(
                endpoint,
                headers=headers,
                timeout=30
            )
            
            if response.status_code == 200:
                data = response.json()
                
                # Extraire les informations de stock
                if isinstance(data, dict):
                    quantity = data.get('quantity', data.get('stock', 0))
                    
                    return {
                        "quantity": quantity,
                        "version": data.get('stock_version', 1),
                        "name": data.get('name', 'Inconnu'),
                        "server_id": product_id,
                        "selling_price": data.get('selling_price', 0),
                        "purchase_price": data.get('purchase_price', 0),
                        "code": data.get('code', ''),
                        "barcode": data.get('barcode', ''),
                        "available_quantity": data.get('available_quantity', 0)
                    }
                elif isinstance(data, list) and len(data) > 0:
                    p = data[0]
                    return {
                        "quantity": p.get('quantity', p.get('stock', 0)),
                        "version": p.get('stock_version', 1),
                        "name": p.get('name', 'Inconnu'),
                        "server_id": product_id
                    }
            
            logger.warning(f"Produit {product_id} non trouvé sur le serveur: HTTP {response.status_code}")
            return None
            
        except Exception as e:
            logger.error(f"Erreur _get_server_product_stock pour {product_id}: {e}")
            return None
    
    def _get_server_stocks_batch(self, product_ids: List[str]) -> Dict[str, Dict]:
        """
        Récupère les stocks de plusieurs produits en une seule requête.
        Utilise l'endpoint /stock avec paramètres.
        """
        if not product_ids:
            return {}
        
        try:
            headers = self._get_headers()
            if not headers:
                return {}
            
            # Essayer d'abord de récupérer tous les produits et filtrer
            # (certains serveurs supportent ?ids=id1,id2)
            ids_param = ','.join(product_ids)
            
            response = self.session.get(
                f"{self.api_url}/stock",
                headers=headers,
                params={"ids": ids_param, "limit": len(product_ids), "get_all": True},
                timeout=60
            )
            
            if response.status_code == 200:
                data = response.json()
                # Gérer différents formats de réponse
                if isinstance(data, dict):
                    products = data.get('products', data.get('data', data.get('items', [])))
                else:
                    products = data if isinstance(data, list) else []
                
                result = {}
                for p in products:
                    pid = str(p.get('id', ''))
                    if pid in product_ids:
                        result[pid] = {
                            "quantity": p.get('quantity', p.get('stock', 0)),
                            "version": p.get('stock_version', 1),
                            "name": p.get('name', 'Inconnu'),
                            "server_id": pid,
                            "selling_price": p.get('selling_price', 0),
                            "code": p.get('code', '')
                        }
                
                # Pour les produits non trouvés, essayer individuellement
                missing_ids = [pid for pid in product_ids if pid not in result]
                for pid in missing_ids:
                    stock = self._get_server_product_stock(pid)
                    if stock:
                        result[pid] = stock
                
                return result
            
            # Fallback: récupérer un par un
            logger.warning(f"Batch stock échoué (HTTP {response.status_code}), fallback individuel")
            result = {}
            for pid in product_ids:
                stock = self._get_server_product_stock(pid)
                if stock:
                    result[pid] = stock
            return result
            
        except Exception as e:
            logger.error(f"Erreur _get_server_stocks_batch: {e}")
            # Fallback: récupérer un par un
            result = {}
            for pid in product_ids:
                stock = self._get_server_product_stock(pid)
                if stock:
                    result[pid] = stock
            return result
    
    def export_sales_with_server_stock(self) -> Dict:
        """
        Exporte les ventes en utilisant le stock serveur pour validation
        """
        unsynced_sales = self.db.get_unsynced_sales_with_metadata()
        
        if not unsynced_sales:
            return {"count": 0, "message": "Aucune vente à exporter"}
        
        headers = self._get_headers()
        if not headers:
            return {"error": "Authentification requise", "count": 0}
        
        try:
            user = self.auth_service.get_current_user()
            branch_id = user.get('active_branch_id') or user.get('branch_id')
            
            # Grouper les ventes par produit
            sales_by_product = defaultdict(list)
            for sale in unsynced_sales:
                product_id = sale.get('product_id')
                sales_by_product[product_id].append(sale)
            
            synced_sales = []
            partial_sales = []
            rejected_sales = []
            stock_updates = []
            
            for product_id, sales in sales_by_product.items():
                # Récupérer le stock serveur actuel
                server_stock = self._get_server_product_stock(product_id)
                
                if not server_stock:
                    logger.warning(f"Impossible de récupérer le stock serveur pour {product_id}")
                    continue
                
                current_server_stock = server_stock['quantity']
                server_version = server_stock['version']
                product_name = server_stock.get('name', 'Inconnu')
                
                # Trier les ventes par date (FIFO)
                sales_sorted = sorted(sales, key=lambda x: x.get('sale_date', x.get('created_at', '')))
                
                logger.info(f"📦 Produit {product_name}: stock serveur={current_server_stock}, "
                        f"{len(sales_sorted)} ventes à traiter")
                
                stock_remaining = current_server_stock
                
                for sale in sales_sorted:
                    requested_qty = sale.get('quantity', 1)
                    sale_id = sale.get('id')
                    stock_at_sale = sale.get('stock_quantity_at_sale', 0)
                    
                    if stock_remaining >= requested_qty:
                        # Acceptation complète
                        stock_remaining -= requested_qty
                        synced_sales.append({
                            "original_id": sale_id,
                            "product_id": product_id,
                            "product_name": product_name,
                            "quantity": requested_qty,
                            "accepted": requested_qty,
                            "rejected": 0,
                            "status": "full"
                        })
                        logger.info(f"✅ Vente {sale_id}: {requested_qty} unités acceptées")
                        
                    elif stock_remaining > 0:
                        # Acceptation partielle
                        accepted_qty = stock_remaining
                        rejected_qty = requested_qty - accepted_qty
                        
                        partial_sales.append({
                            "original_id": sale_id,
                            "product_id": product_id,
                            "product_name": product_name,
                            "requested_quantity": requested_qty,
                            "accepted_quantity": accepted_qty,
                            "rejected_quantity": rejected_qty,
                            "reason": f"Stock insuffisant sur le serveur. {accepted_qty}/{requested_qty} unités acceptées. "
                                    f"Stock serveur: {current_server_stock}, Stock lors de la vente: {stock_at_sale}",
                            "server_stock": current_server_stock,
                            "local_stock": stock_at_sale,
                            "status": "partial"
                        })
                        stock_remaining = 0
                        logger.warning(f"⚠️ Vente partielle {sale_id}: {accepted_qty}/{requested_qty}")
                        
                    else:
                        # Rejet complet
                        rejected_sales.append({
                            "original_id": sale_id,
                            "product_id": product_id,
                            "product_name": product_name,
                            "requested_quantity": requested_qty,
                            "reason": f"Stock épuisé sur le serveur. Stock serveur: {current_server_stock}, "
                                    f"Stock lors de la vente: {stock_at_sale}",
                            "server_stock": current_server_stock,
                            "local_stock": stock_at_sale,
                            "status": "rejected"
                        })
                        logger.error(f"❌ Vente rejetée {sale_id}: stock épuisé")
                
                # Mettre à jour le stock local avec le stock serveur restant
                stock_updates.append({
                    "product_id": product_id,
                    "product_name": product_name,
                    "new_quantity": stock_remaining,
                    "old_quantity": current_server_stock,
                    "sold_quantity": current_server_stock - stock_remaining,
                    "sync_version": server_version + 1
                })
                
                # Mettre à jour le stock local
                self.db.update_local_stock(product_id, stock_remaining, server_version + 1)
            
            # Envoyer les ventes acceptées au serveur
            self._send_sales_to_server(synced_sales, partial_sales, headers, branch_id)
            
            # Marquer les ventes comme synchronisées
            self._mark_sales_synced(synced_sales, partial_sales, rejected_sales)
            
            return {
                "success": True,
                "count": len(synced_sales),
                "partial_sales": partial_sales,
                "rejected_sales": rejected_sales,
                "stock_updates": stock_updates,
                "total_attempted": len(unsynced_sales)
            }
            
        except Exception as e:
            logger.error(f"Erreur export_sales_with_server_stock: {e}", exc_info=True)
            return {"error": str(e), "count": 0, "success": False}
    
    def _mark_sales_synced(self, synced_sales: List[Dict], partial_sales: List[Dict], 
                       rejected_sales: List[Dict]) -> None:
        """Marque les ventes comme synchronisées dans la base locale"""
        try:
            # Ventes complètes
            synced_ids = [s["original_id"] for s in synced_sales]
            if synced_ids:
                self.db.mark_sales_synced(synced_ids)
            
            # Ventes partielles
            for sale in partial_sales:
                self.db.update_sale_quantity(
                    sale["original_id"],
                    sale["accepted_quantity"],
                    sale["rejected_quantity"],
                    sale["reason"]
                )
            
            # Ventes rejetées
            for sale in rejected_sales:
                self.db.mark_sale_rejected(sale["original_id"], sale["reason"])
            
            logger.info(f"✅ {len(synced_ids)} ventes marquées synchronisées")
            
        except Exception as e:
            logger.error(f"Erreur _mark_sales_synced: {e}")
    
    def _send_sales_to_server(self, synced_sales: List[Dict], partial_sales: List[Dict], 
                          headers: Dict, branch_id: str) -> bool:
        """Envoie les ventes au serveur"""
        if not synced_sales and not partial_sales:
            return True
        
        sales_to_send = []
        
        for sale in synced_sales:
            sales_to_send.append({
                "original_id": sale["original_id"],
                "product_id": sale["product_id"],
                "quantity": sale["accepted"],
                "status": "full"
            })
        
        for sale in partial_sales:
            sales_to_send.append({
                "original_id": sale["original_id"],
                "product_id": sale["product_id"],
                "quantity": sale["accepted_quantity"],
                "status": "partial",
                "rejected_quantity": sale["rejected_quantity"],
                "reason": sale["reason"]
            })
        
        try:
            response = self.session.post(
                f"{self.api_url}/sales/batch",
                headers=headers,
                json={
                    "sales": sales_to_send,
                    "branch_id": branch_id,
                    "sync_mode": "stock_update"
                },
                timeout=60
            )
            
            return response.status_code in [200, 201]
            
        except Exception as e:
            logger.error(f"Erreur envoi au serveur: {e}")
            return False
    
   

    def get_next_invoice_number_from_server(self, max_retries: int = 2) -> Optional[str]:
        """
        [DEPRECATED] Cette fonction n'est plus nécessaire.
        Le serveur génère automatiquement les numéros de facture via trigger PostgreSQL.
        Gardée pour compatibilité mais ne fait rien.
        """
        logger.warning("get_next_invoice_number_from_server est déprécié. Le serveur génère automatiquement les numéros.")
        return None

    def confirm_invoice_number_on_server(self, invoice_number: str, pharmacy_id: str = None) -> bool:
        """
        [DEPRECATED] Cette fonction n'est plus nécessaire.
        Gardée pour compatibilité.
        """
        if invoice_number and invoice_number.startswith("LOCAL-"):
            logger.info(f"Numéro local, pas de confirmation serveur: {invoice_number}")
            return True
        
        logger.info(f"Numéro {invoice_number} - Confirmation non nécessaire (trigger auto)")
        return True
        
    def export_expenses(self) -> Dict:
        """
        Exporte les dépenses non synchronisées vers le serveur
        """
        if not hasattr(self.db, 'get_unsynced_expenses'):
            logger.warning("get_unsynced_expenses non disponible")
            return {"count": 0, "warning": "get_unsynced_expenses non disponible"}
        
        unsynced_expenses = self.db.get_unsynced_expenses()
        if not unsynced_expenses:
            logger.info("Aucune dépense à exporter")
            return {"count": 0, "message": "Aucune dépense à exporter"}
        
        headers = self._get_headers()
        if not headers:
            return {"error": "Authentification requise pour l'export", "count": 0, "success": False}
        
        # Types de dépense acceptés par le serveur (basé sur le modèle backend)
        VALID_EXPENSE_TYPES = {
            'salary', 'rent', 'utilities', 'transport', 'marketing', 'maintenance',
            'taxes', 'insurance', 'software', 'equipment', 'stock_purchase',
            'training', 'consulting', 'other'
        }
        
        try:
            user = self.auth_service.get_current_user()
            branch_id = user.get('active_branch_id') or user.get('branch_id')
            
            synced_ids = []
            errors = []
            fixed_expenses = []
            
            # ✅ Envoyer une par une (pas en batch)
            for expense in unsynced_expenses:
                try:
                    # 1. Valider la date
                    expense_date = expense.get('expense_date')
                    if expense_date:
                        # S'assurer que la date est au format ISO (YYYY-MM-DD)
                        if isinstance(expense_date, str):
                            if 'T' in expense_date:
                                expense_date = expense_date.split('T')[0]
                            elif '/' in expense_date:
                                # Format DD/MM/YYYY -> YYYY-MM-DD
                                try:
                                    parts = expense_date.split('/')
                                    if len(parts) == 3:
                                        expense_date = f"{parts[2]}-{parts[1]}-{parts[0]}"
                                except:
                                    pass
                        else:
                            expense_date = datetime.now().date().isoformat()
                    else:
                        expense_date = datetime.now().date().isoformat()
                    
                    # 2. Convertir la catégorie en expense_type valide
                    category = expense.get('category', expense.get('expense_type', 'other'))
                    category_lower = str(category).lower().strip()
                    
                    # Mapping des catégories vers les types acceptés par le serveur
                    type_mapping = {
                        'salaire': 'salary',
                        'loyer': 'rent',
                        'electricite': 'utilities',
                        'électricité': 'utilities',
                        'eau': 'utilities',
                        'internet': 'utilities',
                        'telephone': 'utilities',
                        'transport': 'transport',
                        'marketing': 'marketing',
                        'publicite': 'marketing',
                        'maintenance': 'maintenance',
                        'reparation': 'maintenance',
                        'impots': 'taxes',
                        'taxe': 'taxes',
                        'assurance': 'insurance',
                        'logiciel': 'software',
                        'abonnement': 'software',
                        'materiel': 'equipment',
                        'achat stock': 'stock_purchase',
                        'stock': 'stock_purchase',
                        'formation': 'training',
                        'consultant': 'consulting',
                        'frais bancaire': 'other',
                        'frais_bancaire': 'other',
                        'divers': 'other',
                        'autre': 'other',
                    }
                    
                    expense_type = type_mapping.get(category_lower, 'other')
                    
                    # 3. Préparer les données selon le schéma ExpenseCreate
                    # Le backend attend: expense_type (obligatoire), amount, description, expense_date
                    expense_payload = {
                        "expense_type": expense_type,  # 🔑 Champ OBLIGATOIRE
                        "amount": self._safe_float(expense.get('amount', 0)),
                        "description": self._safe_str(expense.get('description', '')),
                        "expense_date": expense_date,
                        "branch_id": branch_id,
                        "payment_method": "cash",
                        "status": "pending",
                    }
                    
                    # Ajouter les champs optionnels s'ils existent
                    notes = expense.get('notes', '')
                    if notes:
                        expense_payload["notes"] = str(notes)[:500]
                    
                    supplier = expense.get('supplier', '')
                    if supplier:
                        expense_payload["supplier"] = str(supplier)[:200]
                    
                    # Nettoyer: enlever les clés avec valeurs None
                    expense_payload = {k: v for k, v in expense_payload.items() if v is not None}
                    
                    logger.info(f"📤 Envoi dépense: type={expense_type}, amount={expense_payload['amount']}, date={expense_date}")
                    
                    # ✅ Envoi unique à l'endpoint /expenses (pas /expenses/ avec slash final)
                    response = self.session.post(
                        f"{self.api_url}/expenses",
                        headers=headers,
                        json=expense_payload,
                        timeout=30
                    )
                    
                    logger.info(f"Réponse serveur: status={response.status_code}")
                    
                    if response.status_code in [200, 201]:
                        # Succès
                        synced_ids.append(expense.get('id'))
                        data = response.json()
                        logger.info(f"✅ Dépense exportée: ID serveur={data.get('id')}")
                        
                    elif response.status_code == 422:
                        # Erreur de validation - log détaillée
                        error_detail = response.text
                        try:
                            error_json = response.json()
                            error_detail = error_json.get('detail', error_detail)
                        except:
                            pass
                        
                        logger.error(f"❌ Erreur 422 pour dépense {expense.get('id')}: {error_detail}")
                        
                        # Correction supplémentaire: essayer avec expense_type='other'
                        if expense_type != 'other':
                            logger.info(f"Tentative avec expense_type='other'")
                            expense_payload['expense_type'] = 'other'
                            
                            response2 = self.session.post(
                                f"{self.api_url}/expenses",
                                headers=headers,
                                json=expense_payload,
                                timeout=30
                            )
                            
                            if response2.status_code in [200, 201]:
                                synced_ids.append(expense.get('id'))
                                logger.info(f"✅ Dépense exportée avec type 'other'")
                            else:
                                errors.append({
                                    'id': expense.get('id'),
                                    'error': f"422: {error_detail[:200]}"
                                })
                        else:
                            errors.append({
                                'id': expense.get('id'),
                                'error': f"422: {error_detail[:200]}"
                            })
                            
                    elif response.status_code == 401:
                        logger.error("Token expiré ou invalide")
                        return {"error": "Token expiré, veuillez vous reconnecter", "count": 0, "success": False}
                    else:
                        error_text = response.text[:300]
                        logger.error(f"❌ Erreur HTTP {response.status_code}: {error_text}")
                        errors.append({
                            'id': expense.get('id'),
                            'error': f"HTTP {response.status_code}: {error_text}"
                        })
                        
                except Exception as e:
                    logger.error(f"❌ Erreur envoi dépense {expense.get('id')}: {str(e)}")
                    errors.append({
                        'id': expense.get('id'),
                        'error': str(e)
                    })
            
            # Marquer les dépenses synchronisées
            if synced_ids and hasattr(self.db, 'mark_expenses_synced'):
                self.db.mark_expenses_synced(synced_ids)
            
            logger.info(f"✅ Export terminé: {len(synced_ids)} succès, {len(errors)} erreurs")
            
            return {
                "count": len(synced_ids),
                "success": len(errors) == 0,
                "synced_ids": synced_ids,
                "errors": errors,
                "fixed": fixed_expenses,
                "total_attempted": len(unsynced_expenses)
            }
                
        except Exception as e:
            logger.error(f"Erreur export dépenses: {str(e)}", exc_info=True)
            return {"error": str(e), "count": 0, "success": False}


    def _export_expense_individual(self, expense: Dict, headers: Dict, branch_id: str) -> Dict:
        """
        Exporte une dépense individuellement (fallback ultime)
        """
        try:
            response = self.session.post(
                f"{self.api_url}/expenses",
                headers=headers,
                json=expense,
                timeout=30
            )
            
            if response.status_code in [200, 201]:
                return {"success": True}
            else:
                error_msg = response.text[:200]
                try:
                    error_json = response.json()
                    error_msg = error_json.get('detail', error_msg)
                except:
                    pass
                return {"success": False, "error": error_msg}
                
        except Exception as e:
            return {"success": False, "error": str(e)}


    def _validate_expense_date(self, date_str: str) -> tuple:
        """
        Valide et corrige une date de dépense
        
        Returns:
            (is_valid, corrected_date, error_message)
        """
        if not date_str:
            today = datetime.now().date().isoformat()
            return True, today, "Date manquante, remplacée par la date du jour"
        
        try:
            if 'T' in date_str:
                expense_date = datetime.fromisoformat(date_str.split('T')[0])
            else:
                expense_date = datetime.fromisoformat(date_str)
            
            today = datetime.now()
            today_date = today.date()
            expense_date_obj = expense_date.date() if hasattr(expense_date, 'date') else expense_date
            
            # Vérifier si la date est dans le futur
            if expense_date_obj > today_date:
                corrected = today_date.isoformat()
                return True, corrected, f"Date dans le futur ({date_str}), remplacée par la date du jour"
            
            # Date valide
            return True, date_str, None
            
        except Exception as e:
            today = datetime.now().date().isoformat()
            return True, today, f"Format de date invalide ({date_str}), remplacée par la date du jour"


    def _validate_date(self, date_str: str) -> Optional[str]:
        """Valide une date générique"""
        if not date_str:
            return None
        
        try:
            if 'T' in date_str:
                parsed = datetime.fromisoformat(date_str.split('T')[0])
            else:
                parsed = datetime.fromisoformat(date_str)
            
            today = datetime.now().date()
            parsed_date = parsed.date() if hasattr(parsed, 'date') else parsed
            
            if parsed_date > today:
                return today.isoformat()
            
            return date_str
            
        except Exception:
            return None


    def _handle_validation_errors(self, response: requests.Response, expenses: List[Dict], 
                                headers: Dict, branch_id: str) -> Dict:
        """
        Gère les erreurs de validation (422) de manière intelligente
        """
        try:
            data = response.json()
            errors = data.get('detail', [])
            
            # Analyser les erreurs par dépense
            expense_errors = {}
            for error in errors:
                loc = error.get('loc', [])
                if len(loc) >= 3 and loc[1] == 'expenses' and isinstance(loc[2], int):
                    expense_index = loc[2]
                    field = loc[3] if len(loc) > 3 else 'unknown'
                    msg = error.get('msg', '')
                    
                    if expense_index not in expense_errors:
                        expense_errors[expense_index] = {}
                    expense_errors[expense_index][field] = msg
            
            # Corriger les dépenses avec erreurs
            corrected_expenses = []
            for idx, expense in enumerate(expenses):
                if idx in expense_errors:
                    corrected_expense = expense.copy()
                    
                    for field, msg in expense_errors[idx].items():
                        if field == 'expense_date' and 'futur' in msg:
                            # Corriger la date
                            corrected_expense['expense_date'] = datetime.now().date().isoformat()
                            logger.info(f"Correction date pour dépense {expense.get('local_id')}")
                        elif field == 'amount' and 'negative' in msg:
                            # Montant négatif, prendre l'absolu
                            corrected_expense['amount'] = abs(corrected_expense.get('amount', 0))
                            corrected_expense['total_amount'] = abs(corrected_expense.get('total_amount', 0))
                            logger.info(f"Correction montant pour dépense {expense.get('local_id')}")
                    
                    corrected_expenses.append(corrected_expense)
                else:
                    corrected_expenses.append(expense)
            
            # Réessayer l'envoi avec les données corrigées
            logger.info(f"Réessai d'export avec {len(corrected_expenses)} dépenses corrigées")
            
            response = self.session.post(
                f"{self.api_url}/expenses/",
                headers=headers,
                json={
                    "expenses": corrected_expenses,
                    "branch_id": branch_id,
                    "batch_id": str(uuid.uuid4()),
                    "action": "sync",
                    "retry_after_validation": True
                },
                timeout=90
            )
            
            if response.status_code == 200:
                data = response.json()
                synced_local_ids = data.get('synced_local_ids', [])
                
                if synced_local_ids and hasattr(self.db, 'mark_expenses_synced'):
                    self.db.mark_expenses_synced(synced_local_ids)
                
                return {
                    "count": len(synced_local_ids),
                    "success": True,
                    "synced_ids": synced_local_ids,
                    "validation_fixed": True
                }
            else:
                # Si toujours en erreur, passer à l'export individuel
                return self._export_expenses_individual(corrected_expenses, headers, branch_id)
                
        except Exception as e:
            logger.error(f"Erreur _handle_validation_errors: {e}")
            return self._export_expenses_individual(expenses, headers, branch_id)


    def _export_expenses_individual(self, expenses: List[Dict], headers: Dict, branch_id: str) -> Dict:
        """
        Exporte les dépenses une par une (fallback)
        Utilisé quand le batch échoue
        """
        synced_ids = []
        errors = []
        
        for expense in expenses:
            try:
                cleaned_expense = {
                    'expense_date': expense.get('expense_date'),
                    'expense_type': expense.get('expense_type', 'other'),
                    'amount': self._safe_float(expense.get('amount', 0)),
                    'tax_amount': self._safe_float(expense.get('tax_amount', 0)),
                    'total_amount': self._safe_float(expense.get('total_amount', expense.get('amount', 0))),
                    'supplier': self._safe_str(expense.get('supplier', '')),
                    'payee': self._safe_str(expense.get('payee', '')),
                    'payment_method': expense.get('payment_method', 'cash'),
                    'payment_reference': self._safe_str(expense.get('payment_reference', '')),
                    'description': self._safe_str(expense.get('description', '')),
                    'notes': self._safe_str(expense.get('notes', '')),
                    'invoice_number': self._safe_str(expense.get('invoice_number', '')),
                    'invoice_date': expense.get('invoice_date'),
                    'branch_id': branch_id or expense.get('branch_id'),
                    'cost_center': self._safe_str(expense.get('cost_center', '')),
                    'approval_status': expense.get('approval_status', 'pending'),
                }
                
                # Supprimer les champs None
                cleaned_expense = {k: v for k, v in cleaned_expense.items() if v is not None}
                
                response = self.session.post(
                    f"{self.api_url}/expenses",
                    headers=headers,
                    json=cleaned_expense,
                    timeout=30
                )
                
                if response.status_code in [200, 201]:
                    synced_ids.append(expense.get('id'))
                    logger.debug(f"✅ Dépense {expense.get('id')} synchronisée")
                else:
                    error_detail = response.text[:200]
                    try:
                        error_json = response.json()
                        error_detail = error_json.get('detail', error_detail)
                    except:
                        pass
                        
                    errors.append({
                        "id": expense.get('id'),
                        "status": response.status_code,
                        "error": error_detail
                    })
                    logger.error(f"❌ Erreur sync dépense {expense.get('id')}: {response.status_code}")
                    
            except Exception as e:
                errors.append({"id": expense.get('id'), "error": str(e)})
                logger.error(f"❌ Erreur dépense {expense.get('id')}: {str(e)}")
        
        # Marquer les dépenses synchronisées
        if synced_ids and hasattr(self.db, 'mark_expenses_synced'):
            self.db.mark_expenses_synced(synced_ids)
        
        return {
            "count": len(synced_ids),
            "success": len(errors) == 0,
            "synced_ids": synced_ids,
            "errors": errors,
            "total_attempted": len(expenses)
        }


    def _export_expenses_chunked(self, expenses: List[Dict], headers: Dict, branch_id: str, chunk_size: int = 10) -> Dict:
        """
        Exporte les dépenses par lots de taille définie
        
        Args:
            expenses: Liste des dépenses à exporter
            headers: Headers HTTP
            branch_id: ID de la branche
            chunk_size: Taille des lots
        """
        total_synced = 0
        all_errors = []
        all_synced_ids = []
        
        # Diviser en lots
        chunks = [expenses[i:i + chunk_size] for i in range(0, len(expenses), chunk_size)]
        
        logger.info(f"📦 Export de {len(expenses)} dépenses en {len(chunks)} lots de {chunk_size}")
        
        for i, chunk in enumerate(chunks):
            logger.info(f"Lot {i+1}/{len(chunks)}: {len(chunk)} dépenses")
            
            cleaned_chunk = []
            for expense in chunk:
                cleaned_expense = {
                    'local_id': expense.get('id'),
                    'expense_date': expense.get('expense_date'),
                    'expense_type': expense.get('expense_type', 'other'),
                    'amount': self._safe_float(expense.get('amount', 0)),
                    'tax_amount': self._safe_float(expense.get('tax_amount', 0)),
                    'total_amount': self._safe_float(expense.get('total_amount', expense.get('amount', 0))),
                    'supplier': self._safe_str(expense.get('supplier', '')),
                    'payee': self._safe_str(expense.get('payee', '')),
                    'payment_method': expense.get('payment_method', 'cash'),
                    'description': self._safe_str(expense.get('description', '')),
                    'notes': self._safe_str(expense.get('notes', '')),
                    'invoice_number': self._safe_str(expense.get('invoice_number', '')),
                    'branch_id': branch_id or expense.get('branch_id'),
                    'cost_center': self._safe_str(expense.get('cost_center', '')),
                    'approval_status': expense.get('approval_status', 'pending'),
                }
                cleaned_expense = {k: v for k, v in cleaned_expense.items() if v is not None}
                cleaned_chunk.append(cleaned_expense)
            
            try:
                payload = {
                    "expenses": cleaned_chunk,
                    "branch_id": branch_id,
                    "chunk_index": i,
                    "total_chunks": len(chunks),
                    "batch_id": str(uuid.uuid4())
                }
                
                response = self.session.post(
                    f"{self.api_url}/expenses/",
                    headers=headers,
                    json=payload,
                    timeout=60
                )
                
                if response.status_code == 200:
                    data = response.json()
                    synced_local_ids = data.get('synced_local_ids', [])
                    errors = data.get('errors', [])
                    
                    all_synced_ids.extend(synced_local_ids)
                    all_errors.extend(errors)
                    total_synced += len(synced_local_ids)
                    
                    logger.info(f"✅ Lot {i+1}: {len(synced_local_ids)} dépenses synchronisées")
                else:
                    logger.error(f"❌ Lot {i+1} échoué: {response.status_code}")
                    all_errors.append({
                        "chunk": i,
                        "status": response.status_code,
                        "error": response.text[:200]
                    })
                    
            except Exception as e:
                logger.error(f"❌ Lot {i+1} erreur: {e}")
                all_errors.append({"chunk": i, "error": str(e)})
        
        # Marquer les dépenses synchronisées
        if all_synced_ids and hasattr(self.db, 'mark_expenses_synced'):
            self.db.mark_expenses_synced(all_synced_ids)
        
        return {
            "count": total_synced,
            "success": len(all_errors) == 0,
            "synced_ids": all_synced_ids,
            "errors": all_errors,
            "total_attempted": len(expenses),
            "chunks_processed": len(chunks)
        }


    def _apply_expense_conflict_resolution(self, conflicts: List[Dict]) -> None:
        """
        Applique la résolution des conflits pour les dépenses
        
        Args:
            conflicts: Liste des conflits détectés par le serveur
        """
        try:
            for conflict in conflicts:
                local_id = conflict.get('local_id')
                server_expense = conflict.get('server_expense', {})
                resolution = conflict.get('resolution', 'server_wins')
                
                if resolution == 'server_wins':
                    # Mettre à jour la dépense locale avec les données du serveur
                    if hasattr(self.db, 'update_expense_from_server'):
                        self.db.update_expense_from_server(local_id, server_expense)
                        logger.info(f"Dépense {local_id} mise à jour depuis le serveur (conflit résolu)")
                        
                elif resolution == 'merge':
                    # Fusionner les données
                    merged = self._merge_expense_data(conflict.get('local_expense', {}), server_expense)
                    if hasattr(self.db, 'update_expense'):
                        self.db.update_expense(local_id, **merged)
                        logger.info(f"Dépense {local_id} fusionnée avec les données serveur")
                
                elif resolution == 'local_wins':
                    # Garder les données locales, marquer comme à re-synchroniser
                    logger.info(f"Dépense {local_id}: conservation des données locales")
                    
                # Enregistrer le feedback utilisateur
                self._save_sync_feedback({
                    'type': 'expense_conflict',
                    'expense_id': local_id,
                    'message': f"Conflit de dépense résolu: {resolution}",
                    'details': conflict
                })
                
        except Exception as e:
            logger.error(f"Erreur _apply_expense_conflict_resolution: {e}")


    def _merge_expense_data(self, local_expense: Dict, server_expense: Dict) -> Dict:
        """
        Fusionne les données d'une dépense locale et serveur
        
        Args:
            local_expense: Données locales
            server_expense: Données du serveur
        
        Returns:
            Données fusionnées
        """
        merged = {}
        
        # Description: prendre la plus complète
        local_desc = local_expense.get('description', '')
        server_desc = server_expense.get('description', '')
        if local_desc and server_desc:
            merged['description'] = f"{local_desc}\n---\n{server_desc}" if local_desc != server_desc else local_desc
        else:
            merged['description'] = local_desc or server_desc
        
        # Montant: prendre le plus élevé (plus prudent pour les dépenses)
        local_amount = local_expense.get('amount', 0)
        server_amount = server_expense.get('amount', 0)
        merged['amount'] = max(local_amount, server_amount)
        
        # TVA: prendre la plus élevée
        local_tax = local_expense.get('tax_amount', 0)
        server_tax = server_expense.get('tax_amount', 0)
        merged['tax_amount'] = max(local_tax, server_tax)
        
        # Total = somme si différent
        if local_amount != server_amount:
            merged['total_amount'] = max(local_amount + local_tax, server_amount + server_tax)
        else:
            merged['total_amount'] = local_amount + local_tax
        
        # Date: prendre la plus récente
        local_date = local_expense.get('expense_date')
        server_date = server_expense.get('expense_date')
        if local_date and server_date:
            merged['expense_date'] = max(local_date, server_date)
        else:
            merged['expense_date'] = local_date or server_date
        
        # Type: priorité au serveur
        merged['expense_type'] = server_expense.get('expense_type', local_expense.get('expense_type', 'other'))
        
        # Fournisseur: prendre celui du serveur s'il existe
        merged['supplier'] = server_expense.get('supplier') or local_expense.get('supplier', '')
        
        # Notes fusionnées
        local_notes = local_expense.get('notes', '')
        server_notes = server_expense.get('notes', '')
        if local_notes and server_notes:
            merged['notes'] = f"{local_notes}\n---\n{server_notes}"
        else:
            merged['notes'] = local_notes or server_notes
        
        # Statut d'approbation: priorité au serveur
        merged['approval_status'] = server_expense.get('approval_status', local_expense.get('approval_status', 'pending'))
        
        merged['updated_at'] = datetime.now().isoformat()
        merged['is_synced'] = True
        
        return merged


    def _handle_expense_conflict(self, response: requests.Response, unsynced_expenses: List[Dict], 
                                headers: Dict, branch_id: str) -> Dict:
        """
        Gère les conflits de version lors de l'export des dépenses
        """
        try:
            data = response.json()
            server_expenses = data.get('server_expenses', [])
            local_conflicts = data.get('local_conflicts', [])
            
            # Récupérer les dépenses du serveur pour mise à jour locale
            if server_expenses:
                # Mettre à jour les dépenses locales avec les versions serveur
                for server_expense in server_expenses:
                    if hasattr(self.db, 'update_expense_from_server'):
                        self.db.update_expense_from_server(server_expense.get('local_id'), server_expense)
                logger.info(f"📥 {len(server_expenses)} dépenses mises à jour depuis le serveur")
            
            # Réessayer l'export des dépenses non conflictuelles
            non_conflict_expenses = [d for d in unsynced_expenses if d.get('id') not in local_conflicts]
            
            if non_conflict_expenses:
                logger.info(f"Réessai d'export de {len(non_conflict_expenses)} dépenses après conflit")
                return self._export_expenses_batch(non_conflict_expenses, headers, branch_id)
            
            return {
                "count": 0,
                "success": True,
                "message": "Conflits détectés - Synchronisation des dépenses serveur effectuée",
                "conflicts_resolved": True,
                "server_expenses_synced": len(server_expenses)
            }
            
        except Exception as e:
            logger.error(f"Erreur _handle_expense_conflict: {e}")
            return {"error": str(e), "count": 0, "success": False}


    def _export_expenses_batch(self, expenses: List[Dict], headers: Dict, branch_id: str) -> Dict:
        """
        Exporte un batch spécifique de dépenses
        """
        if not expenses:
            return {"count": 0, "success": True}
        
        try:
            user = self.auth_service.get_current_user()
            
            cleaned_expenses = []
            for expense in expenses:
                cleaned_expense = {
                    'local_id': expense.get('id'),
                    'expense_date': expense.get('expense_date'),
                    'expense_type': expense.get('expense_type', 'other'),
                    'amount': self._safe_float(expense.get('amount', 0)),
                    'tax_amount': self._safe_float(expense.get('tax_amount', 0)),
                    'total_amount': self._safe_float(expense.get('total_amount', expense.get('amount', 0))),
                    'supplier': self._safe_str(expense.get('supplier', '')),
                    'payee': self._safe_str(expense.get('payee', '')),
                    'payment_method': expense.get('payment_method', 'cash'),
                    'description': self._safe_str(expense.get('description', '')),
                    'notes': self._safe_str(expense.get('notes', '')),
                    'invoice_number': self._safe_str(expense.get('invoice_number', '')),
                    'branch_id': branch_id,
                    'cost_center': self._safe_str(expense.get('cost_center', '')),
                    'approval_status': expense.get('approval_status', 'pending'),
                }
                cleaned_expense = {k: v for k, v in cleaned_expense.items() if v is not None}
                cleaned_expenses.append(cleaned_expense)
            
            payload = {
                "expenses": cleaned_expenses,
                "branch_id": branch_id,
                "batch_id": str(uuid.uuid4()),
                "action": "sync"
            }
            
            response = self.session.post(
                f"{self.api_url}/expenses/",
                headers=headers,
                json=payload,
                timeout=60
            )
            
            if response.status_code == 200:
                data = response.json()
                synced_local_ids = data.get('synced_local_ids', [])
                
                if synced_local_ids and hasattr(self.db, 'mark_expenses_synced'):
                    self.db.mark_expenses_synced(synced_local_ids)
                
                return {
                    "count": len(synced_local_ids),
                    "success": True,
                    "synced_ids": synced_local_ids
                }
            else:
                return {"count": 0, "success": False, "error": f"Status {response.status_code}"}
                
        except Exception as e:
            logger.error(f"Erreur _export_expenses_batch: {e}")
            return {"error": str(e), "count": 0, "success": False}


    def get_unsynced_expenses_count(self) -> int:
        """
        Récupère le nombre de dépenses non synchronisées
        
        Returns:
            Nombre de dépenses en attente de synchronisation
        """
        if not hasattr(self.db, 'get_unsynced_expenses'):
            return 0
        
        try:
            unsynced = self.db.get_unsynced_expenses()
            return len(unsynced)
        except Exception as e:
            logger.error(f"Erreur get_unsynced_expenses_count: {e}")
            return 0

    def import_subscription(self, branch_id: str = None) -> Dict:
        """
        Importe les informations d'abonnement depuis le serveur
        """
        user = self.auth_service.get_current_user()
        headers = self._get_headers()
        if not headers:
            return {"error": "Utilisateur non authentifié", "code": 401, "success": False}
        
        try:
            # Déterminer la branche active
            if not branch_id:
                branch_id = self.auth_service.get_user_branch_id()
            
            logger.info(f"Import de l'abonnement - branch_id: {branch_id}")
            
            # Configuration SSL avec plus de tolérance
            import ssl
            from requests.adapters import HTTPAdapter
            from urllib3.poolmanager import PoolManager
            
            class SSLAdapter(HTTPAdapter):
                def init_poolmanager(self, *args, **kwargs):
                    ctx = ssl.create_default_context()
                    ctx.check_hostname = False
                    ctx.verify_mode = ssl.CERT_NONE
                    kwargs['ssl_context'] = ctx
                    return super().init_poolmanager(*args, **kwargs)
            
            # Créer une session avec configuration SSL
            session = requests.Session()
            session.mount('https://', SSLAdapter())
            
            # CORRECTION: Utiliser l'endpoint correct avec le bon format
            params = {}
            if branch_id:
                params["branch_id"] = branch_id
            
            # Essayer d'abord l'endpoint /sync/subscription/status
            response = session.get(
                f"{self.api_url}/sync/subscription/status",
                headers=headers,
                params=params,
                timeout=30,
                verify=False  # Désactiver la vérification SSL temporairement
            )
            
            # Si 403, essayer l'endpoint /subscriptions/status
            if response.status_code == 403:
                logger.warning("Accès refusé à /sync/subscription/status, tentative avec /subscriptions/status")
                response = session.get(
                    f"{self.api_url}/subscriptions/status",
                    headers=headers,
                    params=params,
                    timeout=30,
                    verify=False
                )
            
            # Si toujours 403 ou erreur SSL, utiliser le cache
            if response.status_code in [403, 500, 502, 503, 504] or response.status_code >= 500:
                logger.warning(f"API subscription status retourne {response.status_code}, fallback cache")
                cached = self.get_cached_subscription(branch_id)
                return {
                    "success": True,
                    "subscription": cached,
                    "is_active": cached.get("is_active", True),
                    "has_subscription": cached.get("has_subscription", True),
                    "days_remaining": cached.get("subscription", {}).get("days_remaining", 30),
                    "cached": True,
                    "warning": f"Erreur serveur {response.status_code}, utilisation du cache"
                }
            
            if response.status_code == 200:
                data = response.json()
                
                # Extraire les informations
                subscription_data = data.get("subscription", {})
                
                subscription_info = {
                    "has_subscription": data.get("has_subscription", True),
                    "is_active": data.get("is_active", True),
                    "access_mode": data.get("access_mode", "full"),
                    "subscription": {
                        "id": subscription_data.get("id"),
                        "branch_id": subscription_data.get("branch_id"),
                        "plan_name": subscription_data.get("plan_name"),
                        "plan_type": subscription_data.get("plan_type"),
                        "status": subscription_data.get("status"),
                        "current_period_start": subscription_data.get("current_period_start"),
                        "current_period_end": subscription_data.get("current_period_end"),
                        "days_remaining": subscription_data.get("days_remaining", 30),
                        "max_products": subscription_data.get("max_products"),
                        "max_users": subscription_data.get("max_users"),
                        "max_storage_mb": subscription_data.get("max_storage_mb"),
                        "is_trial": subscription_data.get("is_trial", False),
                        "trial_days_remaining": subscription_data.get("trial_days_remaining", 0),
                        "auto_renew": subscription_data.get("auto_renew", True),
                        "billing_cycle": subscription_data.get("billing_cycle", "monthly"),
                        "price": subscription_data.get("price", 0),
                        "currency": subscription_data.get("currency", "EUR")
                    },
                    "limits": {
                        "max_products": subscription_data.get("max_products", "Illimité"),
                        "max_users": subscription_data.get("max_users", "Illimité"),
                    },
                    "usage": {
                        "current_products": 0,
                        "current_users": 0,
                    },
                    "synced_at": datetime.now().isoformat()
                }
                
                # Sauvegarder
                self.auth_service.save_subscription_info(subscription_info)
                
                logger.info(f"✅ Abonnement importé - Actif: {subscription_info['is_active']}")
                
                return {
                    "success": True,
                    "subscription": subscription_info,
                    "is_active": subscription_info["is_active"],
                    "has_subscription": subscription_info["has_subscription"],
                    "days_remaining": subscription_data.get("days_remaining", 30),
                    "plan_name": subscription_data.get("plan_name"),
                    "is_trial": subscription_data.get("is_trial", False)
                }
            else:
                # Fallback cache
                cached = self.get_cached_subscription(branch_id)
                return {
                    "success": True,
                    "subscription": cached,
                    "is_active": cached.get("is_active", True),
                    "has_subscription": cached.get("has_subscription", True),
                    "days_remaining": cached.get("subscription", {}).get("days_remaining", 30),
                    "cached": True,
                    "warning": f"API retourne {response.status_code}, utilisation du cache"
                }
                
        except requests.exceptions.SSLError as e:
            logger.error(f"Erreur SSL import_subscription: {e}")
            # En cas d'erreur SSL, utiliser le cache
            cached = self.get_cached_subscription(branch_id)
            return {
                "success": True,
                "subscription": cached,
                "is_active": cached.get("is_active", True),
                "has_subscription": cached.get("has_subscription", True),
                "days_remaining": cached.get("subscription", {}).get("days_remaining", 30),
                "cached": True,
                "warning": f"Erreur SSL, utilisation du cache: {str(e)}"
            }
        except Exception as e:
            logger.error(f"Erreur import_subscription: {e}")
            cached = self.get_cached_subscription(branch_id)
            return {
                "success": True,
                "subscription": cached,
                "is_active": cached.get("is_active", True),
                "has_subscription": cached.get("has_subscription", True),
                "days_remaining": cached.get("subscription", {}).get("days_remaining", 30),
                "cached": True,
                "warning": str(e)
            }
    
    def _get_default_subscription(self) -> Dict:
        """Retourne un abonnement par défaut"""
        return {
            "has_subscription": True,
            "is_active": True,
            "access_mode": "full",
            "subscription": {
                "plan_name": "Standard",
                "plan_type": "professional",
                "status": "active",
                "days_remaining": 30,
                "max_products": 0,
                "max_users": 0,
                "is_unlimited_products": True,
                "is_unlimited_users": True,
            },
            "limits": {
                "max_products": "Illimité",
                "max_users": "Illimité",
                "max_branches": "Illimité",
            },
            "usage": {
                "current_products": 0,
                "current_users": 0,
            },
            "synced_at": datetime.now().isoformat()
        }

    def get_cached_subscription(self, branch_id: str = None) -> Dict:
        """
        Récupère les informations d'abonnement depuis le cache local.
        Utilisé en mode offline.
        """
        try:
            # Utiliser AuthService pour récupérer l'abonnement
            subscription = self.auth_service.get_subscription_info()
            
            # CORRECTION: Vérifier que subscription n'est pas None
            if subscription is None:
                logger.warning("Aucune information d'abonnement en cache")
                return {
                    "has_subscription": False,
                    "is_active": False,
                    "access_mode": "read_only",
                    "cached": False,
                    "message": "Aucune information d'abonnement en cache"
                }
            
            # Vérifier que subscription est un dictionnaire
            if not isinstance(subscription, dict):
                logger.warning(f"Format d'abonnement invalide: {type(subscription)}")
                return {
                    "has_subscription": False,
                    "is_active": False,
                    "access_mode": "read_only",
                    "cached": False,
                    "message": "Format d'abonnement invalide"
                }
            
            # Extraire les informations
            info = subscription.get('info', {})
            if info is None:
                info = {}
            
            end_date = None
            if isinstance(info, dict):
                sub_info = info.get('subscription', {})
                if sub_info is None:
                    sub_info = {}
                end_date = sub_info.get('end_date')
            
            if end_date:
                try:
                    from datetime import datetime
                    end_dt = datetime.fromisoformat(end_date.replace('Z', '+00:00'))
                    if datetime.now(end_dt.tzinfo) > end_dt:
                        if isinstance(info, dict):
                            info['is_active'] = False
                            info['access_mode'] = 'read_only'
                except Exception as e:
                    logger.error(f"Erreur calcul expiration: {e}")
            
            # Retourner un dictionnaire valide
            if isinstance(info, dict):
                return info
            else:
                return {
                    "has_subscription": False,
                    "is_active": False,
                    "access_mode": "read_only",
                    "cached": True,
                    "message": "Données d'abonnement invalides"
                }
            
        except Exception as e:
            logger.error(f"Erreur get_cached_subscription: {e}")
            return {
                "has_subscription": False,
                "is_active": False,
                "access_mode": "read_only",
                "cached": False,
                "error": str(e)
            }
    
    def save_subscription_to_cache(self, subscription_info: Dict):
        """Sauvegarde l'abonnement dans le cache"""
        return self.auth_service.save_subscription_info(subscription_info)

    def check_subscription_access(self, feature: str = None, branch_id: str = None) -> Dict:
        """
        Vérifie si l'utilisateur a accès à une fonctionnalité
        basée sur l'abonnement en cache.
        
        Returns:
            Dict avec les droits d'accès (jamais None)
        """
        subscription = self.get_cached_subscription(branch_id)
        
        # CORRECTION: Vérifier que subscription n'est pas None et a la bonne structure
        if subscription is None or not isinstance(subscription, dict):
            logger.warning("Subscription invalide ou None, utilisation des valeurs par défaut")
            subscription = self._get_default_subscription()
        
        # Extraire les valeurs avec des valeurs par défaut sûres
        is_active = subscription.get("is_active", True)
        has_subscription = subscription.get("has_subscription", True)
        access_mode = subscription.get("access_mode", "full")
        
        # Vérifier les limites
        limits = subscription.get("limits", {})
        if limits is None:
            limits = {}
        
        usage = subscription.get("usage", {})
        if usage is None:
            usage = {}
        
        # Vérifier les dépassements de limites
        products_limit_exceeded = False
        users_limit_exceeded = False
        
        if limits:
            max_products = limits.get("max_products")
            max_users = limits.get("max_users")
            
            if max_products and max_products != "Illimité":
                try:
                    current_products = usage.get("current_products", 0)
                    max_products_int = int(max_products) if str(max_products).isdigit() else 0
                    products_limit_exceeded = max_products_int > 0 and current_products >= max_products_int
                except:
                    pass
            
            if max_users and max_users != "Illimité":
                try:
                    current_users = usage.get("current_users", 0)
                    max_users_int = int(max_users) if str(max_users).isdigit() else 0
                    users_limit_exceeded = max_users_int > 0 and current_users >= max_users_int
                except:
                    pass
        
        # Fonctionnalités en écriture
        write_features = ["create", "update", "delete", "edit", "add", "remove", "modify",
                        "sale", "vente", "invoice", "facture", "product", "produit"]
        
        is_write_operation = False
        if feature:
            feature_lower = feature.lower()
            is_write_operation = any(wf in feature_lower for wf in write_features)
        
        # Déterminer si l'accès est autorisé
        has_access = False
        reason = None
        
        if not has_subscription:
            reason = "Aucun abonnement actif"
            has_access = False
        elif not is_active:
            reason = "Abonnement expiré"
            has_access = False
        elif is_write_operation and access_mode != "full":
            reason = "Mode lecture seule - Abonnement requis pour les modifications"
            has_access = False
        elif products_limit_exceeded:
            reason = "Limite de produits atteinte"
            has_access = False
        elif users_limit_exceeded:
            reason = "Limite d'utilisateurs atteinte"
            has_access = False
        else:
            reason = None
            has_access = True
        
        return {
            "has_access": has_access,
            "is_active": is_active,
            "has_subscription": has_subscription,
            "access_mode": access_mode,
            "is_read_only": access_mode == "read_only",
            "reason": reason,
            "limits": limits,
            "usage": usage,
            "products_limit_exceeded": products_limit_exceeded,
            "users_limit_exceeded": users_limit_exceeded,
            "subscription": subscription.get("subscription", {})
        }

    def check_subscription_status(self) -> Dict:
        """
        Vérifie le statut de l'abonnement.
        Utilise JSON comme fallback si l'API n'est pas disponible.
        
        Returns:
            Dict avec 'active' (bool) et d'autres informations
        """
        try:
            # Essayer d'abord l'API
            if self.check_internet_connection():
                result = self.import_subscription()
                if result.get('success'):
                    is_active = result.get('is_active', False)
                    return {
                        "active": is_active,
                        "has_subscription": result.get('has_subscription', True),
                        "access_mode": "full" if is_active else "read_only",
                        "days_remaining": result.get('days_remaining', 0),
                        "source": "api"
                    }
            
            # Fallback: Lire depuis JSON
            from services.json_storage import JSONStorage
            subscription = JSONStorage.get_subscription()
            
            if subscription and isinstance(subscription, dict):
                is_active = subscription.get('is_active', True)
                return {
                    "active": is_active,
                    "has_subscription": subscription.get('has_subscription', True),
                    "access_mode": "full" if is_active else "read_only",
                    "days_remaining": subscription.get('days_remaining', 30),
                    "source": "json_cache"
                }
            
            # Fallback par défaut
            return {
                "active": True,
                "has_subscription": True,
                "access_mode": "full",
                "days_remaining": 30,
                "source": "default"
            }
            
        except Exception as e:
            logger.error(f"Erreur check_subscription_status: {e}")
            return {"active": True, "source": "error_fallback"}

    def get_branch_subscription(self, branch_id: str = None) -> Dict:
        """
        Récupère l'abonnement spécifique d'une branche depuis le serveur
        """
        user = self.auth_service.get_current_user()
        headers = self._get_headers()
        if not headers:
            return {"error": "Utilisateur non authentifié", "success": False}
        
        if not branch_id:
            branch_id = user.get('active_branch_id') or user.get('branch_id')
        
        if not branch_id:
            return {"error": "Aucune branche spécifiée", "success": False}
        
        try:
            # Endpoint pour l'abonnement de la branche
            response = self.session.get(
                f"{self.api_url}/sync/subscription/status",
                headers=headers,
                params={"branch_id": branch_id},
                timeout=30
            )
            
            if response.status_code == 200:
                data = response.json()
                
                subscription_info = {
                    "branch_id": branch_id,
                    "has_subscription": data.get("has_subscription", True),
                    "is_active": data.get("is_active", True),
                    "access_mode": data.get("access_mode", "full"),
                    "plan_name": data.get("subscription", {}).get("plan_name", "Standard"),
                    "plan_type": data.get("subscription", {}).get("plan_type", "professional"),
                    "days_remaining": data.get("subscription", {}).get("days_remaining", 30),
                    "max_products": data.get("subscription", {}).get("max_products", "Illimité"),
                    "max_users": data.get("subscription", {}).get("max_users", "Illimité"),
                    "status": data.get("subscription", {}).get("status", "active"),
                    "current_period_end": data.get("subscription", {}).get("current_period_end"),
                    "is_trial": data.get("subscription", {}).get("is_trial", False),
                    "trial_days_remaining": data.get("subscription", {}).get("trial_days_remaining", 0),
                    "synced_at": datetime.now().isoformat()
                }
                
                # Sauvegarder dans le cache
                self.auth_service.save_subscription_info(subscription_info)
                
                logger.info(f"✅ Abonnement branche {branch_id}: actif={subscription_info['is_active']}, plan={subscription_info['plan_name']}")
                
                return {
                    "success": True,
                    "subscription": subscription_info,
                    "is_active": subscription_info["is_active"],
                    "branch_id": branch_id,
                    "days_remaining": subscription_info["days_remaining"]
                }
            else:
                # Utiliser le cache
                cached = self.auth_service.get_subscription_info()
                return {
                    "success": True,
                    "subscription": cached.get("info", {}),
                    "is_active": cached.get("info", {}).get("is_active", True),
                    "branch_id": branch_id,
                    "cached": True
                }
                
        except Exception as e:
            logger.error(f"Erreur get_branch_subscription: {e}")
            return {"error": str(e), "success": False}

    def sync_subscription(self) -> Dict:
        """
        Synchronise uniquement l'abonnement.
        
        Returns:
            Dict avec les informations de synchronisation
        """
        if not self.check_internet_connection():
            # En mode offline, retourner l'abonnement en cache
            cached = self.get_cached_subscription()
            return {
                "success": True,
                "online": False,
                "cached": True,
                "subscription": cached,
                "message": "Mode offline - Utilisation des données en cache"
            }
        
        result = self.import_subscription()
        if "error" in result:
            return {"error": result["error"], "success": False}
        
        return {
            "success": True,
            "online": True,
            "subscription": result.get("subscription"),
            "is_active": result.get("is_active", False),
            "days_remaining": result.get("days_remaining", 0)
        }

    def export_returns(self) -> Dict:
        """Exporte les retours non synchronisés vers le serveur"""
        if not hasattr(self.db, 'get_unsynced_returns'):
            return {"count": 0, "warning": "get_unsynced_returns non disponible"}
        
        unsynced_returns = self.db.get_unsynced_returns()
        if not unsynced_returns:
            return {"count": 0, "message": "Aucun retour à exporter"}
        
        headers = self._get_headers()
        if not headers:
            return {"error": "Authentification requise", "count": 0}
        
        try:
            user = self.auth_service.get_current_user()
            branch_id = user.get('active_branch_id') or user.get('branch_id')
            
            cleaned_returns = []
            for ret in unsynced_returns:
                cleaned_returns.append({
                    'id': ret.get('id'),
                    'sale_id': ret.get('sale_id'),
                    'product_id': ret.get('product_id'),
                    'product_name': ret.get('product_name'),
                    'quantity': ret.get('quantity'),
                    'unit_price': ret.get('unit_price'),
                    'total_price': ret.get('total_price'),
                    'return_date': ret.get('return_date'),
                    'reason': ret.get('reason', ''),
                    'return_type': ret.get('return_type', 'return'),
                    'branch_id': branch_id or ret.get('branch_id'),
                    'customer_name': ret.get('customer_name'),
                    'invoice_number': ret.get('invoice_number'),
                })
            
            response = requests.post(
                f"{self.api_url}/returns/batch",
                headers=headers,
                json={"returns": cleaned_returns},
                timeout=60
            )
            
            if response.status_code == 200:
                data = response.json()
                synced_ids = data.get('synced_ids', [])
                if synced_ids and hasattr(self.db, 'mark_returns_synced'):
                    self.db.mark_returns_synced(synced_ids)
                return {"count": len(synced_ids), "success": True}
            else:
                return {"error": f"Erreur serveur: {response.status_code}", "count": 0, "success": False}
                
        except Exception as e:
            return {"error": str(e), "count": 0, "success": False}

    def export_debts(self) -> Dict:
        """Exporte les dettes non synchronisées vers le serveur"""
        if not hasattr(self.db, 'get_unsynced_debts'):
            return {"count": 0, "warning": "get_unsynced_debts non disponible"}
        
        unsynced_debts = self.db.get_unsynced_debts()
        if not unsynced_debts:
            logger.info("Aucune dette à exporter")
            return {"count": 0, "message": "Aucune dette à exporter", "success": True}
        
        headers = self._get_headers()
        if not headers:
            return {"error": "Authentification requise", "count": 0, "success": False}
        
        try:
            user = self.auth_service.get_current_user()
            branch_id = user.get('active_branch_id') or user.get('branch_id')
            
            synced_ids = []
            errors = []
            
            # ✅ CORRECTION: Utiliser POST sur /debts (pas /debts/batch)
            for debt in unsynced_debts:
                try:
                    # Préparer la dette selon le schéma attendu par le serveur
                    # Format de date: YYYY-MM-DD (sans T)
                    due_date = debt.get('due_date')
                    if due_date:
                        if isinstance(due_date, str):
                            if 'T' in due_date:
                                due_date = due_date.split('T')[0]
                        else:
                            due_date = due_date.isoformat() if hasattr(due_date, 'isoformat') else str(due_date)
                    
                    # Préparer la dette pour l'API
                    cleaned_debt = {
                        "customer_name": self._safe_str(debt.get('customer_name', 'Client inconnu')),
                        "amount": self._safe_float(debt.get('amount', 0)),
                        "remaining_amount": self._safe_float(debt.get('remaining_amount', 0)),
                        "due_date": due_date,
                        "status": debt.get('status', 'pending'),
                        "branch_id": branch_id,
                        "notes": self._safe_str(debt.get('notes', '')),
                        "product_name": self._safe_str(debt.get('product_name', '')),
                        "quantity": self._safe_int(debt.get('quantity', 0)),
                        "unit_price": self._safe_float(debt.get('unit_price', 0)),
                        "created_at": debt.get('created_at') or datetime.now().isoformat(),
                    }
                    
                    # Nettoyer les champs None
                    cleaned_debt = {k: v for k, v in cleaned_debt.items() if v is not None and v != ''}
                    
                    logger.info(f"📤 Envoi dette: client={cleaned_debt['customer_name']}, amount={cleaned_debt['amount']}")
                    
                    # ✅ CORRECTION: Utiliser l'endpoint /debts (pas /debts/batch)
                    response = self.session.post(
                        f"{self.api_url}/debts",
                        headers=headers,
                        json=cleaned_debt,
                        timeout=30
                    )
                    
                    if response.status_code in [200, 201]:
                        synced_ids.append(debt.get('id'))
                        logger.info(f"✅ Dette exportée: {debt.get('customer_name')} - {debt.get('amount')}")
                    else:
                        error_detail = response.text[:200]
                        try:
                            error_json = response.json()
                            error_detail = error_json.get('detail', error_detail)
                        except:
                            pass
                        
                        errors.append({
                            'id': debt.get('id'),
                            'error': f"HTTP {response.status_code}: {error_detail}"
                        })
                        logger.error(f"❌ Erreur export dette {debt.get('id')}: {response.status_code} - {error_detail}")
                        
                except Exception as e:
                    logger.error(f"❌ Erreur export dette {debt.get('id')}: {e}")
                    errors.append({'id': debt.get('id'), 'error': str(e)})
            
            # Marquer les dettes synchronisées
            if synced_ids and hasattr(self.db, 'mark_debts_synced'):
                self.db.mark_debts_synced(synced_ids)
            
            logger.info(f"✅ Export dettes terminé: {len(synced_ids)} succès, {len(errors)} erreurs")
            
            return {
                "count": len(synced_ids),
                "success": len(errors) == 0,
                "synced_ids": synced_ids,
                "errors": errors,
                "total_attempted": len(unsynced_debts)
            }
                    
        except Exception as e:
            logger.error(f"Erreur export dettes: {str(e)}", exc_info=True)
            return {"error": str(e), "count": 0, "success": False}

    def sync_products_only(self) -> Dict:
        """Synchronise uniquement les produits"""
        if not self.check_internet_connection():
            return {"error": "Pas de connexion internet", "success": False}
        
        result = self.import_products()
        if "error" in result:
            return {"error": result["error"], "success": False}
        
        return {"products_imported": result.get("count", 0), "success": True}

    def sync_sales_only(self) -> Dict:
        """Synchronise uniquement les ventes"""
        if not self.check_internet_connection():
            return {"error": "Pas de connexion internet", "success": False}
        
        result = self.export_sales()
        if "error" in result:
            return {"error": result["error"], "success": False}
        
        return {"sales_exported": result.get("count", 0), "success": True}

    def sync_expenses_only(self) -> Dict:
        """Synchronise uniquement les dépenses"""
        if not self.check_internet_connection():
            return {"error": "Pas de connexion internet", "success": False}
        
        result = self.export_expenses()
        if "error" in result:
            return {"error": result["error"], "success": False}
        
        return {"expenses_exported": result.get("count", 0), "success": True}
    
    def get_sync_status(self) -> Dict:
        """
        Récupère le statut de synchronisation
        
        Returns:
            Dict avec les informations de synchronisation
        """
        try:
            pending_sales = self.db.get_unsynced_sales() if hasattr(self.db, 'get_unsynced_sales') else []
            pending_expenses = self.db.get_unsynced_expenses() if hasattr(self.db, 'get_unsynced_expenses') else []
            
            last_sync = self.auth_service.get_current_user()
            last_sync_date = last_sync.get('last_sync') if last_sync else None
            
            return {
                "pending_sales_count": len(pending_sales),
                "pending_expenses_count": len(pending_expenses),
                "last_sync_date": last_sync_date,
                "is_connected": self.check_internet_connection(),
                "success": True
            }
        except Exception as e:
            logger.error(f"Erreur get_sync_status: {e}")
            return {"error": str(e), "success": False}
    
    
    def diagnose_missing_products(self):
        """Diagnostique les produits manquants sur le serveur"""
        if not self._is_online():
            logger.info("📡 Mode offline - Diagnostic des produits manquants ignoré")
            return []

        print("=== DIAGNOSTIC PRODUITS MANQUANTS ===\n")
        
        # 1. Lister les produits locaux
        local_products = self.db.get_all_products()
        print(f"Produits locaux: {len(local_products)}")
        
        # 2. Vérifier les server_id
        missing_server_id = [p for p in local_products if not getattr(p, 'server_id', None)]
        print(f"Produits sans server_id: {len(missing_server_id)}")
        
        # 3. Vérifier l'existence sur le serveur
        not_on_server = []
        for p in local_products[:20]:  # Limite pour test
            server_id = getattr(p, 'server_id', None)
            if server_id:
                # Utiliser self._get_server_product_stock avec gestion d'erreur
                try:
                    result = self._get_server_product_stock(server_id)
                    if not result:
                        not_on_server.append({
                            "id": getattr(p, 'server_id', 'unknown'),
                            "name": getattr(p, 'name', 'Inconnu'),
                            "server_id": server_id,
                            "code": getattr(p, 'code', '')
                        })
                except Exception as e:
                    print(f"Erreur vérification produit {server_id}: {e}")
        
        print(f"\nProduits non trouvés sur le serveur: {len(not_on_server)}")
        for p in not_on_server[:10]:
            print(f"  - {p['name']} (ID serveur: {p['server_id']})")
        
        return not_on_server