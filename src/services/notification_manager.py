# notification_manager.py - Version complètement corrigée

import json
import threading
from datetime import datetime, timedelta, date
from typing import List, Dict, Optional, Callable
from dataclasses import dataclass
from enum import Enum

import flet as ft

from services.connection_manager import ConnectionManager


class AlertType(Enum):
    LOW_STOCK = "low_stock"
    OUT_OF_STOCK = "out_of_stock"
    EXPIRING_SOON = "expiring_soon"
    EXPIRED = "expired"
    SUBSCRIPTION_RENEWAL = "subscription_renewal"
    DEBT_REMINDER = "debt_reminder"
    SYNC_ERROR = "sync_error"
    DAILY_SALES = "daily_sales"
    WEEKLY_REPORT = "weekly_report"


class AlertPriority(Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass
class Alert:
    """Structure d'une alerte"""
    id: str
    type: AlertType
    title: str
    message: str
    priority: AlertPriority
    created_at: datetime
    read: bool = False
    action_data: Optional[Dict] = None
    product_id: Optional[str] = None
    product_name: Optional[str] = None
    quantity: Optional[int] = None
    days_left: Optional[int] = None


class NotificationManager:
    """Gestionnaire central des notifications et alertes avec ConnectionManager"""
    
    def __init__(self, page: ft.Page, db, auth_service, sync_service=None):
        self.page = page
        self.db = db
        self.auth_service = auth_service
        self.sync_service = sync_service
        self.alerts: List[Alert] = []
        self.observers: List[Callable] = []
        self.notification_badge = None
        self.notification_button = None
        self.is_checking = False
        self.check_interval = 300  # 5 minutes par défaut
        self._timer_initialized = False
        self._check_thread = None
        self._stop_auto_check = False
        
        # ========== CONNECTION MANAGER ==========
        self.connection_manager = ConnectionManager()
        if sync_service:
            self.connection_manager.set_sync_service(sync_service)
        
        # S'enregistrer pour les changements de connexion
        self.connection_manager.register_observer(self._on_connection_status_changed)
        
        self._setup_notification_table()
        
        # Ne PAS démarrer le timer automatiquement si sync_service est None
        if sync_service is not None:
            self._ensure_timer_started()
        
    def _ensure_timer_started(self):
        """Démarre le timer de vérification si nécessaire"""
        if self._timer_initialized:
            return
        self._timer_initialized = True
        self._start_check_timer()
        print("✅ NotificationManager: Timer de vérification démarré")
        
    def _start_check_timer(self):
        """Démarre le timer pour les vérifications périodiques"""
        def check_loop():
            # Attendre 30 secondes avant la première vérification
            import time
            time.sleep(30)
            
            while not self._stop_auto_check:
                try:
                    # Exécuter les vérifications
                    self.run_all_checks()
                    
                    # Attendre l'intervalle
                    for _ in range(self.check_interval):
                        if self._stop_auto_check:
                            break
                        time.sleep(1)
                        
                except Exception as e:
                    print(f"Erreur dans la boucle de vérification: {e}")
                    time.sleep(60)
        
        self._stop_auto_check = False
        self._check_thread = threading.Thread(target=check_loop, daemon=True)
        self._check_thread.start()
        
    def set_sync_service(self, sync_service):
        """Définit le service de synchronisation après l'initialisation"""
        self.sync_service = sync_service
        if sync_service:
            self.connection_manager.set_sync_service(sync_service)
            # Démarrer le timer maintenant que sync_service est défini
            self._ensure_timer_started()
        
    def _on_connection_status_changed(self, is_online: bool, force_mode: Optional[bool]):
        """Callback appelé quand le statut de connexion change"""
        print(f"🔔 NotificationManager: Statut connexion changé - online={is_online}, force={force_mode}")
        # Si on passe en mode auto et qu'on redevient online, relancer les vérifications
        if force_mode is None and is_online and self.sync_service is not None:
            self.check_sync_status()
        
    def _setup_notification_table(self):
        """Crée la table des notifications si elle n'existe pas"""
        try:
            with self.db.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS notifications (
                        id TEXT PRIMARY KEY,
                        type TEXT,
                        title TEXT,
                        message TEXT,
                        priority TEXT,
                        created_at TEXT,
                        read INTEGER DEFAULT 0,
                        action_data TEXT,
                        product_id TEXT,
                        product_name TEXT,
                        quantity INTEGER,
                        days_left INTEGER,
                        branch_id TEXT
                    )
                """)
                conn.commit()
        except Exception as e:
            print(f"Erreur création table notifications: {e}")
            
    def add_observer(self, callback: Callable):
        """Ajoute un observateur pour les changements d'alertes"""
        self.observers.append(callback)
        
    def remove_observer(self, callback: Callable):
        """Supprime un observateur"""
        if callback in self.observers:
            self.observers.remove(callback)
            
    def _notify_observers(self):
        """Notifie tous les observateurs du changement"""
        for callback in self.observers:
            try:
                callback(self.alerts)
            except Exception as e:
                print(f"Erreur notification observateur: {e}")
                
    def add_alert(self, alert: Alert, save_to_db: bool = True):
        """Ajoute une nouvelle alerte"""
        # Vérifier si une alerte similaire existe déjà (pour éviter les doublons)
        for existing in self.alerts:
            if (existing.type == alert.type and 
                existing.product_id == alert.product_id and
                not existing.read):
                # Mettre à jour l'alerte existante
                existing.message = alert.message
                existing.created_at = alert.created_at
                existing.days_left = alert.days_left
                existing.quantity = alert.quantity
                if save_to_db:
                    self._update_alert_in_db(existing)
                self._notify_observers()
                return
                
        self.alerts.insert(0, alert)
        
        if save_to_db:
            self._save_alert_to_db(alert)
            
        self._notify_observers()
        self._show_in_app_notification(alert)
        
        # Notification push pour les alertes haute priorité
        if alert.priority in [AlertPriority.HIGH, AlertPriority.CRITICAL]:
            if self.connection_manager.is_online_mode():
                self._send_push_notification(alert)
            
    def _save_alert_to_db(self, alert: Alert):
        """Sauvegarde l'alerte dans la base de données"""
        try:
            branch_id = None
            try:
                branch_id = self.auth_service.get_user_branch_id()
            except:
                pass
                
            with self.db.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT OR REPLACE INTO notifications
                    (id, type, title, message, priority, created_at, read, action_data,
                     product_id, product_name, quantity, days_left, branch_id)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    alert.id,
                    alert.type.value,
                    alert.title,
                    alert.message,
                    alert.priority.value,
                    alert.created_at.isoformat(),
                    1 if alert.read else 0,
                    json.dumps(alert.action_data) if alert.action_data else None,
                    alert.product_id,
                    alert.product_name,
                    alert.quantity,
                    alert.days_left,
                    branch_id
                ))
                conn.commit()
        except Exception as e:
            print(f"Erreur sauvegarde alerte: {e}")
            
    def _update_alert_in_db(self, alert: Alert):
        """Met à jour une alerte dans la base"""
        try:
            with self.db.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    UPDATE notifications
                    SET message = ?, days_left = ?, quantity = ?, created_at = ?
                    WHERE id = ?
                """, (
                    alert.message,
                    alert.days_left,
                    alert.quantity,
                    alert.created_at.isoformat(),
                    alert.id
                ))
                conn.commit()
        except Exception as e:
            print(f"Erreur mise à jour alerte: {e}")
            
    def mark_as_read(self, alert_id: str):
        """Marque une alerte comme lue"""
        for alert in self.alerts:
            if alert.id == alert_id:
                alert.read = True
                break
                
        try:
            with self.db.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("UPDATE notifications SET read = 1 WHERE id = ?", (alert_id,))
                conn.commit()
        except Exception as e:
            print(f"Erreur marquage comme lu: {e}")
            
        self._notify_observers()
        
    def mark_all_as_read(self):
        """Marque toutes les alertes comme lues"""
        for alert in self.alerts:
            alert.read = True
            
        try:
            branch_id = None
            try:
                branch_id = self.auth_service.get_user_branch_id()
            except:
                pass
                
            with self.db.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "UPDATE notifications SET read = 1 WHERE branch_id = ?",
                    (branch_id,)
                )
                conn.commit()
        except Exception as e:
            print(f"Erreur marquage tout comme lu: {e}")
            
        self._notify_observers()
        
    def get_unread_count(self) -> int:
        """Retourne le nombre d'alertes non lues"""
        return sum(1 for alert in self.alerts if not alert.read)
        
    def load_alerts_from_db(self):
        """Charge les alertes depuis la base de données"""
        try:
            branch_id = None
            try:
                branch_id = self.auth_service.get_user_branch_id()
            except:
                pass
                
            with self.db.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT * FROM notifications
                    WHERE branch_id = ? OR branch_id IS NULL
                    ORDER BY created_at DESC
                    LIMIT 100
                """, (branch_id,))
                
                self.alerts = []
                for row in cursor.fetchall():
                    try:
                        alert = Alert(
                            id=row[0],
                            type=AlertType(row[1]),
                            title=row[2],
                            message=row[3],
                            priority=AlertPriority(row[4]),
                            created_at=datetime.fromisoformat(row[5]),
                            read=bool(row[6]),
                            action_data=json.loads(row[7]) if row[7] else None,
                            product_id=row[8],
                            product_name=row[9],
                            quantity=row[10],
                            days_left=row[11]
                        )
                        self.alerts.append(alert)
                    except Exception as e:
                        print(f"Erreur chargement alerte: {e}")
                        continue
        except Exception as e:
            print(f"Erreur chargement alertes DB: {e}")
            
        self._notify_observers()
        
    def _show_in_app_notification(self, alert: Alert):
        """Affiche une notification dans l'application"""
        if not self.page:
            return
            
        color_map = {
            AlertPriority.LOW: ft.Colors.BLUE_400,
            AlertPriority.MEDIUM: ft.Colors.ORANGE_400,
            AlertPriority.HIGH: ft.Colors.RED_400,
            AlertPriority.CRITICAL: ft.Colors.RED_900
        }
        
        try:
            snack = ft.SnackBar(
                content=ft.Row([
                    ft.Icon(
                        self._get_alert_icon(alert.type),
                        color=ft.Colors.WHITE,
                        size=20
                    ),
                    ft.Column([
                        ft.Text(alert.title, size=14, weight=ft.FontWeight.BOLD, color=ft.Colors.WHITE),
                        ft.Text(alert.message, size=12, color=ft.Colors.WHITE_70),
                    ], spacing=2, expand=True)
                ], spacing=10),
                bgcolor=color_map.get(alert.priority, ft.Colors.BLUE_700),
                duration=6000 if alert.priority in [AlertPriority.HIGH, AlertPriority.CRITICAL] else 4000,
                show_close_icon=True,
            )
            
            self.page.snack_bar = snack
            snack.open = True
            self.page.update()
        except Exception as e:
            print(f"Erreur affichage notification: {e}")
        
    def _send_push_notification(self, alert: Alert):
        """Envoie une notification push (pour mobile)"""
        # Pour l'instant, on ne fait rien
        pass
            
    def _get_alert_icon(self, alert_type: AlertType) -> str:
        """Retourne l'icône appropriée pour le type d'alerte"""
        icons = {
            AlertType.LOW_STOCK: ft.Icons.WARNING_AMBER,
            AlertType.OUT_OF_STOCK: ft.Icons.ERROR,
            AlertType.EXPIRING_SOON: ft.Icons.HOURGLASS_EMPTY,
            AlertType.EXPIRED: ft.Icons.DANGEROUS,
            AlertType.SUBSCRIPTION_RENEWAL: ft.Icons.UPDATE,
            AlertType.DEBT_REMINDER: ft.Icons.MONEY_OFF,
            AlertType.SYNC_ERROR: ft.Icons.SYNC_PROBLEM,
            AlertType.DAILY_SALES: ft.Icons.TRENDING_UP,
            AlertType.WEEKLY_REPORT: ft.Icons.ASSESSMENT
        }
        return icons.get(alert_type, ft.Icons.NOTIFICATIONS)
        
    # =========================================================
    # VÉRIFICATIONS AUTOMATIQUES
    # =========================================================
    
    def check_low_stock(self):
        """Vérifie les produits en rupture ou stock faible (toujours actif)"""
        try:
            branch_id = None
            try:
                branch_id = self.auth_service.get_user_branch_id()
            except:
                pass
                
            products = self.db.get_products(branch_id)
            
            for product in products:
                product_id = str(product.get("server_id") or product.get("id"))
                product_name = product.get("name", "Produit")
                quantity = product.get("quantity", 0) or product.get("stock", 0)
                threshold = product.get("alert_threshold", product.get("min_stock", 10))
                
                if quantity <= 0:
                    alert = Alert(
                        id=f"outofstock_{product_id}_{datetime.now().timestamp()}",
                        type=AlertType.OUT_OF_STOCK,
                        title="⚠️ Rupture de stock",
                        message=f"{product_name} n'est plus en stock !",
                        priority=AlertPriority.HIGH,
                        created_at=datetime.now(),
                        action_data={"product_id": product_id, "action": "restock"},
                        product_id=product_id,
                        product_name=product_name,
                        quantity=0
                    )
                    self.add_alert(alert)
                    
                elif quantity <= threshold:
                    alert = Alert(
                        id=f"lowstock_{product_id}_{datetime.now().timestamp()}",
                        type=AlertType.LOW_STOCK,
                        title="📦 Stock faible",
                        message=f"{product_name}: plus que {quantity} unité(s) en stock",
                        priority=AlertPriority.MEDIUM if quantity <= 3 else AlertPriority.LOW,
                        created_at=datetime.now(),
                        action_data={"product_id": product_id, "action": "order"},
                        product_id=product_id,
                        product_name=product_name,
                        quantity=quantity
                    )
                    self.add_alert(alert)
        except Exception as e:
            print(f"Erreur vérification low stock: {e}")
                
    def check_expiring_products(self):
        """Vérifie les produits proches de péremption (toujours actif)"""
        try:
            branch_id = None
            try:
                branch_id = self.auth_service.get_user_branch_id()
            except:
                pass
                
            products = self.db.get_products(branch_id)
            
            for product in products:
                expiry_date = product.get("expiry_date") or product.get("expiration_date")
                
                if not expiry_date:
                    continue
                    
                try:
                    if isinstance(expiry_date, str):
                        if "T" in expiry_date:
                            expiry_date = expiry_date.split("T")[0]
                        expiry = datetime.strptime(expiry_date, "%Y-%m-%d").date()
                    else:
                        expiry = expiry_date
                        
                    today = date.today()
                    days_left = (expiry - today).days
                    product_name = product.get("name", "Produit")
                    product_id = str(product.get("server_id") or product.get("id"))
                    
                    if days_left < 0:
                        alert = Alert(
                            id=f"expired_{product_id}_{datetime.now().timestamp()}",
                            type=AlertType.EXPIRED,
                            title="❌ Produit expiré",
                            message=f"{product_name} est expiré depuis {-days_left} jours",
                            priority=AlertPriority.CRITICAL,
                            created_at=datetime.now(),
                            action_data={"product_id": product_id, "action": "dispose"},
                            product_id=product_id,
                            product_name=product_name,
                            days_left=days_left
                        )
                        self.add_alert(alert)
                        
                    elif days_left <= 30:
                        priority = AlertPriority.HIGH if days_left <= 7 else AlertPriority.MEDIUM
                        alert = Alert(
                            id=f"expiring_{product_id}_{datetime.now().timestamp()}",
                            type=AlertType.EXPIRING_SOON,
                            title="⏰ Péremption imminente",
                            message=f"{product_name} expire dans {days_left} jours",
                            priority=priority,
                            created_at=datetime.now(),
                            action_data={"product_id": product_id, "action": "promote"},
                            product_id=product_id,
                            product_name=product_name,
                            days_left=days_left
                        )
                        self.add_alert(alert)
                        
                except Exception as e:
                    print(f"Erreur vérification expiration pour {product.get('name')}: {e}")
        except Exception as e:
            print(f"Erreur vérification expiring products: {e}")
                
    def check_debts(self):
        """Vérifie les dettes proches de l'échéance (toujours actif)"""
        try:
            branch_id = None
            try:
                branch_id = self.auth_service.get_user_branch_id()
            except:
                pass
                
            try:
                if hasattr(self.db, 'get_active_debts'):
                    debts = self.db.get_active_debts(branch_id)
                else:
                    debts = []
            except:
                debts = []
            
            for debt in debts:
                if isinstance(debt, dict):
                    due_date_str = debt.get("due_date")
                    customer_name = debt.get("customer_name", "Client")
                    remaining_amount = float(debt.get("remaining_amount", 0))
                    debt_id = debt.get("id")
                else:
                    due_date_str = getattr(debt, "due_date", None)
                    customer_name = getattr(debt, "customer_name", "Client")
                    remaining_amount = float(getattr(debt, "remaining_amount", 0))
                    debt_id = getattr(debt, "id", None)
                    
                if not due_date_str:
                    continue
                    
                try:
                    due_date = datetime.strptime(due_date_str, "%Y-%m-%d").date() if isinstance(due_date_str, str) else due_date_str
                    today = date.today()
                    days_left = (due_date - today).days
                    
                    if days_left <= 3 and remaining_amount > 0:
                        alert = Alert(
                            id=f"debt_{debt_id}_{datetime.now().timestamp()}",
                            type=AlertType.DEBT_REMINDER,
                            title="💰 Rappel de dette",
                            message=f"Client {customer_name}: {remaining_amount:,.0f} FC à payer dans {days_left} jours",
                            priority=AlertPriority.HIGH if days_left <= 0 else AlertPriority.MEDIUM,
                            created_at=datetime.now(),
                            action_data={"debt_id": str(debt_id) if debt_id else None, "action": "view_debt"},
                            product_name=customer_name
                        )
                        self.add_alert(alert)
                        
                except Exception as e:
                    print(f"Erreur vérification dette: {e}")
        except Exception as e:
            print(f"Erreur vérification debts: {e}")
                
    def check_subscriptions(self):
        """Vérifie les abonnements à renouveler (toujours actif)"""
        try:
            user = self.auth_service.get_current_user()
            if user and user.get("subscription_end_date"):
                try:
                    end_date = datetime.strptime(user["subscription_end_date"], "%Y-%m-%d").date()
                    today = date.today()
                    days_left = (end_date - today).days
                    
                    if days_left <= 30:
                        alert = Alert(
                            id=f"subscription_{datetime.now().timestamp()}",
                            type=AlertType.SUBSCRIPTION_RENEWAL,
                            title="🔄 Renouvellement abonnement",
                            message=f"Votre abonnement expire dans {days_left} jours. Veuillez renouveler.",
                            priority=AlertPriority.HIGH if days_left <= 7 else AlertPriority.MEDIUM,
                            created_at=datetime.now(),
                            action_data={"action": "renew_subscription"}
                        )
                        self.add_alert(alert)
                        
                except Exception as e:
                    print(f"Erreur vérification abonnement: {e}")
        except Exception as e:
            print(f"Erreur vérification subscriptions: {e}")
                
    def check_sync_status(self):
        """
        Vérifie les erreurs de synchronisation.
        ✅ Protection: ne rien faire si sync_service est None
        """
        # ✅ PROTECTION CRITIQUE: ne rien faire si sync_service n'existe pas
        if self.sync_service is None:
            return
            
        # Ne vérifier la sync que si on est en mode online
        if not self.connection_manager.is_online_mode():
            return
            
        try:
            # Vérifier que les méthodes existent
            if not hasattr(self.db, 'get_unsynced_sales'):
                return
                
            unsynced_sales = self.db.get_unsynced_sales()
            
            unsynced_expenses = []
            if hasattr(self.db, 'get_unsynced_expenses'):
                unsynced_expenses = self.db.get_unsynced_expenses()
            
            total_unsynced = len(unsynced_sales) + len(unsynced_expenses)
            
            if total_unsynced > 10:
                alert = Alert(
                    id=f"sync_{datetime.now().timestamp()}",
                    type=AlertType.SYNC_ERROR,
                    title="🔄 Problème de synchronisation",
                    message=f"{total_unsynced} élément(s) en attente de synchronisation",
                    priority=AlertPriority.MEDIUM,
                    created_at=datetime.now(),
                    action_data={"action": "sync_now"}
                )
                self.add_alert(alert)
            elif total_unsynced > 0:
                # Alerte moins prioritaire
                alert = Alert(
                    id=f"sync_pending_{datetime.now().timestamp()}",
                    type=AlertType.SYNC_ERROR,
                    title="🔄 Synchronisation en attente",
                    message=f"{total_unsynced} élément(s) à synchroniser",
                    priority=AlertPriority.LOW,
                    created_at=datetime.now(),
                    action_data={"action": "sync_now"}
                )
                self.add_alert(alert)
                
        except Exception as e:
            print(f"Erreur vérification sync status: {e}")
            
    def start_auto_check(self, interval_seconds: int = 300):
        """Démarre la vérification automatique des alertes"""
        self.check_interval = interval_seconds
        self.is_checking = True
        
        def check_loop():
            import time
            # Attendre un peu avant la première exécution
            time.sleep(15)
            while self.is_checking:
                try:
                    self.run_all_checks()
                    time.sleep(self.check_interval)
                except Exception as e:
                    print(f"Erreur dans la boucle de vérification: {e}")
                    time.sleep(60)
                    
        thread = threading.Thread(target=check_loop, daemon=True)
        thread.start()
        
    def stop_auto_check(self):
        """Arrête la vérification automatique"""
        self.is_checking = False
        
    def run_all_checks(self):
        """Exécute toutes les vérifications"""
        print(f"🔍 Exécution des vérifications d'alertes...")
        try:
            # Vérifications locales (toujours actives)
            self.check_low_stock()
            self.check_expiring_products()
            self.check_debts()
            self.check_subscriptions()
            
            # ✅ Vérification de synchronisation (seulement si sync_service disponible)
            if self.sync_service is not None:
                # Vérifier si on est en mode online avant de vérifier la sync
                if self.connection_manager.is_online_mode():
                    self.check_sync_status()
                else:
                    print("📡 Mode offline - vérification sync ignorée")
            else:
                print("⚠️ sync_service non disponible - vérification sync ignorée")
            
            unread_count = self.get_unread_count()
            print(f"✅ Vérifications terminées: {unread_count} alertes non lues")
            
        except Exception as e:
            print(f"❌ Erreur lors des vérifications: {e}")
            
    def force_run_all_checks(self):
        """Force l'exécution de toutes les vérifications (appel manuel)"""
        print("🔍 Exécution forcée des vérifications...")
        self.run_all_checks()
            
    # =========================================================
    # INTERFACE UTILISATEUR
    # =========================================================
    
    def create_notification_button(self) -> ft.Stack:
        """Crée un bouton de notification avec badge"""
        
        def on_notification_click(e):
            self.show_notification_center()
            
        self.notification_button = ft.IconButton(
            icon=ft.Icons.NOTIFICATIONS_NONE,
            icon_size=24,
            on_click=on_notification_click,
            icon_color=ft.Colors.WHITE,
        )
        
        self.notification_badge = ft.Container(
            content=ft.Text("0", size=10, color=ft.Colors.WHITE, text_align=ft.TextAlign.CENTER),
            bgcolor=ft.Colors.RED,
            border_radius=10,
            width=18,
            height=18,
            alignment=ft.Alignment(0, 0),
            visible=False,
        )
        
        return ft.Stack(
            controls=[
                self.notification_button,
                ft.Container(
                    content=self.notification_badge,
                    right=0,
                    top=0,
                ),
            ]
        )
        
    def update_notification_badge(self):
        """Met à jour le badge de notification"""
        if not self.notification_badge:
            return
            
        count = self.get_unread_count()
        if count > 0:
            self.notification_badge.content.value = str(count) if count < 100 else "99+"
            self.notification_badge.visible = True
            self.notification_button.icon = ft.Icons.NOTIFICATIONS_ACTIVE
        else:
            self.notification_badge.visible = False
            self.notification_button.icon = ft.Icons.NOTIFICATIONS_NONE
            
        if self.page:
            try:
                self.page.update()
            except:
                pass
            
    def show_notification_center(self):
        """Affiche le centre de notifications"""
        
        def on_mark_all_read(e):
            self.mark_all_as_read()
            self.update_notification_badge()
            refresh_alerts()
            
        def on_alert_click(alert: Alert):
            # Marquer comme lue
            if not alert.read:
                self.mark_as_read(alert.id)
                self.update_notification_badge()
                
            # Action selon le type d'alerte
            if alert.action_data:
                action = alert.action_data.get("action")
                if action == "restock":
                    from screens.products_screen import ProductsScreen
                    products_screen = ProductsScreen(self.page, self.db, self.sync_service, self.auth_service, self.auth_service.get_current_user())
                    products_screen.show()
                elif action == "view_debt":
                    from screens.debt_screen import DebtScreen
                    debt_screen = DebtScreen(self.page, self.db, self.sync_service, self.auth_service, self.auth_service.get_current_user())
                    debt_screen.show()
                elif action == "sync_now":
                    if self.sync_service and self.connection_manager.is_online_mode():
                        # Lancer la synchronisation dans un thread séparé
                        def do_sync():
                            result = self.sync_service.sync_all()
                            print(f"Synchronisation terminée: {result}")
                        thread = threading.Thread(target=do_sync, daemon=True)
                        thread.start()
                    elif not self.connection_manager.is_online_mode():
                        print("⚠️ Impossible de synchroniser: mode offline")
                    
            # Fermer le dialogue
            dialog.open = False
            self.page.update()
            
        def refresh_alerts():
            alerts_list.controls.clear()
            
            if not self.alerts:
                alerts_list.controls.append(
                    ft.Container(
                        content=ft.Column([
                            ft.Icon(ft.Icons.NOTIFICATIONS_OFF, size=50, color=ft.Colors.GREY_400),
                            ft.Text("Aucune notification", color=ft.Colors.GREY_600),
                        ], horizontal_alignment=ft.CrossAxisAlignment.CENTER),
                        padding=40,
                    )
                )
            else:
                for alert in self.alerts[:50]:
                    alert_card = self._create_alert_card(alert, on_alert_click)
                    alerts_list.controls.append(alert_card)
                    
            self.page.update()
            
        alerts_list = ft.ListView(expand=True, spacing=10, padding=10)
        
        dialog = ft.AlertDialog(
            title=ft.Row([
                ft.Text("Notifications", size=20, weight=ft.FontWeight.BOLD, expand=True),
                ft.TextButton(
                    content=ft.Text("Tout marquer comme lu", size=12),
                    on_click=on_mark_all_read,
                ),
            ]),
            content=ft.Container(
                content=alerts_list,
                width=400,
                height=500,
            ),
            actions=[
                ft.TextButton("Fermer", on_click=lambda e: setattr(dialog, 'open', False) or self.page.update()),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
        )
        
        refresh_alerts()
        self.page.dialog = dialog
        dialog.open = True
        self.page.update()
        
    def _create_alert_card(self, alert: Alert, on_click) -> ft.Card:
        """Crée une carte d'alerte"""
        
        color_map = {
            AlertPriority.LOW: ft.Colors.BLUE_50,
            AlertPriority.MEDIUM: ft.Colors.ORANGE_50,
            AlertPriority.HIGH: ft.Colors.RED_50,
            AlertPriority.CRITICAL: ft.Colors.RED_100
        }
        
        bg_color = color_map.get(alert.priority, ft.Colors.GREY_50)
        if alert.read:
            bg_color = ft.Colors.GREY_50
            
        return ft.Card(
            content=ft.Container(
                content=ft.Row([
                    ft.Container(
                        content=ft.Icon(self._get_alert_icon(alert.type), size=24, color=ft.Colors.BLUE_700),
                        padding=10,
                    ),
                    ft.Column([
                        ft.Text(alert.title, size=14, weight=ft.FontWeight.BOLD),
                        ft.Text(alert.message, size=12, color=ft.Colors.GREY_700),
                        ft.Text(
                            alert.created_at.strftime("%d/%m/%Y %H:%M"),
                            size=10,
                            color=ft.Colors.GREY_500,
                        ),
                    ], spacing=4, expand=True),
                    ft.Icon(
                        ft.Icons.CIRCLE if not alert.read else ft.Icons.CIRCLE_OUTLINED,
                        size=12,
                        color=ft.Colors.BLUE if not alert.read else ft.Colors.GREY_400,
                    ),
                ], spacing=5),
                padding=12,
                bgcolor=bg_color,
                border_radius=8,
            ),
            margin=5,
            on_click=lambda e: on_click(alert),
        )
        
    def create_notification_panel(self) -> ft.Container:
        """Crée un panneau de notifications pour le dashboard"""
        
        def on_view_all(e):
            self.show_notification_center()
            
        alerts_preview = ft.Column(spacing=5)
        
        def update_preview():
            alerts_preview.controls.clear()
            
            unread_alerts = [a for a in self.alerts if not a.read][:5]
            
            if not unread_alerts:
                alerts_preview.controls.append(
                    ft.Text("Aucune nouvelle notification", color=ft.Colors.GREY_500, size=12)
                )
            else:
                for alert in unread_alerts:
                    alerts_preview.controls.append(
                        ft.Row([
                            ft.Icon(self._get_alert_icon(alert.type), size=16, color=ft.Colors.BLUE_700),
                            ft.Text(alert.title, size=12, weight=ft.FontWeight.BOLD, expand=True),
                            ft.Text(alert.created_at.strftime("%H:%M"), size=10, color=ft.Colors.GREY_500),
                        ]),
                    )
                    alerts_preview.controls.append(
                        ft.Text(alert.message, size=11, color=ft.Colors.GREY_600),
                    )
                    alerts_preview.controls.append(ft.Divider(height=1))
                    
            if self.page:
                try:
                    self.page.update()
                except:
                    pass
            
        self.add_observer(lambda _: update_preview())
        
        return ft.Container(
            content=ft.Column([
                ft.Row([
                    ft.Text("🔔 Notifications récentes", size=14, weight=ft.FontWeight.BOLD, expand=True),
                    ft.TextButton("Voir tout", on_click=on_view_all, style=ft.ButtonStyle(text_style=ft.TextStyle(size=11))),
                ]),
                ft.Divider(),
                alerts_preview,
            ], spacing=8),
            padding=10,
            bgcolor=ft.Colors.WHITE,
            border_radius=10,
            margin=5,
        )