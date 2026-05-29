# screens/invoice_screen.py
import flet as ft
from datetime import datetime, timedelta, date
from calendar import monthrange
from typing import Dict, List, Optional
import locale
import threading
import logging

logger = logging.getLogger(__name__)

# Essayer de définir la locale pour les noms de mois en français
try:
    locale.setlocale(locale.LC_TIME, 'fr_FR.UTF-8')
except:
    try:
        locale.setlocale(locale.LC_TIME, 'fra')
    except:
        pass


class InvoiceScreen:
    """
    Écran de gestion des factures avec support online/offline.
    
    Mode ONLINE: Affiche les factures du serveur (via /sales) + factures locales non synchronisées
    Mode OFFLINE: Affiche uniquement les factures locales
    """
    
    def __init__(self, page: ft.Page, db, sync_service, auth_service, current_user):
        self.page = page
        self.db = db
        self.sync_service = sync_service
        self.auth_service = auth_service
        self.current_user = current_user
        
        # Récupérer le ConnectionManager (singleton)
        from services.connection_manager import ConnectionManager
        self.connection_manager = ConnectionManager()
        
        # État de l'interface
        self.current_filter = "today"
        self.selected_invoices = set()
        self.invoices_list_view = None
        self.filter_dropdown = None
        self.date_picker_start = None
        self.date_picker_end = None
        self.custom_filter_row = None
        self.search_field = None
        self.select_all_checkbox = None
        self.action_bar = None
        self.invoices_data = []
        
        # Filtres
        self.custom_start_date = None
        self.custom_end_date = None
        self.search_term = ""
        
        # Références aux statistiques
        self.total_stat_text = None
        self.count_stat_text = None
        self.customers_stat_text = None
        
        # État de chargement
        self.loading_indicator = None
        self.connection_status_indicator = None
        self.is_loading = False
        self.current_page = 1
        self.has_more = True
        self.invoices_cache = {}
        self.is_shown = False
        
        # Pour le mode online
        self.server_invoices = []
        self.local_only_invoices = []
        
        # S'abonner aux changements de connexion
        self._setup_connection_observer()
    
    def _setup_connection_observer(self):
        """S'abonne aux changements de statut de connexion"""
        def on_connection_changed(is_online: bool, force_mode: Optional[bool]):
            logger.info(f"Connexion changée: online={is_online}, force_mode={force_mode}")
            if self.is_shown:
                self.load_invoices()
        
        self.connection_manager.register_observer(on_connection_changed)
    
    def _branch_id(self) -> str:
        """Récupère l'ID de la branche"""
        branch_id = (self.current_user.get("active_branch_id") or 
                    self.current_user.get("branch_id") or
                    self.current_user.get("current_branch_id"))
        return str(branch_id) if branch_id else None
    
    def _format_money(self, amount) -> str:
        """Formate un montant en monnaie locale"""
        try:
            return f"{float(amount):,.0f} FC"
        except:
            return "0 FC"
    
    def _format_date(self, date_str: str) -> str:
        """Formate une date pour l'affichage"""
        try:
            if not date_str:
                return ""
            if 'T' in date_str:
                dt = datetime.fromisoformat(date_str.replace('Z', '+00:00'))
                return dt.strftime("%d/%m/%Y %H:%M")
            return date_str
        except:
            return date_str
    
    def _format_date_short(self, date_str: str) -> str:
        """Formate une date courte"""
        try:
            if not date_str:
                return ""
            if 'T' in date_str:
                dt = datetime.fromisoformat(date_str.replace('Z', '+00:00'))
                return dt.strftime("%d/%m/%Y")
            return date_str[:10]
        except:
            return date_str[:10] if date_str else ""
    
    def _get_filter_dates(self) -> tuple:
        """Retourne les dates de début et fin selon le filtre sélectionné"""
        today = datetime.now().date()
        
        if self.current_filter == "today":
            start_date = today
            end_date = today
            
        elif self.current_filter == "yesterday":
            start_date = today - timedelta(days=1)
            end_date = start_date
            
        elif self.current_filter == "last_2_days":
            start_date = today - timedelta(days=2)
            end_date = today
            
        elif self.current_filter == "this_week":
            monday = today - timedelta(days=today.weekday())
            start_date = monday
            end_date = today
            
        elif self.current_filter == "this_month":
            start_date = today.replace(day=1)
            end_date = today
            
        elif self.current_filter.startswith("month_"):
            parts = self.current_filter.split("_")
            if len(parts) == 3:
                year = int(parts[1])
                month = int(parts[2])
                start_date = date(year, month, 1)
                last_day = monthrange(year, month)[1]
                end_date = date(year, month, last_day)
            else:
                start_date = today.replace(day=1)
                end_date = today
                
        elif self.current_filter == "custom" and self.custom_start_date and self.custom_end_date:
            start_date = self.custom_start_date
            end_date = self.custom_end_date
            
        else:
            start_date = today
            end_date = today
        
        logger.info(f"Filtre: {self.current_filter} -> {start_date} à {end_date}")
        
        return start_date, end_date
    
    def _get_month_options(self) -> List[ft.dropdown.Option]:
        """Génère les options de mois pour le dropdown"""
        months = [
            "Janvier", "Février", "Mars", "Avril", "Mai", "Juin",
            "Juillet", "Août", "Septembre", "Octobre", "Novembre", "Décembre"
        ]
        current_year = datetime.now().year
        years = [current_year - 1, current_year, current_year + 1]
        
        options = []
        for year in years:
            for month_num, month_name in enumerate(months, 1):
                options.append(
                    ft.dropdown.Option(
                        key=f"month_{year}_{month_num}",
                        text=f"{month_name} {year}"
                    )
                )
        return options
    
    def load_invoices(self, force_refresh: bool = False):
        """
        Charge les factures:
        - Mode ONLINE: depuis le serveur (via /sales) + factures locales non synchronisées
        - Mode OFFLINE: uniquement depuis la base locale
        """
        if self.is_loading:
            logger.info("Chargement déjà en cours, ignoré")
            return
        
        if not self.is_shown:
            logger.info("Écran non encore affiché, chargement différé")
            return
        
        # DEBUG: Tester la connexion serveur
        test_result = self._test_server_connection()
        logger.info(f"Test connexion serveur: {test_result}")
        
        self.is_loading = True
        self._show_loading(True)
        
        def load():
            try:
                start_date, end_date = self._get_filter_dates()
                start_str = start_date.strftime("%Y-%m-%d") if start_date else None
                end_str = end_date.strftime("%Y-%m-%d") if end_date else None
                
                logger.info(f"Filtres: start={start_str}, end={end_str}, search={self.search_term}")
                
                is_online = self.connection_manager.is_online_mode()
                force_mode = self.connection_manager.get_force_mode()
                
                logger.info(f"Mode: online={is_online}, force_mode={force_mode}")
                
                # Récupérer les factures locales d'abord
                local_invoices = self._load_from_local(start_str, end_str)
                logger.info(f"Factures locales: {len(local_invoices)}")
                
                if is_online and force_mode is not False:
                    # Mode ONLINE: récupérer depuis le serveur
                    logger.info("Mode ONLINE - Chargement des factures depuis le serveur (/sales)")
                    server_invoices = self._load_from_server_sales(start_str, end_str)
                    logger.info(f"Factures serveur: {len(server_invoices)}")
                    
                    if not server_invoices:
                        # Essayer l'endpoint de test
                        test = self._test_server_connection()
                        logger.warning(f"Test serveur: {test}")
                    
                    # Fusionner les factures
                    self.invoices_data = self._merge_invoices(server_invoices, local_invoices)
                    logger.info(f"Fusion terminée: {len(self.invoices_data)} factures")
                    
                    # Sauvegarder les factures serveur en local
                    if server_invoices:
                        self._save_invoices_locally(server_invoices)
                else:
                    # Mode OFFLINE
                    logger.info("Mode OFFLINE - Uniquement factures locales")
                    self.invoices_data = local_invoices
                
                # Mettre à jour l'UI
                self.page.run_thread(lambda: self._update_ui_after_load())
                
            except Exception as e:
                logger.error(f"Erreur chargement factures: {e}", exc_info=True)
                self.page.run_thread(lambda: self._show_error(str(e)))
            finally:
                self.is_loading = False
                self.page.run_thread(lambda: self._show_loading(False))
        
        threading.Thread(target=load, daemon=True).start()
        
    def _load_from_server_sales(self, start_date: str = None, end_date: str = None) -> List[Dict]:
        """
        Charge les factures depuis le serveur via l'API /sales.
        """
        try:
            headers = self.sync_service._get_headers()
            if not headers:
                logger.warning("Pas de headers d'authentification")
                return []
            
            user = self.sync_service.auth_service.get_current_user()
            branch_id = self._branch_id() or user.get('branch_id')
            
            params = {
                "branch_id": branch_id,
                "limit": 500,
                "sort_by": "created_at",
                "sort_order": "desc"
            }
            
            # Convertir les dates si nécessaires
            if start_date:
                # S'assurer que start_date est au bon format
                if isinstance(start_date, str) and 'T' in start_date:
                    start_date = start_date.split('T')[0]
                params["start_date"] = start_date
            if end_date:
                if isinstance(end_date, str) and 'T' in end_date:
                    end_date = end_date.split('T')[0]
                params["end_date"] = end_date
            if self.search_term:
                params["search"] = self.search_term
            
            logger.info(f"Requête GET {self.sync_service.api_url}/sales avec params: {params}")
            
            response = self.sync_service.session.get(
                f"{self.sync_service.api_url}/sales",
                headers=headers,
                params=params,
                timeout=30
            )
            
            logger.info(f"Réponse serveur: HTTP {response.status_code}")
            
            if response.status_code == 200:
                data = response.json()
                logger.info(f"Données reçues: type={type(data)}")
                
                # Gérer différents formats de réponse
                if isinstance(data, dict):
                    sales_data = data.get('items', data.get('sales', data.get('data', [])))
                    # Vérifier s'il y a pagination
                    if not sales_data and 'results' in data:
                        sales_data = data.get('results', [])
                elif isinstance(data, list):
                    sales_data = data
                else:
                    logger.warning(f"Format de réponse inattendu: {type(data)}")
                    sales_data = []
                
                logger.info(f"Ventes récupérées: {len(sales_data)}")
                
                # Afficher les premières ventes pour debug
                if sales_data:
                    for i, sale in enumerate(sales_data[:3]):
                        logger.info(f"Vente {i+1}: ID={sale.get('id')}, "
                                f"invoice={sale.get('invoice_number')}, "
                                f"total={sale.get('total_amount')}")
                
                # Transformer les données
                invoices = self._transform_sale_to_invoice(sales_data)
                logger.info(f"Factures transformées: {len(invoices)}")
                
                return invoices
            else:
                logger.warning(f"Erreur chargement serveur: HTTP {response.status_code} - {response.text[:200]}")
                return []
            
        except Exception as e:
            logger.error(f"Erreur _load_from_server_sales: {e}", exc_info=True)
            return []
    
    def _transform_sale_to_invoice(self, sales: List[Dict]) -> List[Dict]:
        """
        Transforme les données de vente du serveur au format facture attendu par l'UI.
        """
        transformed = []
        
        for sale in sales:
            # S'assurer que sale est un dictionnaire
            if not isinstance(sale, dict):
                continue
                
            # Récupérer les items avec gestion des différents formats
            items = sale.get('items', [])
            if not items and 'sale_items' in sale:
                items = sale.get('sale_items', [])
            
            # Calculer le total si non présent
            total = sale.get('total_amount', sale.get('total', 0))
            if total == 0 and items:
                for item in items:
                    if isinstance(item, dict):
                        total += item.get('total', item.get('total_price', 0))
            
            invoice = {
                'id': sale.get('id'),
                'invoice_number': sale.get('invoice_number', sale.get('reference', 'N/A')),
                'customer_name': sale.get('customer_name', sale.get('client_name', 'Client comptant')),
                'total_amount': float(total),
                'sale_date': sale.get('sale_date', sale.get('created_at', datetime.now().isoformat())),
                'payment_method': sale.get('payment_method', 'cash'),
                'is_modified': sale.get('is_modified', 0),
                'status': sale.get('status', 'completed'),
                'server_synced': True,
                'source': 'server',
                'items': items,
                'customer_phone': sale.get('customer_phone', ''),
                'notes': sale.get('notes', ''),
                'reference': sale.get('reference', ''),
                'subtotal': float(sale.get('subtotal', 0)),
                'total_discount': float(sale.get('total_discount', 0)),
                'total_tva': float(sale.get('total_tva', 0)),
            }
            transformed.append(invoice)
        
        logger.info(f"Transformées: {len(transformed)} factures depuis {len(sales)} ventes")
        return transformed
    
    def _load_from_local(self, start_date: str = None, end_date: str = None) -> List[Dict]:
        """Charge les factures depuis la base de données locale"""
        try:
            invoices = self.db.get_invoices(
                branch_id=self._branch_id(),
                start_date=start_date,
                end_date=end_date,
                search_term=self.search_term
            )
            
            # Marquer les factures locales non synchronisées
            for inv in invoices:
                inv['source'] = 'local'
                inv['server_synced'] = inv.get('server_synced', False)
                if not inv.get('server_synced'):
                    inv['sync_status'] = 'pending'
            
            logger.info(f"Factures chargées depuis la base locale: {len(invoices)}")
            return invoices
            
        except Exception as e:
            logger.error(f"Erreur chargement local: {e}")
            return []
    
    def _merge_invoices(self, server_invoices: List[Dict], local_invoices: List[Dict]) -> List[Dict]:
        """
        Fusionne les factures du serveur et les factures locales.
        - Les factures serveur sont prioritaires (plus à jour)
        - Les factures locales non synchronisées sont ajoutées
        """
        # Créer un set des numéros de facture serveur
        server_numbers = set(inv.get('invoice_number') for inv in server_invoices if inv.get('invoice_number'))
        
        # Factures locales non synchronisées (qui ne sont pas sur le serveur)
        unsynced_locals = [
            inv for inv in local_invoices 
            if not inv.get('server_synced') and inv.get('invoice_number') not in server_numbers
        ]
        
        # Fusionner: factures serveur + factures locales non synchronisées
        merged = server_invoices + unsynced_locals
        
        # Trier par date (plus récentes en premier)
        merged.sort(key=lambda x: x.get('sale_date', ''), reverse=True)
        
        logger.info(f"Fusion terminée: {len(server_invoices)} serveur + {len(unsynced_locals)} locales = {len(merged)} total")
        
        return merged
    
    def _save_invoices_locally(self, invoices: List[Dict]):
        """Sauvegarde les factures serveur localement pour usage offline"""
        try:
            with self.db.get_connection() as conn:
                cursor = conn.cursor()
                
                for invoice in invoices:
                    invoice_number = invoice.get('invoice_number')
                    if not invoice_number:
                        continue
                    
                    # Vérifier si la facture existe déjà
                    cursor.execute(
                        "SELECT invoice_number FROM invoices WHERE invoice_number = ?",
                        (invoice_number,)
                    )
                    exists = cursor.fetchone()
                    
                    if not exists:
                        # Insérer la facture
                        cursor.execute("""
                            INSERT INTO invoices 
                            (invoice_number, customer_name, total_amount, sale_date, 
                             payment_method, is_modified, status, server_synced, 
                             server_id, branch_id, customer_phone, notes)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """, (
                            invoice_number,
                            invoice.get('customer_name', 'Client comptant'),
                            invoice.get('total_amount', 0),
                            invoice.get('sale_date', datetime.now().isoformat()),
                            invoice.get('payment_method', 'cash'),
                            invoice.get('is_modified', 0),
                            invoice.get('status', 'completed'),
                            1,  # server_synced = True
                            invoice.get('id'),
                            self._branch_id(),
                            invoice.get('customer_phone', ''),
                            invoice.get('notes', '')
                        ))
                        
                        # Insérer les lignes de facture
                        for item in invoice.get('items', []):
                            cursor.execute("""
                                INSERT INTO invoice_items 
                                (invoice_number, product_id, product_name, quantity, 
                                 unit_price, total_price, discount_percent)
                                VALUES (?, ?, ?, ?, ?, ?, ?)
                            """, (
                                invoice_number,
                                item.get('product_id', ''),
                                item.get('product_name', ''),
                                item.get('quantity', 1),
                                item.get('unit_price', 0),
                                item.get('total_price', 0),
                                item.get('discount_percent', 0)
                            ))
                
                conn.commit()
                logger.info(f"{len(invoices)} factures sauvegardées localement")
                
        except Exception as e:
            logger.error(f"Erreur sauvegarde locale factures: {e}")
    
    def _update_ui_after_load(self):
        """Met à jour l'interface après chargement"""
        if self.invoices_list_view is None:
            logger.warning("invoices_list_view est None, mise à jour ignorée")
            return
        
        self.update_invoices_list()
        self._update_stats()
        self._update_connection_status_display()
        self.page.update()
    
    def _show_loading(self, show: bool):
        """Affiche ou masque l'indicateur de chargement"""
        if self.loading_indicator:
            self.loading_indicator.visible = show
            self.page.update()
    
    def _show_error(self, error_message: str):
        """Affiche une erreur"""
        self.page.snack_bar = ft.SnackBar(
            content=ft.Text(f"❌ Erreur: {error_message}"),
            bgcolor=ft.Colors.RED_700,
            duration=5000,
        )
        self.page.snack_bar.open = True
        self.page.update()
    
    def _show_success(self, message: str):
        """Affiche un message de succès"""
        self.page.snack_bar = ft.SnackBar(
            content=ft.Text(f"✅ {message}"),
            bgcolor=ft.Colors.GREEN_700,
            duration=3000,
        )
        self.page.snack_bar.open = True
        self.page.update()
    
    def _update_connection_status_display(self):
        """Met à jour l'affichage du statut de connexion"""
        if not self.connection_status_indicator:
            return
        
        status = self.connection_manager.get_display_status()
        
        # Ajouter le compteur de factures non synchronisées
        unsynced_count = len([inv for inv in self.invoices_data if not inv.get('server_synced', True)])
        
        if unsynced_count > 0 and status['text'] != "Offline":
            status_text = f"{status['text']} ({unsynced_count} en attente)"
        else:
            status_text = status['text']
        
        self.connection_status_indicator.content = ft.Row(
            controls=[
                ft.Icon(ft.Icons.WIFI if "Online" in status['text'] else ft.Icons.WIFI_OFF,
                       size=16, color=status['color']),
                ft.Text(status_text, size=12, color=status['color']),
            ],
            spacing=5,
        )
        self.connection_status_indicator.tooltip = status['tooltip']
    
    def update_invoices_list(self):
        """Met à jour l'affichage de la liste des factures"""
        if self.invoices_list_view is None:
            logger.warning("invoices_list_view est None, mise à jour ignorée")
            return
        
        self.invoices_list_view.controls.clear()
        self._update_connection_status_display()
        
        if not self.invoices_data:
            is_online = self.connection_manager.is_online_mode()
            if is_online:
                empty_message = "Aucune facture trouvée sur le serveur"
                empty_submessage = "Vérifiez les filtres ou synchronisez vos ventes"
            else:
                empty_message = "Mode hors-ligne - Aucune facture locale"
                empty_submessage = "Connectez-vous à internet pour synchroniser"
            
            self.invoices_list_view.controls.append(
                ft.Container(
                    content=ft.Column(
                        controls=[
                            ft.Icon(ft.Icons.RECEIPT_OUTLINED, size=60, color=ft.Colors.GREY_400),
                            ft.Text(empty_message, size=16, color=ft.Colors.GREY_600),
                            ft.Text(empty_submessage, size=12, color=ft.Colors.GREY_500),
                        ],
                        horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                        spacing=10,
                    ),
                    padding=40,
                    alignment=ft.Alignment(0, 0),
                )
            )
        else:
            for invoice in self.invoices_data:
                self.invoices_list_view.controls.append(
                    self._create_invoice_card(invoice)
                )
        
        self._update_selection_bar()
        self.page.update()
    
    def _create_invoice_card(self, invoice: Dict) -> ft.Container:
        """Crée une carte pour une facture"""
        invoice_number = invoice.get('invoice_number', 'N/A')
        customer_name = invoice.get('customer_name', 'Client comptant')
        total_amount = invoice.get('total_amount', 0)
        sale_date = self._format_date_short(invoice.get('sale_date', ''))
        payment_method = invoice.get('payment_method', 'cash')
        is_modified = invoice.get('is_modified', 0)
        is_selected = invoice_number in self.selected_invoices
        server_synced = invoice.get('server_synced', True)
        source = invoice.get('source', 'local')
        
        payment_color = ft.Colors.GREEN_700 if payment_method == 'cash' else ft.Colors.BLUE_700
        payment_text = "Espèces" if payment_method == 'cash' else "Carte"
        
        # Badge de statut
        if not server_synced:
            sync_badge = ft.Container(
                content=ft.Text("⏳ En attente", size=10, color=ft.Colors.WHITE),
                bgcolor=ft.Colors.ORANGE_700,
                border_radius=10,
                padding=ft.Padding.symmetric(horizontal=8, vertical=2),
            )
        elif source == 'server':
            sync_badge = ft.Container(
                content=ft.Text("☁️ Cloud", size=10, color=ft.Colors.WHITE),
                bgcolor=ft.Colors.BLUE_600,
                border_radius=10,
                padding=ft.Padding.symmetric(horizontal=8, vertical=2),
            )
        else:
            sync_badge = None
        
        modified_badge = None
        if is_modified:
            modified_badge = ft.Container(
                content=ft.Text("Modifiée", size=10, color=ft.Colors.WHITE),
                bgcolor=ft.Colors.ORANGE_700,
                border_radius=10,
                padding=ft.Padding.symmetric(horizontal=8, vertical=2),
            )
        
        def on_checkbox_change(e, inv_num=invoice_number):
            self._toggle_selection(inv_num, e.control.value)
        
        def on_view_click(e, inv=invoice):
            self.show_invoice_details(inv)
        
        def on_print_click(e, inv=invoice):
            self.print_invoice(inv)
        
        def on_return_click(e, inv=invoice):
            self.show_return_exchange_dialog(inv)
        
        def on_sync_click(e, inv=invoice):
            self._sync_single_invoice(inv)
        
        # Actions disponibles
        action_buttons = [
            ft.IconButton(
                icon=ft.Icons.VISIBILITY,
                icon_size=20,
                tooltip="Voir détails",
                on_click=on_view_click,
            ),
            ft.IconButton(
                icon=ft.Icons.PRINT,
                icon_size=20,
                tooltip="Imprimer",
                on_click=on_print_click,
            ),
            ft.IconButton(
                icon=ft.Icons.SWAP_HORIZ,
                icon_size=20,
                tooltip="Retour/Échange",
                on_click=on_return_click,
            ),
        ]
        
        # Ajouter bouton sync si non synchronisé
        if not server_synced:
            action_buttons.append(
                ft.IconButton(
                    icon=ft.Icons.SYNC,
                    icon_size=20,
                    tooltip="Synchroniser",
                    on_click=on_sync_click,
                )
            )
        
        return ft.Card(
            content=ft.Container(
                content=ft.Row(
                    controls=[
                        ft.Checkbox(
                            value=is_selected,
                            on_change=on_checkbox_change,
                            fill_color=ft.Colors.BLUE_700,
                        ),
                        ft.Column(
                            controls=[
                                ft.Row(
                                    controls=[
                                        ft.Text(invoice_number, size=16, weight=ft.FontWeight.BOLD),
                                        sync_badge if sync_badge else ft.Container(),
                                        modified_badge if modified_badge else ft.Container(),
                                    ],
                                    spacing=8,
                                ),
                                ft.Text(customer_name, size=14, color=ft.Colors.GREY_700),
                                ft.Row(
                                    controls=[
                                        ft.Icon(ft.Icons.CALENDAR_TODAY, size=14, color=ft.Colors.GREY_600),
                                        ft.Text(sale_date, size=12, color=ft.Colors.GREY_600),
                                        ft.Container(width=10),
                                        ft.Icon(ft.Icons.PAYMENT, size=14, color=payment_color),
                                        ft.Text(payment_text, size=12, color=payment_color),
                                    ],
                                    spacing=5,
                                ),
                            ],
                            spacing=4,
                            expand=True,
                        ),
                        ft.Column(
                            controls=[
                                ft.Text(
                                    self._format_money(total_amount),
                                    size=18,
                                    weight=ft.FontWeight.BOLD,
                                    color=ft.Colors.GREEN_700,
                                    text_align=ft.TextAlign.RIGHT,
                                ),
                                ft.Row(
                                    controls=action_buttons,
                                    spacing=0,
                                ),
                            ],
                            horizontal_alignment=ft.CrossAxisAlignment.END,
                            spacing=5,
                        ),
                    ],
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                ),
                padding=12,
            ),
            margin=5,
        )
    
    def _sync_single_invoice(self, invoice: Dict):
        """Synchronise une seule facture avec le serveur"""
        if not self.connection_manager.is_online_mode():
            self._show_error("Impossible de synchroniser: mode hors-ligne")
            return
        
        def sync():
            try:
                # Marquer comme synchronisée localement
                with self.db.get_connection() as conn:
                    cursor = conn.cursor()
                    cursor.execute(
                        "UPDATE invoices SET server_synced = 1, synced_at = ? WHERE invoice_number = ?",
                        (datetime.now().isoformat(), invoice.get('invoice_number'))
                    )
                    conn.commit()
                
                self.page.run_thread(lambda: self.load_invoices(force_refresh=True))
                self.page.run_thread(lambda: self._show_success("Facture synchronisée"))
                
            except Exception as e:
                logger.error(f"Erreur synchronisation facture: {e}")
                self.page.run_thread(lambda: self._show_error(str(e)))
        
        threading.Thread(target=sync, daemon=True).start()
    
    def _toggle_selection(self, invoice_number: str, is_selected: bool):
        """Gère la sélection d'une facture"""
        if is_selected:
            self.selected_invoices.add(invoice_number)
        else:
            self.selected_invoices.discard(invoice_number)
        self._update_selection_bar()
        self.update_invoices_list()
    
    def _update_selection_bar(self):
        """Met à jour la barre d'actions de sélection"""
        count = len(self.selected_invoices)
        
        if count > 0 and self.select_all_checkbox and self.action_bar:
            self.select_all_checkbox.label = f"{count} sélectionnée(s)"
            self.action_bar.visible = True
        elif self.select_all_checkbox and self.action_bar:
            self.select_all_checkbox.label = "Tout sélectionner"
            self.action_bar.visible = False
        
        if self.page:
            self.page.update()
    
    def _select_all(self, e):
        """Sélectionne ou désélectionne toutes les factures"""
        if self.select_all_checkbox.value:
            self.selected_invoices = set([inv.get('invoice_number') for inv in self.invoices_data])
        else:
            self.selected_invoices.clear()
        self._update_selection_bar()
        self.update_invoices_list()
    
    def _delete_selected(self, e):
        """Supprime les factures sélectionnées (uniquement locales non synchronisées)"""
        if not self.selected_invoices:
            return
        
        # Vérifier qu'on ne supprime que des factures non synchronisées
        unsynced_selected = []
        for inv_num in self.selected_invoices:
            invoice = next((inv for inv in self.invoices_data if inv.get('invoice_number') == inv_num), None)
            if invoice and not invoice.get('server_synced', True):
                unsynced_selected.append(inv_num)
        
        if len(unsynced_selected) != len(self.selected_invoices):
            self._show_error("Impossible de supprimer des factures déjà synchronisées")
            return
        
        dialog = ft.AlertDialog(
            title=ft.Text("Confirmer la suppression"),
            content=ft.Text(
                f"Voulez-vous vraiment supprimer {len(self.selected_invoices)} facture(s) non synchronisées ? "
                "Cette action est irréversible."
            ),
            actions=[
                ft.TextButton("Annuler", on_click=lambda _: self._close_dialog(dialog)),
                ft.TextButton("Supprimer", on_click=lambda _: self._confirm_delete(dialog)),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
        )
        self.page.dialog = dialog
        dialog.open = True
        self.page.update()
    
    def _confirm_delete(self, dialog):
        """Confirme la suppression"""
        deleted_count = 0
        for invoice_number in list(self.selected_invoices):
            if self._delete_invoice(invoice_number):
                deleted_count += 1
        
        self.selected_invoices.clear()
        self.load_invoices()
        self._close_dialog(dialog)
        
        self._show_success(f"{deleted_count} facture(s) supprimée(s)")
    
    def _delete_invoice(self, invoice_number: str) -> bool:
        """Supprime une facture et ses lignes (uniquement si non synchronisée)"""
        try:
            with self.db.get_connection() as conn:
                cursor = conn.cursor()
                
                # Vérifier que la facture n'est pas synchronisée
                cursor.execute("SELECT server_synced FROM invoices WHERE invoice_number = ?", (invoice_number,))
                row = cursor.fetchone()
                if row and row['server_synced']:
                    logger.warning(f"Impossible de supprimer la facture synchronisée {invoice_number}")
                    return False
                
                cursor.execute("DELETE FROM invoice_items WHERE invoice_number = ?", (invoice_number,))
                cursor.execute("DELETE FROM invoices WHERE invoice_number = ?", (invoice_number,))
                return True
        except Exception as e:
            logger.error(f"Erreur suppression facture {invoice_number}: {e}")
            return False
    
    def _close_dialog(self, dialog):
        dialog.open = False
        self.page.update()
    
    def show_invoice_details(self, invoice: Dict):
        """Affiche les détails d'une facture dans un écran dédié"""
        from screens.invoice_detail_screen import InvoiceDetailScreen
        detail_screen = InvoiceDetailScreen(
            self.page, self.db, self.sync_service,
            self.auth_service, self.current_user, invoice
        )
        detail_screen.show()
    
    def print_invoice(self, invoice: Dict):
        """Imprime une facture"""
        from utils.print_manager import PrintManager
        
        invoice_number = invoice.get('invoice_number')
        items = self.db.get_invoice_items(invoice_number)
        
        print_manager = PrintManager(self.page, self.db, self.current_user)
        print_manager.print_invoice(invoice, items)
    
    def show_return_exchange_dialog(self, invoice: Dict):
        """
        Affiche l'écran de retour/échange.
        Les retours sont envoyés au serveur via l'API /returns.
        """
        from screens.return_exchange_screen import ReturnExchangeScreen
        
        # Vérifier si on est en ligne pour les retours
        if not self.connection_manager.is_online_mode():
            self._show_error("Mode hors-ligne - Les retours nécessitent une connexion internet")
            return
        
        return_screen = ReturnExchangeScreen(
            self.page, self.db, self.sync_service,
            self.auth_service, self.current_user, invoice
        )
        return_screen.show()
    
    def _change_filter(self, e):
        """Change le filtre actuel"""
        self.current_filter = e.control.value
        if self.custom_filter_row:
            self.custom_filter_row.visible = (self.current_filter == "custom")
        self.current_page = 1
        self.load_invoices()
    
    def _apply_custom_date(self, e):
        """Applique les dates personnalisées"""
        if self.date_picker_start and self.date_picker_start.value and self.date_picker_end and self.date_picker_end.value:
            try:
                self.custom_start_date = datetime.strptime(self.date_picker_start.value, "%Y-%m-%d").date()
                self.custom_end_date = datetime.strptime(self.date_picker_end.value, "%Y-%m-%d").date()
                self.current_page = 1
                self.load_invoices()
            except:
                pass
    
    def _on_search(self, e):
        """Recherche de factures"""
        self.search_term = self.search_field.value if self.search_field else ""
        self.current_page = 1
        self.load_invoices()
    
    def show(self):
        """Affiche l'écran des factures"""
        self.page.clean()
        
        # Header
        header = ft.Container(
            content=ft.Row(
                controls=[
                    ft.IconButton(
                        icon=ft.Icons.ARROW_BACK,
                        on_click=self._go_back,
                        icon_color=ft.Colors.WHITE,
                    ),
                    ft.Text(
                        "Gestion des factures",
                        size=24,
                        weight=ft.FontWeight.BOLD,
                        color=ft.Colors.WHITE,
                        expand=True,
                        text_align=ft.TextAlign.CENTER,
                    ),
                    ft.IconButton(
                        icon=ft.Icons.SYNC,
                        on_click=lambda e: self._sync_all_invoices(),
                        icon_color=ft.Colors.WHITE,
                        tooltip="Synchroniser toutes les factures locales",
                    ),
                    ft.IconButton(
                        icon=ft.Icons.REFRESH,
                        on_click=lambda e: self.load_invoices(force_refresh=True),
                        icon_color=ft.Colors.WHITE,
                        tooltip="Actualiser",
                    ),
                ],
                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            padding=10,
            bgcolor=ft.Colors.BLUE_700,
            border_radius=10,
        )
        
        # Statut de connexion
        self.connection_status_indicator = ft.Container(
            content=ft.Row(controls=[], spacing=5),
            padding=ft.Padding.symmetric(horizontal=10, vertical=5),
            bgcolor=ft.Colors.GREY_100,
            border_radius=15,
        )
        
        # Filtres
        filter_options = [
            ft.dropdown.Option("today", "📅 Aujourd'hui"),
            ft.dropdown.Option("yesterday", "📆 Hier"),
            ft.dropdown.Option("last_2_days", "📆 Avant-hier"),
            ft.dropdown.Option("this_week", "📊 Cette semaine (Lun-Dim)"),
            ft.dropdown.Option("this_month", "📈 Ce mois"),
        ]
        
        filter_options.extend(self._get_month_options())
        filter_options.append(ft.dropdown.Option("custom", "📅 Personnalisé"))
        
        self.filter_dropdown = ft.Dropdown(
            options=filter_options,
            value="today",
            width=250,
            bgcolor=ft.Colors.WHITE,
        )
        self.filter_dropdown.on_change = self._change_filter
        
        # Filtre personnalisé
        self.date_picker_start = ft.TextField(
            hint_text="Date début",
            read_only=True,
            width=130,
        )
        self.date_picker_start.suffix = ft.IconButton(
            ft.Icons.CALENDAR_MONTH, 
            on_click=lambda e: self._show_date_picker(self.date_picker_start)
        )
        
        self.date_picker_end = ft.TextField(
            hint_text="Date fin",
            read_only=True,
            width=130,
        )
        self.date_picker_end.suffix = ft.IconButton(
            ft.Icons.CALENDAR_MONTH, 
            on_click=lambda e: self._show_date_picker(self.date_picker_end)
        )
        
        apply_button = ft.ElevatedButton(
            "Appliquer",
            on_click=self._apply_custom_date,
            style=ft.ButtonStyle(bgcolor=ft.Colors.BLUE_700, color=ft.Colors.WHITE),
        )
        
        self.custom_filter_row = ft.Row(
            controls=[self.date_picker_start, ft.Text("à"), self.date_picker_end, apply_button],
            spacing=10,
            visible=False,
        )
        
        # Recherche
        self.search_field = ft.TextField(
            hint_text="Rechercher par numéro, client, montant...",
            prefix_icon=ft.Icons.SEARCH,
            expand=True,
            border_radius=30,
            filled=True,
            bgcolor=ft.Colors.WHITE,
        )
        self.search_field.on_change = self._on_search
        
        # Barre de sélection
        self.select_all_checkbox = ft.Checkbox(
            label="Tout sélectionner",
        )
        self.select_all_checkbox.on_change = self._select_all
        
        delete_button = ft.ElevatedButton(
            "Supprimer",
            icon=ft.Icons.DELETE,
            on_click=self._delete_selected,
            style=ft.ButtonStyle(bgcolor=ft.Colors.RED_700, color=ft.Colors.WHITE),
        )
        
        self.action_bar = ft.Container(
            content=ft.Row(
                controls=[
                    self.select_all_checkbox,
                    ft.Text("|", color=ft.Colors.GREY_400),
                    delete_button,
                ],
                spacing=15,
            ),
            padding=10,
            bgcolor=ft.Colors.GREY_100,
            border_radius=5,
            visible=False,
        )
        
        # Liste des factures
        self.invoices_list_view = ft.ListView(
            expand=True,
            spacing=10,
            padding=10,
        )
        
        # Indicateur de chargement
        self.loading_indicator = ft.Container(
            content=ft.ProgressRing(),
            alignment=ft.Alignment(0, 0),
            visible=False,
        )
        
        # Statistiques
        self.total_stat_text = ft.Text("0 FC", size=16, weight=ft.FontWeight.BOLD)
        self.count_stat_text = ft.Text("0", size=16, weight=ft.FontWeight.BOLD)
        self.customers_stat_text = ft.Text("0", size=16, weight=ft.FontWeight.BOLD)
        
        stats_container = ft.Container(
            content=ft.Row(
                controls=[
                    self._create_stat_card("Total", self.total_stat_text, ft.Icons.ATTACH_MONEY, ft.Colors.GREEN_700),
                    self._create_stat_card("Factures", self.count_stat_text, ft.Icons.RECEIPT, ft.Colors.BLUE_700),
                    self._create_stat_card("Clients", self.customers_stat_text, ft.Icons.PEOPLE, ft.Colors.PURPLE_700),
                ],
                spacing=10,
                expand=True,
            ),
            padding=10,
        )
        
        # Bouton de synchronisation rapide
        sync_all_button = ft.ElevatedButton(
            "🔄 Synchroniser toutes les factures locales",
            icon=ft.Icons.CLOUD_UPLOAD,
            on_click=lambda e: self._sync_all_invoices(),
            style=ft.ButtonStyle(bgcolor=ft.Colors.GREEN_700, color=ft.Colors.WHITE),
        )
        
        # Assemblage
        main_content = ft.Column(
            controls=[
                self.connection_status_indicator,
                ft.Container(
                    content=ft.Column(
                        controls=[
                            ft.Row([self.filter_dropdown], alignment=ft.MainAxisAlignment.CENTER),
                            self.custom_filter_row,
                            ft.Row([self.search_field], spacing=10),
                        ],
                        spacing=10,
                    ),
                    padding=10,
                ),
                stats_container,
                ft.Container(
                    content=sync_all_button,
                    padding=ft.Padding.symmetric(horizontal=10, vertical=5),
                ),
                self.action_bar,
                ft.Container(
                    content=ft.Text(
                        "Liste des factures",
                        size=16,
                        weight=ft.FontWeight.BOLD,
                    ),
                    padding=ft.Padding.symmetric(horizontal=10, vertical=5),
                ),
                self.invoices_list_view,
                self.loading_indicator,
            ],
            expand=True,
            spacing=5,
        )
        
        self.page.add(
            ft.Container(
                content=ft.Column(
                    controls=[header, main_content],
                    expand=True,
                ),
                expand=True,
                padding=10,
            )
        )
        
        self.is_shown = True
        self.load_invoices()
    
    def _sync_all_invoices(self):
        """Synchronise toutes les factures locales non synchronisées"""
        if not self.connection_manager.is_online_mode():
            self._show_error("Mode hors-ligne - Impossible de synchroniser")
            return
        
        unsynced = [inv for inv in self.invoices_data if not inv.get('server_synced', True)]
        
        if not unsynced:
            self._show_success("Aucune facture à synchroniser")
            return
        
        self._show_loading(True)
        
        def sync_all():
            success_count = 0
            error_count = 0
            
            for invoice in unsynced:
                try:
                    # Marquer comme synchronisée
                    with self.db.get_connection() as conn:
                        cursor = conn.cursor()
                        cursor.execute(
                            "UPDATE invoices SET server_synced = 1, synced_at = ? WHERE invoice_number = ?",
                            (datetime.now().isoformat(), invoice.get('invoice_number'))
                        )
                        conn.commit()
                    success_count += 1
                except Exception as e:
                    error_count += 1
                    logger.error(f"Erreur sync facture {invoice.get('invoice_number')}: {e}")
            
            self.page.run_thread(lambda: self._show_success(f"Synchronisation terminée: {success_count} succès, {error_count} erreurs"))
            self.page.run_thread(lambda: self.load_invoices(force_refresh=True))
            self.page.run_thread(lambda: self._show_loading(False))
        
        threading.Thread(target=sync_all, daemon=True).start()
    
    def _create_stat_card(self, title: str, value_widget: ft.Text, icon, color) -> ft.Container:
        return ft.Container(
            content=ft.Row(
                controls=[
                    ft.Icon(icon, size=24, color=color),
                    ft.Column(
                        controls=[
                            ft.Text(title, size=11, color=ft.Colors.GREY_600),
                            value_widget,
                        ],
                        spacing=2,
                    ),
                ],
                spacing=8,
            ),
            padding=10,
            bgcolor=ft.Colors.WHITE,
            border_radius=10,
            expand=True,
        )
    
    def _update_stats(self):
        """Met à jour les statistiques"""
        total = sum(inv.get('total_amount', 0) for inv in self.invoices_data)
        count = len(self.invoices_data)
        customers = len(set(inv.get('customer_name') for inv in self.invoices_data))
        
        if self.total_stat_text:
            self.total_stat_text.value = self._format_money(total)
        if self.count_stat_text:
            self.count_stat_text.value = str(count)
        if self.customers_stat_text:
            self.customers_stat_text.value = str(customers)
        self.page.update()
    
    def _show_date_picker(self, text_field):
        """Affiche un sélecteur de date"""
        def on_date_selected(e):
            if e.control.value:
                text_field.value = e.control.value.strftime("%Y-%m-%d")
                text_field.update()
            self.page.close(self.date_picker_dialog)
            if self.date_picker_start and self.date_picker_start.value and self.date_picker_end and self.date_picker_end.value:
                self._apply_custom_date(None)
        
        self.date_picker_dialog = ft.DatePicker(
            on_change=on_date_selected,
            first_date=datetime(year=2020, month=1, day=1),
            last_date=datetime.now(),
        )
        self.page.overlay.append(self.date_picker_dialog)
        self.date_picker_dialog.open = True
        self.page.update()
    
    def _debug_check_invoices(self):
        """Méthode de debug pour vérifier les factures dans la base"""
        try:
            with self.db.get_connection() as conn:
                cursor = conn.cursor()
                
                # Vérifier la table sales
                cursor.execute("SELECT COUNT(*) as count FROM sales WHERE invoice_number IS NOT NULL AND invoice_number != ''")
                sales_count = cursor.fetchone()['count']
                logger.info(f"DEBUG - Ventes avec facture dans sales: {sales_count}")
                
                if sales_count > 0:
                    cursor.execute("""
                        SELECT invoice_number, customer_name, total_price, sale_date 
                        FROM sales 
                        WHERE invoice_number IS NOT NULL 
                        LIMIT 5
                    """)
                    for row in cursor.fetchall():
                        logger.info(f"DEBUG - Facture dans sales: {row['invoice_number']}, client={row['customer_name']}, montant={row['total_price']}")
                
                # Vérifier la table invoices
                cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='invoices'")
                if cursor.fetchone():
                    cursor.execute("SELECT COUNT(*) as count FROM invoices")
                    invoices_count = cursor.fetchone()['count']
                    logger.info(f"DEBUG - Factures dans table invoices: {invoices_count}")
                    
                    if invoices_count > 0:
                        cursor.execute("SELECT invoice_number, customer_name, total_amount FROM invoices LIMIT 5")
                        for row in cursor.fetchall():
                            logger.info(f"DEBUG - Facture dans invoices: {row['invoice_number']}, client={row['customer_name']}, montant={row['total_amount']}")
                else:
                    logger.info("DEBUG - Table invoices n'existe pas")
                    
        except Exception as e:
            logger.error(f"DEBUG - Erreur: {e}")
    
    def _test_server_connection(self):
        """Teste la connexion au serveur pour debug"""
        try:
            headers = self.sync_service._get_headers()
            if not headers:
                return {"status": "no_auth"}
            
            response = self.sync_service.session.get(
                f"{self.sync_service.api_url}/sales/test-invoices",
                headers=headers,
                timeout=15
            )
            
            return {
                "status": "ok" if response.status_code == 200 else "error",
                "status_code": response.status_code,
                "data": response.json() if response.status_code == 200 else None
            }
        except Exception as e:
            return {"status": "error", "error": str(e)}
        
    def _go_back(self, e):
        """Retour à l'écran précédent"""
        if len(self.page.views) > 1:
            self.page.views.pop()
            self.page.update()
        else:
            from screens.dashboard_screen import DashboardScreen
            dashboard = DashboardScreen(
                self.page,
                self.db,
                self.sync_service,
                self.auth_service,
                self.current_user,
                None
            )
            dashboard.show()