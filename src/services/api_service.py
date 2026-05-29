import requests
import json
from typing import Dict, List, Any, Optional
from datetime import datetime
import logging
from services.connection_manager import ConnectionManager

logger = logging.getLogger(__name__)

class APIService:
    """Service de communication avec l'API backend"""
    
    def __init__(self, base_url: str = "https://my-backend-ydit.onrender.com"):
        self.base_url = base_url
        self.api_url = f"{base_url}/api/v1"
        self.timeout = 30
        self.connection_manager = ConnectionManager()
    
    def _is_online(self) -> bool:
        return self.connection_manager.is_online_mode()
    
    def _check_online(self, operation: str) -> bool:
        if not self._is_online():
            logger.warning(f"⚠️ Hors ligne - {operation} ignorée")
            return False
        return True
    
    def set_auth_token(self, token: str):
        """Définir le token d'authentification"""
        self.token = token
        self.headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json"
        }
    
    def login(self, username: str, password: str) -> Dict:
        """Authentification de l'utilisateur"""
        try:
            response = requests.post(
                f"{self.api_url}/auth/login",
                json={"username": username, "password": password},
                timeout=self.timeout
            )
            
            if response.status_code == 200:
                return response.json()
            else:
                error_msg = response.json().get('detail', 'Erreur d\'authentification')
                return {"error": error_msg, "status_code": response.status_code}
        except requests.RequestException as e:
            return {"error": str(e)}
    
    def sync_pull(self, last_sync: Optional[str] = None) -> Dict:
        """
        Récupérer les modifications depuis le serveur (PULL)
        
        Args:
            last_sync: Date de dernière synchronisation au format ISO
        """
        if not self._check_online("sync_pull"):
            return {"error": "Mode hors ligne", "data": []}
        
        try:
            params = {}
            if last_sync:
                params['last_sync'] = last_sync
            
            response = requests.get(
                f"{self.api_url}/sync/pull",
                headers=self.headers,
                params=params,
                timeout=self.timeout
            )
            
            if response.status_code == 200:
                return response.json()
            else:
                return {"error": f"Erreur {response.status_code}", "data": []}
        except requests.RequestException as e:
            logger.error(f"Erreur sync_pull: {str(e)}")
            return {"error": str(e), "data": []}
    
    def sync_push(self, items: List[Dict]) -> Dict:
        """
        Envoyer les modifications au serveur (PUSH)
        
        Args:
            items: Liste des items à synchroniser
            Chaque item doit avoir: table_name, action, data
        """
        try:
            payload = {"items": items}
            
            response = requests.post(
                f"{self.api_url}/sync/",
                headers=self.headers,
                json=payload,
                timeout=self.timeout
            )
            
            if response.status_code == 200:
                return response.json()
            else:
                return {"error": f"Erreur {response.status_code}", "summary": {"processed_items": 0}}
        except requests.RequestException as e:
            logger.error(f"Erreur sync_push: {str(e)}")
            return {"error": str(e), "summary": {"processed_items": 0}}
    
    def sync_batch(self, items: List[Dict]) -> Dict:
        """Synchronisation par lots pour les gros volumes"""
        try:
            payload = {"items": items}
            
            response = requests.post(
                f"{self.api_url}/sync/batch",
                headers=self.headers,
                json=payload,
                timeout=self.timeout * 2
            )
            
            if response.status_code == 200:
                return response.json()
            else:
                return {"error": f"Erreur {response.status_code}"}
        except requests.RequestException as e:
            logger.error(f"Erreur sync_batch: {str(e)}")
            return {"error": str(e)}
    
    def get_sync_status(self) -> Dict:
        """Vérifier le statut de synchronisation"""
        try:
            response = requests.get(
                f"{self.api_url}/sync/status",
                headers=self.headers,
                timeout=self.timeout
            )
            
            if response.status_code == 200:
                return response.json()
            else:
                return {"error": f"Erreur {response.status_code}"}
        except requests.RequestException as e:
            return {"error": str(e)}
    
    def get_products(self, branch_id: int, last_sync: Optional[str] = None) -> List[Dict]:
        """Récupérer les produits depuis le serveur"""
        try:
            params = {"branch_id": branch_id}
            if last_sync:
                params['last_sync'] = last_sync
            
            response = requests.get(
                f"{self.api_url}/stock",
                headers=self.headers,
                params=params,
                timeout=self.timeout
            )
            
            if response.status_code == 200:
                data = response.json()
                return data.get('products', [])
            else:
                return []
        except requests.RequestException as e:
            logger.error(f"Erreur get_products: {str(e)}")
            return []
    
    def post_sales(self, sales: List[Dict]) -> Dict:
        """Envoyer les ventes au serveur"""
        try:
            response = requests.post(
                f"{self.api_url}/sales/batch",
                headers=self.headers,
                json={"sales": sales},
                timeout=self.timeout
            )
            
            if response.status_code == 200:
                return response.json()
            else:
                return {"error": f"Erreur {response.status_code}", "synced_ids": []}
        except requests.RequestException as e:
            return {"error": str(e), "synced_ids": []}
    
    def get_branches(self) -> List[Dict]:
        """Récupérer la liste des succursales"""
        try:
            response = requests.get(
                f"{self.api_url}/branches",
                headers=self.headers,
                timeout=self.timeout
            )
            
            if response.status_code == 200:
                data = response.json()
                return data.get('branches', [])
            else:
                return []
        except requests.RequestException as e:
            logger.error(f"Erreur get_branches: {str(e)}")
            return []
    
    def health_check(self) -> bool:
        """Vérifier si l'API est disponible"""
        try:
            response = requests.get(
                f"{self.base_url}/health",
                timeout=5
            )
            return response.status_code == 200
        except:
            return False
    
    def sync_health(self) -> Dict:
        """Vérifier la santé du service de synchronisation"""
        try:
            response = requests.get(
                f"{self.api_url}/sync/health",
                timeout=5
            )
            
            if response.status_code == 200:
                return response.json()
            else:
                return {"status": "unhealthy"}
        except:
            return {"status": "unhealthy"}