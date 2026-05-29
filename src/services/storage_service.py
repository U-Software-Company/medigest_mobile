# services/storage_service.py - Version corrigée avec élimination des fichiers JSON

"""
Service de stockage local.

IMPORTANT: Ce service est DÉPRÉCIÉ pour les données utilisateur.
Les données utilisateur sont maintenant stockées dans SQLite via DatabaseManager et AuthService.

Ce service est conservé UNIQUEMENT pour:
- Les préférences UI (thème, langue, etc.)
- Les données temporaires non critiques
- La compatibilité ascendante avec l'ancien code

NE PAS UTILISER pour:
- Les tokens d'authentification
- Les données utilisateur
- Les données métier (ventes, produits, etc.)
"""

import json
import os
import logging
from typing import Any, Optional
from utils.paths import get_app_dir, get_user_data_path

logger = logging.getLogger(__name__)


class StorageService:
    """
    Service de stockage local avec isolation par répertoire.
    
    Méthodes dépréciées:
    - save_user / get_user / delete_user → Utiliser AuthService.get_current_user()
    - Toute sauvegarde de données critiques → Utiliser DatabaseManager
    """
    
    # ⚠️ Indicateur de dépréciation
    _deprecation_warning_shown = False
    
    @staticmethod
    def _get_storage_path(key: str) -> str:
        """
        Retourne le chemin complet pour un fichier de stockage.
        Tous les fichiers sont dans le répertoire de l'application.
        """
        app_dir = get_app_dir()
        # Nettoyer le nom de fichier
        safe_key = "".join(c for c in key if c.isalnum() or c in ('_', '-'))
        return os.path.join(app_dir, f"{safe_key}.json")
    
    @staticmethod
    def _show_deprecation_warning():
        """Affiche un avertissement unique de dépréciation."""
        if not StorageService._deprecation_warning_shown:
            logger.warning("=" * 60)
            logger.warning("⚠️  ATTENTION: StorageService est DÉPRÉCIÉ")
            logger.warning("⚠️  Les données utilisateur doivent utiliser SQLite via AuthService")
            logger.warning("⚠️  StorageService est conservé UNIQUEMENT pour les préférences UI")
            logger.warning("=" * 60)
            StorageService._deprecation_warning_shown = True
    
    # =========================================================================
    # MÉTHODES GÉNÉRIQUES (pour préférences UI uniquement)
    # =========================================================================
    
    @staticmethod
    def save(key: str, value: Any) -> bool:
        """
        Sauvegarde une valeur dans un fichier JSON.
        
        ⚠️ DÉPRÉCIÉ pour les données critiques.
        Utiliser UNIQUEMENT pour les préférences UI (thème, langue, etc.)
        """
        StorageService._show_deprecation_warning()
        
        try:
            filepath = StorageService._get_storage_path(key)
            
            # S'assurer que le répertoire existe
            os.makedirs(os.path.dirname(filepath), exist_ok=True)
            
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(value, f, indent=2, ensure_ascii=False)
            
            logger.debug(f"💾 Données sauvegardées: {key} → {filepath}")
            return True
            
        except Exception as e:
            logger.error(f"❌ Erreur sauvegarde {key}: {e}")
            return False
    
    @staticmethod
    def get(key: str, default: Any = None) -> Any:
        """
        Récupère une valeur depuis un fichier JSON.
        
        ⚠️ DÉPRÉCIÉ pour les données critiques.
        """
        StorageService._show_deprecation_warning()
        
        try:
            filepath = StorageService._get_storage_path(key)
            
            if not os.path.exists(filepath):
                return default
            
            with open(filepath, 'r', encoding='utf-8') as f:
                return json.load(f)
                
        except json.JSONDecodeError:
            logger.warning(f"⚠️ Fichier corrompu pour {key}, utilisation de la valeur par défaut")
            return default
        except Exception as e:
            logger.error(f"❌ Erreur lecture {key}: {e}")
            return default
    
    @staticmethod
    def delete(key: str) -> bool:
        """Supprime un fichier de stockage."""
        try:
            filepath = StorageService._get_storage_path(key)
            if os.path.exists(filepath):
                os.remove(filepath)
                logger.debug(f"🗑️ Fichier supprimé: {key}")
                return True
            return False
        except Exception as e:
            logger.error(f"❌ Erreur suppression {key}: {e}")
            return False
    
    @staticmethod
    def exists(key: str) -> bool:
        """Vérifie si un fichier de stockage existe."""
        filepath = StorageService._get_storage_path(key)
        return os.path.exists(filepath)
    
    @staticmethod
    def clear_all():
        """Supprime tous les fichiers de stockage JSON (sauf current_user.json)."""
        app_dir = get_app_dir()
        
        try:
            deleted_count = 0
            for file in os.listdir(app_dir):
                if file.endswith('.json') and file not in ['current_user.json']:
                    filepath = os.path.join(app_dir, file)
                    try:
                        os.remove(filepath)
                        deleted_count += 1
                    except Exception as e:
                        logger.error(f"Erreur suppression {file}: {e}")
            
            logger.info(f"🗑️ {deleted_count} fichiers de stockage supprimés")
            
        except Exception as e:
            logger.error(f"Erreur clear_all: {e}")
    
    # =========================================================================
    # MÉTHODES SPÉCIFIQUES POUR LES PRÉFÉRENCES UI (usage autorisé)
    # =========================================================================
    
    @staticmethod
    def save_theme(theme: str) -> bool:
        """Sauvegarde la préférence de thème."""
        return StorageService.save("ui_theme", {"theme": theme, "updated_at": str(__import__('datetime').datetime.now())})
    
    @staticmethod
    def get_theme(default: str = "light") -> str:
        """Récupère la préférence de thème."""
        data = StorageService.get("ui_theme", {})
        return data.get("theme", default) if isinstance(data, dict) else default
    
    @staticmethod
    def save_language(lang: str) -> bool:
        """Sauvegarde la préférence de langue."""
        return StorageService.save("ui_language", {"language": lang})
    
    @staticmethod
    def get_language(default: str = "fr") -> str:
        """Récupère la préférence de langue."""
        data = StorageService.get("ui_language", {})
        return data.get("language", default) if isinstance(data, dict) else default
    
    # =========================================================================
    # MÉTHODES DÉPRÉCIÉES - NE PLUS UTILISER
    # =========================================================================
    
    @staticmethod
    def save_user(user_data: dict) -> bool:
        """
        ❌ DÉPRÉCIÉ - Utiliser AuthService.save_user() à la place.
        
        Cette méthode est conservée uniquement pour la compatibilité
        avec l'ancien code. Elle redirige vers le fichier correct
        mais ne doit plus être utilisée.
        """
        logger.error("❌❌❌ StorageService.save_user() est DÉPRÉCIÉ !")
        logger.error("❌❌❌ Utilisez AuthService.save_user() qui stocke dans SQLite !")
        
        # Sauvegarde de secours dans le fichier JSON (pour compatibilité)
        try:
            filepath = get_user_data_path()
            os.makedirs(os.path.dirname(filepath), exist_ok=True)
            
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(user_data, f, indent=2, ensure_ascii=False)
            
            logger.info(f"⚠️ Données utilisateur sauvegardées en JSON (fallback): {filepath}")
            logger.warning("⚠️ Ces données NE SERONT PAS utilisées par AuthService !")
            return True
            
        except Exception as e:
            logger.error(f"❌ Erreur sauvegarde JSON fallback: {e}")
            return False
    
    @staticmethod
    def get_user(default: dict = None) -> Optional[dict]:
        """
        ❌ DÉPRÉCIÉ - Utiliser AuthService.get_current_user() à la place.
        """
        logger.error("❌❌❌ StorageService.get_user() est DÉPRÉCIÉ !")
        logger.error("❌❌❌ Utilisez AuthService.get_current_user() qui lit depuis SQLite !")
        
        try:
            filepath = get_user_data_path()
            if os.path.exists(filepath):
                with open(filepath, 'r', encoding='utf-8') as f:
                    return json.load(f)
        except Exception as e:
            logger.error(f"Erreur lecture JSON fallback: {e}")
        
        return default or {}
    
    @staticmethod
    def delete_user() -> bool:
        """
        ❌ DÉPRÉCIÉ - Utiliser AuthService.logout() à la place.
        """
        logger.error("❌❌❌ StorageService.delete_user() est DÉPRÉCIÉ !")
        logger.error("❌❌❌ Utilisez AuthService.logout() qui supprime de SQLite !")
        
        try:
            filepath = get_user_data_path()
            if os.path.exists(filepath):
                os.remove(filepath)
                logger.info("🗑️ Fichier JSON utilisateur supprimé (fallback)")
                return True
            return False
        except Exception as e:
            logger.error(f"Erreur suppression JSON fallback: {e}")
            return False