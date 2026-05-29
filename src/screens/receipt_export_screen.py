import flet as ft
from datetime import datetime
import json
import base64
try:
    import qrcode
    from io import BytesIO
    QRCODE_AVAILABLE = True
except ImportError:
    QRCODE_AVAILABLE = False
    print("Warning: qrcode module not installed. Run: pip install qrcode")

class ReceiptExportScreen:
    """Écran pour l'exportation et l'impression des reçus avec QR code"""
    
    def __init__(self, page: ft.Page, db, sync_service, auth_service, current_user):
        self.page = page
        self.db = db
        self.sync_service = sync_service
        self.auth_service = auth_service
        self.current_user = current_user
    
    def show_sale_receipt(self, sale_id: int, sale_data: dict):
        """Afficher le reçu d'une vente avec QR code"""
        self.page.clean()
        
        # Générer les données pour le QR code
        receipt_data = {
            "type": "sale",
            "id": sale_id,
            "date": sale_data.get('sale_date', datetime.now().isoformat()),
            "product": sale_data.get('product_name', 'N/A'),
            "quantity": sale_data.get('quantity', 0),
            "unit_price": sale_data.get('unit_price', 0),
            "total": sale_data.get('total_price', 0),
            "customer": sale_data.get('customer_name', 'Client comptant'),
            "branch": self.current_user.get('branch_name', 'N/A'),
            "seller": self.current_user.get('full_name', 'N/A'),
            "receipt_number": f"FV-{sale_id}-{datetime.now().strftime('%Y%m%d')}"
        }
        
        # Générer le QR code
        qr_image = self.generate_qr_code(receipt_data)
        
        # Header
        header = ft.Container(
            content=ft.Row([
                ft.IconButton(icon=ft.Icons.ARROW_BACK, on_click=lambda e: self.go_back(), icon_color=ft.Colors.WHITE),
                ft.Text("Reçu de vente", size=24, weight=ft.FontWeight.BOLD, color=ft.Colors.WHITE),
                ft.IconButton(icon=ft.Icons.PRINT, on_click=lambda e: self.print_receipt(receipt_data), icon_color=ft.Colors.WHITE, tooltip="Imprimer"),
            ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
            padding=10,
            bgcolor=ft.Colors.GREEN_700,
        )
        
        # Contenu du reçu
        receipt_content = self.create_receipt_content(receipt_data, qr_image)
        
        self.page.add(header, receipt_content)
        self.page.update()
    
    def show_expense_receipt(self, expense_id: int, expense_data: dict):
        """Afficher le reçu d'une dépense avec QR code"""
        self.page.clean()
        
        # Générer les données pour le QR code
        receipt_data = {
            "type": "expense",
            "id": expense_id,
            "date": expense_data.get('expense_date', datetime.now().isoformat()),
            "description": expense_data.get('description', 'N/A'),
            "amount": expense_data.get('amount', 0),
            "category": expense_data.get('category', 'Divers'),
            "branch": self.current_user.get('branch_name', 'N/A'),
            "recorded_by": self.current_user.get('full_name', 'N/A'),
            "receipt_number": f"DP-{expense_id}-{datetime.now().strftime('%Y%m%d')}"
        }
        
        # Générer le QR code
        qr_image = self.generate_qr_code(receipt_data)
        
        # Header
        header = ft.Container(
            content=ft.Row([
                ft.IconButton(icon=ft.Icons.ARROW_BACK, on_click=lambda e: self.go_back(), icon_color=ft.Colors.WHITE),
                ft.Text("Reçu de dépense", size=24, weight=ft.FontWeight.BOLD, color=ft.Colors.WHITE),
                ft.IconButton(icon=ft.Icons.PRINT, on_click=lambda e: self.print_receipt(receipt_data), icon_color=ft.Colors.WHITE, tooltip="Imprimer"),
            ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
            padding=10,
            bgcolor=ft.Colors.RED_700,
        )
        
        # Contenu du reçu
        receipt_content = self.create_receipt_content(receipt_data, qr_image)
        
        self.page.add(header, receipt_content)
        self.page.update()
    
    def show_debt_receipt(self, debt_id: int, debt_data: dict, payment_data: dict = None):
        """Afficher le reçu d'une dette ou d'un paiement avec QR code"""
        self.page.clean()
        
        is_payment = payment_data is not None
        
        # Générer les données pour le QR code
        if is_payment:
            receipt_data = {
                "type": "debt_payment",
                "debt_id": debt_id,
                "payment_id": payment_data.get('id', 0),
                "date": payment_data.get('payment_date', datetime.now().isoformat()),
                "customer": debt_data.get('customer_name', 'N/A'),
                "amount_paid": payment_data.get('amount', 0),
                "remaining_amount": debt_data.get('remaining_amount', 0),
                "total_debt": debt_data.get('amount', 0),
                "branch": self.current_user.get('branch_name', 'N/A'),
                "receipt_number": f"PAI-{debt_id}-{datetime.now().strftime('%Y%m%d')}"
            }
            title = "Reçu de paiement"
            bgcolor = ft.Colors.BLUE_700
        else:
            receipt_data = {
                "type": "debt",
                "id": debt_id,
                "date": debt_data.get('created_at', datetime.now().isoformat()),
                "customer": debt_data.get('customer_name', 'N/A'),
                "amount": debt_data.get('amount', 0),
                "remaining": debt_data.get('remaining_amount', 0),
                "due_date": debt_data.get('due_date', 'N/A'),
                "product": debt_data.get('product_name', 'N/A'),
                "quantity": debt_data.get('quantity', 0),
                "unit_price": debt_data.get('unit_price', 0),
                "branch": self.current_user.get('branch_name', 'N/A'),
                "recorded_by": self.current_user.get('full_name', 'N/A'),
                "receipt_number": f"DEB-{debt_id}-{datetime.now().strftime('%Y%m%d')}"
            }
            title = "Reçu de dette"
            bgcolor = ft.Colors.ORANGE_700
        
        # Générer le QR code
        qr_image = self.generate_qr_code(receipt_data)
        
        # Header
        header = ft.Container(
            content=ft.Row([
                ft.IconButton(icon=ft.Icons.ARROW_BACK, on_click=lambda e: self.go_back(), icon_color=ft.Colors.WHITE),
                ft.Text(title, size=24, weight=ft.FontWeight.BOLD, color=ft.Colors.WHITE),
                ft.IconButton(icon=ft.Icons.PRINT, on_click=lambda e: self.print_receipt(receipt_data), icon_color=ft.Colors.WHITE, tooltip="Imprimer"),
            ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
            padding=10,
            bgcolor=bgcolor,
        )
        
        # Contenu du reçu
        receipt_content = self.create_receipt_content(receipt_data, qr_image)
        
        self.page.add(header, receipt_content)
        self.page.update()
    
    def generate_qr_code(self, data: dict) -> ft.Image:
        """Générer un QR code à partir des données"""
        if not QRCODE_AVAILABLE:
            return ft.Container(
                content=ft.Text("Module QR code non installé", size=10, color=ft.Colors.GREY),
                width=100,
                height=100,
                bgcolor=ft.Colors.GREY_200,
                alignment=ft.Alignment.CENTER,
            )
        
        try:
            # Convertir les données en JSON
            json_data = json.dumps(data, ensure_ascii=False)
            
            # Créer le QR code
            qr = qrcode.QRCode(
                version=3,
                error_correction=qrcode.constants.ERROR_CORRECT_M,
                box_size=4,
                border=2,
            )
            qr.add_data(json_data)
            qr.make(fit=True)
            
            # Générer l'image
            img = qr.make_image(fill_color="black", back_color="white")
            
            # Convertir en bytes
            buffer = BytesIO()
            img.save(buffer, format="PNG")
            buffer.seek(0)
            
            # Encoder en base64 pour Flet
            img_base64 = base64.b64encode(buffer.read()).decode()
            
            return ft.Image(
                src_base64=img_base64,
                width=120,
                height=120,
                fit=ft.ImageFit.CONTAIN,
            )
        except Exception as e:
            print(f"Erreur génération QR code: {e}")
            return ft.Container(
                content=ft.Text("Erreur QR", size=10, color=ft.Colors.RED),
                width=100,
                height=100,
                bgcolor=ft.Colors.GREY_200,
                alignment=ft.Alignment.CENTER,
            )
    
    def create_receipt_content(self, receipt_data: dict, qr_image: ft.Image) -> ft.Container:
        """Créer le contenu du reçu"""
        
        # En-tête du reçu
        header_section = ft.Container(
            content=ft.Column([
                ft.Text("MEDIGEST PRO", size=20, weight=ft.FontWeight.BOLD, text_align=ft.TextAlign.CENTER),
                ft.Text(self.current_user.get('branch_name', 'Succursale'), size=12, text_align=ft.TextAlign.CENTER),
                ft.Text(f"Tél: {self.current_user.get('phone', 'N/A')}", size=10, text_align=ft.TextAlign.CENTER),
                ft.Divider(),
            ], horizontal_alignment=ft.CrossAxisAlignment.CENTER),
            padding=10,
        )
        
        # Informations du reçu
        receipt_number = receipt_data.get('receipt_number', f"REC-{datetime.now().strftime('%Y%m%d%H%M%S')}")
        receipt_date = receipt_data.get('date', datetime.now().isoformat())
        if isinstance(receipt_date, str):
            try:
                receipt_date = datetime.fromisoformat(receipt_date).strftime("%d/%m/%Y à %H:%M")
            except:
                receipt_date = datetime.now().strftime("%d/%m/%Y à %H:%M")
        
        info_section = ft.Container(
            content=ft.Column([
                ft.Row([
                    ft.Text("N° Reçu:", size=12, weight=ft.FontWeight.BOLD),
                    ft.Text(receipt_number, size=12),
                ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                ft.Row([
                    ft.Text("Date:", size=12, weight=ft.FontWeight.BOLD),
                    ft.Text(receipt_date, size=12),
                ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
            ]),
            padding=10,
            bgcolor=ft.Colors.GREY_100,
            border_radius=5,
        )
        
        # Détails selon le type
        if receipt_data.get('type') == 'sale':
            details_section = self.create_sale_details(receipt_data)
        elif receipt_data.get('type') == 'expense':
            details_section = self.create_expense_details(receipt_data)
        elif receipt_data.get('type') == 'debt':
            details_section = self.create_debt_details(receipt_data)
        elif receipt_data.get('type') == 'debt_payment':
            details_section = self.create_debt_payment_details(receipt_data)
        else:
            details_section = ft.Text("Type de reçu non reconnu")
        
        # Signature
        signature_section = ft.Container(
            content=ft.Column([
                ft.Divider(),
                ft.Row([
                    ft.Text("Signature du client:", size=10),
                    ft.Text("___________________", size=10),
                ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                ft.Text(f"Émis par: {self.current_user.get('full_name', 'N/A')}", size=10, text_align=ft.TextAlign.CENTER),
            ]),
            padding=10,
        )
        
        # QR code section
        qr_section = ft.Container(
            content=ft.Column([
                ft.Text("Scanner ce QR code pour vérifier l'authenticité", size=10, text_align=ft.TextAlign.CENTER),
                qr_image,
            ], horizontal_alignment=ft.CrossAxisAlignment.CENTER),
            padding=10,
        )
        
        # Pied de page
        footer_section = ft.Container(
            content=ft.Text("Merci de votre confiance !", size=10, text_align=ft.TextAlign.CENTER),
            padding=10,
        )
        
        return ft.Container(
            content=ft.Column([
                header_section,
                info_section,
                details_section,
                signature_section,
                qr_section,
                footer_section,
            ], spacing=10, scroll=ft.ScrollMode.AUTO),
            padding=20,
            bgcolor=ft.Colors.WHITE,
            border_radius=10,
            margin=10,
            shadow=ft.BoxShadow(blur_radius=10, color=ft.Colors.GREY_400),
        )
    
    def create_sale_details(self, data: dict) -> ft.Container:
        """Créer les détails d'une vente"""
        return ft.Container(
            content=ft.Column([
                ft.Text("DÉTAILS DE LA VENTE", size=14, weight=ft.FontWeight.BOLD),
                ft.Row([
                    ft.Text("Produit:", size=12),
                    ft.Text(data.get('product', 'N/A'), size=12, weight=ft.FontWeight.BOLD),
                ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                ft.Row([
                    ft.Text("Quantité:", size=12),
                    ft.Text(str(data.get('quantity', 0)), size=12),
                ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                ft.Row([
                    ft.Text("Prix unitaire:", size=12),
                    ft.Text(f"{data.get('unit_price', 0):,.0f} FC", size=12),
                ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                ft.Divider(),
                ft.Row([
                    ft.Text("TOTAL:", size=14, weight=ft.FontWeight.BOLD),
                    ft.Text(f"{data.get('total', 0):,.0f} FC", size=16, weight=ft.FontWeight.BOLD, color=ft.Colors.GREEN_700),
                ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                ft.Row([
                    ft.Text("Client:", size=12),
                    ft.Text(data.get('customer', 'Client comptant'), size=12),
                ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                ft.Row([
                    ft.Text("Vendeur:", size=12),
                    ft.Text(data.get('seller', 'N/A'), size=12),
                ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
            ]),
            padding=10,
        )
    
    def create_expense_details(self, data: dict) -> ft.Container:
        """Créer les détails d'une dépense"""
        return ft.Container(
            content=ft.Column([
                ft.Text("DÉTAILS DE LA DÉPENSE", size=14, weight=ft.FontWeight.BOLD),
                ft.Row([
                    ft.Text("Description:", size=12),
                    ft.Text(data.get('description', 'N/A'), size=12),
                ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                ft.Row([
                    ft.Text("Catégorie:", size=12),
                    ft.Text(data.get('category', 'Divers'), size=12),
                ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                ft.Divider(),
                ft.Row([
                    ft.Text("MONTANT:", size=14, weight=ft.FontWeight.BOLD),
                    ft.Text(f"{data.get('amount', 0):,.0f} FC", size=16, weight=ft.FontWeight.BOLD, color=ft.Colors.RED_700),
                ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                ft.Row([
                    ft.Text("Enregistré par:", size=12),
                    ft.Text(data.get('recorded_by', 'N/A'), size=12),
                ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
            ]),
            padding=10,
        )
    
    def create_debt_details(self, data: dict) -> ft.Container:
        """Créer les détails d'une dette"""
        return ft.Container(
            content=ft.Column([
                ft.Text("DÉTAILS DE LA DETTE", size=14, weight=ft.FontWeight.BOLD),
                ft.Row([
                    ft.Text("Client:", size=12),
                    ft.Text(data.get('customer', 'N/A'), size=12, weight=ft.FontWeight.BOLD),
                ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                ft.Row([
                    ft.Text("Produit:", size=12),
                    ft.Text(data.get('product', 'N/A'), size=12),
                ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                ft.Row([
                    ft.Text("Quantité:", size=12),
                    ft.Text(str(data.get('quantity', 0)), size=12),
                ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                ft.Row([
                    ft.Text("Prix unitaire:", size=12),
                    ft.Text(f"{data.get('unit_price', 0):,.0f} FC", size=12),
                ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                ft.Divider(),
                ft.Row([
                    ft.Text("MONTANT TOTAL:", size=14, weight=ft.FontWeight.BOLD),
                    ft.Text(f"{data.get('amount', 0):,.0f} FC", size=14, weight=ft.FontWeight.BOLD, color=ft.Colors.ORANGE_700),
                ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                ft.Row([
                    ft.Text("RESTE À PAYER:", size=12, weight=ft.FontWeight.BOLD),
                    ft.Text(f"{data.get('remaining', 0):,.0f} FC", size=12, color=ft.Colors.RED_700),
                ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                ft.Row([
                    ft.Text("Date d'échéance:", size=12),
                    ft.Text(data.get('due_date', 'N/A'), size=12),
                ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
            ]),
            padding=10,
        )
    
    def create_debt_payment_details(self, data: dict) -> ft.Container:
        """Créer les détails d'un paiement de dette"""
        return ft.Container(
            content=ft.Column([
                ft.Text("DÉTAILS DU PAIEMENT", size=14, weight=ft.FontWeight.BOLD),
                ft.Row([
                    ft.Text("Client:", size=12),
                    ft.Text(data.get('customer', 'N/A'), size=12, weight=ft.FontWeight.BOLD),
                ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                ft.Divider(),
                ft.Row([
                    ft.Text("MONTANT PAYÉ:", size=14, weight=ft.FontWeight.BOLD),
                    ft.Text(f"{data.get('amount_paid', 0):,.0f} FC", size=16, weight=ft.FontWeight.BOLD, color=ft.Colors.GREEN_700),
                ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                ft.Row([
                    ft.Text("Reste à payer:", size=12),
                    ft.Text(f"{data.get('remaining_amount', 0):,.0f} FC", size=12, color=ft.Colors.RED_700 if data.get('remaining_amount', 0) > 0 else ft.Colors.GREEN),
                ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                ft.Row([
                    ft.Text("Dette totale initiale:", size=12),
                    ft.Text(f"{data.get('total_debt', 0):,.0f} FC", size=12),
                ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
            ]),
            padding=10,
        )
    
    def print_receipt(self, receipt_data: dict):
        """Imprimer le reçu (simulation - à adapter selon l'imprimante)"""
        # Générer le texte du reçu
        receipt_text = self.generate_receipt_text(receipt_data)
        
        # Afficher dans une boîte de dialogue pour copier
        dialog = ft.AlertDialog(
            title=ft.Text("Impression du reçu"),
            content=ft.Container(
                content=ft.Column([
                    ft.Text("Copiez ce texte pour l'imprimer:", size=12),
                    ft.TextField(
                        value=receipt_text,
                        multiline=True,
                        min_lines=15,
                        max_lines=25,
                        read_only=True,
                    ),
                ]),
                width=400,
                height=500,
            ),
            actions=[
                ft.TextButton("Fermer", on_click=lambda e: setattr(dialog, 'open', False)),
                ft.ElevatedButton("Copier", on_click=lambda e: self.page.set_clipboard(receipt_text)),
            ],
        )
        self.page.dialog = dialog
        dialog.open = True
        self.page.update()
        
        self.page.show_snack_bar(
            ft.SnackBar(content=ft.Text("Reçu prêt à être imprimé"), bgcolor=ft.Colors.GREEN)
        )
    
    def generate_receipt_text(self, data: dict) -> str:
        """Générer le texte du reçu pour impression"""
        receipt_number = data.get('receipt_number', f"REC-{datetime.now().strftime('%Y%m%d%H%M%S')}")
        receipt_date = data.get('date', datetime.now().isoformat())
        if isinstance(receipt_date, str):
            try:
                receipt_date = datetime.fromisoformat(receipt_date).strftime("%d/%m/%Y à %H:%M")
            except:
                receipt_date = datetime.now().strftime("%d/%m/%Y à %H:%M")
        
        text = f"""
{'='*40}
MEDIGEST PRO
{self.current_user.get('branch_name', 'Succursale')}
{'='*40}
N° Reçu: {receipt_number}
Date: {receipt_date}
{'-'*40}
"""
        
        if data.get('type') == 'sale':
            text += f"""
DÉTAILS DE LA VENTE
Produit: {data.get('product', 'N/A')}
Quantité: {data.get('quantity', 0)}
Prix unitaire: {data.get('unit_price', 0):,.0f} FC
{'-'*40}
TOTAL: {data.get('total', 0):,.0f} FC
Client: {data.get('customer', 'Client comptant')}
Vendeur: {data.get('seller', 'N/A')}
"""
        elif data.get('type') == 'expense':
            text += f"""
DÉTAILS DE LA DÉPENSE
Description: {data.get('description', 'N/A')}
Catégorie: {data.get('category', 'Divers')}
{'-'*40}
MONTANT: {data.get('amount', 0):,.0f} FC
Enregistré par: {data.get('recorded_by', 'N/A')}
"""
        elif data.get('type') == 'debt':
            text += f"""
DÉTAILS DE LA DETTE
Client: {data.get('customer', 'N/A')}
Produit: {data.get('product', 'N/A')}
Quantité: {data.get('quantity', 0)}
Prix unitaire: {data.get('unit_price', 0):,.0f} FC
{'-'*40}
MONTANT TOTAL: {data.get('amount', 0):,.0f} FC
RESTE À PAYER: {data.get('remaining', 0):,.0f} FC
Échéance: {data.get('due_date', 'N/A')}
"""
        elif data.get('type') == 'debt_payment':
            text += f"""
DÉTAILS DU PAIEMENT
Client: {data.get('customer', 'N/A')}
{'-'*40}
MONTANT PAYÉ: {data.get('amount_paid', 0):,.0f} FC
Reste à payer: {data.get('remaining_amount', 0):,.0f} FC
Dette totale: {data.get('total_debt', 0):,.0f} FC
"""
        
        text += f"""
{'-'*40}
Signature du client: ___________________
Émis par: {self.current_user.get('full_name', 'N/A')}
{'='*40}
Merci de votre confiance !
QR code disponible pour vérification
"""
        return text
    
    def go_back(self):
        from screens.dashboard_screen import DashboardScreen
        dashboard = DashboardScreen(self.page, self.db, self.sync_service, self.auth_service, self.current_user)
        dashboard.show()