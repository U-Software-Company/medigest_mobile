import flet as ft
from datetime import datetime
import sqlite3
import os
import tempfile
import logging

logger = logging.getLogger(__name__)


class StockPdfScreen:
    def __init__(self, page: ft.Page, db, sync_service, auth_service, current_user, connection_manager=None):
        self.page = page
        self.db = db
        self.sync_service = sync_service
        self.auth_service = auth_service
        self.current_user = current_user
        self.connection_manager = connection_manager
        self.pdf_content = None
    
    # =========================================================
    # OUTILS
    # =========================================================
    def _branch_id(self):
        """Récupère l'ID de la branche"""
        branch_id = (self.current_user.get("active_branch_id") or 
                    self.current_user.get("branch_id") or
                    self.current_user.get("current_branch_id"))
        
        if branch_id is None:
            user = self.auth_service.get_current_user()
            if user:
                branch_id = user.get("active_branch_id") or user.get("branch_id")
        
        return branch_id
    
    def _get_product_attr(self, product, attr_name, default=None):
        """Récupère un attribut d'un produit (dictionnaire ou objet)"""
        if isinstance(product, dict):
            return product.get(attr_name, default)
        else:
            return getattr(product, attr_name, default)
    
    def _product_name(self, product):
        name = self._get_product_attr(product, 'name')
        return str(name) if name else "N/A"
    
    def _product_code(self, product):
        code = self._get_product_attr(product, 'code')
        return str(code) if code else "N/A"
    
    def _product_stock(self, product):
        stock = self._get_product_attr(product, 'quantity')
        if stock is None:
            stock = self._get_product_attr(product, 'stock', 0)
        return self._safe_int(stock, 0)
    
    def _product_price(self, product):
        price = self._get_product_attr(product, 'selling_price')
        if price is None:
            price = self._get_product_attr(product, 'price', 0)
        return self._safe_float(price, 0.0)
    
    def _product_id(self, product):
        server_id = self._get_product_attr(product, 'server_id')
        if server_id:
            return server_id
        return self._get_product_attr(product, 'id')
    
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
    
    def get_sold_quantity(self, product_id, branch_id):
        """Récupère la quantité vendue d'un produit"""
        try:
            with self.db.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT COALESCE(SUM(quantity), 0) as total
                    FROM sales 
                    WHERE product_id = ? AND branch_id = ?
                """, (str(product_id), str(branch_id)))
                row = cursor.fetchone()
                return self._safe_int(row['total'] if row else 0, 0)
        except Exception as e:
            logger.error(f"Erreur get_sold_quantity: {e}")
            return 0
    
    def get_borrowed_quantity(self, product_id, branch_id):
        """Récupère la quantité empruntée d'un produit"""
        try:
            with self.db.get_connection() as conn:
                cursor = conn.cursor()
                try:
                    cursor.execute("""
                        SELECT COALESCE(SUM(quantity), 0) as total
                        FROM debts 
                        WHERE product_id = ? AND branch_id = ? AND status IN ('pending', 'partial')
                    """, (str(product_id), str(branch_id)))
                    row = cursor.fetchone()
                    if row and 'total' in row.keys():
                        return self._safe_int(row['total'], 0)
                except sqlite3.OperationalError:
                    return 0
                return 0
        except Exception as e:
            logger.error(f"Erreur get_borrowed_quantity: {e}")
            return 0
    
    def get_available_stock(self, stock, sold, borrowed):
        """Calcule le stock disponible restant"""
        return max(0, stock - sold - borrowed)
    
    def is_online(self) -> bool:
        """Vérifie si on est en mode online"""
        if self.connection_manager:
            return self.connection_manager.is_online_mode()
        return self.sync_service and self.sync_service.check_internet_connection()
    
    def sync_products_if_needed(self):
        """Synchronise les produits si nécessaire et si en ligne"""
        if not self.is_online():
            return False
        
        try:
            branch_id = self._branch_id()
            result = self.sync_service.import_products_improved(branch_id)
            return result.get("success", False)
        except Exception as e:
            logger.error(f"Erreur sync_products_if_needed: {e}")
            return False
    
    def generate_pdf_content(self):
        """Génère le contenu du rapport PDF sous forme de texte formaté"""
        branch_id = self._branch_id()
        
        # Synchroniser si nécessaire et si en ligne
        if self.is_online() and self.sync_service:
            self.sync_products_if_needed()
        
        # Récupérer les produits
        try:
            products = self.db.get_products(branch_id)
            if not products and self.is_online():
                self.sync_products_if_needed()
                products = self.db.get_products(branch_id)
        except Exception as e:
            logger.error(f"Erreur récupération produits: {e}")
            products = []
        
        branch_name = self.current_user.get('branch_name', 'N/A')
        branch_address = self.current_user.get('branch_address', '')
        
        # Statistiques
        total_products = len(products)
        low_stock_count = 0
        out_of_stock_count = 0
        products_with_no_available = 0
        total_stock_value = 0
        
        product_lines = []
        
        for p in products:
            try:
                product_id = self._product_id(p)
                stock = self._product_stock(p)
                price = self._product_price(p)
                name = self._product_name(p)
                code = self._product_code(p)
                
                sold = self.get_sold_quantity(product_id, branch_id)
                borrowed = self.get_borrowed_quantity(product_id, branch_id)
                available = self.get_available_stock(stock, sold, borrowed)
                
                total_stock_value += stock * price
                
                if stock < 10:
                    low_stock_count += 1
                if stock == 0:
                    out_of_stock_count += 1
                if available <= 0:
                    products_with_no_available += 1
                
                product_lines.append({
                    'name': name,
                    'code': code,
                    'stock': stock,
                    'sold': sold,
                    'borrowed': borrowed,
                    'available': available,
                    'price': price
                })
            except Exception as e:
                logger.error(f"Erreur traitement produit: {e}")
                continue
        
        # Trier par nom
        product_lines.sort(key=lambda x: x['name'])
        
        # Générer le texte du rapport
        now = datetime.now()
        
        report_lines = []
        report_lines.append("=" * 60)
        report_lines.append(" " * 20 + "RAPPORT DE STOCK")
        report_lines.append("=" * 60)
        report_lines.append("")
        report_lines.append(f"Date d'édition: {now.strftime('%d/%m/%Y à %H:%M:%S')}")
        report_lines.append(f"Succursale: {branch_name}")
        if branch_address:
            report_lines.append(f"Adresse: {branch_address}")
        report_lines.append("")
        report_lines.append("=" * 60)
        report_lines.append(" " * 24 + "RÉSUMÉ")
        report_lines.append("=" * 60)
        report_lines.append("")
        report_lines.append(f"Total produits en stock: {total_products}")
        report_lines.append(f"Valeur totale du stock: {self._format_money(total_stock_value)}")
        report_lines.append(f"Produits en stock faible (<10): {low_stock_count}")
        report_lines.append(f"Produits en rupture de stock: {out_of_stock_count}")
        report_lines.append(f"Produits plus disponibles: {products_with_no_available}")
        report_lines.append("")
        report_lines.append("=" * 60)
        report_lines.append(" " * 20 + "DÉTAIL DES PRODUITS")
        report_lines.append("=" * 60)
        report_lines.append("")
        
        # En-tête du tableau
        report_lines.append(f"{'Produit':<35} {'Code':<12} {'Stock':>6} {'Vendu':>6} {'Emprunté':>8} {'Reste':>6}")
        report_lines.append(f"{'-'*35} {'-'*12} {'-'*6} {'-'*6} {'-'*8} {'-'*6}")
        
        # Ajouter chaque produit
        for p in product_lines:
            name = p['name'][:34] if len(p['name']) > 34 else p['name']
            code = p['code'][:11] if len(p['code']) > 11 else p['code']
            report_lines.append(
                f"{name:<35} {code:<12} {p['stock']:>6} {p['sold']:>6} {p['borrowed']:>8} {p['available']:>6}"
            )
        
        report_lines.append("")
        report_lines.append("=" * 60)
        report_lines.append(f"Fin du rapport - Généré le {now.strftime('%d/%m/%Y %H:%M:%S')}")
        report_lines.append("=" * 60)
        
        return "\n".join(report_lines)
    
    def show_snack_bar(self, message, is_error=False):
        """Affiche un SnackBar"""
        color = ft.Colors.RED if is_error else ft.Colors.GREEN
        snack_bar = ft.SnackBar(
            content=ft.Text(message),
            bgcolor=color,
            duration=3000,
        )
        self.page.overlay.append(snack_bar)
        snack_bar.open = True
        self.page.update()
    
    def download_pdf(self, e):
        """Télécharge le rapport sous forme de fichier texte"""
        if not self.pdf_content:
            self.pdf_content = self.generate_pdf_content()
        
        # Créer un fichier temporaire
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"rapport_stock_{timestamp}.txt"
        
        # Sauvegarder le fichier
        file_path = os.path.join(tempfile.gettempdir(), filename)
        try:
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(self.pdf_content)
            
            # Afficher un dialogue avec le chemin
            def copy_path(e):
                self.page.set_clipboard(file_path)
                self.show_snack_bar("Chemin copié dans le presse-papier")
                dialog.open = False
                self.page.update()
            
            def open_folder(e):
                os.startfile(tempfile.gettempdir())
                dialog.open = False
                self.page.update()
            
            dialog = ft.AlertDialog(
                title=ft.Text("Rapport généré avec succès"),
                content=ft.Column([
                    ft.Text("Le rapport a été sauvegardé dans:", size=14),
                    ft.Text(file_path, selectable=True, size=12, color=ft.Colors.BLUE_700),
                    ft.Text("Vous pouvez copier le chemin ou ouvrir le dossier.", size=12, color=ft.Colors.GREY_600),
                ], tight=True, spacing=10),
                actions=[
                    ft.TextButton("Fermer", on_click=lambda e: self.close_dialog(dialog)),
                    ft.ElevatedButton("Copier le chemin", on_click=copy_path),
                    ft.ElevatedButton("Ouvrir le dossier", on_click=open_folder),
                ],
                actions_alignment=ft.MainAxisAlignment.END,
            )
            self.page.dialog = dialog
            dialog.open = True
            self.page.update()
            
        except Exception as e:
            self.show_snack_bar(f"Erreur lors de la sauvegarde: {str(e)}", is_error=True)
    
    def close_dialog(self, dialog):
        dialog.open = False
        self.page.update()
    
    def show(self):
        """Affiche l'écran PDF avec le rapport"""
        self.page.clean()
        
        # Afficher un indicateur de chargement
        loading_text = ft.Text("Génération du rapport en cours...", size=16)
        self.page.add(ft.Container(content=loading_text, alignment=ft.Alignment.CENTER, expand=True))
        self.page.update()
        
        # Générer le contenu
        try:
            self.pdf_content = self.generate_pdf_content()
        except Exception as e:
            self.pdf_content = f"Erreur lors de la génération du rapport: {str(e)}"
        
        # Header
        header = ft.Container(
            content=ft.Row([
                ft.IconButton(icon=ft.Icons.ARROW_BACK, on_click=lambda e: self.go_back(), icon_color=ft.Colors.WHITE),
                ft.Text("Rapport de Stock", size=24, weight=ft.FontWeight.BOLD, color=ft.Colors.WHITE),
                ft.Row([
                    ft.IconButton(
                        icon=ft.Icons.REFRESH, 
                        on_click=lambda e: self.refresh_report(), 
                        icon_color=ft.Colors.WHITE, 
                        tooltip="Rafraîchir"
                    ),
                    ft.IconButton(
                        icon=ft.Icons.DOWNLOAD, 
                        on_click=self.download_pdf, 
                        icon_color=ft.Colors.WHITE, 
                        tooltip="Télécharger"
                    ),
                ]),
            ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
            padding=10,
            bgcolor=ft.Colors.GREEN_700,
        )
        
        # Diviser le texte en lignes pour un meilleur affichage
        lines = self.pdf_content.split('\n')
        
        # Créer une liste de Text pour chaque ligne
        text_lines = []
        for line in lines:
            if line.startswith('='):
                text_lines.append(ft.Text(line, size=12, color=ft.Colors.GREY_600, selectable=True, font_family="monospace"))
            elif line.strip() and not line.startswith(' '):
                text_lines.append(ft.Text(line, size=12, weight=ft.FontWeight.BOLD, selectable=True, font_family="monospace"))
            else:
                text_lines.append(ft.Text(line, size=12, selectable=True, font_family="monospace"))
        
        # Utiliser un ListView pour l'affichage du rapport avec défilement
        report_list = ft.ListView(
            controls=text_lines,
            expand=True,
            spacing=2,
            padding=10,
        )
        
        # Conteneur pour le rapport
        report_container = ft.Container(
            content=report_list,
            expand=True,
            border=ft.border.all(1, ft.Colors.GREY_300),
            border_radius=8,
            margin=ft.Margin.all(10),
            bgcolor=ft.Colors.WHITE,
        )
        
        # Boutons d'action
        action_row = ft.Row([
            ft.ElevatedButton(
                "Télécharger le rapport",
                icon=ft.Icons.DOWNLOAD,
                on_click=self.download_pdf,
                color=ft.Colors.WHITE,
                bgcolor=ft.Colors.GREEN_700,
            ),
            ft.OutlinedButton(
                "Copier le contenu",
                icon=ft.Icons.COPY,
                on_click=lambda e: self.copy_to_clipboard(),
            ),
        ], alignment=ft.MainAxisAlignment.CENTER, spacing=20)
        
        # Barre d'information
        info_text = ft.Text(
            f"Total: {len([l for l in lines if l and not l.startswith('=') and 'Produit' not in l and '---' not in l and 'RAPPORT' not in l and 'RÉSUMÉ' not in l and 'DÉTAIL' not in l])} produits",
            size=12,
            color=ft.Colors.GREY_600,
        )
        
        main_content = ft.Column([
            header,
            ft.Container(
                content=ft.Row([
                    ft.Text("Aperçu du rapport", size=16, weight=ft.FontWeight.BOLD),
                    info_text,
                ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                margin=ft.Margin.only(top=10, left=15, right=15),
            ),
            report_container,
            action_row,
            ft.Container(height=10),  # Espace en bas
        ], expand=True, spacing=10)
        
        self.page.clean()
        self.page.add(main_content)
        self.page.update()
    
    def refresh_report(self):
        """Rafraîchit le rapport"""
        self.pdf_content = self.generate_pdf_content()
        self.show()
    
    def copy_to_clipboard(self):
        """Copie le contenu du rapport dans le presse-papier"""
        if self.pdf_content:
            self.page.set_clipboard(self.pdf_content)
            self.show_snack_bar("Contenu copié dans le presse-papier")
    
    def go_back(self):
        from screens.stock_report_screen import StockReportScreen
        stock_report = StockReportScreen(
            self.page,
            self.db,
            self.sync_service,
            self.auth_service,
            self.current_user,
            self.connection_manager
        )
        stock_report.show()