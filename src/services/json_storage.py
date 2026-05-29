# services/json_storage.py
"""
Service de stockage JSON pour les données critiques (utilisateur et abonnement)
Solution de secours lorsque SQLite ne persiste pas correctement.
Stockage dans le répertoire de l'application (fonctionne sur Android)
"""

import json
import os
import logging
from typing import Dict, Optional, Any
from datetime import datetime
from utils.paths import get_app_dir, get_user_data_path, get_storage_dir

logger = logging.getLogger(__name__)


class JSONStorage:
    """
    Stockage JSON simple et fiable pour les données utilisateur et abonnement.
    Utilisé comme solution de secours ou principale selon la configuration.
    Tous les fichiers sont stockés dans le répertoire de l'application.
    """
    
    # Noms des fichiers
    USER_FILE = "current_user.json"
    SUBSCRIPTION_FILE = "subscription.json"
    
    @classmethod
    def _get_file_path(cls, filename: str) -> str:
        """
        Retourne le chemin complet du fichier.
        Stocke dans le répertoire principal de l'application.
        """
        app_dir = get_app_dir()
        os.makedirs(app_dir, exist_ok=True)
        return os.path.join(app_dir, filename)
    
    @classmethod
    def _get_storage_file_path(cls, filename: str) -> str:
        """
        Retourne le chemin complet du fichier dans le sous-dossier storage.
        """
        storage_dir = get_storage_dir()
        return os.path.join(storage_dir, filename)
    
    # =========================================================================
    # GESTION DE L'UTILISATEUR
    # =========================================================================
    
    @classmethod
    def save_user(cls, user_data: Dict) -> bool:
        """
        Sauvegarde les données utilisateur dans un fichier JSON.
        
        Args:
            user_data: Dictionnaire contenant les données utilisateur
            
        Returns:
            True si la sauvegarde a réussi, False sinon
        """
        try:
            # Utiliser le même chemin que get_user_data_path() pour compatibilité
            filepath = get_user_data_path()
            os.makedirs(os.path.dirname(filepath), exist_ok=True)
            
            # Ajouter des métadonnées
            data_to_save = {
                "user": user_data,
                "saved_at": datetime.now().isoformat(),
                "version": "1.0"
            }
            
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(data_to_save, f, indent=2, ensure_ascii=False, default=str)
            
            logger.info(f"✅ Utilisateur sauvegardé dans JSON: {filepath}")
            logger.info(f"   Username: {user_data.get('username')}")
            logger.info(f"   Token: {'✓' if user_data.get('token') else '✗'}")
            return True
            
        except Exception as e:
            logger.error(f"❌ Erreur sauvegarde utilisateur JSON: {e}")
            return False
    
    @classmethod
    def get_user(cls) -> Optional[Dict]:
        """
        Récupère les données utilisateur depuis le fichier JSON.
        
        Returns:
            Dictionnaire des données utilisateur ou None si non trouvé
        """
        try:
            filepath = get_user_data_path()
            
            if not os.path.exists(filepath):
                logger.info(f"ℹ️ Aucun fichier utilisateur JSON trouvé: {filepath}")
                return None
            
            with open(filepath, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            user_data = data.get("user", {})
            
            if user_data and user_data.get('token'):
                saved_at = data.get("saved_at", "inconnue")
                logger.info(f"✅ Utilisateur chargé depuis JSON (sauvegardé le {saved_at})")
                logger.info(f"   Fichier: {filepath}")
                logger.info(f"   Username: {user_data.get('username')}")
                logger.info(f"   Token: {'✓' if user_data.get('token') else '✗'}")
                return user_data
            else:
                logger.warning("⚠️ Fichier JSON utilisateur présent mais sans token valide")
                return None
                
        except json.JSONDecodeError as e:
            logger.error(f"❌ Erreur de parsing JSON: {e}")
            return None
        except Exception as e:
            logger.error(f"❌ Erreur lecture utilisateur JSON: {e}")
            return None
    
    @classmethod
    def delete_user(cls) -> bool:
        """
        Supprime le fichier utilisateur JSON.
        
        Returns:
            True si la suppression a réussi ou si le fichier n'existe pas
        """
        try:
            filepath = get_user_data_path()
            if os.path.exists(filepath):
                os.remove(filepath)
                logger.info(f"🗑️ Fichier utilisateur JSON supprimé: {filepath}")
            return True
        except Exception as e:
            logger.error(f"❌ Erreur suppression utilisateur JSON: {e}")
            return False
    
    @classmethod
    def user_exists(cls) -> bool:
        """Vérifie si un fichier utilisateur JSON existe."""
        filepath = get_user_data_path()
        return os.path.exists(filepath)
    
    # =========================================================================
    # GESTION DE L'ABONNEMENT
    # =========================================================================
    
    @classmethod
    def save_subscription(cls, subscription_data: Dict, branch_id: str = None) -> bool:
        """
        Sauvegarde les données d'abonnement dans un fichier JSON.
        
        Args:
            subscription_data: Dictionnaire contenant les données d'abonnement
            branch_id: ID de la branche (optionnel)
            
        Returns:
            True si la sauvegarde a réussi, False sinon
        """
        try:
            filepath = cls._get_file_path(cls.SUBSCRIPTION_FILE)
            
            # Structure avec métadonnées
            data_to_save = {
                "subscription": subscription_data,
                "branch_id": branch_id,
                "saved_at": datetime.now().isoformat(),
                "version": "1.0"
            }
            
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(data_to_save, f, indent=2, ensure_ascii=False, default=str)
            
            logger.info(f"✅ Abonnement sauvegardé dans JSON: {filepath}")
            is_active = subscription_data.get('is_active', False) if isinstance(subscription_data, dict) else False
            logger.info(f"   Actif: {is_active}")
            if branch_id:
                logger.info(f"   Branche: {branch_id}")
            return True
            
        except Exception as e:
            logger.error(f"❌ Erreur sauvegarde abonnement JSON: {e}")
            return False
    
    @classmethod
    def get_subscription(cls, branch_id: str = None) -> Optional[Dict]:
        """
        Récupère les données d'abonnement depuis le fichier JSON.
        
        Args:
            branch_id: ID de la branche pour vérification (optionnel)
            
        Returns:
            Dictionnaire des données d'abonnement ou None si non trouvé
        """
        try:
            filepath = cls._get_file_path(cls.SUBSCRIPTION_FILE)
            
            if not os.path.exists(filepath):
                logger.info(f"ℹ️ Aucun fichier abonnement JSON trouvé: {filepath}")
                return None
            
            with open(filepath, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            subscription_data = data.get("subscription", {})
            saved_branch_id = data.get("branch_id")
            saved_at = data.get("saved_at", "inconnue")
            
            # Vérifier que c'est la bonne branche
            if branch_id and saved_branch_id and branch_id != saved_branch_id:
                logger.warning(f"⚠️ Abonnement JSON pour branche différente: {saved_branch_id} vs {branch_id}")
                return None
            
            logger.info(f"✅ Abonnement chargé depuis JSON (sauvegardé le {saved_at})")
            logger.info(f"   Fichier: {filepath}")
            
            if isinstance(subscription_data, dict):
                is_active = subscription_data.get('is_active', False)
                logger.info(f"   Actif: {is_active}")
            
            return subscription_data if isinstance(subscription_data, dict) else None
                
        except json.JSONDecodeError as e:
            logger.error(f"❌ Erreur de parsing JSON abonnement: {e}")
            return None
        except Exception as e:
            logger.error(f"❌ Erreur lecture abonnement JSON: {e}")
            return None
    
    @classmethod
    def delete_subscription(cls) -> bool:
        """
        Supprime le fichier abonnement JSON.
        
        Returns:
            True si la suppression a réussi ou si le fichier n'existe pas
        """
        try:
            filepath = cls._get_file_path(cls.SUBSCRIPTION_FILE)
            if os.path.exists(filepath):
                os.remove(filepath)
                logger.info(f"🗑️ Fichier abonnement JSON supprimé: {filepath}")
            return True
        except Exception as e:
            logger.error(f"❌ Erreur suppression abonnement JSON: {e}")
            return False
    
    @classmethod
    def subscription_exists(cls) -> bool:
        """Vérifie si un fichier abonnement JSON existe."""
        filepath = cls._get_file_path(cls.SUBSCRIPTION_FILE)
        return os.path.exists(filepath)
    
    # =========================================================================
    # UTILITAIRES
    # =========================================================================
    
    @classmethod
    def clear_all(cls):
        """Supprime tous les fichiers JSON de stockage."""
        cls.delete_user()
        cls.delete_subscription()
        logger.info("🗑️ Tous les fichiers JSON de stockage supprimés")
    
    @classmethod
    def get_all_files(cls) -> Dict[str, str]:
        """
        Retourne tous les chemins des fichiers de stockage.
        Utile pour le débogage.
        """
        return {
            "user_file": get_user_data_path(),
            "subscription_file": cls._get_file_path(cls.SUBSCRIPTION_FILE),
            "app_dir": get_app_dir(),
            "storage_dir": get_storage_dir()
        }
    
    @classmethod
    def list_all(cls) -> list:
        """
        Liste tous les fichiers JSON dans le répertoire de l'application.
        """
        app_dir = get_app_dir()
        try:
            files = [f for f in os.listdir(app_dir) if f.endswith('.json')]
            return files
        except Exception as e:
            logger.error(f"Erreur liste fichiers: {e}")
            return []
    
    @classmethod
    def debug_paths(cls):
        """Affiche tous les chemins pour le débogage (utile sur Android)."""
        paths = cls.get_all_files()
        logger.info("=" * 50)
        logger.info("📁 PATHS DE STOCKAGE JSON")
        logger.info("=" * 50)
        for name, path in paths.items():
            exists = os.path.exists(path) if path else False
            logger.info(f"  {name}: {path}")
            logger.info(f"    Existe: {exists}")
            if exists and name == "user_file":
                try:
                    with open(path, 'r') as f:
                        data = json.load(f)
                        user = data.get('user', {})
                        logger.info(f"    Username: {user.get('username')}")
                        logger.info(f"    Token: {'✓' if user.get('token') else '✗'}")
                except:
                    pass
        logger.info("=" * 50)