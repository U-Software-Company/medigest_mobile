"""
Gestionnaire d'impression pour tickets 80mm - Version avec nouvelle vue
"""
import flet as ft
from datetime import datetime
from typing import Optional, Dict, Any, List
import time


class PrintManager:
    """Gestionnaire d'impression pour tickets 80mm - Affichage dans nouvelle vue"""
    
    def __init__(self, page=None, db=None, current_user=None):
        self.page = page
        self.db = db
        self.current_user = current_user or {}
        
    def _generate_invoice_number(self) -> str:
        """
        Génère un numéro de facture - Priorité au serveur
        """
        import threading
        import time
        
        # Éviter les appels multiples simultanés
        if not hasattr(PrintManager, '_invoice_lock'):
            PrintManager._invoice_lock = threading.Lock()
        
        with PrintManager._invoice_lock:
            # 1. Tenter d'obtenir un numéro du serveur
            server_number = self._get_server_invoice_number()
            if server_number:
                return server_number
            
            # 2. Fallback: numéro local si serveur indisponible
            if self.db and hasattr(self.db, 'get_next_invoice_number'):
                local_number = self.db.get_next_invoice_number()
                # Marquer comme numéro local pour éviter envoi conflictuel
                if local_number and not local_number.startswith('INV-'):
                    return f"LOCAL-{local_number}"
                return local_number
            
            # 3. Fallback ultime
            return f"LOCAL-{datetime.now().strftime('%Y%m%d%H%M%S%f')}"
    
    def _get_server_invoice_number(self, max_retries: int = 3) -> Optional[str]:
        """
        Récupère un numéro de facture unique depuis le serveur
        """
        import requests
        
        try:
            # Récupérer l'URL de l'API
            api_url = "https://backend-medigest.onrender.com/api/v1"
            
            # Récupérer le token depuis l'utilisateur courant
            token = self.current_user.get('token')
            if not token:
                # Essayer de récupérer depuis la base
                if self.db and hasattr(self.db, 'get_current_user'):
                    user = self.db.get_current_user()
                    token = user.get('token') if user else None
            
            if not token:
                return None
            
            headers = {
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json"
            }
            
            for attempt in range(max_retries):
                try:
                    response = requests.get(
                        f"{api_url}/sales/next-invoice-number",
                        headers=headers,
                        timeout=10,
                        verify=False  # Désactiver SSL pour test
                    )
                    
                    if response.status_code == 200:
                        data = response.json()
                        invoice_number = data.get('invoice_number')
                        
                        if invoice_number and invoice_number.startswith('INV-'):
                            print(f"✅ Numéro facture serveur: {invoice_number}")
                            return invoice_number
                        else:
                            print(f"⚠️ Format invalide: {invoice_number}")
                            
                    elif response.status_code == 500:
                        print(f"⚠️ Erreur serveur (tentative {attempt + 1}/{max_retries})")
                        time.sleep(1)
                        
                except Exception as e:
                    print(f"⚠️ Erreur connexion (tentative {attempt + 1}/{max_retries}): {e}")
                    time.sleep(1)
            
            return None
            
        except Exception as e:
            print(f"❌ Erreur _get_server_invoice_number: {e}")
            return None
    
    def sync_invoice_counter_with_server(self) -> bool:
        """
        Synchronise le compteur local avec le serveur
        """
        import requests
        
        try:
            api_url = "https://backend-medigest.onrender.com/api/v1"
            token = self.current_user.get('token')
            
            if not token:
                return False
            
            headers = {
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json"
            }
            
            # Récupérer le dernier numéro utilisé depuis le serveur
            response = requests.get(
                f"{api_url}/sales/last-invoice-number",
                headers=headers,
                timeout=10,
                verify=False
            )
            
            if response.status_code == 200:
                data = response.json()
                last_sequence = data.get('last_sequence', 0)
                
                # Mettre à jour le compteur local
                if self.db and hasattr(self.db, 'sync_invoice_counter'):
                    self.db.sync_invoice_counter(last_sequence + 1)
                    print(f"✅ Compteur synchronisé: prochain numéro séquence {last_sequence + 1}")
                    return True
            
            return False
            
        except Exception as e:
            print(f"⚠️ Erreur synchronisation compteur: {e}")
            return False
    
    def _format_money(self, amount) -> str:
        """Formate un montant en monnaie locale"""
        try:
            return f"{float(amount):,.0f} FC"
        except:
            return "0 FC"
    
    def _format_money_no_currency(self, amount) -> str:
        """Formate un montant sans symbole monétaire"""
        try:
            return f"{float(amount):,.0f}"
        except:
            return "0"
    
    def _get_pharmacy_name(self) -> str:
        """Récupère le nom de la pharmacie depuis current_user"""
        return self.current_user.get('pharmacy_name', self.current_user.get('branch_name', 'Pharmacie'))
    
    # =========================================================
    # SAUVEGARDE FACTURE
    # =========================================================
    
    def save_invoice_from_sale(self, sale_data: Dict, items: List[Dict]) -> str:
        """
        Sauvegarde une facture à partir des données de vente
        """
        # Utiliser le générateur de la base de données
        if self.db and hasattr(self.db, 'get_next_invoice_number'):
            invoice_number = self.db.get_next_invoice_number()
        else:
            invoice_number = self._generate_invoice_number()
        
        invoice = {
            'invoice_number': invoice_number,
            'sale_date': sale_data.get('sale_date', datetime.now().isoformat()),
            'customer_name': sale_data.get('customer_name', 'Client comptant'),
            'total_amount': sale_data.get('total_price', 0),
            'payment_method': sale_data.get('payment_method', 'cash'),
            'branch_id': sale_data.get('branch_id'),
            'seller_id': sale_data.get('seller_id', self.current_user.get('id')),
            'seller_name': sale_data.get('seller_name', self.current_user.get('full_name', 'Vendeur')),
            'status': 'completed',
            'is_modified': 0,
            'original_invoice_number': None,
            'modification_date': None,
            'modification_reason': None
        }
        
        # Sauvegarder dans la base de données si disponible
        if self.db and hasattr(self.db, 'save_invoice'):
            self.db.save_invoice(invoice, items)
            print(f"✅ Facture sauvegardée: {invoice_number}")
        else:
            print(f"⚠️ Base de données non disponible, facture non sauvegardée: {invoice_number}")
        
        return invoice_number
    
    # =========================================================
    # IMPRESSION FACTURE EXISTANTE
    # =========================================================
    
    def print_invoice(self, invoice_data: Dict, items: List[Dict]):
        """Imprime une facture existante avec ses produits"""
        is_modified = invoice_data.get('is_modified', 0)
        original_invoice = invoice_data.get('original_invoice_number')
        is_duplicate = invoice_data.get('is_duplicate', False)
        
        # Construction des lignes produit
        product_rows = []
        for item in items:
            product_name = item.get('product_name', 'Produit')
            quantity = item.get('quantity', 1)
            unit_price = item.get('unit_price', 0)
            total_price = item.get('total_price', quantity * unit_price)
            
            # Ligne produit principale
            product_rows.append(
                ft.Row(
                    controls=[
                        ft.Text(product_name[:25], size=12, expand=2),
                        ft.Text(str(quantity), size=12, width=40, text_align=ft.TextAlign.CENTER),
                        ft.Text(self._format_money_no_currency(unit_price), size=12, width=70, text_align=ft.TextAlign.RIGHT),
                        ft.Text(self._format_money_no_currency(total_price), size=12, width=80, text_align=ft.TextAlign.RIGHT),
                    ],
                    spacing=0,
                )
            )
            
            # Ajouter les informations d'échange/retour si présentes
            if item.get('is_returned'):
                if item.get('exchange_product_name'):
                    exchange_qty = item.get('exchange_quantity', 0)
                    exchange_price = item.get('exchange_unit_price', 0)
                    product_rows.append(
                        ft.Row(
                            controls=[
                                ft.Icon(ft.Icons.SWAP_HORIZ, size=12, color=ft.Colors.PURPLE),
                                ft.Text(f"↺ Échangé: {item.get('exchange_product_name')[:20]}", size=10, color=ft.Colors.PURPLE, expand=True),
                                ft.Text(f"x{exchange_qty}", size=10, color=ft.Colors.PURPLE),
                                ft.Text(self._format_money_no_currency(exchange_qty * exchange_price), size=10, color=ft.Colors.PURPLE, width=80, text_align=ft.TextAlign.RIGHT),
                            ],
                            spacing=5,
                        )
                    )
                elif item.get('returned_quantity', 0) > 0:
                    product_rows.append(
                        ft.Row(
                            controls=[
                                ft.Icon(ft.Icons.UNDO, size=12, color=ft.Colors.ORANGE),
                                ft.Text(f"↺ Retourné: {item.get('returned_quantity')} unités", size=10, color=ft.Colors.ORANGE, expand=True),
                            ],
                            spacing=5,
                        )
                    )
        
        # Titre du ticket
        title = "FACTURE"
        if is_duplicate:
            title = "DUPLICATA"
        elif is_modified:
            title = "FACTURE MODIFIÉE"
        
        # Formater la date
        sale_date = invoice_data.get('sale_date', '')
        if 'T' in str(sale_date):
            try:
                sale_date = datetime.fromisoformat(sale_date.replace('Z', '+00:00')).strftime('%d/%m/%Y %H:%M')
            except:
                sale_date = sale_date.split('T')[0]
        
        # Créer la vue du ticket
        receipt_view = ft.Container(
            content=ft.Column(
                controls=[
                    # En-tête
                    ft.Column(
                        controls=[
                            ft.Text(self._get_pharmacy_name(), size=20, weight=ft.FontWeight.BOLD, text_align=ft.TextAlign.CENTER),
                            ft.Text(invoice_data.get('branch_name', self.current_user.get('branch_name', '')), size=12, color=ft.Colors.GREY_700, text_align=ft.TextAlign.CENTER) if invoice_data.get('branch_name') or self.current_user.get('branch_name') else ft.Container(),
                            ft.Divider(height=1, color=ft.Colors.GREY_400),
                        ],
                        horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                        spacing=5,
                    ),
                    
                    # Titre
                    ft.Text(title, size=18, weight=ft.FontWeight.BOLD, text_align=ft.TextAlign.CENTER),
                    
                    # Numéro
                    ft.Text(f"N°: {invoice_data.get('invoice_number')}", size=12, color=ft.Colors.GREY_700, text_align=ft.TextAlign.CENTER),
                    
                    # Mention facture originale si duplicata
                    ft.Text(
                        f"(Original: {invoice_data.get('original_invoice_number')})" if is_duplicate and invoice_data.get('original_invoice_number') else "",
                        size=10,
                        color=ft.Colors.GREY_500,
                        text_align=ft.TextAlign.CENTER,
                    ),
                    
                    # Informations
                    ft.Column(
                        controls=[
                            self._info_row("Date:", sale_date),
                            self._info_row("Client:", invoice_data.get('customer_name', 'Client comptant')),
                            self._info_row("Vendeur:", invoice_data.get('seller_name', 'Vendeur')),
                            self._info_row("Paiement:", "Espèces" if invoice_data.get('payment_method') == 'cash' else 'Carte'),
                        ],
                        spacing=5,
                    ),
                    
                    ft.Divider(height=1, color=ft.Colors.GREY_400),
                    
                    # En-tête produits
                    ft.Row(
                        controls=[
                            ft.Text("Désignation", size=12, weight=ft.FontWeight.BOLD, expand=2),
                            ft.Text("Qté", size=12, weight=ft.FontWeight.BOLD, width=40, text_align=ft.TextAlign.CENTER),
                            ft.Text("Prix", size=12, weight=ft.FontWeight.BOLD, width=70, text_align=ft.TextAlign.RIGHT),
                            ft.Text("Total", size=12, weight=ft.FontWeight.BOLD, width=80, text_align=ft.TextAlign.RIGHT),
                        ],
                        spacing=0,
                    ),
                    
                    ft.Divider(height=1, color=ft.Colors.GREY_300),
                    
                    # Liste des produits
                    ft.Column(product_rows, spacing=3),
                    
                    ft.Divider(height=1, color=ft.Colors.GREY_400),
                    
                    # Total
                    ft.Row(
                        controls=[
                            ft.Text("TOTAL À PAYER", size=16, weight=ft.FontWeight.BOLD, expand=True),
                            ft.Text(self._format_money(invoice_data.get('total_amount', 0)), size=16, weight=ft.FontWeight.BOLD, color=ft.Colors.GREEN_700),
                        ],
                        spacing=0,
                    ),
                    
                    ft.Divider(height=1, color=ft.Colors.GREY_400),
                    
                    # Remerciements
                    ft.Text("Merci de votre confiance !", size=13, text_align=ft.TextAlign.CENTER, italic=True),
                    
                    # Code barre simplifié
                    ft.Text(invoice_data.get('invoice_number', ''), size=16, text_align=ft.TextAlign.CENTER, font_family="monospace", weight=ft.FontWeight.BOLD),
                    
                    ft.Divider(height=1, color=ft.Colors.GREY_400),
                    
                    # Pied de page
                    ft.Column(
                        controls=[
                            ft.Text("Produits échangés et remboursés sous 7 jours", size=10, text_align=ft.TextAlign.CENTER, color=ft.Colors.GREY_600),
                            ft.Text("sur présentation du ticket", size=10, text_align=ft.TextAlign.CENTER, color=ft.Colors.GREY_600),
                        ],
                        spacing=3,
                        horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                ],
                spacing=5,
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            padding=15,
            bgcolor=ft.Colors.WHITE,
            border_radius=10,
            width=400,
        )
        
        # Afficher dans une nouvelle page
        self.show_receipt_as_page(
            receipt_view, 
            f"{title} - {invoice_data.get('invoice_number', '')}",
            invoice_data
        )
    
    def create_receipt_view(self, sale_data: Dict) -> ft.Container:
        """
        Crée un Container Flet avec le ticket pour affichage intégré
        """
        # Utiliser le numéro de facture fourni ou en générer un nouveau
        receipt_number = sale_data.get('invoice_number')
        if not receipt_number:
            receipt_number = sale_data.get('receipt_number')
        if not receipt_number:
            receipt_number = self._generate_invoice_number()
        
        product_name = sale_data.get('product_name', 'Produit')
        quantity = sale_data.get('quantity', 1)
        unit_price = sale_data.get('unit_price', 0)
        total_price = sale_data.get('total_price', quantity * unit_price)
        customer_name = sale_data.get('customer_name', 'Client comptant')
        sale_date = sale_data.get('sale_date', datetime.now().strftime('%d/%m/%Y %H:%M'))
        payment_method = sale_data.get('payment_method', 'Espèces')
        seller_name = sale_data.get('seller_name', self.current_user.get('full_name', 'Vendeur'))
        branch_name = sale_data.get('branch_name', self.current_user.get('branch_name', ''))
        pharmacy_name = self._get_pharmacy_name()
        
        return ft.Container(
            content=ft.Column(
                controls=[
                    # En-tête
                    ft.Container(
                        content=ft.Column(
                            controls=[
                                ft.Text(pharmacy_name, size=20, weight=ft.FontWeight.BOLD, text_align=ft.TextAlign.CENTER),
                                ft.Text(branch_name, size=12, color=ft.Colors.GREY_700, text_align=ft.TextAlign.CENTER) if branch_name else ft.Container(),
                                ft.Text("Tel: +243 XXX XXX XXX", size=11, color=ft.Colors.GREY_600, text_align=ft.TextAlign.CENTER),
                                ft.Divider(height=1, color=ft.Colors.GREY_400),
                            ],
                            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                            spacing=5,
                        ),
                        padding=ft.Padding.only(bottom=10),
                    ),
                    
                    # Titre
                    ft.Text("FACTURE", size=18, weight=ft.FontWeight.BOLD, text_align=ft.TextAlign.CENTER),
                    ft.Text(f"N°: {receipt_number}", size=12, color=ft.Colors.GREY_700, text_align=ft.TextAlign.CENTER),
                    
                    # Informations
                    ft.Container(
                        content=ft.Column(
                            controls=[
                                self._info_row("Date:", sale_date),
                                self._info_row("Client:", customer_name),
                                self._info_row("Vendeur:", seller_name),
                                self._info_row("Paiement:", payment_method),
                            ],
                            spacing=5,
                        ),
                        padding=ft.Padding.symmetric(vertical=10),
                    ),
                    
                    ft.Divider(height=1, color=ft.Colors.GREY_400),
                    
                    # En-tête produits
                    ft.Container(
                        content=ft.Row(
                            controls=[
                                ft.Text("Désignation", size=12, weight=ft.FontWeight.BOLD, expand=2),
                                ft.Text("Qté", size=12, weight=ft.FontWeight.BOLD, width=40, text_align=ft.TextAlign.CENTER),
                                ft.Text("Prix", size=12, weight=ft.FontWeight.BOLD, width=70, text_align=ft.TextAlign.RIGHT),
                                ft.Text("Total", size=12, weight=ft.FontWeight.BOLD, width=80, text_align=ft.TextAlign.RIGHT),
                            ],
                            spacing=0,
                        ),
                        padding=ft.Padding.symmetric(vertical=5),
                    ),
                    
                    ft.Divider(height=1, color=ft.Colors.GREY_300),
                    
                    # Ligne produit
                    ft.Container(
                        content=ft.Row(
                            controls=[
                                ft.Text(product_name[:30], size=12, expand=2),
                                ft.Text(str(quantity), size=12, width=40, text_align=ft.TextAlign.CENTER),
                                ft.Text(self._format_money_no_currency(unit_price), size=12, width=70, text_align=ft.TextAlign.RIGHT),
                                ft.Text(self._format_money_no_currency(total_price), size=12, width=80, text_align=ft.TextAlign.RIGHT, weight=ft.FontWeight.BOLD),
                            ],
                            spacing=0,
                        ),
                        padding=ft.Padding.symmetric(vertical=5),
                    ),
                    
                    ft.Divider(height=1, color=ft.Colors.GREY_400),
                    
                    # Total
                    ft.Container(
                        content=ft.Row(
                            controls=[
                                ft.Text("TOTAL À PAYER", size=16, weight=ft.FontWeight.BOLD, expand=True),
                                ft.Text(self._format_money(total_price), size=16, weight=ft.FontWeight.BOLD, color=ft.Colors.GREEN_700),
                            ],
                            spacing=0,
                        ),
                        padding=ft.Padding.symmetric(vertical=10),
                    ),
                    
                    ft.Divider(height=1, color=ft.Colors.GREY_400),
                    
                    # Remerciements
                    ft.Container(
                        content=ft.Text("Merci de votre confiance !", size=13, text_align=ft.TextAlign.CENTER, italic=True),
                        padding=ft.Padding.symmetric(vertical=10),
                    ),
                    
                    # Code barre simplifié
                    ft.Container(
                        content=ft.Text(receipt_number, size=16, text_align=ft.TextAlign.CENTER, font_family="monospace", weight=ft.FontWeight.BOLD),
                        padding=ft.Padding.symmetric(vertical=10),
                    ),
                    
                    ft.Divider(height=1, color=ft.Colors.GREY_400),
                    
                    # Pied de page
                    ft.Container(
                        content=ft.Column(
                            controls=[
                                ft.Text("Produits échangés et remboursés sous 7 jours", size=10, text_align=ft.TextAlign.CENTER, color=ft.Colors.GREY_600),
                                ft.Text("sur présentation du ticket", size=10, text_align=ft.TextAlign.CENTER, color=ft.Colors.GREY_600),
                            ],
                            spacing=3,
                            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                        ),
                        padding=ft.Padding.only(top=10),
                    ),
                ],
                spacing=5,
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            padding=15,
            bgcolor=ft.Colors.WHITE,
            border_radius=10,
        )
    
    def create_multiple_receipt_view(self, sales_data: List[Dict], customer_name: str = "Client comptant", total_amount: float = 0, invoice_number: str = None) -> ft.Container:
        """
        Crée un Container Flet avec le ticket pour plusieurs produits (panier)
        """
        # Utiliser le numéro de facture fourni ou en générer un nouveau
        if not invoice_number:
            invoice_number = self._generate_invoice_number()
        
        sale_date = datetime.now().strftime('%d/%m/%Y %H:%M')
        seller_name = self.current_user.get('full_name', 'Vendeur')
        branch_name = self.current_user.get('branch_name', '')
        pharmacy_name = self._get_pharmacy_name()
        
        # Construction des lignes produits
        product_rows = []
        for item in sales_data:
            product_name = item.get('product_name', 'Produit')
            quantity = item.get('quantity', 1)
            unit_price = item.get('unit_price', 0)
            total_price = item.get('total_price', quantity * unit_price)
            
            product_rows.append(
                ft.Container(
                    content=ft.Row(
                        controls=[
                            ft.Text(product_name[:30], size=12, expand=2),
                            ft.Text(str(quantity), size=12, width=40, text_align=ft.TextAlign.CENTER),
                            ft.Text(self._format_money_no_currency(unit_price), size=12, width=70, text_align=ft.TextAlign.RIGHT),
                            ft.Text(self._format_money_no_currency(total_price), size=12, width=80, text_align=ft.TextAlign.RIGHT),
                        ],
                        spacing=0,
                    ),
                    padding=ft.Padding.symmetric(vertical=3),
                )
            )
        
        return ft.Container(
            content=ft.Column(
                controls=[
                    # En-tête
                    ft.Container(
                        content=ft.Column(
                            controls=[
                                ft.Text(pharmacy_name, size=20, weight=ft.FontWeight.BOLD, text_align=ft.TextAlign.CENTER),
                                ft.Text(branch_name, size=12, color=ft.Colors.GREY_700, text_align=ft.TextAlign.CENTER) if branch_name else ft.Container(),
                                ft.Text("Tel: +243 XXX XXX XXX", size=11, color=ft.Colors.GREY_600, text_align=ft.TextAlign.CENTER),
                                ft.Divider(height=1, color=ft.Colors.GREY_400),
                            ],
                            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                            spacing=5,
                        ),
                        padding=ft.Padding.only(bottom=10),
                    ),
                    
                    # Titre
                    ft.Text("FACTURE", size=18, weight=ft.FontWeight.BOLD, text_align=ft.TextAlign.CENTER),
                    ft.Text(f"N°: {invoice_number}", size=12, color=ft.Colors.GREY_700, text_align=ft.TextAlign.CENTER),
                    
                    # Informations
                    ft.Container(
                        content=ft.Column(
                            controls=[
                                self._info_row("Date:", sale_date),
                                self._info_row("Client:", customer_name),
                                self._info_row("Vendeur:", seller_name),
                                self._info_row("Paiement:", "Espèces"),
                            ],
                            spacing=5,
                        ),
                        padding=ft.Padding.symmetric(vertical=10),
                    ),
                    
                    ft.Divider(height=1, color=ft.Colors.GREY_400),
                    
                    # En-tête produits
                    ft.Container(
                        content=ft.Row(
                            controls=[
                                ft.Text("Désignation", size=12, weight=ft.FontWeight.BOLD, expand=2),
                                ft.Text("Qté", size=12, weight=ft.FontWeight.BOLD, width=40, text_align=ft.TextAlign.CENTER),
                                ft.Text("Prix", size=12, weight=ft.FontWeight.BOLD, width=70, text_align=ft.TextAlign.RIGHT),
                                ft.Text("Total", size=12, weight=ft.FontWeight.BOLD, width=80, text_align=ft.TextAlign.RIGHT),
                            ],
                            spacing=0,
                        ),
                        padding=ft.Padding.symmetric(vertical=5),
                    ),
                    
                    ft.Divider(height=1, color=ft.Colors.GREY_300),
                    
                    # Liste des produits
                    ft.Column(product_rows, spacing=0),
                    
                    ft.Divider(height=1, color=ft.Colors.GREY_400),
                    
                    # Total
                    ft.Container(
                        content=ft.Row(
                            controls=[
                                ft.Text("TOTAL À PAYER", size=16, weight=ft.FontWeight.BOLD, expand=True),
                                ft.Text(self._format_money(total_amount), size=16, weight=ft.FontWeight.BOLD, color=ft.Colors.GREEN_700),
                            ],
                            spacing=0,
                        ),
                        padding=ft.Padding.symmetric(vertical=10),
                    ),
                    
                    ft.Divider(height=1, color=ft.Colors.GREY_400),
                    
                    # Remerciements
                    ft.Container(
                        content=ft.Text("Merci de votre confiance !", size=13, text_align=ft.TextAlign.CENTER, italic=True),
                        padding=ft.Padding.symmetric(vertical=10),
                    ),
                    
                    # Code barre simplifié
                    ft.Container(
                        content=ft.Text(invoice_number, size=16, text_align=ft.TextAlign.CENTER, font_family="monospace", weight=ft.FontWeight.BOLD),
                        padding=ft.Padding.symmetric(vertical=10),
                    ),
                    
                    ft.Divider(height=1, color=ft.Colors.GREY_400),
                    
                    # Pied de page
                    ft.Container(
                        content=ft.Column(
                            controls=[
                                ft.Text("Produits échangés et remboursés sous 7 jours", size=10, text_align=ft.TextAlign.CENTER, color=ft.Colors.GREY_600),
                                ft.Text("sur présentation du ticket", size=10, text_align=ft.TextAlign.CENTER, color=ft.Colors.GREY_600),
                            ],
                            spacing=3,
                            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                        ),
                        padding=ft.Padding.only(top=10),
                    ),
                ],
                spacing=5,
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            padding=15,
            bgcolor=ft.Colors.WHITE,
            border_radius=10,
        )
    
    def _info_row(self, label: str, value: str) -> ft.Row:
        """Crée une ligne d'information clé-valeur"""
        return ft.Row(
            controls=[
                ft.Text(label, size=12, weight=ft.FontWeight.W_500, width=80),
                ft.Text(value, size=12, expand=True),
            ],
            spacing=5,
        )
    
    def show_receipt_as_page(self, receipt_view: ft.Container, title: str = "Ticket de vente", sale_data: Dict = None):
        """
        Affiche le ticket dans une nouvelle page (vue) - Version ultra simple
        """
        if not self.page:
            print("❌ Erreur: Page non initialisée dans PrintManager")
            return
        
        def go_back(e):
            if len(self.page.views) > 1:
                self.page.views.pop()
                self.page.update()
        
        def print_ticket(e):
            self.page.snack_bar = ft.SnackBar(
                content=ft.Text("Préparation de l'impression..."),
                bgcolor=ft.Colors.BLUE_700,
                duration=3000,
            )
            self.page.snack_bar.open = True
            self.page.update()
        
        def share_ticket(e):
            if sale_data:
                pharmacy_name = self._get_pharmacy_name()
                ticket_text = f"""{pharmacy_name}
Facture: {sale_data.get('invoice_number', sale_data.get('receipt_number', 'N/A'))}
Produit: {sale_data.get('product_name', 'N/A')}
Quantité: {sale_data.get('quantity', 1)}
Total: {self._format_money(sale_data.get('total_price', 0))}
Date: {sale_data.get('sale_date', datetime.now().strftime('%d/%m/%Y %H:%M'))}"""
                self.page.clipboard = ticket_text
                self.page.snack_bar = ft.SnackBar(
                    content=ft.Text("Ticket copié dans le presse-papier"),
                    bgcolor=ft.Colors.GREEN_700,
                    duration=2000,
                )
                self.page.snack_bar.open = True
                self.page.update()
        
        # Construction simple de la page
        new_view = ft.View()
        new_view.route = "/ticket"
        new_view.padding = 0
        new_view.vertical_alignment = ft.MainAxisAlignment.START
        new_view.horizontal_alignment = ft.CrossAxisAlignment.CENTER
        
        # AppBar
        app_bar = ft.AppBar(
            title=ft.Text(title, color=ft.Colors.WHITE),
            bgcolor=ft.Colors.BLUE_700,
        )
        app_bar.leading = ft.IconButton(ft.Icons.ARROW_BACK, on_click=go_back, icon_color=ft.Colors.WHITE)
        
        # Contenu
        content_container = ft.Container(
            content=ft.Column(
                [
                    ft.Container(content=receipt_view, expand=True),
                    ft.Row(
                        [
                            ft.ElevatedButton("Partager", icon=ft.Icons.SHARE, on_click=share_ticket, expand=True),
                            ft.ElevatedButton("Imprimer", icon=ft.Icons.PRINT, on_click=print_ticket, expand=True),
                        ],
                        spacing=10,
                    ),
                ],
                spacing=10,
                expand=True,
            ),
            padding=20,
            expand=True,
            bgcolor=ft.Colors.GREY_50,
        )
        
        new_view.controls = [app_bar, content_container]
        
        self.page.views.append(new_view)
        self.page.update()
        print(f"✅ Nouvelle page du ticket ouverte: {title}")
    
    def print_sale(self, sale_data: Dict):
        """
        Affiche le ticket pour une vente simple dans une nouvelle page
        Utilise le numéro de facture déjà généré par la base de données
        """
        # Ne pas générer de nouveau numéro, utiliser celui déjà existant
        # Si aucun numéro n'est fourni (cas rare), on en génère un
        if not sale_data.get('invoice_number') and not sale_data.get('receipt_number'):
            sale_data['receipt_number'] = self._generate_invoice_number()
        
        print(f"🖨️ Génération du ticket pour: {sale_data.get('product_name')} - Facture: {sale_data.get('invoice_number', sale_data.get('receipt_number'))}")
        receipt_view = self.create_receipt_view(sale_data)
        self.show_receipt_as_page(
            receipt_view, 
            f"Ticket - {sale_data.get('invoice_number', sale_data.get('receipt_number', 'Vente'))}",
            sale_data
        )
    
    def print_multiple_sale(self, sales_data: List[Dict], customer_name: str = "Client comptant", total_amount: float = 0, invoice_number: str = None):
        """
        Affiche le ticket pour plusieurs produits (panier) dans une nouvelle page
        Utilise le numéro de facture fourni ou en génère un nouveau
        """
        # Si aucun numéro n'est fourni, on en génère un
        if not invoice_number:
            invoice_number = self._generate_invoice_number()
        
        receipt_view = self.create_multiple_receipt_view(sales_data, customer_name, total_amount, invoice_number)
        self.show_receipt_as_page(
            receipt_view, 
            f"Ticket - {invoice_number}"
        )
    
    def show_print_preview(self, lines: List[str], title: str = "Aperçu impression"):
        """Affiche un aperçu d'impression à partir de lignes de texte"""
        if not self.page:
            print("❌ Erreur: Page non initialisée dans PrintManager")
            return
        
        def go_back(e):
            if len(self.page.views) > 1:
                self.page.views.pop()
                self.page.update()
        
        # Convertir les lignes en texte
        preview_text = "\n".join(lines)
        
        new_view = ft.View()
        new_view.route = "/print_preview"
        new_view.padding = 0
        
        app_bar = ft.AppBar(
            title=ft.Text(title, color=ft.Colors.WHITE),
            bgcolor=ft.Colors.BLUE_700,
        )
        app_bar.leading = ft.IconButton(ft.Icons.ARROW_BACK, on_click=go_back, icon_color=ft.Colors.WHITE)
        
        content_container = ft.Container(
            content=ft.Column(
                [
                    ft.Container(
                        content=ft.Text(
                            preview_text,
                            size=12,
                            font_family="monospace",
                            selectable=True,
                        ),
                        padding=20,
                        bgcolor=ft.Colors.WHITE,
                        border_radius=10,
                    ),
                ],
                spacing=10,
                expand=True,
            ),
            padding=20,
            expand=True,
            bgcolor=ft.Colors.GREY_50,
        )
        
        new_view.controls = [app_bar, content_container]
        
        self.page.views.append(new_view)
        self.page.update()