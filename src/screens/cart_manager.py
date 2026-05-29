"""
Gestionnaire centralisé du panier
"""
from datetime import datetime
from typing import List, Dict, Optional
import logging
logger = logging.getLogger(__name__)


class CartManager:
    """Gère toutes les opérations liées au panier"""
    
    def __init__(self, db):
        self.db = db
    
    def get_cart_items(self, session_id: str = 'current') -> List[Dict]:
        """Récupère tous les articles du panier"""
        try:
            with self.db.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT * FROM cart_items WHERE session_id = ? ORDER BY added_at",
                    (session_id,)
                )
                rows = cursor.fetchall()
                return [dict(row) for row in rows]
        except Exception as e:
            print(f"Erreur get_cart_items: {e}")
            return []
    
    def add_item(self, product_id: str, product_name: str, unit_price: float, 
                 quantity: int = 1, session_id: str = 'current') -> bool:
        """Ajoute un article au panier"""
        try:
            with self.db.get_connection() as conn:
                cursor = conn.cursor()
                
                # Vérifier si l'article existe déjà
                cursor.execute(
                    "SELECT id, quantity FROM cart_items WHERE product_id = ? AND session_id = ?",
                    (product_id, session_id)
                )
                existing = cursor.fetchone()
                
                if existing:
                    # Mettre à jour la quantité
                    new_quantity = existing[1] + quantity
                    new_total = round(new_quantity * unit_price, 2)
                    cursor.execute(
                        """
                        UPDATE cart_items 
                        SET quantity = ?, total_price = ?, added_at = ?
                        WHERE id = ?
                        """,
                        (new_quantity, new_total, datetime.now().isoformat(), existing[0])
                    )
                else:
                    # Ajouter un nouvel article
                    cursor.execute(
                        """
                        INSERT INTO cart_items 
                        (product_id, product_name, quantity, unit_price, total_price, added_at, session_id)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                        """,
                        (product_id, product_name, quantity, unit_price, 
                         round(quantity * unit_price, 2), datetime.now().isoformat(), session_id)
                    )
                
                conn.commit()
                return True
        except Exception as e:
            print(f"Erreur add_item: {e}")
            return False
    
    def update_quantity(self, item_id: int, new_quantity: int) -> bool:
        """Met à jour la quantité avec calcul correct du total"""
        try:
            with self.db.get_connection() as conn:
                cursor = conn.cursor()
                # ✅ CORRECTION 10: Utiliser la formule SQL pour recalculer
                cursor.execute("""
                    UPDATE cart_items 
                    SET quantity = ?, 
                        total_price = quantity * unit_price 
                    WHERE id = ?
                """, (new_quantity, item_id))
                conn.commit()
                return cursor.rowcount > 0
        except Exception as e:
            logger.error(f"Erreur mise à jour panier: {e}")
            return False
    
    def remove_item(self, item_id: int) -> bool:
        """Supprime un article du panier"""
        try:
            with self.db.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("DELETE FROM cart_items WHERE id = ?", (item_id,))
                conn.commit()
                return cursor.rowcount > 0
        except Exception as e:
            print(f"Erreur remove_item: {e}")
            return False
    
    def clear_cart(self, session_id: str = 'current') -> bool:
        """Vide le panier"""
        try:
            with self.db.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("DELETE FROM cart_items WHERE session_id = ?", (session_id,))
                conn.commit()
                return True
        except Exception as e:
            print(f"Erreur clear_cart: {e}")
            return False
    
    def get_total(self, session_id: str = 'current') -> float:
        """Calcule le total du panier"""
        try:
            with self.db.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT COALESCE(SUM(total_price), 0) as total FROM cart_items WHERE session_id = ?",
                    (session_id,)
                )
                row = cursor.fetchone()
                return row['total'] if row else 0.0
        except Exception as e:
            print(f"Erreur get_total: {e}")
            return 0.0
    
    def get_count(self, session_id: str = 'current') -> int:
        """Nombre d'articles dans le panier"""
        try:
            with self.db.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT COUNT(*) as count FROM cart_items WHERE session_id = ?",
                    (session_id,)
                )
                row = cursor.fetchone()
                return row['count'] if row else 0
        except Exception as e:
            print(f"Erreur get_count: {e}")
            return 0