# services/connection_manager.py - Version corrigée

import threading
import socket
import requests
from typing import Optional, Callable, List
import logging

logger = logging.getLogger(__name__)


class ConnectionManager:
    """
    Gestionnaire central de l'état de connexion internet.
    Permet à tous les écrans de connaître le mode actuel (online/offline).
    """
    
    _instance = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        
        # Mode forcé par l'utilisateur (None = auto, True = force online, False = force offline)
        self.force_mode: Optional[bool] = None
        self._actual_internet_status: bool = False
        self._observers: List[Callable] = []
        self._status_check_thread: Optional[threading.Thread] = None
        self._stop_checking: bool = False
        self._is_online = False
        self._force_mode = None
        self._sync_service = None
        
        # Démarrer la vérification automatique
        self.start_internet_checking()
    
    # ==================== OBSERVATEURS ====================
    
    def register_observer(self, callback: Callable[[bool, Optional[bool]], None]):
        """Enregistre un callback pour être notifié des changements de mode."""
        if callback not in self._observers:
            self._observers.append(callback)
            try:
                callback(self.is_online_mode(), self.force_mode)
            except Exception as e:
                logger.error(f"Erreur lors de la notification initiale: {e}")
    
    def unregister_observer(self, callback: Callable):
        """Désenregistre un callback"""
        if callback in self._observers:
            self._observers.remove(callback)
    
    def _notify_observers(self):
        """Notifie tous les observateurs du changement de statut"""
        for observer in self._observers:
            try:
                observer(self._is_online, self._force_mode)
            except Exception as e:
                logger.error(f"Erreur notification observateur: {e}")
    
    # ==================== GESTION INTERNET ====================
    
    def set_sync_service(self, sync_service):
        """Injecte le sync_service pour vérifier la connexion"""
        self._sync_service = sync_service
    
    def check_real_internet_status(self) -> bool:
        """
        Vérifie le vrai statut de la connexion internet.
        Utilise plusieurs méthodes pour plus de fiabilité.
        """
        # Méthode 1: Vérification DNS de base
        try:
            socket.setdefaulttimeout(5)
            socket.gethostbyname('google.com')
            logger.debug("✅ DNS check passed")
            return True
        except Exception as e:
            logger.debug(f"DNS check failed: {e}")
        
        # Méthéthode 2: Vérification HTTP avec requests
        try:
            response = requests.get(
                'https://8.8.8.8',  # Google DNS
                timeout=5,
                verify=False
            )
            if response.status_code >= 200:
                logger.debug("✅ HTTP check passed")
                return True
        except Exception as e:
            logger.debug(f"HTTP check failed: {e}")
        
        # Méthode 3: Vérification du backend
        if self._sync_service:
            try:
                result = self._sync_service.check_internet_connection()
                if result:
                    logger.debug("✅ Backend check passed")
                    return True
            except Exception as e:
                logger.debug(f"Backend check failed: {e}")
        
        logger.debug("❌ All internet checks failed")
        return False
    
    def get_current_mode(self) -> str:
        """Retourne le mode actuel (online/offline)"""
        if self.force_mode is not None:
            return "online" if self.force_mode else "offline"
        return "online" if self._actual_internet_status else "offline"
    
    def is_online_mode(self) -> bool:
        """Retourne True si on est en mode online"""
        return self.get_current_mode() == "online"
    
    def is_force_mode(self) -> bool:
        """Retourne True si un mode forcé est activé"""
        return self.force_mode is not None
    
    def get_force_mode(self) -> Optional[bool]:
        """Retourne le mode forcé actuel"""
        return self.force_mode
    
    def set_force_mode(self, mode: Optional[bool]):
        """Définit manuellement le mode (Force Online, Force Offline, Auto)"""
        old_mode = self.force_mode
        self.force_mode = mode
        self._force_mode = mode
        
        # Re-vérifier le statut si on passe en mode auto
        if mode is None:
            self._actual_internet_status = self.check_real_internet_status()
            self._is_online = self._actual_internet_status
        
        self._notify_observers()
    
    def toggle_mode(self):
        """Bascule entre les modes: Auto -> Force Online -> Force Offline -> Auto"""
        if self.force_mode is None:
            self.set_force_mode(True)  # Force online
        elif self.force_mode is True:
            self.set_force_mode(False)  # Force offline
        else:
            self.set_force_mode(None)  # Auto
    
    def start_internet_checking(self, interval_seconds: int = 30):
        """Démarre la vérification périodique"""
        def check_loop():
            logger.info(f"🔄 Vérificateur internet démarré (intervalle: {interval_seconds}s)")
            while not self._stop_checking:
                try:
                    if self.force_mode is None:  # Mode auto
                        new_status = self.check_real_internet_status()
                        if new_status != self._actual_internet_status:
                            self._actual_internet_status = new_status
                            self._is_online = new_status
                            logger.info(f"🌐 Statut internet changé: {'ONLINE' if new_status else 'OFFLINE'}")
                            self._notify_observers()
                except Exception as e:
                    logger.error(f"Erreur vérification internet: {e}")
                
                # Attendre l'intervalle
                for _ in range(interval_seconds):
                    if self._stop_checking:
                        break
                    import time
                    time.sleep(1)
        
        self._stop_checking = False
        self._status_check_thread = threading.Thread(target=check_loop, daemon=True)
        self._status_check_thread.start()
        
        # Vérification initiale immédiate
        if self.force_mode is None:
            self._actual_internet_status = self.check_real_internet_status()
            self._is_online = self._actual_internet_status
            logger.info(f"🌐 Statut internet initial: {'ONLINE' if self._actual_internet_status else 'OFFLINE'}")
    
    def stop_internet_checking(self):
        """Arrête la vérification périodique"""
        self._stop_checking = True
        if self._status_check_thread:
            self._status_check_thread.join(timeout=2)
    
    def get_display_status(self) -> dict:
        """Retourne le statut à afficher"""
        mode = self.get_current_mode()
        is_force = self.force_mode is not None
        
        if mode == "online":
            if is_force:
                return {
                    "color": "blue",
                    "text": "ONLINE (Forcé)",
                    "icon": "🔌",
                    "tooltip": "Mode online forcé - Toutes les opérations utilisent internet"
                }
            return {
                "color": "green",
                "text": "Online",
                "icon": "🌐",
                "tooltip": "Mode connecté - Synchronisation automatique"
            }
        else:
            if is_force:
                return {
                    "color": "orange",
                    "text": "OFFLINE (Forcé)",
                    "icon": "✈️",
                    "tooltip": "Mode hors-ligne forcé - Aucune synchronisation"
                }
            return {
                "color": "red",
                "text": "Offline",
                "icon": "📡",
                "tooltip": "Mode hors-ligne - Pas de connexion internet"
            }