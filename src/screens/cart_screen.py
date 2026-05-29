"""
Écran du panier d'achat - Version Responsive
Gère l'affichage, la modification et la finalisation des ventes
Adapté pour mobile, tablette et desktop
Version utilisant la configuration de config_screen.py
"""
import flet as ft
from datetime import datetime
from typing import List, Dict, Optional
from .cart_manager import CartManager
from utils.print_manager import PrintManager
from services.connection_manager import ConnectionManager
import logging

logger = logging.getLogger(__name__)


class CartScreen:
    """Écran de gestion du panier - Version Responsive"""
    
    def __init__(self, page: ft.Page, db, sync_service, auth_service, current_user):
        self.page = page
        self.db = db
        self.sync_service = sync_service
        self.auth_service = auth_service
        self.current_user = current_user
        
        self.cart_manager = CartManager(db)
        self.print_manager = PrintManager(page, db, current_user)
        self._is_header_initialized = False
        
        # ========== CONFIGURATION DEPUIS config_screen.py ==========
        # auto_invoice = True -> générer et afficher la facture après vente
        # auto_invoice = False -> sauvegarder la facture sans l'afficher
        self.auto_invoice = True
        self.confirm_before_sale = True
        self.print_receipt = True
        
        # ========== CONNECTION MANAGER ==========
        self.connection_manager = ConnectionManager()
        self.connection_manager.register_observer(self._on_connection_status_changed)
        self._is_online = self.connection_manager.is_online_mode()
        
        # Éléments d'interface
        self.cart_list_view = None
        self.total_text = None
        self.customer_name_field = None
        self.payment_method_dropdown = None
        self.cart_items = []
        
        # Cache pour éviter les requêtes DB redondantes
        self._total_cache = 0.0
        self._update_timer = None
        
        # Indicateur de connexion
        self.connection_indicator = None
        
        # Cache pour le numéro de facture serveur
        self._server_invoice_number = None
        
        # Charger la configuration
        self._load_configuration()
        
    # ==================== CHARGEMENT CONFIGURATION ====================
    
    def _load_configuration(self):
        """Charge la configuration depuis la base de données (compatible config_screen)"""
        try:
            with self.db.get_connection() as conn:
                cursor = conn.cursor()
                
                # Créer la table si elle n'existe pas
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS app_config (
                        key TEXT PRIMARY KEY,
                        value TEXT,
                        updated_at TEXT
                    )
                """)
                conn.commit()
                
                # Valeurs par défaut
                self.auto_invoice = True
                self.confirm_before_sale = True
                self.print_receipt = True
                
                # Récupérer auto_invoice
                cursor.execute("SELECT value FROM app_config WHERE key = 'auto_invoice'")
                row = cursor.fetchone()
                if row:
                    self.auto_invoice = row[0].lower() == 'true'
                    logger.info(f"📋 auto_invoice chargé depuis DB: {self.auto_invoice}")
                else:
                    self._save_config('auto_invoice', 'true')
                    self.auto_invoice = True
                    logger.info(f"📋 auto_invoice non trouvé, valeur par défaut: {self.auto_invoice}")
                
                # Récupérer confirm_before_sale
                cursor.execute("SELECT value FROM app_config WHERE key = 'confirm_before_sale'")
                row = cursor.fetchone()
                if row:
                    self.confirm_before_sale = row[0].lower() == 'true'
                    logger.info(f"📋 confirm_before_sale chargé depuis DB: {self.confirm_before_sale}")
                else:
                    self._save_config('confirm_before_sale', 'true')
                    self.confirm_before_sale = True
                    logger.info(f"📋 confirm_before_sale non trouvé, valeur par défaut: {self.confirm_before_sale}")
                
                # Récupérer print_receipt
                cursor.execute("SELECT value FROM app_config WHERE key = 'print_receipt'")
                row = cursor.fetchone()
                if row:
                    self.print_receipt = row[0].lower() == 'true'
                    logger.info(f"📋 print_receipt chargé depuis DB: {self.print_receipt}")
                else:
                    self._save_config('print_receipt', 'true')
                    self.print_receipt = True
                    logger.info(f"📋 print_receipt non trouvé, valeur par défaut: {self.print_receipt}")
                
                logger.info(f"✅ Configuration finale chargée: auto_invoice={self.auto_invoice}, "
                        f"confirm_before_sale={self.confirm_before_sale}, "
                        f"print_receipt={self.print_receipt}")
                
        except Exception as e:
            logger.error(f"❌ Erreur chargement configuration: {e}")
            # Valeurs par défaut en cas d'erreur
            self.auto_invoice = True
            self.confirm_before_sale = True
            self.print_receipt = True
            logger.warning(f"⚠️ Utilisation des valeurs par défaut: auto_invoice={self.auto_invoice}")
    
    def _save_config(self, key: str, value: str):
        """Sauvegarde une configuration dans la base de données"""
        try:
            with self.db.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT OR REPLACE INTO app_config (key, value, updated_at)
                    VALUES (?, ?, ?)
                """, (key, value, datetime.now().isoformat()))
                conn.commit()
        except Exception as e:
            logger.error(f"Erreur sauvegarde configuration {key}: {e}")
    
    # ==================== GESTION STATUT CONNEXION ====================
    
    def _on_connection_status_changed(self, is_online: bool, force_mode: Optional[bool]):
        """Callback appelé quand le statut de connexion change"""
        self._is_online = is_online
        
        if self._is_header_initialized and self.connection_indicator:
            self.update_connection_indicator()
            self.page.update()
        
        status = self.connection_manager.get_display_status()
        self.show_success_dialog("Mode", f"Mode: {status['text']}")
    
    def update_connection_indicator(self):
        """Met à jour l'indicateur de connexion"""
        if not self.connection_indicator:
            return
        
        status = self.connection_manager.get_display_status()
        
        if status["color"] == "green":
            color = ft.Colors.GREEN
            tooltip = "Mode Online - Ventes enregistrées directement sur le serveur"
        elif status["color"] == "blue":
            color = ft.Colors.BLUE
            tooltip = "Mode Online forcé - Ventes enregistrées directement sur le serveur"
        elif status["color"] == "orange":
            color = ft.Colors.ORANGE
            tooltip = "Mode Offline forcé - Ventes enregistrées localement"
        else:
            color = ft.Colors.RED
            tooltip = "Mode Offline - Ventes enregistrées localement"
        
        icon = ft.Icons.WIFI if status["icon"] in ["🌐", "🔌"] else ft.Icons.WIFI_OFF
        
        self.connection_indicator.content = ft.Row(
            [
                ft.Icon(icon, color=color, size=16),
                ft.Text(status["text"], size=11, color=color, weight=ft.FontWeight.BOLD),
            ],
            spacing=4,
        )
        self.connection_indicator.tooltip = tooltip
    
    def create_connection_indicator(self):
        """Crée l'indicateur de connexion pour le header"""
        status = self.connection_manager.get_display_status()
        
        if status["color"] == "green":
            color = ft.Colors.GREEN
        elif status["color"] == "blue":
            color = ft.Colors.BLUE
        elif status["color"] == "orange":
            color = ft.Colors.ORANGE
        else:
            color = ft.Colors.RED
        
        icon = ft.Icons.WIFI if status["icon"] in ["🌐", "🔌"] else ft.Icons.WIFI_OFF
        
        self.connection_indicator = ft.Container(
            content=ft.Row(
                [
                    ft.Icon(icon, color=color, size=16),
                    ft.Text(status["text"], size=11, color=color, weight=ft.FontWeight.BOLD),
                ],
                spacing=4,
            ),
            bgcolor=ft.Colors.WHITE,
            padding=ft.Padding.symmetric(horizontal=8, vertical=4),
            border_radius=15,
        )
        return self.connection_indicator
    
    # ==================== DIALOG POUR MOBILE ====================
    
    def show_success_dialog(self, title: str, message: str, details: dict = None):
        """Affiche un dialog de confirmation sur mobile"""
        content_controls = [
            ft.Icon(
                ft.Icons.CHECK_CIRCLE,
                size=50,
                color=ft.Colors.GREEN_700,
            ),
            ft.Text(
                title,
                size=20,
                weight=ft.FontWeight.BOLD,
                text_align=ft.TextAlign.CENTER,
            ),
            ft.Divider(height=10, color=ft.Colors.TRANSPARENT),
            ft.Text(
                message,
                size=14,
                text_align=ft.TextAlign.CENTER,
            ),
        ]
        
        if details:
            content_controls.append(ft.Divider(height=5, color=ft.Colors.TRANSPARENT))
            for key, value in details.items():
                if value:
                    content_controls.append(
                        ft.Text(
                            f"{key}: {value}",
                            size=12,
                            color=ft.Colors.GREY_700,
                            text_align=ft.TextAlign.CENTER,
                        )
                    )
        
        content_controls.append(ft.Divider(height=10, color=ft.Colors.TRANSPARENT))
        
        dialog = ft.AlertDialog(
            title=ft.Text("", size=0),
            content=ft.Container(
                content=ft.Column(
                    controls=content_controls,
                    horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                    spacing=8,
                ),
                padding=20,
                width=300,
            ),
            actions=[
                ft.TextButton(
                    "OK",
                    on_click=lambda e: self.close_dialog(dialog),
                    style=ft.ButtonStyle(color=ft.Colors.GREEN_700),
                ),
            ],
            actions_alignment=ft.MainAxisAlignment.CENTER,
            shape=ft.RoundedRectangleBorder(radius=20),
        )
        
        self.page.dialog = dialog
        dialog.open = True
        self.page.update()
    
    def close_dialog(self, dialog):
        """Ferme le dialog"""
        dialog.open = False
        self.page.update()
    
    def show_invoice_dialog(self, sale_data_list: list, invoice_number: str, total_amount: float, is_online: bool):
        """Affiche un dialog avec les détails de la facture"""
        status_text = "✅ Vente en ligne" if is_online else "📱 Vente hors-ligne"
        status_color = ft.Colors.GREEN_700 if is_online else ft.Colors.BLUE_700
        
        # Construire la liste des articles
        items_controls = []
        for item in sale_data_list:
            items_controls.append(
                ft.Row(
                    controls=[
                        ft.Text(item['product_name'], size=13, expand=True),
                        ft.Text(f"x{item['quantity']}", size=13),
                        ft.Text(
                            self._format_money(item['total_price']),
                            size=13,
                            weight=ft.FontWeight.BOLD,
                            color=ft.Colors.GREEN_700,
                        ),
                    ],
                    alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                )
            )
        
        dialog = ft.AlertDialog(
            title=ft.Text(
                "🧾 FACTURE",
                size=18,
                weight=ft.FontWeight.BOLD,
                text_align=ft.TextAlign.CENTER,
            ),
            content=ft.Container(
                content=ft.Column(
                    controls=[
                        ft.Container(
                            content=ft.Column(
                                controls=[
                                    ft.Text(
                                        invoice_number,
                                        size=14,
                                        weight=ft.FontWeight.BOLD,
                                        text_align=ft.TextAlign.CENTER,
                                    ),
                                    ft.Text(
                                        datetime.now().strftime("%d/%m/%Y %H:%M"),
                                        size=12,
                                        color=ft.Colors.GREY_600,
                                        text_align=ft.TextAlign.CENTER,
                                    ),
                                ],
                                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                                spacing=4,
                            ),
                            padding=10,
                            bgcolor=ft.Colors.GREY_100,
                            border_radius=10,
                        ),
                        ft.Divider(),
                        ft.Text("Articles", size=14, weight=ft.FontWeight.BOLD),
                        ft.Column(items_controls, spacing=5, scroll=ft.ScrollMode.AUTO, height=200),
                        ft.Divider(),
                        ft.Row(
                            controls=[
                                ft.Text("TOTAL", size=16, weight=ft.FontWeight.BOLD),
                                ft.Text(
                                    self._format_money(total_amount),
                                    size=16,
                                    weight=ft.FontWeight.BOLD,
                                    color=ft.Colors.GREEN_700,
                                ),
                            ],
                            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                        ),
                        ft.Divider(height=10, color=ft.Colors.TRANSPARENT),
                        ft.Container(
                            content=ft.Text(
                                status_text,
                                size=12,
                                color=status_color,
                                text_align=ft.TextAlign.CENTER,
                            ),
                            padding=ft.Padding.symmetric(vertical=5, horizontal=10),
                            bgcolor=ft.Colors.GREY_100,
                            border_radius=15,
                        ),
                    ],
                    spacing=8,
                ),
                padding=15,
                width=350,
                height=450,
            ),
            actions=[
                ft.TextButton(
                    "IMPRIMER",
                    on_click=lambda e: self._print_invoice_and_close(dialog, sale_data_list, invoice_number, total_amount, is_online),
                    style=ft.ButtonStyle(color=ft.Colors.BLUE_700),
                ),
                ft.TextButton(
                    "FERMER",
                    on_click=lambda e: self.close_dialog(dialog),
                    style=ft.ButtonStyle(color=ft.Colors.GREY_700),
                ),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
            shape=ft.RoundedRectangleBorder(radius=20),
        )
        
        self.page.dialog = dialog
        dialog.open = True
        self.page.update()
    
    def _print_invoice_and_close(self, dialog, sale_data_list, invoice_number, total_amount, is_online):
        """Imprime la facture et ferme le dialog"""
        dialog.open = False
        self.page.update()
        
        ticket_data = {
            'sales_data': sale_data_list,
            'customer_name': self.customer_name_field.value.strip() if self.customer_name_field else "Client comptant",
            'total_amount': total_amount,
            'payment_method': self.payment_method_dropdown.value if self.payment_method_dropdown else "cash",
            'seller_name': self.current_user.get('full_name', 'Vendeur'),
            'branch_name': self.current_user.get('branch_name', 'MédiGest Pro'),
            'invoice_number': invoice_number,
            'sale_date': datetime.now().strftime('%d/%m/%Y %H:%M'),
        }
        
        self.print_multiple_sale_ticket(ticket_data)
    
    # ==================== NUMÉROS DE FACTURE SERVEUR ====================
    def _get_local_sequential_number(self) -> int:
        """Génère un numéro séquentiel local (1-9999)"""
        try:
            with self.db.get_connection() as conn:
                cursor = conn.cursor()
                # Récupérer le dernier numéro local utilisé aujourd'hui
                today = datetime.now().strftime("%Y%m%d")
                cursor.execute("""
                    SELECT MAX(CAST(SUBSTR(invoice_number, -4) AS INTEGER)) as last_num
                    FROM sales 
                    WHERE invoice_number LIKE 'LOCAL-%' 
                    AND invoice_number LIKE ?
                """, (f'LOCAL-{today}-%',))
                row = cursor.fetchone()
                
                last_num = row[0] if row and row[0] else 0
                next_num = last_num + 1
                
                # Limiter à 9999
                if next_num > 9999:
                    next_num = 1
                
                return next_num
                
        except Exception as e:
            logger.error(f"Erreur _get_local_sequential_number: {e}")
            return 1
    
    def get_next_invoice_number_from_server(self) -> Optional[str]:
        """Récupère le prochain numéro de facture depuis le serveur"""
        if not self.sync_service:
            return None
        
        try:
            headers = self.sync_service._get_headers()
            if not headers:
                return None
            
            user = self.auth_service.get_current_user()
            pharmacy_id = user.get('pharmacy_id')
            
            response = self.sync_service.session.get(
                f"{self.sync_service.api_url}/sales/next-invoice-number",
                headers=headers,
                params={"pharmacy_id": pharmacy_id},
                timeout=10
            )
            
            if response.status_code == 200:
                data = response.json()
                invoice_number = data.get('invoice_number')
                logger.info(f"📋 Nouveau numéro de facture serveur: {invoice_number}")
                return invoice_number
            else:
                logger.warning(f"Erreur récupération numéro facture: {response.status_code}")
                return None
                
        except Exception as e:
            logger.error(f"Erreur get_next_invoice_number_from_server: {e}")
            return None
    
    def confirm_invoice_number_on_server(self, invoice_number: str) -> bool:
        """Confirme l'utilisation d'un numéro de facture sur le serveur"""
        if not self.sync_service:
            return False
        
        if invoice_number.startswith("LOCAL-"):
            logger.info(f"Numéro local, pas de confirmation serveur: {invoice_number}")
            return True
        
        try:
            headers = self.sync_service._get_headers()
            if not headers:
                return False
            
            user = self.auth_service.get_current_user()
            pharmacy_id = user.get('pharmacy_id')
            
            response = self.sync_service.session.post(
                f"{self.sync_service.api_url}/sales/confirm-invoice-number",
                headers=headers,
                json={
                    "invoice_number": invoice_number,
                    "pharmacy_id": pharmacy_id
                },
                timeout=10
            )
            
            if response.status_code == 200:
                logger.info(f"✅ Numéro facture confirmé sur le serveur: {invoice_number}")
                return True
            else:
                logger.warning(f"Erreur confirmation facture: {response.status_code}")
                return True  # Non bloquant
                
        except Exception as e:
            logger.error(f"Erreur confirm_invoice_number_on_server: {e}")
            return True  # Non bloquant
    
    def generate_local_invoice_number(self) -> str:
        """Génère un numéro de facture local unique avec séquence"""
        today = datetime.now().strftime("%Y%m%d")
        seq_num = self._get_local_sequential_number()
        return f"LOCAL-{today}-{seq_num:04d}"
    
    def _get_server_counter_from_sync(self) -> int:
        """Récupère le dernier compteur serveur via la synchronisation"""
        try:
            # Chercher la dernière facture serveur synchronisée
            with self.db.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT server_invoice_number FROM invoices 
                    WHERE server_invoice_number IS NOT NULL 
                    AND server_invoice_number LIKE 'INV-%'
                    ORDER BY id DESC LIMIT 1
                """)
                row = cursor.fetchone()
                
                if row:
                    import re
                    match = re.search(r'(\d+)$', row[0])
                    if match:
                        return int(match.group(1))
            
            # Si aucune, demander au serveur
            if self.sync_service and self._is_online:
                headers = self.sync_service._get_headers()
                if headers:
                    user = self.auth_service.get_current_user()
                    pharmacy_id = user.get('pharmacy_id')
                    
                    response = self.sync_service.session.get(
                        f"{self.sync_service.api_url}/sales/current-invoice-counter",
                        headers=headers,
                        params={"pharmacy_id": pharmacy_id},
                        timeout=10
                    )
                    
                    if response.status_code == 200:
                        data = response.json()
                        return data.get('current_counter', 0)
            
            return 0
            
        except Exception as e:
            logger.error(f"Erreur _get_server_counter: {e}")
            return 0
    
    def sync_invoice_counter_with_server(self):
        """Synchronise le compteur local avec le serveur après reconnexion"""
        if not self._is_online:
            logger.info("Mode offline, synchronisation différée")
            return
        
        try:
            logger.info("🔄 Synchronisation des numéros de facture...")
            
            # 1. Récupérer les factures locales non synchronisées
            with self.db.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT invoice_number, id 
                    FROM invoices 
                    WHERE sync_status = 'pending' OR sync_status IS NULL
                    AND invoice_number LIKE 'LOCAL-%'
                    ORDER BY created_at
                """)
                pending_invoices = cursor.fetchall()
            
            if not pending_invoices:
                logger.info("✅ Aucune facture locale en attente")
                return
            
            logger.info(f"📋 {len(pending_invoices)} facture(s) locale(s) en attente de synchronisation")
            
            # 2. Récupérer le dernier compteur serveur
            server_counter = self._get_server_counter_from_sync()
            logger.info(f"📊 Dernier compteur serveur: {server_counter}")
            
            # 3. Pour chaque facture locale, demander un mapping serveur
            for invoice in pending_invoices:
                local_number = invoice[0]
                
                # Demander au serveur de convertir le numéro local
                result = self._convert_local_to_server_invoice(local_number)
                
                if result and result.get('server_invoice_number'):
                    # Mettre à jour la facture locale avec le numéro serveur
                    with self.db.get_connection() as conn:
                        cursor = conn.cursor()
                        cursor.execute("""
                            UPDATE invoices 
                            SET server_invoice_number = ?,
                                sync_status = 'synced',
                                sync_date = ?
                            WHERE invoice_number = ?
                        """, (result['server_invoice_number'], datetime.now().isoformat(), local_number))
                        
                        # Mettre à jour aussi dans la table sales
                        cursor.execute("""
                            UPDATE sales 
                            SET invoice_number = ?,
                                original_local_invoice = ?
                            WHERE invoice_number = ? AND is_synced = 0
                        """, (result['server_invoice_number'], local_number, local_number))
                        
                    logger.info(f"✅ Facture {local_number} → {result['server_invoice_number']}")
                else:
                    logger.warning(f"⚠️ Impossible de synchroniser {local_number}")
            
            conn.commit()
            
            # 4. Mettre à jour le compteur local
            self._update_local_counter_from_server()
            
            logger.info("✅ Synchronisation des factures terminée")
            
        except Exception as e:
            logger.error(f"Erreur sync_invoice_counter_with_server: {e}")
    
    def _convert_local_to_server_invoice(self, local_number: str) -> Optional[Dict]:
        """Demande au serveur de convertir un numéro local en numéro serveur"""
        try:
            headers = self.sync_service._get_headers()
            if not headers:
                return None
            
            user = self.auth_service.get_current_user()
            pharmacy_id = user.get('pharmacy_id')
            
            response = self.sync_service.session.post(
                f"{self.sync_service.api_url}/sales/convert-local-invoice",
                headers=headers,
                json={
                    "local_invoice_number": local_number,
                    "pharmacy_id": pharmacy_id,
                    "sale_data": self._get_sale_data_by_invoice(local_number)
                },
                timeout=15
            )
            
            if response.status_code == 200:
                return response.json()
            else:
                logger.error(f"Erreur conversion: {response.status_code}")
                return None
                
        except Exception as e:
            logger.error(f"Erreur _convert_local_to_server_invoice: {e}")
            return None
    
    def _get_sale_data_by_invoice(self, invoice_number: str) -> Dict:
        """Récupère les données de vente pour une facture locale"""
        try:
            with self.db.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT * FROM sales 
                    WHERE invoice_number = ? 
                    LIMIT 1
                """, (invoice_number,))
                row = cursor.fetchone()
                if row:
                    return dict(row)
                return {}
        except Exception as e:
            logger.error(f"Erreur _get_sale_data_by_invoice: {e}")
            return {}
    
    def _update_local_counter_from_server(self):
        """Met à jour le compteur local avec la valeur du serveur"""
        try:
            headers = self.sync_service._get_headers()
            if not headers:
                return
            
            user = self.auth_service.get_current_user()
            pharmacy_id = user.get('pharmacy_id')
            
            response = self.sync_service.session.get(
                f"{self.sync_service.api_url}/sales/current-invoice-counter",
                headers=headers,
                params={"pharmacy_id": pharmacy_id},
                timeout=10
            )
            
            if response.status_code == 200:
                data = response.json()
                server_counter = data.get('current_counter', 0)
                
                if server_counter > 0:
                    with self.db.get_connection() as conn:
                        cursor = conn.cursor()
                        cursor.execute("""
                            UPDATE invoice_counter 
                            SET current_number = max(current_number, ?),
                                last_synced = ?
                            WHERE id = 1
                        """, (server_counter + 1, datetime.now().isoformat()))
                        conn.commit()
                    logger.info(f"📊 Compteur local mis à jour: {server_counter + 1}")
                    
        except Exception as e:
            logger.error(f"Erreur _update_local_counter_from_server: {e}")
    
    def check_and_sync_invoices(self):
        """Vérifie et synchronise les factures lors de la reconnexion internet"""
        # À appeler dans _on_connection_status_changed quand internet revient
        if self._is_online:
            logger.info("🌐 Connexion internet rétablie, synchronisation des factures...")
            self.sync_invoice_counter_with_server()
    # =========================================================
    # OUTILS RESPONSIVE
    # =========================================================
    
    def is_mobile(self):
        """Détecte si l'appareil est mobile (largeur < 600px)"""
        return (self.page.width or 0) < 600
    
    def is_tablet(self):
        """Détecte si l'appareil est une tablette (600px - 1024px)"""
        width = self.page.width or 0
        return 600 <= width < 1024
    
    def get_card_width(self):
        """Retourne la largeur des cartes selon l'appareil"""
        if self.is_mobile():
            return None
        elif self.is_tablet():
            return 400
        return 500
    
    def get_font_size(self, base_size):
        """Ajuste la taille de police selon l'appareil"""
        if self.is_mobile():
            return base_size - 2
        return base_size
    
    def get_padding(self, default=15):
        """Ajuste le padding selon l'appareil"""
        if self.is_mobile():
            return 10
        return default
    
    # =========================================================
    # OUTILS
    # =========================================================
    
    def _branch_id(self) -> Optional[str]:
        """Récupère l'ID de la branche"""
        branch_id = (self.current_user.get("active_branch_id") or 
                    self.current_user.get("branch_id") or
                    self.current_user.get("current_branch_id"))
        
        if not branch_id:
            print("⚠️ ATTENTION: Aucun branch_id trouvé")
            return None
        
        return str(branch_id)
    
    def _safe_int(self, value, default=0):
        try:
            if value is None or value == "":
                return default
            return int(float(value))
        except Exception:
            return default
    
    def _safe_float(self, value, default=0.0):
        try:
            if value is None or value == "":
                return default
            return float(value)
        except Exception:
            return default
    
    def _format_money(self, amount):
        try:
            return f"{float(amount):,.0f} FC"
        except Exception:
            return "0 FC"
    
    def _format_money_no_currency(self, amount):
        try:
            return f"{float(amount):,.0f}"
        except Exception:
            return "0"
    
    # =========================================================
    # CHARGEMENT DES DONNÉES (OPTIMISÉ)
    # =========================================================
    
    def load_cart_items(self):
        """Charge les articles du panier depuis la base"""
        self.cart_items = self.cart_manager.get_cart_items()
        self._update_total_cache()
        self.update_cart_display()
    
    def _update_total_cache(self):
        """Met à jour le cache du total sans requête DB"""
        self._total_cache = sum(item.get('total_price', 0) for item in self.cart_items)
    
    def update_cart_display(self):
        """Met à jour l'affichage du panier avec calculs corrects"""
        if not self.cart_list_view:
            return
        
        scroll_offset = None
        if hasattr(self.cart_list_view, 'offset') and self.cart_list_view.offset:
            scroll_offset = self.cart_list_view.offset
        
        self.cart_list_view.controls.clear()
        
        if not self.cart_items:
            self._show_empty_cart_message()
        else:
            # ✅ CORRECTION 4: Recalculer tous les totaux avant affichage
            corrected_total = 0
            for item in self.cart_items:
                # Recalculer le total_price si nécessaire
                if item.get('total_price', 0) != item.get('quantity', 0) * item.get('unit_price', 0):
                    item['total_price'] = item.get('quantity', 0) * item.get('unit_price', 0)
                corrected_total += item.get('total_price', 0)
            
            # Mettre à jour le cache
            self._total_cache = corrected_total
            
            for item in self.cart_items:
                self.cart_list_view.controls.append(
                    self.create_cart_item_card(item)
                )
        
        if self.total_text:
            self.total_text.value = self._format_money(self._total_cache)
        
        if scroll_offset is not None:
            self.cart_list_view.scroll_to(offset=scroll_offset, duration=0)
        
        self.page.update()
    
    def _show_empty_cart_message(self):
        """Affiche le message de panier vide (responsive)"""
        self.cart_list_view.controls.append(
            ft.Container(
                content=ft.Column(
                    controls=[
                        ft.Icon(ft.Icons.SHOPPING_CART_OUTLINED, 
                               size=60 if self.is_mobile() else 80, 
                               color=ft.Colors.GREY_400),
                        ft.Text("Votre panier est vide", 
                               size=self.get_font_size(18), 
                               color=ft.Colors.GREY_600),
                        ft.Text("Ajoutez des produits depuis l'écran de vente", 
                               size=self.get_font_size(14), 
                               color=ft.Colors.GREY_500),
                        ft.Button(
                            "Continuer les achats",
                            icon=ft.Icons.SHOPPING_BAG,
                            on_click=lambda e: self.go_back(),
                            style=ft.ButtonStyle(
                                color=ft.Colors.WHITE,
                                bgcolor=ft.Colors.BLUE_700,
                            ),
                        ),
                    ],
                    horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                    spacing=15,
                ),
                padding=ft.Padding.all(30 if self.is_mobile() else 50),
                alignment=ft.Alignment.CENTER,
                expand=True,
            )
        )
    
    def create_cart_item_card(self, item: Dict) -> ft.Card:
        """Crée une carte pour un article du panier avec calcul correct"""
        item_id = item.get('id')
        product_name = item.get('product_name', 'Produit')
        quantity = item.get('quantity', 1)
        unit_price = self._safe_float(item.get('unit_price', 0))
        # ✅ CORRECTION 5: Recalculer le total_price pour être sûr
        total_price = quantity * unit_price
        
        is_mobile = self.is_mobile()
        
        # Stocker unit_price dans un attribut accessible
        item_unit_price = unit_price
        
        quantity_field = ft.TextField(
            value=str(quantity),
            width=50 if is_mobile else 60,
            height=40,
            text_align=ft.TextAlign.CENTER,
            border_radius=5,
            border_color=ft.Colors.GREY_400,
            content_padding=ft.Padding.symmetric(horizontal=5, vertical=0),
        )
        
        total_price_text = ft.Text(
            self._format_money(total_price),
            size=14 if is_mobile else 16,
            weight=ft.FontWeight.BOLD,
            color=ft.Colors.GREEN_700,
        )
        
        def update_display_after_change():
            try:
                new_qty = int(quantity_field.value)
                if new_qty <= 0:
                    self.remove_item_instant(item_id)
                    return
                
                # ✅ CORRECTION 6: Recalculer avec la valeur actuelle de unit_price
                new_total = new_qty * item_unit_price
                
                # Mettre à jour l'affichage local
                total_price_text.value = self._format_money(new_total)
                
                # Mettre à jour les données en mémoire
                for cart_item in self.cart_items:
                    if cart_item.get('id') == item_id:
                        cart_item['quantity'] = new_qty
                        cart_item['total_price'] = new_total
                        break
                
                # Recalculer le total global
                self._total_cache = sum(i.get('total_price', 0) for i in self.cart_items)
                
                if self.total_text:
                    self.total_text.value = self._format_money(self._total_cache)
                
                self.page.update()
            except ValueError:
                pass
        
        def on_decrement(e):
            current_qty = self._safe_int(quantity_field.value, 1)
            if current_qty > 1:
                new_qty = current_qty - 1
                quantity_field.value = str(new_qty)
                # ✅ CORRECTION 7: Mettre à jour en base de données
                self.update_quantity_async(item_id, new_qty)
                update_display_after_change()
        
        def on_increment(e):
            current_qty = self._safe_int(quantity_field.value, 1)
            new_qty = current_qty + 1
            quantity_field.value = str(new_qty)
            # ✅ CORRECTION 8: Mettre à jour en base de données
            self.update_quantity_async(item_id, new_qty)
            update_display_after_change()
            
        def on_quantity_change(e):
            try:
                new_qty = int(quantity_field.value)
                if new_qty > 0:
                    self.update_quantity_async(item_id, new_qty)
                    update_display_after_change()
                else:
                    quantity_field.value = "1"
                    self.update_quantity_async(item_id, 1)
                    update_display_after_change()
            except ValueError:
                quantity_field.value = "1"
                self.update_quantity_async(item_id, 1)
                update_display_after_change()
        
        quantity_field.on_change = on_quantity_change
        
        if is_mobile:
            return ft.Card(
                content=ft.Container(
                    padding=ft.Padding.all(10),
                    content=ft.Column(
                        controls=[
                            ft.Row(
                                controls=[
                                    ft.Container(
                                        content=ft.Icon(ft.Icons.MEDICATION, size=35, color=ft.Colors.BLUE_400),
                                        width=45,
                                        height=45,
                                        border_radius=10,
                                        bgcolor=ft.Colors.BLUE_50,
                                    ),
                                    ft.Column(
                                        controls=[
                                            ft.Text(product_name, size=15, weight=ft.FontWeight.BOLD),
                                            ft.Text(f"Prix: {self._format_money(unit_price)}", size=11, color=ft.Colors.GREY_600),
                                        ],
                                        spacing=2,
                                        expand=True,
                                    ),
                                    ft.IconButton(
                                        icon=ft.Icons.DELETE_OUTLINE,
                                        icon_size=22,
                                        icon_color=ft.Colors.RED_400,
                                        on_click=lambda e, iid=item_id: self.remove_item_instant(iid),
                                        tooltip="Supprimer",
                                    ),
                                ],
                                vertical_alignment=ft.CrossAxisAlignment.CENTER,
                            ),
                            ft.Row(
                                controls=[
                                    ft.Text("Qté:", size=13),
                                    ft.IconButton(
                                        icon=ft.Icons.REMOVE_CIRCLE_OUTLINE,
                                        icon_size=24,
                                        on_click=on_decrement,
                                    ),
                                    quantity_field,
                                    ft.IconButton(
                                        icon=ft.Icons.ADD_CIRCLE_OUTLINE,
                                        icon_size=24,
                                        on_click=on_increment,
                                    ),
                                    ft.Container(expand=True),
                                    total_price_text,
                                ],
                                vertical_alignment=ft.CrossAxisAlignment.CENTER,
                                spacing=5,
                            ),
                        ],
                        spacing=8,
                    ),
                ),
                margin=ft.Margin.symmetric(vertical=5, horizontal=0),
            )
        else:
            return ft.Card(
                content=ft.Container(
                    padding=ft.Padding.all(12),
                    content=ft.Row(
                        controls=[
                            ft.Container(
                                content=ft.Icon(ft.Icons.MEDICATION, size=40, color=ft.Colors.BLUE_400),
                                width=50,
                                height=50,
                                border_radius=10,
                                bgcolor=ft.Colors.BLUE_50,
                            ),
                            ft.Column(
                                controls=[
                                    ft.Text(product_name, size=16, weight=ft.FontWeight.BOLD),
                                    ft.Text(f"Prix unitaire: {self._format_money(unit_price)}", size=12, color=ft.Colors.GREY_600),
                                ],
                                spacing=2,
                                expand=True,
                            ),
                            ft.Column(
                                controls=[
                                    ft.Row(
                                        controls=[
                                            ft.IconButton(
                                                icon=ft.Icons.REMOVE_CIRCLE_OUTLINE,
                                                icon_size=28,
                                                on_click=on_decrement,
                                                tooltip="Diminuer",
                                            ),
                                            quantity_field,
                                            ft.IconButton(
                                                icon=ft.Icons.ADD_CIRCLE_OUTLINE,
                                                icon_size=28,
                                                on_click=on_increment,
                                                tooltip="Augmenter",
                                            ),
                                        ],
                                        alignment=ft.MainAxisAlignment.CENTER,
                                        spacing=5,
                                    ),
                                    total_price_text,
                                ],
                                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                                spacing=5,
                            ),
                            ft.IconButton(
                                icon=ft.Icons.DELETE_OUTLINE,
                                icon_size=24,
                                icon_color=ft.Colors.RED_400,
                                on_click=lambda e, iid=item_id: self.remove_item_instant(iid),
                                tooltip="Supprimer",
                            ),
                        ],
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                        spacing=10,
                    ),
                ),
                margin=ft.Margin.symmetric(vertical=5, horizontal=0),
            )
    
    def update_total_display(self):
        """Met à jour l'affichage du total (instantané)"""
        if self.total_text:
            self.total_text.value = self._format_money(self._total_cache)
            self.page.update()
    
    def update_quantity_async(self, item_id: int, new_quantity: int):
        """Met à jour la quantité en arrière-plan avec calcul correct du total"""
        if new_quantity <= 0:
            self.remove_item_async(item_id)
            return
        
        for item in self.cart_items:
            if item.get('id') == item_id:
                # ✅ CORRECTION 1: Recalculer correctement le total_price
                unit_price = self._safe_float(item.get('unit_price', 0))
                new_total_price = new_quantity * unit_price
                
                item['quantity'] = new_quantity
                item['total_price'] = new_total_price
                break
        
        # ✅ CORRECTION 2: Recalculer le cache total
        self._update_total_cache()
        
        try:
            # ✅ CORRECTION 3: Mettre à jour la base avec le nouveau total
            with self.db.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    UPDATE cart_items 
                    SET quantity = ?, total_price = quantity * unit_price 
                    WHERE id = ?
                """, (new_quantity, item_id))
                conn.commit()
        except Exception as e:
            logger.error(f"Erreur mise à jour DB: {e}")
    
    def update_quantity(self, item_id: int, new_quantity: int):
        """Met à jour la quantité d'un article (synchrone - pour compatibilité)"""
        if new_quantity <= 0:
            self.remove_item(item_id)
            return
        
        success = self.cart_manager.update_quantity(item_id, new_quantity)
        
        if success:
            self.load_cart_items()
    
    def on_quantity_change(self, e, item_id: int, unit_price: float):
        """Gère le changement manuel de quantité"""
        try:
            new_quantity = int(e.control.value)
            if new_quantity > 0:
                self.update_quantity(item_id, new_quantity)
            else:
                e.control.value = "1"
                self.update_quantity(item_id, 1)
        except ValueError:
            e.control.value = "1"
            self.update_quantity(item_id, 1)
    
    def remove_item_instant(self, item_id: int):
        """Supprime un article instantanément"""
        self.cart_items = [item for item in self.cart_items if item.get('id') != item_id]
        self._update_total_cache()
        self.update_cart_display()
        
        try:
            self.cart_manager.remove_item(item_id)
        except Exception as e:
            print(f"Erreur suppression DB: {e}")
        
        self.show_success_dialog("Article supprimé", "Article supprimé du panier")
    
    def remove_item_async(self, item_id: int):
        """Supprime un article de manière asynchrone"""
        self.remove_item_instant(item_id)
    
    def remove_item(self, item_id: int):
        """Supprime un article du panier (synchrone - pour compatibilité)"""
        success = self.cart_manager.remove_item(item_id)
        
        if success:
            self.load_cart_items()
            self.show_success_dialog("Article supprimé", "Article supprimé du panier")
        else:
            self.show_success_dialog("Erreur", "Erreur lors de la suppression")
    
    # =========================================================
    # FINALISATION DE LA VENTE
    # =========================================================
    
    def finalize_sale(self, e):
        """Finalise la vente - Le serveur génère toujours son propre numéro de facture"""
        if not self.cart_items:
            self.show_success_dialog("Panier vide", "Le panier est vide")
            return
        
        customer_name = self.customer_name_field.value.strip() if self.customer_name_field else "Client comptant"
        if not customer_name:
            customer_name = "Client comptant"
        
        payment_method = self.payment_method_dropdown.value if self.payment_method_dropdown else "cash"
        branch_id = self._branch_id()
        
        if not branch_id:
            self.show_success_dialog("Erreur", "Aucune succursale sélectionnée")
            return
        
        is_online_mode = self._is_online
        sale_date = datetime.now().isoformat()
        seller_id = self.current_user.get('id', '')
        seller_name = self.current_user.get('full_name', 'Vendeur')
        
        sales_data_for_ticket = []
        cart_items_backup = self.cart_items.copy()
        total_amount = sum(item.get('total_price', 0) for item in cart_items_backup)
        invoice_items = []
        sales_recorded = 0
        errors = []
        final_invoice_number = None
        response = None
        
        # ========== MODE ONLINE : Enregistrement sur le serveur SANS numéro ==========
        if is_online_mode:
            print("🌐 Mode ONLINE - Enregistrement sur le serveur (sans numéro de facture)")
            
            items_payload = []
            for item in self.cart_items:
                items_payload.append({
                    "product_id": str(item.get('product_id')),
                    "quantity": item.get('quantity', 1),
                    "discount_percent": 0
                })
            
            # ⚠️ CRITIQUE: NE PAS inclure invoice_number dans le payload
            payload = {
                "items": items_payload,
                "customer_name": customer_name,
                "payment_method": payment_method,
                "global_discount": 0,
                "notes": "Vente panier synchro",
                "branch_id": str(branch_id),
                "pharmacy_id": str(self.current_user.get('pharmacy_id')) if self.current_user.get('pharmacy_id') else None,
                "sale_date": sale_date
            }
            
            # Supprimer les clés avec valeur None
            payload = {k: v for k, v in payload.items() if v is not None}
            
            print(f"📤 Payload envoyé au serveur: {payload}")
            
            try:
                headers = self.sync_service._get_headers()
                if headers:
                    response = self.sync_service.session.post(
                        f"{self.sync_service.api_url}/sales",
                        headers=headers,
                        json=payload,
                        timeout=30
                    )
                    
                    if response.status_code in [200, 201]:
                        data = response.json()
                        print(f"✅ Vente enregistrée sur le serveur")
                        sales_recorded = len(self.cart_items)
                        
                        # Récupérer le numéro de facture généré par le serveur
                        final_invoice_number = data.get('invoice_number')
                        if not final_invoice_number and 'sale' in data:
                            final_invoice_number = data['sale'].get('invoice_number')
                        if not final_invoice_number:
                            final_invoice_number = data.get('generated_invoice_number')
                        
                        print(f"📋 Numéro de facture généré par le serveur: {final_invoice_number}")
                        
                        # Mettre à jour les stocks locaux
                        with self.db.get_connection() as conn:
                            cursor = conn.cursor()
                            for item in self.cart_items:
                                product_id = str(item.get('product_id'))
                                quantity = item.get('quantity', 1)
                                cursor.execute(
                                    "UPDATE products SET quantity = quantity - ? WHERE server_id = ? AND quantity >= ?",
                                    (quantity, product_id, quantity)
                                )
                            conn.commit()
                        
                        # Préparer les données pour le ticket
                        for item in self.cart_items:
                            sales_data_for_ticket.append({
                                'product_name': item.get('product_name'),
                                'quantity': item.get('quantity', 1),
                                'unit_price': self._safe_float(item.get('unit_price', 0)),
                                'total_price': self._safe_float(item.get('total_price', 0)),
                            })
                            
                            invoice_items.append({
                                'product_id': str(item.get('product_id')),
                                'product_name': item.get('product_name'),
                                'quantity': item.get('quantity', 1),
                                'unit_price': self._safe_float(item.get('unit_price', 0)),
                                'total_price': self._safe_float(item.get('total_price', 0)),
                                'is_returned': 0,
                                'returned_quantity': 0,
                                'exchange_product_id': None,
                                'exchange_product_name': None,
                                'exchange_quantity': 0,
                                'exchange_unit_price': 0,
                                'exchange_total': 0
                            })
                        
                        self.show_success_dialog(
                            "Vente réussie!",
                            f"{sales_recorded} article(s) vendu(s)",
                            {
                                "Montant": self._format_money(total_amount),
                                "Facture": final_invoice_number if final_invoice_number else "Générée par le serveur",
                                "Mode": "En ligne"
                            }
                        )
                    else:
                        # Échec serveur - Fallback local
                        error_text = response.text[:200] if response else "No response"
                        print(f"⚠️ Échec serveur (HTTP {response.status_code if response else 'No response'}): {error_text}")
                        print("🔄 Fallback vers mode local...")
                        
                        fallback_invoice = self.generate_local_invoice_number()
                        sales_recorded, errors = self._save_sale_to_local(
                            branch_id, customer_name, payment_method, fallback_invoice,
                            sale_date, seller_id, seller_name, total_amount,
                            sales_data_for_ticket, invoice_items
                        )
                        final_invoice_number = fallback_invoice
                        
                        if sales_recorded > 0:
                            self.show_success_dialog(
                                "Vente en mode local",
                                f"{sales_recorded} article(s) vendu(s) (serveur indisponible)",
                                {
                                    "Montant": self._format_money(total_amount),
                                    "Facture": final_invoice_number,
                                    "Mode": "Hors-ligne"
                                }
                            )
                else:
                    # Pas de headers - Fallback local
                    print("⚠️ Pas de headers d'authentification - Fallback local")
                    fallback_invoice = self.generate_local_invoice_number()
                    sales_recorded, errors = self._save_sale_to_local(
                        branch_id, customer_name, payment_method, fallback_invoice,
                        sale_date, seller_id, seller_name, total_amount,
                        sales_data_for_ticket, invoice_items
                    )
                    final_invoice_number = fallback_invoice
                    
            except Exception as err:
                print(f"⚠️ Erreur réseau: {err}")
                print("🔄 Fallback vers mode local...")
                
                fallback_invoice = self.generate_local_invoice_number()
                sales_recorded, errors = self._save_sale_to_local(
                    branch_id, customer_name, payment_method, fallback_invoice,
                    sale_date, seller_id, seller_name, total_amount,
                    sales_data_for_ticket, invoice_items
                )
                final_invoice_number = fallback_invoice
                
                if sales_recorded > 0:
                    self.show_success_dialog(
                        "Vente en mode local",
                        f"{sales_recorded} article(s) vendu(s) (problème réseau)",
                        {
                            "Montant": self._format_money(total_amount),
                            "Facture": final_invoice_number,
                            "Mode": "Hors-ligne"
                        }
                    )
        
        else:
            # ========== MODE OFFLINE : Enregistrement local uniquement ==========
            print("✈️ Mode OFFLINE - Enregistrement local")
            
            local_invoice_number = self.generate_local_invoice_number()
            sales_recorded, errors = self._save_sale_to_local(
                branch_id, customer_name, payment_method, local_invoice_number,
                sale_date, seller_id, seller_name, total_amount,
                sales_data_for_ticket, invoice_items
            )
            final_invoice_number = local_invoice_number
            
            if sales_recorded > 0:
                self.show_success_dialog(
                    "Vente hors-ligne",
                    f"{sales_recorded} article(s) vendu(s)",
                    {
                        "Montant": self._format_money(total_amount),
                        "Facture": final_invoice_number,
                        "Mode": "Hors-ligne"
                    }
                )
        
        # ========== FIN: Nettoyage et affichage facture selon config ==========
        if sales_recorded > 0:
            # Sauvegarder la facture localement (toujours pour avoir une trace)
            invoice_data = {
                'invoice_number': final_invoice_number,
                'sale_date': sale_date,
                'customer_name': customer_name,
                'total_amount': total_amount,
                'payment_method': payment_method,
                'branch_id': str(branch_id),
                'seller_id': seller_id,
                'seller_name': seller_name,
                'status': 'completed',
                'is_modified': 0,
                'original_invoice_number': None,
                'modification_date': None,
                'modification_reason': None
            }
            
            saved_invoice = self.db.save_invoice(invoice_data, invoice_items)
            if saved_invoice:
                print(f"✅ Facture sauvegardée localement: {saved_invoice}")
            
            # Vider le panier
            self.cart_manager.clear_cart()
            self.cart_items = []
            self._total_cache = 0.0
            
            if errors:
                self.show_success_dialog(
                    "Vente partielle",
                    f"{sales_recorded} article(s) vendu(s). {len(errors)} erreur(s)"
                )
            
            # Afficher la facture SEULEMENT si auto_invoice est activé dans la config
            if self.auto_invoice and sales_data_for_ticket:
                ticket_data = {
                    'sales_data': sales_data_for_ticket,
                    'customer_name': customer_name,
                    'total_amount': total_amount,
                    'payment_method': 'Espèces' if payment_method == 'cash' else 'Carte' if payment_method == 'card' else 'Mobile Money',
                    'seller_name': seller_name,
                    'branch_name': self.current_user.get('branch_name', ''),
                    'invoice_number': final_invoice_number,
                    'sale_date': datetime.now().strftime('%d/%m/%Y %H:%M'),
                }
                self.print_multiple_sale_ticket(ticket_data)
            elif sales_data_for_ticket:
                print(f"📄 Facture sauvegardée sans affichage (auto_invoice=False): {final_invoice_number}")
                self.show_success_dialog(
                    "Facture sauvegardée",
                    f"Facture {final_invoice_number} sauvegardée sans affichage"
                )
            
            self.update_cart_display()
        else:
            self.show_success_dialog(
                "Erreur",
                f"Aucune vente enregistrée. {', '.join(errors) if errors else 'Erreur inconnue'}"
            )
    
    def _save_sale_to_local(self, branch_id, customer_name, payment_method, invoice_number,
                           sale_date, seller_id, seller_name, total_amount,
                           sales_data_for_ticket, invoice_items) -> tuple:
        """Enregistre la vente localement"""
        sales_recorded = 0
        errors = []
        
        try:
            with self.db.get_connection() as conn:
                cursor = conn.cursor()
                
                for item in self.cart_items:
                    product_id = str(item.get('product_id'))
                    product_name = item.get('product_name')
                    quantity = item.get('quantity', 1)
                    unit_price = self._safe_float(item.get('unit_price', 0))
                    total_price_item = self._safe_float(item.get('total_price', quantity * unit_price))
                    
                    cursor.execute(
                        "SELECT quantity FROM products WHERE server_id = ?",
                        (product_id,)
                    )
                    row = cursor.fetchone()
                    
                    if not row:
                        errors.append(f"Produit {product_name} non trouvé")
                        continue
                    
                    current_stock = self._safe_int(row[0], 0)
                    
                    if quantity > current_stock:
                        errors.append(f"Stock insuffisant pour {product_name}. Disponible: {current_stock}")
                        continue
                    
                    cursor.execute("""
                        INSERT INTO sales 
                        (product_id, product_name, quantity, unit_price, total_price, sale_date, 
                        customer_name, branch_id, is_synced, seller_id, payment_method, invoice_number)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        product_id,
                        product_name,
                        quantity,
                        unit_price,
                        total_price_item,
                        sale_date,
                        customer_name,
                        branch_id,
                        0,
                        seller_id,
                        payment_method,
                        invoice_number
                    ))
                    
                    cursor.execute(
                        "UPDATE products SET quantity = quantity - ? WHERE server_id = ?",
                        (quantity, product_id)
                    )
                    
                    sales_recorded += 1
                    
                    sales_data_for_ticket.append({
                        'product_name': product_name,
                        'quantity': quantity,
                        'unit_price': unit_price,
                        'total_price': total_price_item,
                    })
                    
                    invoice_items.append({
                        'product_id': product_id,
                        'product_name': product_name,
                        'quantity': quantity,
                        'unit_price': unit_price,
                        'total_price': total_price_item,
                        'is_returned': 0,
                        'returned_quantity': 0,
                        'exchange_product_id': None,
                        'exchange_product_name': None,
                        'exchange_quantity': 0,
                        'exchange_unit_price': 0,
                        'exchange_total': 0
                    })
                
                conn.commit()
            
        except Exception as e:
            print(f"❌ Erreur dans _save_sale_to_local: {e}")
            import traceback
            traceback.print_exc()
            errors.append(str(e))
        
        return sales_recorded, errors
    
    def print_multiple_sale_ticket(self, ticket_data: Dict):
        """Affiche le ticket pour la vente multiple"""
        receipt_view = self.print_manager.create_multiple_receipt_view(
            ticket_data.get('sales_data', []),
            ticket_data.get('customer_name', 'Client comptant'),
            ticket_data.get('total_amount', 0)
        )
        
        self.print_manager.show_receipt_as_page(
            receipt_view,
            f"Ticket - {ticket_data.get('invoice_number', 'Vente')}"
        )
    
    # =========================================================
    # VIDER LE PANIER
    # =========================================================
    
    def clear_cart(self, e):
        """Vide complètement le panier après confirmation"""
        if not self.cart_items:
            return
        
        def confirm_clear(confirm_e):
            if confirm_e.control.text == "Oui":
                success = self.cart_manager.clear_cart()
                if success:
                    self.cart_items = []
                    self._total_cache = 0.0
                    self.update_cart_display()
                    self.show_success_dialog("Panier vidé", "Panier vidé avec succès")
                else:
                    self.show_success_dialog("Erreur", "Erreur lors du vidage du panier")
            self.page.dialog.open = False
            self.page.update()
        
        dialog = ft.AlertDialog(
            title=ft.Text("Vider le panier"),
            content=ft.Text("Êtes-vous sûr de vouloir vider tout le panier ?"),
            actions=[
                ft.TextButton("Non", on_click=confirm_clear),
                ft.TextButton("Oui", on_click=confirm_clear),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
        )
        
        self.page.dialog = dialog
        dialog.open = True
        self.page.update()
    
    # =========================================================
    # AFFICHAGE DE L'ÉCRAN (RESPONSIVE)
    # =========================================================
    
    def show(self):
        """Affiche l'écran du panier (version responsive)"""
        self.page.clean()
        
        is_mobile = self.is_mobile()
        font_size_title = 20 if is_mobile else 24
        padding = self.get_padding()
        
        connection_indicator = self.create_connection_indicator()
        self._is_header_initialized = True
        
        app_bar = ft.AppBar(
            title=ft.Text("Mon Panier", size=font_size_title, weight=ft.FontWeight.BOLD),
            bgcolor=ft.Colors.BLUE_700,
            leading=ft.IconButton(
                icon=ft.Icons.ARROW_BACK,
                icon_color=ft.Colors.WHITE,
                on_click=lambda e: self.go_back(),
            ),
            actions=[
                connection_indicator,
                ft.IconButton(
                    icon=ft.Icons.DELETE_SWEEP,
                    icon_color=ft.Colors.WHITE,
                    on_click=self.clear_cart,
                    tooltip="Vider le panier",
                ),
            ],
        )
        
        self.cart_list_view = ft.ListView(
            expand=True,
            spacing=10,
            padding=ft.Padding.all(padding),
        )
        
        self.customer_name_field = ft.TextField(
            hint_text="Nom du client (optionnel)",
            prefix_icon=ft.Icons.PERSON,
            expand=True,
            border_radius=30,
            filled=True,
            bgcolor=ft.Colors.WHITE,
        )
        
        self.payment_method_dropdown = ft.Dropdown(
            hint_text="Mode de paiement",
            value="cash",
            options=[
                ft.dropdown.Option("cash", "Espèces"),
                ft.dropdown.Option("card", "Carte bancaire"),
                ft.dropdown.Option("mobile_money", "Mobile Money"),
            ],
            width=180 if not is_mobile else None,
            expand=is_mobile,
            border_radius=30,
            filled=True,
            bgcolor=ft.Colors.WHITE,
        )
        
        if is_mobile:
            customer_section = ft.Column(
                controls=[
                    self.customer_name_field,
                    self.payment_method_dropdown,
                ],
                spacing=10,
            )
        else:
            customer_section = ft.Row(
                controls=[
                    self.customer_name_field,
                    self.payment_method_dropdown,
                ],
                spacing=10,
            )
        
        self._update_total_cache()
        total_size = 24 if is_mobile else 28
        self.total_text = ft.Text(
            self._format_money(self._total_cache),
            size=total_size,
            weight=ft.FontWeight.BOLD,
            color=ft.Colors.GREEN_700,
        )
        
        finalize_button = ft.Button(
            content=ft.Row(
                controls=[
                    ft.Icon(ft.Icons.CHECK_CIRCLE, color=ft.Colors.WHITE, size=20 if is_mobile else 24),
                    ft.Text("Finaliser la vente", 
                           size=16 if is_mobile else 18, 
                           weight=ft.FontWeight.BOLD),
                ],
                spacing=10,
            ),
            on_click=self.finalize_sale,
            style=ft.ButtonStyle(
                color=ft.Colors.WHITE,
                bgcolor=ft.Colors.GREEN_700,
                padding=ft.Padding.symmetric(vertical=15, horizontal=20) if is_mobile else 20,
                shape=ft.RoundedRectangleBorder(radius=10),
            ),
            expand=True,
        )
        
        summary_panel = ft.Container(
            content=ft.Column(
                controls=[
                    ft.Divider(height=2, color=ft.Colors.GREY_300),
                    ft.Row(
                        controls=[
                            ft.Text("TOTAL", size=18 if is_mobile else 20, weight=ft.FontWeight.BOLD),
                            self.total_text,
                        ],
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                    ),
                    ft.Divider(height=1, color=ft.Colors.GREY_200),
                    customer_section,
                    finalize_button,
                ],
                spacing=15,
            ),
            padding=ft.Padding.all(padding),
            bgcolor=ft.Colors.GREY_50,
            border_radius=ft.BorderRadius(top_left=20, top_right=20, bottom_left=0, bottom_right=0),
        )
        
        main_content = ft.Column(
            controls=[
                self.cart_list_view,
                summary_panel,
            ],
            expand=True,
            spacing=0,
        )
        
        self.page.add(
            ft.Container(
                content=ft.Column(
                    controls=[app_bar, main_content],
                    expand=True,
                    spacing=0,
                ),
                expand=True,
                bgcolor=ft.Colors.GREY_100,
            )
        )
        
        self.load_cart_items()
        self.page.update()
    
    def go_back(self):
        """Retourne à l'écran de vente"""
        from screens.sale_screen import SaleScreen
        
        sale_screen = SaleScreen(
            self.page,
            self.db,
            self.sync_service,
            self.auth_service,
            self.current_user,
        )
        sale_screen.show()