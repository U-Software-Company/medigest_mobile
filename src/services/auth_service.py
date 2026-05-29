# services/auth_service.py - Version finale alignée avec l'architecture branche-first

import json
import os
import logging
from datetime import datetime
from typing import Dict, Optional
from services.json_storage import JSONStorage

logger = logging.getLogger(__name__)


class AuthService:
    """
    Service d'authentification locale.
    
    Architecture:
    - L'utilisateur appartient à une BRANCHE (active_branch_id)
    - La branche appartient à une PHARMACIE (parent_pharmacy_id)
    - La pharmacie appartient à un TENANT
    - L'abonnement est lié à la BRANCHE (BranchSubscription)
    
    Sources de données:
    - pharmacies.py → /api/v1/pharmacies/active → pharmacy.name
    - subscriptions.py → /api/v1/subscriptions/status → abonnement de la branche
    - branches.py → /api/v1/branches → infos de la branche
    """
    
    def __init__(self, db):
        self.db = db
        self._ensure_table()
    
    def _ensure_table(self):
        """Crée la table user avec la structure optimisée pour l'architecture branche-first."""
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            
            # Supprimer l'ancienne table si elle existe
            cursor.execute("DROP TABLE IF EXISTS user")
            
            cursor.execute("""
                CREATE TABLE user (
                    -- Identité
                    id TEXT PRIMARY KEY,
                    username TEXT NOT NULL,
                    email TEXT DEFAULT '',
                    full_name TEXT DEFAULT '',
                    role TEXT DEFAULT 'cashier',
                    
                    -- Authentification
                    token TEXT NOT NULL DEFAULT '',
                    refresh_token TEXT DEFAULT '',
                    
                    -- Hiérarchie: User → Branche → Pharmacie → Tenant
                    active_branch_id TEXT DEFAULT '',
                    branch_name TEXT DEFAULT '',
                    pharmacy_id TEXT DEFAULT '',
                    pharmacy_name TEXT DEFAULT '',
                    tenant_id TEXT DEFAULT '',
                    tenant_name TEXT DEFAULT '',
                    
                    -- Abonnement (lié à la branche)
                    subscription_data TEXT DEFAULT '{}',
                    
                    -- Synchronisation
                    last_sync TEXT DEFAULT '',
                    
                    -- Métadonnées
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.commit()
            logger.info("✅ Table user créée (architecture branche-first)")

    # =========================================================================
    # SAUVEGARDE DE L'UTILISATEUR (PREMIÈRE CONNEXION)
    # =========================================================================

    def save_user_simple(self, user_data: Dict) -> bool:
        """
        Version simplifiée de sauvegarde pour la première connexion.
        À utiliser quand les données complètes ne sont pas disponibles.
        """
        try:
            logger.info("💾 Sauvegarde utilisateur (mode simplifié)")
            
            # Extraire les données de base
            token = user_data.get('access_token') or user_data.get('token', '')
            if not token:
                logger.error("❌ Aucun token - sauvegarde impossible")
                return False
            
            user_id = str(user_data.get('id', user_data.get('user_id', '')))
            username = user_data.get('username', user_data.get('email', 'user'))
            email = user_data.get('email', '')
            full_name = user_data.get('full_name', user_data.get('nom_complet', username))
            role = user_data.get('role', 'cashier')
            
            # Extraire la branche
            branch_id = str(user_data.get('branch_id', user_data.get('active_branch_id', '0')))
            branch_name = user_data.get('branch_name', user_data.get('current_branch_name', 'Branche principale'))
            
            # Extraire la pharmacie
            pharmacy_id = str(user_data.get('pharmacy_id', user_data.get('tenant_id', '0')))
            pharmacy_name = user_data.get('pharmacy_name', user_data.get('tenant_name', 'Pharmacie'))
            
            with self.db.get_connection() as conn:
                cursor = conn.cursor()
                
                # Supprimer l'ancien
                cursor.execute("DELETE FROM user")
                
                # Insérer le nouveau
                cursor.execute("""
                    INSERT INTO user (
                        id, username, email, full_name, role,
                        token, refresh_token,
                        active_branch_id, branch_name,
                        pharmacy_id, pharmacy_name,
                        tenant_id, tenant_name,
                        last_sync, subscription_data, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    user_id, username, email, full_name, role,
                    token, user_data.get('refresh_token', ''),
                    branch_id, branch_name,
                    pharmacy_id, pharmacy_name,
                    pharmacy_id, pharmacy_name,  # tenant_id = pharmacy_id, tenant_name = pharmacy_name
                    datetime.now().isoformat(),
                    json.dumps({"has_subscription": True, "is_active": True}),
                    datetime.now().isoformat()
                ))
                conn.commit()
                
                logger.info(f"✅ Utilisateur sauvegardé: {username} (ID: {user_id})")
                return True
                
        except Exception as e:
            logger.error(f"❌ Erreur sauvegarde simplifiée: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    def save_user(self, user_data: Dict) -> bool:
        """
        Sauvegarde l'utilisateur dans la base locale lors de la première connexion.
        
        Structure attendue de user_data (depuis l'API login):
        {
            "user": {
                "id": "...",
                "username": "...",
                "email": "...",
                "full_name": "...",
                "role": "...",
                "active_branch_id": "..."
            },
            "access_token": "...",
            "refresh_token": "...",
            "current_branch": {
                "id": "...",
                "name": "..."
            },
            "current_pharmacy": {
                "id": "...",
                "name": "..."
            },
            "tenant": {
                "id": "...",
                "nom_pharmacie": "..."  // ou "name"
            },
            "subscription": {
                "has_subscription": true,
                "is_active": true,
                "access_mode": "full",
                "subscription": {...},
                "limits": {...},
                "usage": {...}
            },
            "branches": [...]
        }
        """
        try:
            logger.info("=" * 60)
            logger.info("💾 SAUVEGARDE UTILISATEUR - ARCHITECTURE BRANCHE-FIRST")
            logger.info("=" * 60)
            
            # -----------------------------------------------------------------
            # 1. EXTRAIRE LES DONNÉES BRUTES
            # -----------------------------------------------------------------
            user_info = user_data.get('user', {}) if isinstance(user_data.get('user'), dict) else {}
            tenant_info = user_data.get('tenant', {}) if isinstance(user_data.get('tenant'), dict) else {}
            branches = user_data.get('branches', []) if isinstance(user_data.get('branches'), list) else []
            current_branch = user_data.get('current_branch', {}) if isinstance(user_data.get('current_branch'), dict) else {}
            current_pharmacy = user_data.get('current_pharmacy', {}) if isinstance(user_data.get('current_pharmacy'), dict) else {}
            subscription = user_data.get('subscription', {}) if isinstance(user_data.get('subscription'), dict) else {}
            
            # -----------------------------------------------------------------
            # 2. EXTRAIRE LA BRANCHE ACTIVE (priorité multiple)
            # -----------------------------------------------------------------
            active_branch_id = None
            branch_name = None
            
            logger.info("🔍 RECHERCHE DE LA BRANCHE ACTIVE")
            logger.info(f"   current_branch: {current_branch}")
            logger.info(f"   branches disponibles: {len(branches)}")
            logger.info(f"   user_info.active_branch_id: {user_info.get('active_branch_id')}")
            
            # Priorité 1: current_branch (fourni par l'API login)
            if current_branch.get('id'):
                active_branch_id = str(current_branch.get('id'))
                branch_name = current_branch.get('name') or current_branch.get('nom')
                logger.info(f"   ✅ Priorité 1 (current_branch): {branch_name} ({active_branch_id})")
            
            # Priorité 2: Chercher dans la liste des branches
            if not branch_name and active_branch_id and branches:
                for branch in branches:
                    if str(branch.get('id')) == active_branch_id:
                        branch_name = branch.get('name') or branch.get('nom')
                        logger.info(f"   ✅ Priorité 2 (liste branches): {branch_name}")
                        break
            
            # Priorité 3: user_info.active_branch_id
            if not active_branch_id and user_info.get('active_branch_id'):
                active_branch_id = str(user_info.get('active_branch_id'))
                logger.info(f"   🔍 Priorité 3 (user_info): {active_branch_id}")
                if branches:
                    for branch in branches:
                        if str(branch.get('id')) == active_branch_id:
                            branch_name = branch.get('name') or branch.get('nom')
                            logger.info(f"   ✅ Nom trouvé: {branch_name}")
                            break
            
            # Priorité 4: Première branche de la liste
            if not active_branch_id and branches:
                first_branch = branches[0]
                active_branch_id = str(first_branch.get('id'))
                branch_name = first_branch.get('name') or first_branch.get('nom')
                logger.info(f"   ⚠️ Priorité 4 (première branche): {branch_name} ({active_branch_id})")
            
            # Fallback
            if not active_branch_id:
                active_branch_id = "0"
                logger.warning("   ❌ Aucune branche trouvée, ID = 0")
            if not branch_name:
                branch_name = "Branche sans nom"
                logger.warning("   ❌ Aucun nom de branche trouvé")
            
            # -----------------------------------------------------------------
            # 3. EXTRAIRE LE NOM DE LA PHARMACIE
            # -----------------------------------------------------------------
            pharmacy_id = None
            pharmacy_name = None
            
            logger.info("🏪 RECHERCHE DE LA PHARMACIE")
            
            # current_pharmacy (fourni par pharmacies.py → /pharmacies/active)
            if current_pharmacy:
                pharmacy_id = str(current_pharmacy.get('id')) if current_pharmacy.get('id') else None
                pharmacy_name = current_pharmacy.get('name')
                if pharmacy_name:
                    logger.info(f"   ✅ Via current_pharmacy: {pharmacy_name} (ID: {pharmacy_id})")
            
            # Fallback: tenant_info
            if not pharmacy_name and tenant_info:
                pharmacy_id = str(tenant_info.get('id')) if tenant_info.get('id') else pharmacy_id
                pharmacy_name = (
                    tenant_info.get('nom_pharmacie') or 
                    tenant_info.get('name') or 
                    tenant_info.get('pharmacy_name')
                )
                if pharmacy_name:
                    logger.info(f"   ✅ Via tenant_info: {pharmacy_name} (ID: {pharmacy_id})")
            
            # Fallback: user_info
            if not pharmacy_id and user_info.get('active_pharmacy_id'):
                pharmacy_id = str(user_info.get('active_pharmacy_id'))
            
            if not pharmacy_name:
                pharmacy_name = "Pharmacie"
                logger.warning("   ⚠️ Nom pharmacie par défaut")
            if not pharmacy_id:
                pharmacy_id = "0"
            
            tenant_name = pharmacy_name  # Le tenant_name = nom de la pharmacie
            
            # -----------------------------------------------------------------
            # 4. EXTRAIRE LE TENANT
            # -----------------------------------------------------------------
            tenant_id = None
            if tenant_info.get('id'):
                tenant_id = str(tenant_info.get('id'))
            elif user_info.get('tenant_id'):
                tenant_id = str(user_info.get('tenant_id'))
            elif user_data.get('tenant_id'):
                tenant_id = str(user_data.get('tenant_id'))
            
            if not tenant_id:
                tenant_id = "0"
                logger.warning("   ⚠️ Tenant ID par défaut: 0")
            else:
                logger.info(f"🏢 Tenant ID: {tenant_id}")
            
            # -----------------------------------------------------------------
            # 5. EXTRAIRE L'ABONNEMENT (depuis subscriptions.py)
            # -----------------------------------------------------------------
            subscription_info = self._extract_subscription_info(subscription, user_data)
            logger.info(f"📋 Abonnement: has={subscription_info.get('has_subscription')}, active={subscription_info.get('is_active')}")
            
            # -----------------------------------------------------------------
            # 6. TOKEN ET IDENTITÉ
            # -----------------------------------------------------------------
            token = user_data.get('access_token') or user_data.get('token', '')
            refresh_token = user_data.get('refresh_token', '')
            role = user_info.get('role') or user_data.get('role', 'cashier')
            
            if not token:
                logger.error("❌ AUCUN TOKEN - SAUVEGARDE IMPOSSIBLE")
                return False
            
            user_id = str(user_info.get('id') or user_data.get('id', ''))
            username = user_info.get('username') or user_info.get('email') or user_data.get('email', 'user')
            email = user_info.get('email') or user_data.get('email', '')
            full_name = (user_info.get('full_name') or user_info.get('nom_complet') or 
                        user_data.get('nom_complet') or user_data.get('full_name', ''))
            
            # -----------------------------------------------------------------
            # 7. ASSEMBLER LES DONNÉES NETTOYÉES
            # -----------------------------------------------------------------
            cleaned_data = {
                'id': user_id or '0',
                'username': username,
                'email': email or '',
                'full_name': full_name or '',
                'role': role,
                'token': token,
                'refresh_token': refresh_token or '',
                'active_branch_id': active_branch_id,
                'branch_name': branch_name,
                'pharmacy_id': pharmacy_id,
                'pharmacy_name': pharmacy_name,
                'tenant_id': tenant_id,
                'tenant_name': tenant_name,
                'last_sync': datetime.now().isoformat(),
                'subscription_data': json.dumps({
                    "branch_id": active_branch_id,
                    "info": subscription_info,
                    "last_update": datetime.now().isoformat()
                }),
                'updated_at': datetime.now().isoformat()
            }
            
            logger.info("📝 DONNÉES PRÉPARÉES:")
            logger.info(f"   Utilisateur: {cleaned_data['full_name']} ({cleaned_data['username']})")
            logger.info(f"   Rôle: {cleaned_data['role']}")
            logger.info(f"   Branche: {cleaned_data['branch_name']} (ID: {cleaned_data['active_branch_id']})")
            logger.info(f"   Pharmacie: {cleaned_data['pharmacy_name']} (ID: {cleaned_data['pharmacy_id']})")
            logger.info(f"   Tenant: {cleaned_data['tenant_name']} (ID: {cleaned_data['tenant_id']})")
            logger.info(f"   Token: {'***' + token[-8:] if token else 'MANQUANT'}")
            
            # -----------------------------------------------------------------
            # 8. SAUVEGARDE DANS SQLITE
            # -----------------------------------------------------------------
            with self.db.get_connection() as conn:
                cursor = conn.cursor()
                
                # Supprimer l'ancien utilisateur
                cursor.execute("DELETE FROM user")
                logger.info("🗑️ Ancien utilisateur supprimé")
                
                # Insérer le nouveau
                cursor.execute("""
                    INSERT INTO user (
                        id, username, email, full_name, role,
                        token, refresh_token,
                        active_branch_id, branch_name,
                        pharmacy_id, pharmacy_name,
                        tenant_id, tenant_name,
                        last_sync, subscription_data, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    cleaned_data['id'],
                    cleaned_data['username'],
                    cleaned_data['email'],
                    cleaned_data['full_name'],
                    cleaned_data['role'],
                    cleaned_data['token'],
                    cleaned_data['refresh_token'],
                    cleaned_data['active_branch_id'],
                    cleaned_data['branch_name'],
                    cleaned_data['pharmacy_id'],
                    cleaned_data['pharmacy_name'],
                    cleaned_data['tenant_id'],
                    cleaned_data['tenant_name'],
                    cleaned_data['last_sync'],
                    cleaned_data['subscription_data'],
                    cleaned_data['updated_at']
                ))
                conn.commit()
                
                # Vérification
                cursor.execute("SELECT COUNT(*) FROM user")
                count = cursor.fetchone()[0]
                
                if count > 0:
                    logger.info("✅✅✅ UTILISATEUR SAUVEGARDÉ AVEC SUCCÈS")
                    logger.info("=" * 60)
                    return True
                else:
                    logger.error("❌ Échec insertion - aucune ligne trouvée")
                    return False
                    
        except Exception as e:
            logger.error(f"❌ Erreur sauvegarde: {e}")
            import traceback
            traceback.print_exc()
            return False

    def save_user_from_login(self, login_response: Dict) -> bool:
        """
        Version simplifiée pour sauvegarder l'utilisateur après login.
        Sauvegarde à la fois dans SQLite ET dans JSON (fallback).
        """
        try:
            logger.info("=" * 60)
            logger.info("💾 SAUVEGARDE UTILISATEUR (DEPUIS LOGIN)")
            logger.info("=" * 60)
            
            # Vérification du token
            token = login_response.get('access_token') or login_response.get('token')
            if not token:
                logger.error("❌ Aucun token dans la réponse")
                return False
            
            # --- Extraire les données (même code que précédemment) ---
            user_info = login_response.get('user', {})
            if not isinstance(user_info, dict):
                user_info = {}
            
            current_branch = login_response.get('current_branch', {})
            if not isinstance(current_branch, dict):
                current_branch = {}
            
            current_pharmacy = login_response.get('current_pharmacy', {})
            if not isinstance(current_pharmacy, dict):
                current_pharmacy = {}
            
            tenant_info = login_response.get('tenant', {})
            if not isinstance(tenant_info, dict):
                tenant_info = {}
            
            subscription = login_response.get('subscription', {})
            if not isinstance(subscription, dict):
                subscription = {}
            
            # --- Déterminer la branche active ---
            active_branch_id = (
                current_branch.get('id') or 
                user_info.get('active_branch_id') or 
                '0'
            )
            branch_name = (
                current_branch.get('name') or 
                current_branch.get('nom') or 
                user_info.get('branch_name') or 
                'Branche principale'
            )
            
            # --- Déterminer la pharmacie ---
            pharmacy_id = (
                current_pharmacy.get('id') or 
                tenant_info.get('id') or 
                user_info.get('pharmacy_id') or 
                '0'
            )
            pharmacy_name = (
                current_pharmacy.get('name') or 
                tenant_info.get('nom_pharmacie') or 
                tenant_info.get('name') or 
                user_info.get('pharmacy_name') or 
                'Pharmacie'
            )
            
            # --- Déterminer le tenant ---
            tenant_id = (
                tenant_info.get('id') or 
                user_info.get('tenant_id') or 
                pharmacy_id
            )
            tenant_name = pharmacy_name
            
            # --- Données utilisateur ---
            user_id = str(user_info.get('id') or login_response.get('id', '0'))
            username = (
                user_info.get('username') or 
                user_info.get('email') or 
                login_response.get('email', 'user')
            )
            email = user_info.get('email') or ''
            full_name = (
                user_info.get('full_name') or 
                user_info.get('nom_complet') or 
                username
            )
            role = user_info.get('role') or 'cashier'
            refresh_token = login_response.get('refresh_token', '')
            
            # --- Abonnement ---
            subscription_data = {
                "has_subscription": subscription.get('has_subscription', True),
                "is_active": subscription.get('is_active', True),
                "access_mode": subscription.get('access_mode', 'full'),
                "plan_name": subscription.get('subscription', {}).get('plan_name', 'Standard'),
                "days_remaining": subscription.get('subscription', {}).get('days_remaining', 30),
                "last_update": datetime.now().isoformat()
            }
            
            # --- Préparer les données pour SQLite et JSON ---
            cleaned_data = {
                'id': user_id,
                'username': username,
                'email': email,
                'full_name': full_name,
                'role': role,
                'token': token,
                'refresh_token': refresh_token,
                'active_branch_id': str(active_branch_id),
                'branch_name': branch_name,
                'pharmacy_id': str(pharmacy_id),
                'pharmacy_name': pharmacy_name,
                'tenant_id': str(tenant_id),
                'tenant_name': tenant_name,
                'last_sync': datetime.now().isoformat(),
                'subscription_data': json.dumps(subscription_data),
                'updated_at': datetime.now().isoformat()
            }
            
            logger.info(f"📝 DONNÉES PRÉPARÉES:")
            logger.info(f"   Utilisateur: {cleaned_data['full_name']} ({cleaned_data['username']})")
            logger.info(f"   Branche: {cleaned_data['branch_name']} (ID: {cleaned_data['active_branch_id']})")
            logger.info(f"   Pharmacie: {cleaned_data['pharmacy_name']} (ID: {cleaned_data['pharmacy_id']})")
            logger.info(f"   Token: {'✓' + token[-8:] if token else '✗'}")
            
            # ✅ ÉTAPE 1: Sauvegarde dans SQLite
            sqlite_success = False
            try:
                with self.db.get_connection() as conn:
                    cursor = conn.cursor()
                    cursor.execute("DELETE FROM user")
                    cursor.execute("""
                        INSERT INTO user (
                            id, username, email, full_name, role,
                            token, refresh_token,
                            active_branch_id, branch_name,
                            pharmacy_id, pharmacy_name,
                            tenant_id, tenant_name,
                            last_sync, subscription_data, updated_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        cleaned_data['id'],
                        cleaned_data['username'],
                        cleaned_data['email'],
                        cleaned_data['full_name'],
                        cleaned_data['role'],
                        cleaned_data['token'],
                        cleaned_data['refresh_token'],
                        cleaned_data['active_branch_id'],
                        cleaned_data['branch_name'],
                        cleaned_data['pharmacy_id'],
                        cleaned_data['pharmacy_name'],
                        cleaned_data['tenant_id'],
                        cleaned_data['tenant_name'],
                        cleaned_data['last_sync'],
                        cleaned_data['subscription_data'],
                        cleaned_data['updated_at']
                    ))
                    conn.commit()
                    sqlite_success = True
                    logger.info("✅ SQLite: Utilisateur sauvegardé")
            except Exception as e:
                logger.error(f"❌ SQLite: Erreur sauvegarde: {e}")
            
            # ✅ ÉTAPE 2: Sauvegarde dans JSON (fallback TOUJOURS)
            json_success = JSONStorage.save_user(cleaned_data)
            if json_success:
                logger.info("✅ JSON: Utilisateur sauvegardé")
            
            # ✅ ÉTAPE 3: Sauvegarde de l'abonnement dans JSON
            sub_success = JSONStorage.save_subscription(subscription_data, str(active_branch_id))
            if sub_success:
                logger.info("✅ JSON: Abonnement sauvegardé")
            
            # Succès si au moins une méthode a fonctionné
            success = sqlite_success or json_success
            
            if success:
                logger.info("✅ UTILISATEUR SAUVEGARDÉ AVEC SUCCÈS (SQLite + JSON)")
            else:
                logger.error("❌ ÉCHEC TOTAL de la sauvegarde utilisateur")
            
            logger.info("=" * 60)
            return success
            
        except Exception as e:
            logger.error(f"❌ Erreur sauvegarde: {e}")
            import traceback
            traceback.print_exc()
            return False

    
    def _extract_subscription_info(self, subscription: Dict, user_data: Dict) -> Dict:
        """
        Extrait les informations d'abonnement depuis la réponse de subscriptions.py.
        
        Structure attendue (depuis /subscriptions/status):
        {
            "has_subscription": true,
            "is_active": true,
            "access_mode": "full",
            "subscription": {
                "plan": "professional",
                "plan_name": "Professionnel",
                "end_date": "...",
                "days_remaining": 25,
                "is_trial": false,
                ...
            },
            "limits": {
                "max_products": "Illimité",
                "max_users": "20",
                ...
            },
            "usage": {
                "current_products": 150,
                "current_users": 5
            }
        }
        """
        try:
            # Si pas de données d'abonnement
            if not subscription or not isinstance(subscription, dict):
                # Vérifier si user_data contient subscription_active
                if user_data.get('subscription_active') is not None:
                    is_active = user_data.get('subscription_active', True)
                    return {
                        "has_subscription": True,
                        "is_active": is_active,
                        "access_mode": "full" if is_active else "read_only",
                        "plan": "Standard",
                        "status": "active" if is_active else "expired",
                        "subscription": {},
                        "limits": {},
                        "usage": {}
                    }
                return {
                    "has_subscription": False,
                    "is_active": False,
                    "access_mode": "read_only",
                    "plan": "Aucun",
                    "status": "inactive",
                    "subscription": {},
                    "limits": {},
                    "usage": {}
                }
            
            # Extraire les sous-objets
            sub_data = subscription.get('subscription', {})
            if not isinstance(sub_data, dict):
                sub_data = {}
            
            limits_data = subscription.get('limits', {})
            if not isinstance(limits_data, dict):
                limits_data = {}
            
            usage_data = subscription.get('usage', {})
            if not isinstance(usage_data, dict):
                usage_data = {}
            
            # Construire l'info
            info = {
                "has_subscription": subscription.get('has_subscription', True),
                "is_active": subscription.get('is_active', True),
                "access_mode": subscription.get('access_mode', 'full'),
                "plan": sub_data.get('plan') or sub_data.get('plan_name', 'Standard'),
                "plan_name": sub_data.get('plan_name') or subscription.get('plan_name', 'Standard'),
                "status": sub_data.get('status', 'active'),
                "subscription": {
                    "id": sub_data.get('id'),
                    "branch_id": sub_data.get('branch_id'),
                    "plan": sub_data.get('plan'),
                    "plan_name": sub_data.get('plan_name'),
                    "status": sub_data.get('status'),
                    "end_date": sub_data.get('end_date'),
                    "days_remaining": sub_data.get('days_remaining', 0),
                    "is_trial": sub_data.get('is_trial', False),
                    "trial_days_remaining": sub_data.get('trial_days_remaining', 0),
                    "price": sub_data.get('price', 0),
                    "currency": sub_data.get('currency', 'EUR'),
                    "billing_cycle": sub_data.get('billing_cycle', 'monthly'),
                    "max_products": sub_data.get('max_products', 0),
                    "max_users": sub_data.get('max_users', 0),
                    "max_storage_mb": sub_data.get('max_storage_mb', 0),
                    "auto_renew": sub_data.get('auto_renew', True)
                },
                "limits": {
                    "max_products": limits_data.get('max_products', 'Illimité'),
                    "max_users": limits_data.get('max_users', 'Illimité'),
                    "max_storage_mb": limits_data.get('max_storage_mb', 'Illimité')
                },
                "usage": {
                    "current_products": usage_data.get('current_products', 0),
                    "current_users": usage_data.get('current_users', 0)
                }
            }
            
            # Nettoyer les None du sous-objet subscription
            info['subscription'] = {
                k: v for k, v in info['subscription'].items()
                if v is not None
            }
            
            return info
            
        except Exception as e:
            logger.error(f"Erreur extraction abonnement: {e}")
            return {
                "has_subscription": True,
                "is_active": True,
                "access_mode": "full",
                "plan": "Standard",
                "status": "active",
                "subscription": {},
                "limits": {},
                "usage": {},
                "error": str(e)
            }

    # =========================================================================
    # SYNCHRONISATION DE LA BRANCHE
    # =========================================================================
    
    def sync_user_branch_from_server(self) -> Dict:
        """
        Synchronise la branche de l'utilisateur depuis les endpoints:
        - /api/v1/sync/user/branch
        - /api/v1/users/me
        - /api/v1/auth/me
        - /api/v1/branches/current
        """
        user = self.get_current_user()
        if not user:
            return {"error": "Utilisateur non connecté", "success": False}
        
        token = user.get('token')
        if not token:
            return {"error": "Token manquant", "success": False}
        
        import urllib3
        import requests
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        
        endpoints = [
            "/api/v1/sync/user/branch",
            "/api/v1/users/me",
            "/api/v1/auth/me",
            "/api/v1/branches/current"
        ]
        
        for endpoint in endpoints:
            try:
                response = requests.get(
                    f"https://my-backend-ydit.onrender.com{endpoint}",
                    headers={
                        "Authorization": f"Bearer {token}",
                        "Content-Type": "application/json"
                    },
                    timeout=30,
                    verify=False
                )
                
                if response.status_code == 200:
                    data = response.json()
                    
                    branch_id = None
                    branch_name = None
                    
                    if 'branch_id' in data:
                        branch_id = data.get('branch_id')
                        branch_name = data.get('branch_name')
                    elif 'user' in data:
                        user_data = data.get('user', {})
                        branch_id = user_data.get('active_branch_id') or user_data.get('branch_id')
                        branch_name = user_data.get('branch_name')
                    else:
                        branch_id = data.get('active_branch_id') or data.get('branch_id')
                        branch_name = data.get('branch_name')
                    
                    if branch_id:
                        with self.db.get_connection() as conn:
                            cursor = conn.cursor()
                            cursor.execute("""
                                UPDATE user 
                                SET active_branch_id = ?, branch_name = ?, updated_at = ?
                                WHERE id = ?
                            """, (str(branch_id), branch_name or '', datetime.now().isoformat(), user['id']))
                            conn.commit()
                        
                        logger.info(f"✅ Branche synchronisée: {branch_name} ({branch_id}) via {endpoint}")
                        return {
                            "success": True,
                            "branch_id": str(branch_id),
                            "branch_name": branch_name or '',
                            "endpoint_used": endpoint
                        }
                        
            except Exception as e:
                logger.warning(f"Erreur sur endpoint {endpoint}: {e}")
                continue
        
        return {"error": "Impossible de récupérer la branche", "success": False}
    
    # =========================================================================
    # LECTURE DE L'UTILISATEUR
    # =========================================================================
    
    def get_current_user(self) -> Optional[Dict]:
        """
        Récupère l'utilisateur courant depuis la base locale.
        Fallback vers JSON si SQLite est vide.
        """
        try:
            # 🔍 D'abord, essayer SQLite
            with self.db.get_connection() as conn:
                cursor = conn.cursor()
                
                # Vérifier si la table existe
                cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='user'")
                if cursor.fetchone():
                    cursor.execute("SELECT * FROM user LIMIT 1")
                    row = cursor.fetchone()
                    
                    if row:
                        columns = [description[0] for description in cursor.description]
                        user_data = dict(zip(columns, row))
                        
                        # Restaurer subscription_data
                        if user_data.get('subscription_data'):
                            try:
                                if isinstance(user_data['subscription_data'], str):
                                    user_data['subscription_data'] = json.loads(user_data['subscription_data'])
                            except Exception as e:
                                logger.error(f"Erreur parsing subscription_data: {e}")
                                user_data['subscription_data'] = {}
                        
                        if user_data.get('token'):
                            logger.info(f"✅ Utilisateur chargé depuis SQLite: {user_data.get('username')}")
                            return user_data
        
        except Exception as e:
            logger.error(f"❌ Erreur lecture SQLite: {e}")
        
        # 🔍 Fallback: Lire depuis JSON
        logger.info("🔍 Fallback: Tentative de lecture depuis JSON...")
        user_data = JSONStorage.get_user()
        
        if user_data and user_data.get('token'):
            logger.info(f"✅ Utilisateur chargé depuis JSON: {user_data.get('username')}")
            
            # Optionnel: Restaurer dans SQLite pour la prochaine fois
            try:
                self._restore_user_to_sqlite(user_data)
            except Exception as e:
                logger.warning(f"Impossible de restaurer dans SQLite: {e}")
            
            return user_data
        
        logger.info("ℹ️ Aucun utilisateur trouvé (ni SQLite, ni JSON)")
        return None
    
    
    def _restore_user_to_sqlite(self, user_data: Dict):
        """Restaure un utilisateur depuis JSON vers SQLite."""
        try:
            with self.db.get_connection() as conn:
                cursor = conn.cursor()
                
                # Supprimer l'ancien
                cursor.execute("DELETE FROM user")
                
                # Insérer le nouveau
                cursor.execute("""
                    INSERT INTO user (
                        id, username, email, full_name, role,
                        token, refresh_token,
                        active_branch_id, branch_name,
                        pharmacy_id, pharmacy_name,
                        tenant_id, tenant_name,
                        last_sync, subscription_data, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    user_data.get('id', ''),
                    user_data.get('username', ''),
                    user_data.get('email', ''),
                    user_data.get('full_name', ''),
                    user_data.get('role', 'cashier'),
                    user_data.get('token', ''),
                    user_data.get('refresh_token', ''),
                    user_data.get('active_branch_id', ''),
                    user_data.get('branch_name', ''),
                    user_data.get('pharmacy_id', ''),
                    user_data.get('pharmacy_name', ''),
                    user_data.get('tenant_id', ''),
                    user_data.get('tenant_name', ''),
                    user_data.get('last_sync', datetime.now().isoformat()),
                    user_data.get('subscription_data', '{}'),
                    datetime.now().isoformat()
                ))
                conn.commit()
                logger.info("✅ Utilisateur restauré dans SQLite depuis JSON")
        except Exception as e:
            logger.error(f"❌ Erreur restauration SQLite: {e}")
    # =========================================================================
    # GETTERS
    # =========================================================================
    
    def get_user_role(self, user_id: str = None) -> str:
        user = self.get_current_user() if not user_id else None
        return user.get('role', 'cashier') if user else 'cashier'
    
    def get_user_branch_id(self) -> Optional[str]:
        user = self.get_current_user()
        return user.get('active_branch_id') if user else None
    
    def get_user_token(self) -> Optional[str]:
        user = self.get_current_user()
        return user.get('token') if user else None
    
    def get_user_pharmacy_id(self) -> Optional[str]:
        user = self.get_current_user()
        return user.get('pharmacy_id') if user else None
    
    def is_authenticated(self) -> bool:
        user = self.get_current_user()
        return bool(user and user.get('token'))
    
    # =========================================================================
    # GESTION DE L'ABONNEMENT
    # =========================================================================
    
    def save_subscription_info(self, subscription_info: Dict) -> bool:
        """Sauvegarde les informations d'abonnement dans le cache local."""
        try:
            user = self.get_current_user()
            if not user:
                logger.warning("Aucun utilisateur pour sauvegarder l'abonnement")
                return False
            
            branch_id = user.get('active_branch_id', '0')
            
            subscription_data = {
                "branch_id": branch_id,
                "info": subscription_info if subscription_info else {},
                "last_update": datetime.now().isoformat()
            }
            
            with self.db.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "UPDATE user SET subscription_data = ?, updated_at = ? WHERE id = ?",
                    (json.dumps(subscription_data), datetime.now().isoformat(), user['id'])
                )
                conn.commit()
            
            logger.info(f"✅ Abonnement sauvegardé pour la branche {branch_id}")
            return True
            
        except Exception as e:
            logger.error(f"Erreur sauvegarde abonnement: {e}")
            return False
    
    def get_subscription_info(self) -> Dict:
        """Récupère les informations d'abonnement depuis le cache."""
        try:
            user_data = self.get_current_user()
            if user_data and user_data.get('subscription_data'):
                try:
                    if isinstance(user_data['subscription_data'], str):
                        sub_data = json.loads(user_data['subscription_data'])
                    else:
                        sub_data = user_data['subscription_data']
                    
                    if sub_data and isinstance(sub_data, dict):
                        return sub_data.get('info', {})
                except Exception as e:
                    logger.error(f"Erreur parsing subscription_data: {e}")
            
            return {}
            
        except Exception as e:
            logger.error(f"Erreur récupération abonnement: {e}")
            return {}
    
    def is_subscription_valid(self) -> bool:
        sub_info = self.get_subscription_info()
        return sub_info.get('is_active', False) if sub_info else False
    
    def get_subscription_status(self) -> Dict:
        """Statut complet de l'abonnement."""
        sub_info = self.get_subscription_info()
        
        if not sub_info or not isinstance(sub_info, dict):
            return {
                "has_subscription": False,
                "is_active": False,
                "access_mode": "read_only",
                "blocked": True,
                "reason": "Aucune information d'abonnement"
            }
        
        is_active = sub_info.get('is_active', False)
        
        return {
            "has_subscription": sub_info.get('has_subscription', False),
            "is_active": is_active,
            "access_mode": "full" if is_active else "read_only",
            "blocked": not is_active,
            "subscription": sub_info.get('subscription'),
            "limits": sub_info.get('limits'),
            "usage": sub_info.get('usage'),
            "reason": None if is_active else "Abonnement expiré ou inactif"
        }
    
    def clear_subscription_cache(self):
        """Efface le cache d'abonnement."""
        try:
            with self.db.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("UPDATE user SET subscription_data = NULL")
                conn.commit()
            logger.info("✅ Cache d'abonnement effacé")
            return True
        except Exception as e:
            logger.error(f"Erreur effacement cache: {e}")
            return False
    
    # =========================================================================
    # MISE À JOUR
    # =========================================================================
    
    def update_last_sync(self, sync_time: str) -> bool:
        """Met à jour la date de dernière synchronisation."""
        user = self.get_current_user()
        if user:
            try:
                with self.db.get_connection() as conn:
                    cursor = conn.cursor()
                    cursor.execute(
                        "UPDATE user SET last_sync = ?, updated_at = ? WHERE id = ?",
                        (sync_time, datetime.now().isoformat(), user['id'])
                    )
                    conn.commit()
                return True
            except Exception as e:
                logger.error(f"Erreur mise à jour last_sync: {e}")
        return False
    
    # =========================================================================
    # DÉCONNEXION (SEUL MOMENT OÙ LES DONNÉES SONT EFFACÉES)
    # =========================================================================
    
    def logout(self) -> bool:
        """
        Déconnecte l'utilisateur.
        Supprime TOUTES les données dans SQLite ET dans JSON.
        """
        success = True
        
        # ✅ Supprimer TOUTES les données de la base (produits, ventes, etc.)
        try:
            self.db.clear_all_data()
            logger.info("✅ Toutes les données locales supprimées (produits, ventes, dépenses)")
        except Exception as e:
            logger.error(f"❌ Erreur suppression données: {e}")
            success = False
        
        # Supprimer l'utilisateur de SQLite
        try:
            with self.db.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("DELETE FROM user")
                conn.commit()
                logger.info("✅ SQLite: Données utilisateur supprimées")
        except Exception as e:
            logger.error(f"❌ SQLite: Erreur déconnexion: {e}")
            success = False
        
        # Supprimer de JSON
        if JSONStorage.delete_user():
            logger.info("✅ JSON: Données utilisateur supprimées")
        else:
            success = False
        
        if JSONStorage.delete_subscription():
            logger.info("✅ JSON: Données abonnement supprimées")
        
        # ✅ Vider le cache de session
        try:
            if hasattr(self, '_current_user'):
                self._current_user = None
        except:
            pass
        
        return success